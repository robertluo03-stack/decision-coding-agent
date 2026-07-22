"""Token 使用量拦截器。

通过 monkey-patch langchain_deepseek.ChatDeepSeek.invoke 捕获每次 LLM 调用的
token usage（prompt_tokens / completion_tokens / total_tokens）。

因为每个节点各自创建 ChatDeepSeek 实例（非依赖注入），patch 类方法是最低侵入的方案，
可同时覆盖 5 个 LLM 调用点（planner / coder / debugger×2 / reporter / text_to_sql）。

用法:
    from src.benchmark.token_tracker import start_token_tracking, stop_token_tracking, get_token_totals

    start_token_tracking()
    # ... run agent tasks ...
    totals = get_token_totals()  # → {prompt_tokens, completion_tokens, total_tokens}
    stop_token_tracking()

线程安全：使用 threading.Lock 保护全局计数器，兼容 runner.py 的子线程超时控制。
"""

from __future__ import annotations

import threading
from typing import Any, Callable

# ── 全局状态 ──────────────────────────────────────────────────

_original_invoke: Callable[..., Any] | None = None
_lock = threading.Lock()
_totals: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
_active: bool = False


def start_token_tracking() -> None:
    """启动 token 拦截。

    monkey-patch ChatDeepSeek.invoke，在每次调用后从 response.usage_metadata
    中提取 input_tokens / output_tokens / total_tokens 并累加到全局计数器。

    幂等：重复调用不重复 patch。
    """
    global _original_invoke, _active

    if _active:
        return

    from langchain_deepseek import ChatDeepSeek

    if _original_invoke is None:
        _original_invoke = ChatDeepSeek.invoke

    def _tracking_invoke(self_instance: Any, *args: Any, **kwargs: Any) -> Any:
        """包装后的 invoke：调用原始方法 → 捕获 usage_metadata → 累加。"""
        response = _original_invoke(self_instance, *args, **kwargs)  # type: ignore[misc]

        # 从 AIMessage 中提取 token usage
        usage = getattr(response, "usage_metadata", None) or {}
        if isinstance(usage, dict):
            prompt = usage.get("input_tokens", 0)
            completion = usage.get("output_tokens", 0)
            total = usage.get("total_tokens", 0)
            _accumulate(prompt, completion, total)

        return response

    # 类级别 patch
    ChatDeepSeek.invoke = _tracking_invoke  # type: ignore[method-assign]
    _active = True


def stop_token_tracking() -> None:
    """停止 token 拦截，恢复原始 invoke 方法。

    幂等：未启动时调用不报错。
    """
    global _original_invoke, _active

    if not _active or _original_invoke is None:
        return

    from langchain_deepseek import ChatDeepSeek

    ChatDeepSeek.invoke = _original_invoke  # type: ignore[method-assign]
    _original_invoke = None
    _active = False


def reset_token_totals() -> None:
    """重置全局 token 计数器为零。"""
    global _totals
    with _lock:
        _totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def get_token_totals() -> dict[str, int]:
    """获取当前累计 token 用量并重置计数器。

    Returns:
        {prompt_tokens, completion_tokens, total_tokens} 的副本。
        调用后内部计数器清零。
    """
    with _lock:
        result = dict(_totals)
    reset_token_totals()
    return result


# ── 内部辅助 ──────────────────────────────────────────────────


def _accumulate(prompt: int, completion: int, total: int) -> None:
    """线程安全地累加 token 计数。

    Args:
        prompt: 本轮 prompt tokens。
        completion: 本轮 completion tokens。
        total: 本轮 total tokens。
    """
    with _lock:
        _totals["prompt_tokens"] += prompt
        _totals["completion_tokens"] += completion
        _totals["total_tokens"] += total

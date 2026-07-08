"""NodeTracer — 节点执行追踪器，包装节点函数记录状态/耗时/异常。

设计：
- 不修改节点文件本身（零侵入）
- 包装函数在 graph 组装阶段替换原始 run 函数
- 异常时更新 UI 状态并 re-raise（不吞异常）
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.agent.ui.manager import UIManager


class NodeTracer:
    """单个节点的执行追踪器。

    包装节点 run 函数，在调用前后记录开始/结束/耗时/异常状态，
    通过 UIManager 的 update_node() 和 log() 推送至终端 UI。
    """

    def __init__(self, ui: UIManager, node_name: str) -> None:
        """初始化追踪器。

        Args:
            ui: UIManager 实例（线程安全）。
            node_name: 节点名称（Planner / Coder / Executor / Debugger / Reporter）。
        """
        self._ui = ui
        self._node_name = node_name

    def trace(self, func: Callable[..., dict]) -> Callable[..., dict]:
        """包装节点函数，添加执行追踪。

        包装函数签名保持与原节点一致（接收 AgentState，返回 dict），
        因此 LangGraph 的 invoke/stream 无需任何修改。

        Args:
            func: 原始节点 run 函数（run(state: AgentState) → dict）

        Returns:
            包装后的函数，签名一致
        """
        node_name = self._node_name
        ui = self._ui

        def wrapper(state: dict) -> dict:
            retry = state.get("retry_count", 0) if isinstance(state, dict) else 0
            ui.update_node(node_name, "运行中", 0.0, retry=retry)
            ui.log(f"[{node_name}] 开始执行", level="info")

            t_start = time.perf_counter()
            try:
                result = func(state)
                elapsed = time.perf_counter() - t_start
                ui.update_node(node_name, "完成", elapsed, retry=retry)
                ui.log(
                    f"[{node_name}] 完成（耗时 {elapsed:.2f}s）", level="info"
                )
                return result
            except Exception as exc:
                elapsed = time.perf_counter() - t_start
                error_msg = f"{type(exc).__name__}: {exc}"
                ui.update_node(node_name, "错误", elapsed, retry=retry)
                ui.log(f"[{node_name}] 异常 {error_msg}", level="error")
                raise

        # 保留原函数引用，方便调试
        wrapper.__name__ = f"traced_{func.__name__}"
        wrapper.__qualname__ = f"NodeTracer.{func.__qualname__}"
        return wrapper


def trace_graph_nodes(
    ui_manager: UIManager,
    node_funcs: dict[str, Callable[..., dict]],
) -> dict[str, Callable[..., dict]]:
    """为所有节点函数创建 tracer 包装。

    Args:
        ui_manager: UIManager 实例。
        node_funcs: {节点名: run 函数} 的字典。

    Returns:
        包装后的 {节点名: traced_run} 字典。
    """
    traced: dict[str, Callable[..., dict]] = {}
    for name, func in node_funcs.items():
        tracer = NodeTracer(ui_manager, name)
        traced[name] = tracer.trace(func)
    return traced

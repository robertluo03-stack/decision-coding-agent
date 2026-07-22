"""测试 Token 使用量拦截器。

验证：
- start/stop 生命周期
- 调用 invoke 后累加 token
- reset_token_totals 清零
- stop 后恢复原始 invoke
- 多次 invoke → 累加
- 幂等性
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.benchmark.token_tracker import (
    start_token_tracking,
    stop_token_tracking,
    get_token_totals,
    reset_token_totals,
)


class TestTokenTrackerLifecycle:
    """start/stop 生命周期测试。"""

    def test_start_idempotent(self) -> None:
        """重复 start 不报错。"""
        start_token_tracking()
        start_token_tracking()  # 幂等
        stop_token_tracking()

    def test_stop_idempotent(self) -> None:
        """未 start 时 stop 不报错。"""
        stop_token_tracking()  # 应该不报错

    def test_start_stop_restore(self) -> None:
        """stop 后原始 invoke 方法应恢复。"""
        from langchain_deepseek import ChatDeepSeek

        original = ChatDeepSeek.invoke
        start_token_tracking()
        assert ChatDeepSeek.invoke is not original
        stop_token_tracking()
        assert ChatDeepSeek.invoke is original


class TestTokenAccumulation:
    """token 累加逻辑测试。"""

    def test_single_invoke_accumulates_tokens(self) -> None:
        """单次 invoke 后 token 累加正确。"""
        # 构造 mock AIMessage
        mock_msg = MagicMock()
        mock_msg.usage_metadata = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_token_details": {"cache_read": 0},
            "output_token_details": {},
        }

        from langchain_deepseek import ChatDeepSeek
        real_original = ChatDeepSeek.invoke

        start_token_tracking()
        try:
            # 直接替换 _original_invoke（tracking wrapper 内部会调用它）
            import src.benchmark.token_tracker as tt
            tt._original_invoke = lambda self, *args, **kwargs: mock_msg
            llm = ChatDeepSeek(model="deepseek-chat", api_key="sk-test")
            llm.invoke([{"role": "user", "content": "hi"}])
        finally:
            stop_token_tracking()
            ChatDeepSeek.invoke = real_original

        totals = get_token_totals()
        assert totals["prompt_tokens"] == 100
        assert totals["completion_tokens"] == 50
        assert totals["total_tokens"] == 150

    def test_multiple_invokes_accumulate(self) -> None:
        """多次 invoke 后 token 累加正确。"""
        totals1 = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        totals2 = {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}

        mock_msg1 = MagicMock()
        mock_msg1.usage_metadata = dict(totals1, input_token_details={}, output_token_details={})
        mock_msg2 = MagicMock()
        mock_msg2.usage_metadata = dict(totals2, input_token_details={}, output_token_details={})

        from langchain_deepseek import ChatDeepSeek
        real_original = ChatDeepSeek.invoke

        start_token_tracking()
        try:
            import src.benchmark.token_tracker as tt
            # 第一轮：替换 _original_invoke
            tt._original_invoke = lambda self, *args, **kwargs: mock_msg1
            llm = ChatDeepSeek(model="deepseek-chat", api_key="sk-test")
            llm.invoke([{"role": "user", "content": "msg1"}])
            # 第二轮
            tt._original_invoke = lambda self, *args, **kwargs: mock_msg2
            llm.invoke([{"role": "user", "content": "msg2"}])
        finally:
            stop_token_tracking()
            ChatDeepSeek.invoke = real_original

        totals = get_token_totals()
        assert totals["prompt_tokens"] == 30
        assert totals["completion_tokens"] == 15
        assert totals["total_tokens"] == 45


class TestReset:
    """reset_token_totals 测试。"""

    def test_reset_zeros_counts(self) -> None:
        """reset 后计数器为零。"""
        mock_msg = MagicMock()
        mock_msg.usage_metadata = {
            "input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
            "input_token_details": {}, "output_token_details": {},
        }

        from langchain_deepseek import ChatDeepSeek
        real_original = ChatDeepSeek.invoke

        start_token_tracking()
        try:
            import src.benchmark.token_tracker as tt
            tt._original_invoke = lambda self, *args, **kwargs: mock_msg
            llm = ChatDeepSeek(model="deepseek-chat", api_key="sk-test")
            llm.invoke([{"role": "user", "content": "hi"}])
        finally:
            stop_token_tracking()
            ChatDeepSeek.invoke = real_original

        # 获取（内部会 reset）
        first = get_token_totals()
        assert first["total_tokens"] == 150

        # 再次获取 → 0（已 reset）
        second = get_token_totals()
        assert second["total_tokens"] == 0


class TestGetTokenTotals:
    """get_token_totals 测试。"""

    def test_empty_when_no_tracking(self) -> None:
        """未启动 tracking 时 get 返回零。"""
        # 确保 stop 了
        stop_token_tracking()
        totals = get_token_totals()
        assert totals["prompt_tokens"] == 0
        assert totals["completion_tokens"] == 0
        assert totals["total_tokens"] == 0

    def test_get_resets_after(self) -> None:
        """get 后计数器清零。"""
        totals = get_token_totals()
        assert totals["total_tokens"] == 0

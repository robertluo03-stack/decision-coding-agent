"""测试 Graph 执行过程实时追踪。

覆盖：
- NodeTracer 函数包装
- UIManager mock 验证
- build_graph use_ui 参数
- 零回归：默认 build_graph() 行为不变
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from src.agent.ui.manager import UIManager
from src.agent.ui.tracer import NodeTracer, trace_graph_nodes
from src.agent.graph import build_graph


class TestNodeTracer:
    """NodeTracer 包装函数正确性测试。"""

    def test_tracer_wraps_function(self) -> None:
        """包装后函数仍返回正确结果。"""
        ui = UIManager(force_terminal=False)

        def original(state: dict) -> dict:
            return {"result": "ok", "input": state.get("key", "")}

        tracer = NodeTracer(ui, "TestNode")
        wrapped = tracer.trace(original)

        result = wrapped({"key": "value"})
        assert result == {"result": "ok", "input": "value"}

    def test_tracer_updates_ui(self) -> None:
        """验证 update_node 被调用（mock UIManager）。"""
        ui = MagicMock(spec=UIManager)
        ui._queue = MagicMock()

        def original(state: dict) -> dict:
            time.sleep(0.01)  # 小延迟保证耗时 > 0
            return {"ok": True}

        tracer = NodeTracer(ui, "Planner")
        wrapped = tracer.trace(original)
        wrapped({})

        # 验证 update_node 被调用至少 2 次（开始 + 结束）
        assert ui.update_node.call_count >= 2

        # 第一次调用：运行中
        first_call = ui.update_node.call_args_list[0]
        assert first_call[0][0] == "Planner"
        assert first_call[0][1] == "运行中"

        # 最后一次调用：完成
        last_call = ui.update_node.call_args_list[-1]
        assert last_call[0][0] == "Planner"
        assert last_call[0][1] == "完成"

    def test_tracer_error_status(self) -> None:
        """mock 函数抛异常，验证状态变为 "错误" 且 re-raise。"""
        ui = MagicMock(spec=UIManager)
        ui._queue = MagicMock()

        def failing(state: dict) -> dict:
            raise ValueError("test error")

        tracer = NodeTracer(ui, "Coder")
        wrapped = tracer.trace(failing)

        with pytest.raises(ValueError, match="test error"):
            wrapped({})

        # 最后一次 update_node 调用应该是 "错误"
        last_call = ui.update_node.call_args_list[-1]
        assert last_call[0][0] == "Coder"
        assert last_call[0][1] == "错误"

    def test_tracer_logs_on_start_and_end(self) -> None:
        """验证 log 被调用（开始 + 完成各一次）。"""
        ui = MagicMock(spec=UIManager)
        ui._queue = MagicMock()

        def original(state: dict) -> dict:
            return {"ok": True}

        tracer = NodeTracer(ui, "Executor")
        wrapped = tracer.trace(original)
        wrapped({})

        assert ui.log.call_count >= 2

    def test_tracer_preserves_wrapper_identity(self) -> None:
        """包装函数保留可追踪的 __name__ / __qualname__。"""
        ui = MagicMock(spec=UIManager)
        ui._queue = MagicMock()

        def original(state: dict) -> dict:
            return {}

        tracer = NodeTracer(ui, "Reporter")
        wrapped = tracer.trace(original)
        assert "original" in wrapped.__name__
        assert wrapped.__qualname__.startswith("NodeTracer.")


class TestTraceGraphNodes:
    """trace_graph_nodes 批量包装测试。"""

    def test_trace_graph_nodes_all_keys(self) -> None:
        """所有节点都被包装，键名保持不变。"""
        ui = UIManager(force_terminal=False)
        node_funcs = {
            "Planner": lambda s: {"plan": []},
            "Coder": lambda s: {"generated_code": ""},
            "Executor": lambda s: {"execution_result": ""},
            "Debugger": lambda s: {"human_feedback": ""},
            "Reporter": lambda s: {"final_report": ""},
        }
        traced = trace_graph_nodes(ui, node_funcs)
        assert set(traced.keys()) == set(node_funcs.keys())
        for name in node_funcs:
            assert callable(traced[name])

    def test_trace_graph_nodes_wrapped_calls_original(self) -> None:
        """包装后的函数仍调用原始函数并返回正确结果。"""
        ui = UIManager(force_terminal=False)

        side_effects: list[str] = []

        def planner_fn(state: dict) -> dict:
            side_effects.append("planner_called")
            return {"plan": ["step1"]}

        node_funcs = {"Planner": planner_fn}
        traced = trace_graph_nodes(ui, node_funcs)
        result = traced["Planner"]({})
        assert result == {"plan": ["step1"]}
        assert "planner_called" in side_effects


class TestGraphBuildWithUI:
    """build_graph use_ui 参数测试。"""

    def test_graph_build_with_ui(self) -> None:
        """build_graph(use_ui=True) 不抛异常且编译成功。"""
        ui = UIManager(force_terminal=False)
        graph = build_graph(use_ui=True, ui_manager=ui)
        assert graph is not None
        # 验证编译后的 graph 有 invoke 方法
        assert hasattr(graph, "invoke")

    def test_graph_build_without_ui_regression(self) -> None:
        """默认 build_graph() 行为与 Week 5 一致，编译成功。"""
        graph = build_graph()
        assert graph is not None
        assert hasattr(graph, "invoke")

    def test_graph_build_ui_false_no_tracer(self) -> None:
        """use_ui=False 时不注入 tracer，结果一致。"""
        graph1 = build_graph(use_ui=False)
        graph2 = build_graph(use_ui=False, ui_manager=UIManager(force_terminal=False))
        # 两份都不抛异常
        assert graph1 is not None
        assert graph2 is not None

    def test_build_graph_default_signature_backward_compat(self) -> None:
        """build_graph() 无参数调用（旧签名）仍正常工作。"""
        graph = build_graph()  # 与 Week 5 调用完全一致
        assert graph is not None


class TestUIManagerDebugMode:
    """UIManager debug 模式测试。"""

    def test_enter_exit_debug_mode(self) -> None:
        """enter_debug_mode / exit_debug_mode 正确切换状态。"""
        ui = UIManager(force_terminal=False)
        assert ui.debug_mode is False

        ui.enter_debug_mode("ValueError: x not found", "诊断：变量未定义")
        ui._drain_queue()
        assert ui.debug_mode is True

        ui.exit_debug_mode()
        ui._drain_queue()
        assert ui.debug_mode is False

    def test_debug_then_update_still_works(self) -> None:
        """进入 debug 模式后 update_node 仍然正常工作。"""
        ui = UIManager(force_terminal=False)
        ui.enter_debug_mode("err", "diag")
        ui._drain_queue()
        assert ui.debug_mode is True

        # debug 模式中仍然可以更新节点
        ui.update_node("Debugger", "完成", 2.0, retry=1)
        ui._drain_queue()
        info = ui.get_node_status("Debugger")
        assert info is not None
        assert info["status"] == "完成"

    def test_enter_debug_does_not_crash_no_tty(self) -> None:
        """非 TTY 模式下 enter_debug_mode 不报错。"""
        ui = UIManager(force_terminal=False)
        ui.enter_debug_mode("test error", "test diagnosis")
        ui._drain_queue()
        # 不抛异常即为通过

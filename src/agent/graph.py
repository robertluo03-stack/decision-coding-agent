"""LangGraph StateGraph — 主图编译和入口。

状态流转:
    Planner → Coder → Executor ──┬─ (error 且非 ABORT) → Debugger
                                  │           │
                                  │    ┌──────┘
                                  │    ▼
                                  │   (非 ABORT) → Coder (loop)
                                  │   (ABORT)    → Reporter
                                  │
                                  └─ (无 error 或 ABORT) → Reporter → END

两个条件路由函数:
    route_after_executor(state)  — Executor 之后决定走 Debugger 还是 Reporter
    route_after_debugger(state)  — Debugger 之后决定回到 Coder 还是进入 Reporter
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.agent.state import AgentState

if TYPE_CHECKING:
    from src.agent.ui.manager import UIManager

# ---------------------------------------------------------------------------
# 延迟导入节点函数，避免循环依赖
# ---------------------------------------------------------------------------

_planner_node = None
_coder_node = None
_executor_node = None
_debugger_node = None
_reporter_node = None


def _ensure_imports() -> None:
    """惰性导入所有节点模块（延迟到 graph 实际编译时）。"""
    global _planner_node, _coder_node, _executor_node, _debugger_node, _reporter_node

    if _planner_node is None:
        from src.agent.nodes.planner import run as _planner_node
        from src.agent.nodes.coder import run as _coder_node
        from src.agent.nodes.executor import run as _executor_node
        from src.agent.nodes.debugger import run as _debugger_node
        from src.agent.nodes.reporter import run as _reporter_node


# ---------------------------------------------------------------------------
# 条件路由函数
# ---------------------------------------------------------------------------


def route_after_executor(state: AgentState) -> str:
    """Executor 之后的条件路由。

    规则:
        - 有 error 且 human_feedback != "ABORT" → "debug"（进入 Debugger）
        - 否则 → "report"（进入 Reporter）

    Args:
        state: 当前 AgentState

    Returns:
        "debug" 或 "report"
    """
    error = state.get("error")
    human_feedback = state.get("human_feedback")

    if error and human_feedback != "ABORT":
        return "debug"
    return "report"


def route_after_debugger(state: AgentState) -> str:
    """Debugger 之后的条件路由。

    规则:
        - human_feedback == "ABORT" → "report"（进入 Reporter）
        - 否则 → "code"（回到 Coder 重新生成代码）

    Args:
        state: 当前 AgentState

    Returns:
        "code" 或 "report"
    """
    human_feedback = state.get("human_feedback")

    if human_feedback == "ABORT":
        return "report"
    return "code"


# ---------------------------------------------------------------------------
# Graph 编译
# ---------------------------------------------------------------------------


def build_graph(
    use_ui: bool = False,
    ui_manager: UIManager | None = None,
) -> StateGraph:
    """构建并编译 DecisionCoder 的 LangGraph StateGraph。

    节点:
        planner  — 任务拆解
        coder    — 代码生成
        executor — 沙箱执行
        debugger — 人在回路调试
        reporter — 报告生成

    边:
        planner → coder → executor
        executor → route_after_executor → debugger | reporter
        debugger → route_after_debugger → coder | reporter
        reporter → END

    Args:
        use_ui: 是否启用 Rich 终端 UI 追踪（默认 False）。
        ui_manager: UIManager 实例（use_ui=True 时必须提供）。

    Returns:
        编译后的 StateGraph Runnable
    """
    _ensure_imports()

    # ---- 初始化日志系统 ----
    from src.agent.logger_config import init_logger

    init_logger()

    builder = StateGraph(AgentState)

    # ---- 获取节点函数（可能被 tracer 包装） ----
    planner_fn = _planner_node
    coder_fn = _coder_node
    executor_fn = _executor_node
    debugger_fn = _debugger_node
    reporter_fn = _reporter_node

    if use_ui and ui_manager is not None:
        from src.agent.ui.tracer import trace_graph_nodes

        # 注入 UIManager 给 debugger 的 _safe_input 使用
        from src.agent.nodes import debugger as debugger_module
        debugger_module.set_ui_manager(ui_manager)

        node_funcs = {
            "Planner": planner_fn,
            "Coder": coder_fn,
            "Executor": executor_fn,
            "Debugger": debugger_fn,
            "Reporter": reporter_fn,
        }
        traced = trace_graph_nodes(ui_manager, node_funcs)
        planner_fn = traced["Planner"]
        coder_fn = traced["Coder"]
        executor_fn = traced["Executor"]
        debugger_fn = traced["Debugger"]
        reporter_fn = traced["Reporter"]

    # ---- 注册节点 ----
    builder.add_node("planner", planner_fn)
    builder.add_node("coder", coder_fn)
    builder.add_node("executor", executor_fn)
    builder.add_node("debugger", debugger_fn)
    builder.add_node("reporter", reporter_fn)

    # ---- 入口 ----
    builder.set_entry_point("planner")

    # ---- 线性边 ----
    builder.add_edge("planner", "coder")
    builder.add_edge("coder", "executor")

    # ---- 条件边 1: Executor → Debugger 或 Reporter ----
    builder.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "debug": "debugger",
            "report": "reporter",
        },
    )

    # ---- 条件边 2: Debugger → Coder（循环）或 Reporter（终止） ----
    builder.add_conditional_edges(
        "debugger",
        route_after_debugger,
        {
            "code": "coder",
            "report": "reporter",
        },
    )

    # ---- 终点 ----
    builder.add_edge("reporter", END)

    # ---- 编译（不带 checkpointer，纯内存模式） ----
    graph = builder.compile()
    return graph


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------


def run(
    user_query: str,
    workspace_path: str = "./src/workspace",
    *,
    initial_state_overrides: dict | None = None,
) -> dict:
    """运行一次完整的 Agent 闭环。

    构造初始 AgentState，调用 graph.invoke() 走完 Plan→Code→Execute→[Debug]→Report。

    Args:
        user_query: 用户自然语言需求
        workspace_path: 工作区路径（默认 ./src/workspace）
        initial_state_overrides: 可选的初始状态覆盖字段，用于测试注入

    Returns:
        最终的 AgentState 字典（包含 final_report）
    """
    app = build_graph()

    initial_state: dict = {
        "user_query": user_query,
        "workspace_path": workspace_path,
        "plan": [],
        "generated_code": "",
        "file_path": None,
        "execution_result": None,
        "error": None,
        "retry_count": 0,
        "human_feedback": None,
        "final_report": None,
    }

    if initial_state_overrides:
        initial_state.update(initial_state_overrides)

    # 使用线程 id 区分不同 run（避免 checkpointer 冲突）
    import uuid
    config = {"configurable": {"thread_id": str(uuid.uuid4())[:8]}}
    result = app.invoke(initial_state, config)
    return result

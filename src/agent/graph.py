"""LangGraph StateGraph — 主图编译和入口。

Plan → Code → Execute → Router → Debugger (loop) → Report
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.agent.state import AgentState
from src.agent.nodes.planner import planner_node
from src.agent.nodes.coder import coder_node
from src.agent.nodes.executor import executor_node
from src.agent.nodes.debugger import debugger_node
from src.agent.nodes.reporter import reporter_node


def router(state: AgentState) -> str:
    """条件路由：根据 error 和 retry_count 决定下一步。"""
    if state.get("human_feedback") == "ABORT":
        return "reporter"
    if state.get("error") and state.get("retry_count", 0) < 2:
        return "debugger"
    if state.get("retry_count", 0) >= 2:
        return "reporter"
    return "reporter"


def build_graph() -> StateGraph:
    """构建并编译 DecisionCoder 的 StateGraph。"""
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("planner", planner_node)
    workflow.add_node("coder", coder_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("debugger", debugger_node)
    workflow.add_node("reporter", reporter_node)

    # 设置入口
    workflow.set_entry_point("planner")

    # 线性边
    workflow.add_edge("planner", "coder")
    workflow.add_edge("coder", "executor")

    # 条件边：执行后根据结果路由
    workflow.add_conditional_edges(
        "executor",
        router,
        {
            "debugger": "debugger",
            "reporter": "reporter",
        },
    )

    # debugger 后回到 coder
    workflow.add_edge("debugger", "coder")

    # reporter 结束
    workflow.add_edge("reporter", END)

    # 编译（带内存检查点，支持 Human-in-the-loop）
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app


def run(user_query: str, workspace_path: str = "./src/workspace") -> AgentState:
    """运行一次完整的 Agent 闭环。

    Args:
        user_query: 用户自然语言需求
        workspace_path: 工作区路径

    Returns:
        最终的 AgentState（包含 final_report）
    """
    app = build_graph()
    initial_state: AgentState = {
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
    config = {"configurable": {"thread_id": "default"}}
    result = app.invoke(initial_state, config)
    return result

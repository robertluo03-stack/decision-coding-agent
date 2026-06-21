"""AgentState TypeDict specification.

This is the single source of truth for the state shape flowing through
the LangGraph StateGraph. All nodes read from and write to this schema.
"""

from typing import List, Optional, TypedDict


class AgentState(TypedDict):
    """Core state that flows through all LangGraph nodes.

    Fields are additive — each node returns a partial update, and
    LangGraph merges them into the accumulated state.

    Constraints:
        - retry_count >= 2 时强制进入 Reporter，不再循环
        - human_feedback == "ABORT" 时 Reporter 生成失败报告
        - 所有节点必须返回完整的 AgentState 子集
    """

    user_query: str
    """用户原始自然语言需求"""

    workspace_path: str
    """工作区绝对路径"""

    plan: List[str]
    """Planner 输出的执行计划步骤列表"""

    generated_code: str
    """Coder 生成的 Python 代码"""

    file_path: Optional[str]
    """Executor 输出的临时执行文件路径"""

    execution_result: Optional[str]
    """Executor 输出的 stdout"""

    error: Optional[str]
    """Executor 输出的 stderr / 异常信息"""

    retry_count: int
    """当前重试次数（初始 0，上限 2）"""

    human_feedback: Optional[str]
    """人在回路反馈：
        - "AI_FIX:<code>" — 接受 AI 修复的代码
        - "USER_FIX:<指令>" — 人类自定义指令
        - "SKIP" — 跳过当前步骤
        - "ABORT" — 中止并生成失败报告
    """

    final_report: Optional[str]
    """Reporter 输出的 Markdown 格式最终报告"""

"""Planner user message builder."""


def build_planner_user_message(query: str) -> str:
    """Build the user message for the Planner LLM call.

    Args:
        query: 用户自然语言需求

    Returns:
        Formatted user message string.
    """
    return f"用户需求: {query}\n\n请生成执行计划："

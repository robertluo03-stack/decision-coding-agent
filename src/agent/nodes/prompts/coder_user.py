"""Coder user message builder."""


def build_coder_user_message(query: str, plan: list[str]) -> str:
    """Build the user message for the Coder LLM call.

    Args:
        query: 用户原始自然语言需求
        plan: 执行计划步骤列表

    Returns:
        Formatted user message string.
    """
    plan_lines = "\n".join(
        f"{i + 1}. {step}" for i, step in enumerate(plan)
    )
    return (
        f"用户需求：{query}\n\n"
        f"执行计划：\n{plan_lines}\n\n"
        f"请按照上述计划生成完整的 Python 代码。"
        f"数据文件放在 ./data/ 目录下，使用相对路径读取。"
        f"输出结果请用 print() 打印。"
    )

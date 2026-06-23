"""Debugger user message builders."""


def build_analysis_user_message(error: str, code: str) -> str:
    """Build the user message for error analysis.

    Args:
        error: 错误信息字符串
        code: 当前生成的代码

    Returns:
        Formatted user message for the analysis LLM call.
    """
    return (
        f"错误信息:\n```\n{error}\n```\n\n"
        f"原始代码:\n```python\n{code}\n```\n\n"
        f"请分析错误原因（1-2 句话）。"
    )


def build_fix_user_message(
    error: str,
    code: str,
    user_instruction: str | None = None,
) -> str:
    """Build the user message for code fix generation.

    Args:
        error: 错误信息
        code: 当前代码
        user_instruction: 可选，用户的修复指令

    Returns:
        Formatted user message for the fix LLM call.
    """
    if user_instruction:
        instruction_text = f"用户的修复指令: {user_instruction}"
    else:
        instruction_text = "根据错误信息自动分析最优修复方案。"

    return (
        f"错误信息:\n```\n{error}\n```\n\n"
        f"原始代码:\n```python\n{code}\n```\n\n"
        f"{instruction_text}\n\n"
        f"请输出修复后的完整 Python 代码。"
    )

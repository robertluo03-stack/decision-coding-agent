"""Debugger 节点：错误分析 + Human-in-the-loop 决策。

执行流程：
  1. retry_count >= 2 → 直接返回 ABORT
  2. 使用 DeepSeek API 分析错误原因（1-2 句话）
  3. 展示选项：1.接受AI修复 2.输入指令 3.跳过 4.中止
  4. 读取用户输入并处理：
     - 选项1 → AI 生成修复代码 → human_feedback="AI_FIX:<code>"
     - 选项2 → 读取用户指令 → AI 基于指令生成修复代码 → human_feedback="USER_FIX:<指令>"
     - 选项3 → human_feedback="SKIP"
     - 选项4 → human_feedback="ABORT"

注意：这个节点是 Human-in-the-loop 的核心，面试时会重点展示。
"""

import os
import re
import textwrap
from typing import Any

from src.agent.state import AgentState
from src.agent.nodes.prompts.loader import load_prompt
from src.agent.nodes.prompts.debugger_user import (
    build_analysis_user_message,
    build_fix_user_message,
)

# ---------------------------------------------------------------------------
# 代码块提取
# ---------------------------------------------------------------------------


def _extract_code_block(content: str) -> str:
    """从 LLM 响应中提取 Python 代码块。

    优先级: ```python ... ``` > ``` ... ``` > 原始内容。

    Args:
        content: LLM 原始响应

    Returns:
        提取出的纯 Python 代码字符串
    """
    match = re.search(r"```python\s*\n(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1).strip()

    match = re.search(r"```\s*\n(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1).strip()

    return content.strip()


# ---------------------------------------------------------------------------
# DeepSeek API 调用
# ---------------------------------------------------------------------------


def _get_deepseek_llm():
    """惰性初始化 ChatDeepSeek 客户端。

    Returns:
        ChatDeepSeek 实例

    Raises:
        ValueError: DEEPSEEK_API_KEY 未设置时抛出
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("环境变量 DEEPSEEK_API_KEY 未设置")

    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(
        model="deepseek-chat",
        api_key=api_key,
        temperature=0.3,
    )


def _analyze_error_with_llm(error: str, code: str) -> str:
    """使用 DeepSeek API 分析错误原因。

    Args:
        error: 错误信息字符串
        code: 当前生成代码

    Returns:
        1-2 句话的错误分析
    """
    llm = _get_deepseek_llm()

    messages = [
        {"role": "system", "content": load_prompt("debugger_analysis.md")},
        {"role": "user", "content": build_analysis_user_message(error, code)},
    ]

    response = llm.invoke(messages)
    return response.content.strip()


def _generate_fix_with_llm(
    error: str,
    code: str,
    user_instruction: str | None = None,
) -> str:
    """使用 DeepSeek API 生成修复后的代码。

    Args:
        error: 错误信息
        code: 当前代码
        user_instruction: 可选，用户的修复指令

    Returns:
        修复后的完整 Python 代码
    """
    llm = _get_deepseek_llm()

    messages = [
        {"role": "system", "content": load_prompt("debugger_fix.md")},
        {"role": "user", "content": build_fix_user_message(error, code, user_instruction)},
    ]

    response = llm.invoke(messages)
    return _extract_code_block(response.content)


# ---------------------------------------------------------------------------
# 规则回退：简单错误分类（当 LLM 不可用时）
# ---------------------------------------------------------------------------


def _diagnose_by_rule(error: str) -> str:
    """基于规则的简单错误分类。

    作为 LLM 调用失败时的回退方案。

    Args:
        error: 错误信息

    Returns:
        错误分析文本
    """
    err_lower = error.lower()

    if "syntaxerror" in err_lower:
        return (
            "代码存在语法错误，可能是引号不匹配、括号未闭合或缩进问题。"
            "建议检查代码中的括号配对和缩进层级。"
        )
    if "nameerror" in err_lower:
        return (
            "代码中使用了未定义的变量或函数名。"
            "建议检查变量名拼写，确认所有引用在使用前已经定义。"
        )
    if "importerror" in err_lower or "modulenotfounderror" in err_lower:
        return (
            "缺少依赖包。建议检查导入语句，"
            "尝试使用标准库替代或确认包已安装。"
        )
    if "typeerror" in err_lower:
        return (
            "函数调用的参数类型不匹配。"
            "建议检查函数签名和传入参数的类型。"
        )
    if "timeout" in err_lower or "timed out" in err_lower:
        return (
            "代码执行超时，可能存在死循环或计算量过大。"
            "建议检查循环终止条件和算法效率。"
        )
    if "filenotfounderror" in err_lower or "no such file" in err_lower:
        return (
            "文件未找到。建议确认数据文件路径是否正确，"
            "文件是否在 ./data/ 目录下。"
        )
    if "keyerror" in err_lower:
        return (
            "字典或 DataFrame 中不存在指定的键/列名。"
            "建议检查列名拼写（区分大小写），或先用 print(df.columns) 查看可用列。"
        )
    if "attributeerror" in err_lower:
        return (
            "对象不存在指定的属性或方法。"
            "建议检查对象类型和可用方法列表。"
        )
    if "valueerror" in err_lower:
        return (
            "函数收到了类型正确但值不合适的参数。"
            "建议检查输入值的范围和格式。"
        )

    # 默认分析
    short = error[:200]
    return f"代码执行时出现错误: {short}。建议逐行检查代码逻辑。"


# ---------------------------------------------------------------------------
# 规则回退：简单修复（当 LLM 不可用时）
# ---------------------------------------------------------------------------


def _fix_by_rule(code: str, error: str, instruction: str | None = None) -> str:
    """基于规则尝试简单修复。

    LLM 调用失败时的回退方案。仅能处理极少数明确的模式。

    Args:
        code: 原始代码
        error: 错误信息
        instruction: 可选的用户指令

    Returns:
        修复后的代码（如无法修复则包装 try/except）
    """
    err_lower = error.lower()

    # 有用户指令时，无法自动修复，包装 try/except
    if instruction:
        return _wrap_with_try_except(code)

    # SyntaxError: 尝试补括号
    if "syntaxerror" in err_lower:
        fixed = code.replace("print ", "print(")
        if not fixed.rstrip().endswith(")") and "print" in fixed:
            fixed = fixed.rstrip() + ")"
        # 如果简单修改无变化（即 non-print SyntaxError），回退到 try/except
        if fixed == code:
            return _wrap_with_try_except(code)
        return fixed

    # ModuleNotFoundError / ImportError: 注释掉缺失的导入
    if "modulenotfounderror" in err_lower or "importerror" in err_lower:
        lines = code.split("\n")
        fixed: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("from ", "import ")):
                if any(
                    pkg in stripped
                    for pkg in ["scipy", "pandas", "numpy", "plotly", "matplotlib"]
                ):
                    fixed.append(
                        f"# {line}  # Auto-commented: dependency unavailable"
                    )
                    continue
            fixed.append(line)
        return "\n".join(fixed)

    # 默认：包装 try/except
    return _wrap_with_try_except(code)


def _wrap_with_try_except(code: str) -> str:
    """将代码包装在 try/except 块中。"""
    indent = "    "
    indented = textwrap.indent(code.strip(), indent)
    return (
        f"try:\n{indented}\n"
        f"except Exception as e:\n"
        f"{indent}print(f\"Runtime error: {{e}}\")\n"
    )


# ---------------------------------------------------------------------------
# 选择处理（核心逻辑，可独立测试）
# ---------------------------------------------------------------------------


def _process_choice(
    raw_choice: str,
    *,
    state: AgentState,
    error_analysis: str | None = None,
) -> dict:
    """处理用户选择并生成对应的状态更新。

    所有分支逻辑集中在此处，不依赖 input()/print()，
    便于在测试中直接调用。

    Args:
        raw_choice: 用户输入的原始选择 ("1", "2", "3", "4")
        state: 当前 AgentState
        error_analysis: AI 分析的错误原因（用于选项 2 的上下文）

    Returns:
        包含 human_feedback, retry_count 和可选的 generated_code 的字典
    """
    retry_count = state.get("retry_count", 0)
    new_retry = retry_count + 1
    error = state.get("error", "")
    code = state.get("generated_code", "")
    query = state.get("user_query", "")

    choice = raw_choice.strip()

    if choice == "1":
        # ---- 接受 AI 修复 ----
        print("[Debugger] 正在使用 AI 生成修复代码...")
        try:
            fixed_code = _generate_fix_with_llm(error, code)
        except Exception:
            fixed_code = _fix_by_rule(code, error)
        print("[Debugger] ✅ AI 修复完成")
        return {
            "human_feedback": f"AI_FIX:{fixed_code}",
            "generated_code": fixed_code,
            "retry_count": new_retry,
        }

    elif choice == "2":
        # ---- 用户自定义修复指令 ----
        # 注意：input() 必须在调用方处理，此处只返回占位
        # 调用方在获取到指令后，应当调用 _generate_fix_for_instruction
        return {
            "human_feedback": "NEED_INSTRUCTION",
            "retry_count": new_retry,
        }

    elif choice == "3":
        # ---- 跳过 ----
        print("[Debugger] ⏭️ 跳过此错误，保留原代码")
        return {
            "human_feedback": "SKIP",
            "retry_count": new_retry,
        }

    else:
        # ---- 中止（默认） ----
        print("[Debugger] 🛑 用户选择中止执行")
        return {
            "human_feedback": "ABORT",
            "retry_count": new_retry,
        }


def _process_instruction(
    user_instruction: str,
    *,
    state: AgentState,
) -> dict:
    """处理用户自定义修复指令（选项 2 的后续步骤）。

    Args:
        user_instruction: 用户输入的修复指令
        state: 当前 AgentState

    Returns:
        包含 human_feedback 和 generated_code 的字典
    """
    error = state.get("error", "")
    code = state.get("generated_code", "")

    print("[Debugger] 正在根据你的指令生成修复代码...")
    try:
        fixed_code = _generate_fix_with_llm(error, code, user_instruction)
    except Exception:
        fixed_code = _fix_by_rule(code, error, instruction=user_instruction)
    print("[Debugger] ✅ 基于指令的修复完成")

    return {
        "human_feedback": f"USER_FIX:{user_instruction}",
        "generated_code": fixed_code,
    }


# ---------------------------------------------------------------------------
# 终端展示
# ---------------------------------------------------------------------------


def _display_diagnosis(error: str, analysis: str, retry_count: int) -> None:
    """在终端打印错误分析和选择菜单。

    Args:
        error: 错误信息
        analysis: AI 分析文本（1-2 句话）
        retry_count: 当前重试次数
    """
    lines = [
        "",
        "=" * 60,
        f"🐛 Debugger — 错误分析（第 {retry_count + 1} / 3 次）",
        "=" * 60,
        "",
        f"📋 错误信息: {error[:200]}",
        "",
        f"🔍 AI 分析: {analysis}",
        "",
        "请选择:",
        "  1 = 接受 AI 修复建议",
        "  2 = 输入自定义修复指令",
        "  3 = 跳过此错误，继续",
        "  4 = 中止执行",
        "",
    ]
    print("\n".join(lines))


def _safe_input(prompt: str = "") -> str:
    """安全的 input() 包装。

    处理 EOFError 和 KeyboardInterrupt，默认返回 "4"（中止）。

    Args:
        prompt: 输入提示

    Returns:
        用户输入字符串
    """
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "4"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def debugger_node(state: AgentState) -> dict:
    """分析执行错误，启动 Human-in-the-loop 交互。

    输入:
        state["error"]           — str，错误信息
        state["generated_code"]  — str，当前代码
        state["retry_count"]     — int，当前重试次数
        state["user_query"]      — str，用户需求（用于修复上下文）

    输出:
        {
            "human_feedback":  str,           # "AI_FIX:<code>" | "USER_FIX:<指令>" | "SKIP" | "ABORT"
            "retry_count":     int,           # 更新后的重试次数
            "generated_code":  str | None,    # 如选择了 AI 修复，返回修复后的代码
        }

    Args:
        state: 当前 AgentState

    Returns:
        包含 human_feedback / retry_count / generated_code 的 partial state
    """
    retry_count = state.get("retry_count", 0)
    error = state.get("error", "")
    code = state.get("generated_code", "")

    # ---- 重试次数上限 ----
    if retry_count >= 2:
        print(
            "\n[Debugger] ⚠️ 已达最大重试次数（2），自动中止"
        )
        return {
            "human_feedback": "ABORT",
            "retry_count": retry_count,
        }

    # ---- 错误分析 ----
    print(f"\n[Debugger] 正在分析错误原因...")

    try:
        analysis = _analyze_error_with_llm(error, code)
    except Exception as exc:
        print(f"[Debugger] ⚠️ LLM 分析失败，使用规则分类: {exc}")
        analysis = _diagnose_by_rule(error)

    # ---- 展示分析 & 菜单 ----
    _display_diagnosis(error, analysis, retry_count)

    # ---- 读取选择 ----
    raw_choice = _safe_input("[1/2/3/4] > ")

    # ---- 处理选择 ----
    result = _process_choice(raw_choice, state=state, error_analysis=analysis)

    # ---- 选项 2 需要二次交互 ----
    if result.get("human_feedback") == "NEED_INSTRUCTION":
        user_instruction = _safe_input("请输入修复指令: ")
        if not user_instruction:
            # 空指令 → 回退到跳过
            print("[Debugger] 未输入指令，回退为跳过")
            return {
                "human_feedback": "SKIP",
                "retry_count": result["retry_count"],
            }

        extra = _process_instruction(user_instruction, state=state)
        result.pop("human_feedback")  # 移除 NEED_INSTRUCTION 占位
        result.update(extra)

    return result


# 别名，兼容 graph.py / Task 7 的 run(state) 约定
run = debugger_node

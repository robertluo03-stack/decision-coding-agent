"""Debugger 节点：分析执行错误 + Human-in-the-loop 决策。

错误分析 → 生成修复建议 → 人类选择：
    1. 接受 AI 修复
    2. 输入自定义指令
    3. 跳过
    4. 中止
"""

import textwrap
import sys

from loguru import logger

from src.agent.state import AgentState


def debugger_node(state: AgentState) -> dict:
    """分析错误，等待人类决策。

    Week 1 版本：简单错误分类 + CLI 交互
    Week 3+ 版本：LLM 分析 + Streamlit UI

    Args:
        state: 当前 AgentState

    Returns:
        包含 human_feedback 和 retry_count 的 partial state
    """
    error = state.get("error", "")
    code = state.get("generated_code", "")
    retry_count = state.get("retry_count", 0)

    # 分析错误
    diagnosis = _diagnose_error(error, code)
    print(diagnosis)

    # 人类选择
    choice = _get_human_choice(state)
    return choice


def _diagnose_error(error: str, code: str) -> str:
    """简单错误分类（Week 1 规则版）。

    TODO: Week 3+ 用 LLM + debugger.md prompt 替换。
    """
    lines = [
        "=" * 60,
        "[Debugger] 执行错误分析",
        "=" * 60,
        f"错误信息: {error}",
    ]

    if "SyntaxError" in error:
        lines.append("\n分析: 代码语法错误，可能是引号/缩进问题")
        lines.append(f"建议修复: 检查代码中的引号匹配和缩进")
    elif "NameError" in error:
        lines.append("\n分析: 使用了未定义的变量或函数名")
        lines.append(f"建议修复: 检查变量名拼写，确认所有引用已定义")
    elif "ImportError" in error or "ModuleNotFoundError" in error:
        lines.append("\n分析: 缺少依赖包")
        lines.append(f"建议修复: 检查导入语句，考虑使用标准库替代")
    elif "TypeError" in error:
        lines.append("\n分析: 类型不匹配")
        lines.append(f"建议修复: 检查函数参数类型")
    elif "timeout" in error.lower() or "timed out" in error.lower():
        lines.append("\n分析: 代码执行超时（可能死循环）")
        lines.append(f"建议修复: 检查循环终止条件")
    else:
        lines.append(f"\n分析: {error[:200]}")

    lines.extend([
        "",
        "请选择:",
        "  1 = 接受 AI 修复建议",
        "  2 = 输入自定义修复指令",
        "  3 = 跳过此错误，继续",
        "  4 = 中止执行",
    ])
    return "\n".join(lines)


def _get_human_choice(state: AgentState) -> dict:
    """从 CLI 读取人类决策。"""
    retry_count = state.get("retry_count", 0)

    try:
        raw = input("\n[1/2/3/4] > ").strip()
    except (EOFError, KeyboardInterrupt):
        raw = "4"

    new_retry = retry_count + 1

    if raw == "1":
        # 接受 AI 修复 — 简单修复逻辑
        error = state.get("error", "")
        code = state.get("generated_code", "")
        fixed_code = _simple_fix(code, error)
        logger.info("Human chose: ACCEPT AI FIX")
        return {
            "human_feedback": f"AI_FIX:{fixed_code}",
            "retry_count": new_retry,
        }
    elif raw == "2":
        user_instruction = input("请输入修复指令: ").strip()
        logger.info(f"Human chose: USER FIX — {user_instruction}")
        return {
            "human_feedback": f"USER_FIX:{user_instruction}",
            "retry_count": new_retry,
        }
    elif raw == "3":
        logger.info("Human chose: SKIP")
        return {
            "human_feedback": "SKIP",
            "retry_count": new_retry,
        }
    else:
        logger.info("Human chose: ABORT")
        return {
            "human_feedback": "ABORT",
            "retry_count": new_retry,
        }


def _simple_fix(code: str, error: str) -> str:
    """简单的自动修复逻辑（Week 1 临时版）。

    TODO: Week 3+ 用 LLM 分析后生成修复代码。
    """
    if "ModuleNotFoundError" in error:
        # 尝试注释掉可能失败的导入
        lines = code.split("\n")
        fixed = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("from ") or stripped.startswith("import "):
                if any(pkg in stripped for pkg in ["scipy", "pandas", "numpy", "plotly"]):
                    fixed.append(f"# {line}  # Auto-commented: missing dependency")
                    continue
            fixed.append(line)
        return "\n".join(fixed)

    if "SyntaxError" in error and "print" in error.lower():
        # 尝试补充缺失的括号
        return code.replace("print ", "print(").replace("\n", ")\n")

    # 默认：添加 try/except 包装
    return textwrap.dedent(f"""\
        try:
        {textwrap.indent(code, '    ')}
        except Exception as e:
            print(f"Runtime error: {{e}}")
    """)

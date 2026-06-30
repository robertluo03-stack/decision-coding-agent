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

import hashlib
import os
import re
import textwrap
from typing import Any

from loguru import logger

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
# 错误信息提取辅助函数（供 _diagnose_by_rule / _fix_by_rule 使用）
# ---------------------------------------------------------------------------


def _extract_error_line(error: str) -> str:
    """从错误信息中提取行号提示。

    Args:
        error: 错误信息字符串

    Returns:
        如 "（第 5 行）" 或空字符串
    """
    # Pattern: "line 5", "line 12," "at line 7"
    for pat in [r"line (\d+)", r"在第 (\d+)", r":(\d+):"]:
        m = re.search(pat, error, re.IGNORECASE)
        if m:
            return f"（第 {m.group(1)} 行）"
    return ""


def _extract_undefined_name(error: str) -> str:
    """从 NameError 中提取未定义的名称。

    Args:
        error: 错误信息字符串

    Returns:
        未定义的变量/函数名，或空字符串
    """
    # "NameError: name 'pd' is not defined"
    m = re.search(r"name '(\w+)' is not defined", error)
    if m:
        return m.group(1)
    return ""


def _extract_missing_module(error: str) -> str:
    """从 ModuleNotFoundError 中提取缺失的模块名。

    Args:
        error: 错误信息字符串

    Returns:
        缺失的模块名，或空字符串
    """
    # "ModuleNotFoundError: No module named 'pandas'"
    m = re.search(r"No module named '(\w+)'", error)
    if m:
        return m.group(1)
    return ""


def _extract_key_name(error: str) -> str:
    """从 KeyError 中提取缺失的键名。

    Args:
        error: 错误信息字符串

    Returns:
        缺失的键名，或空字符串
    """
    # "KeyError: 'sku'" or "KeyError('sku')"
    m = re.search(r"KeyError[(:]\s*'([^']+)'", error)
    if m:
        return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# 规则回退：简单错误分类（当 LLM 不可用时）
# ---------------------------------------------------------------------------


def _diagnose_by_rule(error: str) -> str:
    """基于规则的错误分类与诊断（LLM 不可用时的回退方案）。

    覆盖 Python 最常见的 12 类运行时/编译时错误，
    每类提供中文诊断文本和具体的修复建议。

    Args:
        error: 错误信息字符串（来自 Executor 的 stderr / error 字段）

    Returns:
        中文错误分析文本（2-4 句话），包含原因和修复方向
    """
    err_lower = error.lower()

    # ---- SyntaxError: 语法/缩进错误 ----
    if "syntaxerror" in err_lower or "indentationerror" in err_lower:
        # 尝试提取行号
        line_hint = _extract_error_line(error)
        return (
            f"代码存在语法错误{line_hint}，常见原因：引号/括号不匹配、"
            f"缩进层级不一致、缺少冒号（:）、"
            f"表达式不完整（如 print 缺少闭合括号）。"
            f"建议逐行检查第{line_hint}附近的括号配对和缩进层级。"
        )

    # ---- NameError: 未定义的变量/函数 ----
    if "nameerror" in err_lower:
        name = _extract_undefined_name(error)
        hint = f"（'{name}'）" if name else ""
        return (
            f"代码中使用了未定义的变量或函数名{hint}。"
            f"建议检查变量名拼写是否正确、是否忘记导入模块、"
            f"定义是否在引用之前。常见遗漏：import pandas/import math。"
        )

    # ---- ModuleNotFoundError / ImportError: 缺失依赖 ----
    if "modulenotfounderror" in err_lower or "importerror" in err_lower:
        mod = _extract_missing_module(error)
        mod_hint = f"（{mod}）" if mod else ""
        return (
            f"缺少依赖模块{mod_hint}。"
            f"建议：1) 确认模块已安装（pip install {mod}）；"
            f"2) 使用标准库替代（如 csv 代替 pandas, json 代替 yaml）；"
            f"3) 检查模块名拼写是否正确（区分大小写）。"
        )

    # ---- TypeError: 类型不匹配 ----
    if "typeerror" in err_lower:
        return (
            "函数调用的参数类型不匹配。"
            "常见原因：整数与字符串拼接、传给函数的参数数量或类型不对、"
            "None 作为可迭代对象使用。"
            "建议：1) 用 type() 或 print() 确认变量类型；"
            "2) 使用 str()/int()/float() 显式转换；"
            "3) 检查函数签名与传入参数是否一致。"
        )

    # ---- IndexError: 索引越界 ----
    if "indexerror" in err_lower:
        return (
            "列表/元组索引超出范围。"
            "常见原因：访问的索引 >= 序列长度、空列表取第 0 个元素、"
            "循环中的索引变量超出末尾。"
            "建议：访问前检查 len(seq) 是否大于索引，"
            "或使用 try/except IndexError 保护边界操作。"
        )

    # ---- KeyError: 键不存在 ----
    if "keyerror" in err_lower:
        key = _extract_key_name(error)
        key_hint = f"（'{key}'）" if key else ""
        return (
            f"字典或 DataFrame 中不存在指定的键/列名{key_hint}。"
            f"建议：1) 检查键名拼写（区分大小写）；"
            f"2) 对于 DataFrame 先用 print(df.columns) 查看可用列；"
            f"3) 使用 dict.get(key, default) 提供默认值避免 KeyError。"
        )

    # ---- ZeroDivisionError: 除零错误 ----
    if "zerodivisionerror" in err_lower:
        return (
            "代码中存在除以零的操作。"
            "常见原因：分母变量为 0、数据中某列为空导致求和/均值为 0。"
            "建议：1) 在除法前添加条件判断 if divisor != 0；"
            "2) 使用 try/except ZeroDivisionError 捕获异常；"
            "3) 检查数据源是否存在全零或空值列。"
        )

    # ---- ValueError: 值错误 ----
    if "valueerror" in err_lower:
        return (
            "函数收到了类型正确但值不合适的参数。"
            "常见原因：数学运算传入负数、字符串转数字格式不正确、"
            "数组形状不一致。"
            "建议：1) 检查输入值的范围和格式；2) 用 print() 输出中间值定位；"
            "3) 添加参数合法性校验。"
        )

    # ---- AttributeError: 属性不存在 ----
    if "attributeerror" in err_lower:
        return (
            "对象不存在指定的属性或方法。"
            "常见原因：对象为 None 后调用方法、变量类型与预期不符、"
            "拼写错误（如 .lower() 写成 .lower()）。"
            "建议：1) 用 print(type(obj)) 确认类型；"
            "2) 检查方法名拼写；3) 用 hasattr(obj, 'name') 防御性检查。"
        )

    # ---- FileNotFoundError: 文件缺失 ----
    if "filenotfounderror" in err_lower or "no such file" in err_lower:
        return (
            "文件未找到。"
            "建议：1) 确认文件路径是否正确（相对路径需相对于执行目录）；"
            "2) 文件是否存在于 ./data/ 目录下；"
            "3) 用 os.path.exists(path) 检查文件是否存在再读取。"
        )

    # ---- Timeout: 执行超时 ----
    if "timeout" in err_lower or "timed out" in err_lower:
        return (
            "代码执行超时，可能存在死循环或计算量过大。"
            "建议：1) 检查循环终止条件是否正确；2) 确认 while 循环有递增/退出逻辑；"
            "3) 大数据集可先取子集（df.head(100)）测试；"
            "4) 考虑使用更高效的算法或数据结构。"
        )

    # ---- 未知错误：通用提示 ----
    short = error[:200] if error else "(无错误信息)"
    return (
        f"未知错误，建议检查代码逻辑。"
        f"错误摘要：{short}。"
        f"可能原因：第三方库抛出的自定义异常、权限问题、或资源不足。"
        f"建议逐行排查代码，或添加 print() 定位崩溃点。"
    )


# ---------------------------------------------------------------------------
# 规则回退：简单修复（当 LLM 不可用时）
# ---------------------------------------------------------------------------


def _fix_by_rule(code: str, error: str, instruction: str | None = None) -> str:
    """基于规则尝试自动修复代码（LLM 不可用时的回退方案）。

    按错误类型采用不同修复策略，优先级从高到低：
      1. SyntaxError — 尝试补全缺失的括号/引号
      2. ModuleNotFoundError / ImportError — 注释掉缺失的导入
      3. ZeroDivisionError — 添加除零保护条件
      4. NameError — 提示缺少导入（不修改代码结构）
      5. KeyError — 包装 .get() 防御性访问
      6. 默认 — try/except 包装

    Args:
        code: 原始 Python 代码
        error: 错误信息字符串
        instruction: 可选用户修复指令。有指令时直接走 try/except 包装

    Returns:
        修复后的代码字符串
    """
    err_lower = error.lower()

    # 有用户指令时，无法自动修复，包装 try/except 并注入指令注释
    if instruction:
        return _wrap_with_try_except(
            code, comment=f"用户指令: {instruction}"
        )

    # ---- SyntaxError: 尝试补全括号/引号 ----
    if "syntaxerror" in err_lower or "indentationerror" in err_lower:
        # 提取行号，尝试定位修复
        line_num = _extract_error_line_number(error)
        return _fix_syntax_error(code, line_num)

    # ---- ModuleNotFoundError / ImportError: 注释掉缺失的导入 ----
    if "modulenotfounderror" in err_lower or "importerror" in err_lower:
        return _fix_missing_import(code, error)

    # ---- ZeroDivisionError: 添加除零保护 ----
    if "zerodivisionerror" in err_lower:
        return _fix_division_by_zero(code)

    # ---- NameError: 提供缺失导入提示（不修改代码结构） ----
    if "nameerror" in err_lower:
        return _fix_name_error(code, error)

    # ---- KeyError: 提示用 .get() 防御 ----
    if "keyerror" in err_lower:
        return _fix_key_error(code, error)

    # ---- IndexError: try/except 包裹 ----
    if "indexerror" in err_lower:
        return _wrap_with_try_except(code, comment="IndexError: 索引越界防护")

    # ---- TypeError: try/except 包裹 ----
    if "typeerror" in err_lower:
        return _wrap_with_try_except(code, comment="TypeError: 类型不匹配防护")

    # ---- ValueError: try/except 包裹 ----
    if "valueerror" in err_lower:
        return _wrap_with_try_except(code, comment="ValueError: 值错误防护")

    # ---- AttributeError: try/except 包裹 ----
    if "attributeerror" in err_lower:
        return _wrap_with_try_except(code, comment="AttributeError: 属性不存在防护")

    # ---- 未知错误: 通用 try/except 包装 ----
    return _wrap_with_try_except(code, comment="规则回退: 通用异常防护")


def _wrap_with_try_except(code: str, comment: str = "") -> str:
    """将代码包装在 try/except 块中，提供运行时错误保护。

    Args:
        code: 原始 Python 代码
        comment: 可选的注释，会插入 try 块之前说明包装原因

    Returns:
        包装后的代码字符串
    """
    indent = "    "
    indented = textwrap.indent(code.strip(), indent)
    if comment:
        header = f"# {comment}\n"
    else:
        header = ""
    return (
        f"{header}try:\n{indented}\n"
        f"except Exception as e:\n"
        f"{indent}print(f\"Runtime error: {{e}}\")\n"
    )


# ---------------------------------------------------------------------------
# 规则修复辅助函数（供 _fix_by_rule 使用）
# ---------------------------------------------------------------------------


def _extract_error_line_number(error: str) -> int:
    """从错误信息中提取行号（整数）。

    Args:
        error: 错误信息字符串

    Returns:
        行号整数，或 0 表示未找到
    """
    for pat in [r"line (\d+)", r"在第 (\d+)", r":(\d+):"]:
        m = re.search(pat, error, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return 0


def _fix_syntax_error(code: str, line_num: int) -> str:
    """尝试修复常见语法错误。

    策略：
      - 第 1 行：补 print 括号
      - 任意行：检查括号配对并补全
      - 无法定位：包装 try/except

    Args:
        code: 原始代码
        line_num: 错误行号（0 = 未知）

    Returns:
        修复后的代码
    """
    # 常见 print 缺少括号
    fixed = code.replace("print ", "print(")
    if "print" in fixed:
        # 为每行独立的 print 补括号
        lines = fixed.split("\n")
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("print("):
                if not stripped.rstrip().endswith(")"):
                    line = line.rstrip() + ")"
            new_lines.append(line)
        fixed = "\n".join(new_lines)
    else:
        fixed = code

    # 检查括号配对是否失衡（简单计数）
    if _has_unbalanced_parens(fixed):
        # 尝试补全缺失的闭合括号
        if fixed.rstrip()[-1] not in (")", "]", "}", "'", '"'):
            fixed = fixed.rstrip() + ")"
        else:
            fixed += ")"

    # 修复后有变化 → 返回；无变化 → 回退
    if fixed == code:
        return _wrap_with_try_except(code, comment="SyntaxError: 自动修复未成功，已添加异常保护")
    return fixed


def _has_unbalanced_parens(code: str) -> bool:
    """快速检查括号是否失衡。

    Args:
        code: 源代码字符串

    Returns:
        True 表示括号数量不匹配
    """
    pairs = [("(", ")"), ("[", "]"), ("{", "}")]
    for left, right in pairs:
        if code.count(left) != code.count(right):
            return True
    return False


def _fix_missing_import(code: str, error: str) -> str:
    """处理缺失模块导入：注释掉不可用的导入行。

    匹配错误信息中的模块名，注释对应行。
    保留标准库导入（os/sys/math/csv/...）。

    Args:
        code: 原始代码
        error: 错误信息

    Returns:
        修复后的代码
    """
    mod = _extract_missing_module(error)
    stdlib = frozenset({
        "os", "sys", "math", "csv", "json", "re", "time", "datetime",
        "pathlib", "collections", "itertools", "functools", "typing",
        "hashlib", "uuid", "textwrap", "tempfile", "subprocess",
    })

    # 标准库不应出现 ModuleNotFoundError，保持原样
    if mod and mod in stdlib:
        return _wrap_with_try_except(
            code, comment=f"ModuleNotFoundError: {mod}（标准库，检查环境）"
        )

    lines = code.split("\n")
    fixed_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("from ", "import ")):
            # 检测是否匹配缺失模块
            if mod and mod.lower() in stripped.lower():
                fixed_lines.append(
                    f"# {line}  # 规则回退: 缺失模块 {mod}，已注释"
                )
                continue
            # 常见重量级第三方库，缺失时注释掉
            if any(
                pkg in stripped.lower()
                for pkg in ("scipy", "pandas", "numpy", "plotly", "matplotlib",
                           "tensorflow", "torch", "sklearn", "xgboost", "lightgbm",
                           "seaborn", "pillow", "opencv")
            ):
                fixed_lines.append(
                    f"# {line}  # 规则回退: 缺失第三方库，已注释"
                )
                continue
        fixed_lines.append(line)
    return "\n".join(fixed_lines)


def _fix_division_by_zero(code: str) -> str:
    """为零除错误添加保护条件。

    识别常见的除法模式 (a / b) 并包装 if 保护。

    Args:
        code: 原始代码

    Returns:
        添加除零保护后的代码
    """
    # 简单策略：在代码块前添加除零检查的提示
    # 更复杂的 AST 重构由 LLM 完成
    preamble = textwrap.dedent("""\
        # 规则回退: 添加除零保护
        # 请检查所有除法运算的分母，确保不为 0

    """)
    # 尝试将常见写法 a / b 包装
    if "/" in code:
        # 简易保护：用 try/except ZeroDivisionError 包裹
        return _wrap_with_try_except(code, comment="ZeroDivisionError: 除零保护")
    return preamble + code


def _fix_name_error(code: str, error: str) -> str:
    """为 NameError 提供修复提示。

    尝试识别缺失的变量名并添加注释提示。

    Args:
        code: 原始代码
        error: 错误信息

    Returns:
        带注释提示和 try/except 保护的代码
    """
    name = _extract_undefined_name(error)
    hint_lines = [
        "# 规则回退: NameError — 变量未定义",
    ]
    if name:
        hint_lines.append(f"# 缺失变量: '{name}'")
        # 常见模式的修复建议
        if "pd" in name:
            hint_lines.append("# 建议: 添加 import pandas as pd")
        elif "np" in name:
            hint_lines.append("# 建议: 添加 import numpy as np")
        elif "math" in name:
            hint_lines.append("# 建议: 添加 import math")
        elif "plt" in name:
            hint_lines.append("# 建议: 添加 import matplotlib.pyplot as plt")
        else:
            hint_lines.append(f"# 建议: 检查 '{name}' 的拼写，或在使用前定义")
    hint_lines.append("")
    return "\n".join(hint_lines) + _wrap_with_try_except(
        code, comment="NameError: 变量未定义防护"
    )


def _fix_key_error(code: str, error: str) -> str:
    """为 KeyError 提供防御性访问提示。

    尝试将 dict[key] 转换为 dict.get(key)。

    Args:
        code: 原始代码
        error: 错误信息

    Returns:
        修复后的代码
    """
    key = _extract_key_name(error)
    hint_lines = [
        "# 规则回退: KeyError — 键不存在",
    ]
    if key:
        hint_lines.append(f"# 缺失键: '{key}'")
        hint_lines.append(f"# 建议: 使用 dict.get('{key}', default) 或 df.columns 检查列名")
    hint_lines.append("")
    return "\n".join(hint_lines) + _wrap_with_try_except(
        code, comment="KeyError: 键不存在防护"
    )
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
        包含 human_feedback, retry_count 和可选的 generated_code 的字典。
        LangGraph 按 partial state 合并，未返回的字段（如 error/file_path）在图中保持不变。
    """
    retry_count = state.get("retry_count", 0)
    # 新重试次数 = 当前 + 1。与 debugger_node 入口上限检查协同：
    #   - 当前 retry_count=0 → _process_choice 返回1，Coder→Executor→重新分析。
    #   - 当前 retry_count=1 → _process_choice 返回2，再次出现错误后，下次进入
    #     debugger_node 时上限检查触发直接 ABORT。
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
            logger.error("[Debugger] AI 修复失败，回退到规则修复")
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
        logger.error("[Debugger] 基于指令的修复失败，回退到规则修复")
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

    retry_count 生命周期（与 graph.py 路由协同）:
        retry=0 首次错误 → Debugger 分析 + 修复 → Coder → Executor
        retry=1 再次错误 → Debugger 分析 + 修复 → Coder → Executor
        retry=2 第三次错误 → Debugger 入口上限检查 → 直接 ABORT → Reporter
        正常流程最多 2 次重试，第 3 个错误直接终止。

    Args:
        state: 当前 AgentState

    Returns:
        包含 human_feedback / retry_count / generated_code 的 partial state
    """
    retry_count = state.get("retry_count", 0)
    error = state.get("error", "")
    code = state.get("generated_code", "")

    # ---- 入口日志 ----
    logger.info(
        "[Debugger] 进入节点 | error={!r} | code_len={} | code_hash={} | retry_count={}",
        (error or "")[:100],
        len(code),
        hashlib.md5(code.encode()).hexdigest()[:8] if code else "N/A",
        retry_count,
    )

    # ---- 重试次数上限 ----
    # 约束：根据 AgentState 设计，retry_count >= 2 时强制终止循环，
    # 不再调用 LLM（节省 token），直接返回 ABORT 进入 Reporter。
    # 此时不递增 retry_count — 已触发上限，立即终止绕开所有 LLM 调用。
    # flow: Executor(error) → Debugger(entry check) → Reporter(ABORT)
    if retry_count >= 2:
        abort_msg = "已达到最大重试次数（2），强制终止"
        logger.warning("[Debugger] {}", abort_msg)
        print(f"\n[Debugger] ⚠️ {abort_msg}")
        logger.info(
            "[Debugger] 退出节点（重试上限） | human_feedback=ABORT | retry_count={} | error={!r}",
            retry_count,
            abort_msg,
        )
        return {
            "human_feedback": "ABORT",
            "retry_count": retry_count,
            "error": abort_msg,
        }

    # ---- 错误分析 ----
    print(f"\n[Debugger] 正在分析错误原因...")

    try:
        analysis = _analyze_error_with_llm(error, code)
    except Exception as exc:
        logger.error("[Debugger] LLM 分析失败，使用规则分类 | type={} | message={}", type(exc).__name__, exc)
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
            # 空指令 → 回退到跳过。retry_count 保持 process_choice 返回的值（已递增）。
            print("[Debugger] 未输入指令，回退为跳过")
            return {
                "human_feedback": "SKIP",
                "retry_count": result["retry_count"],
            }

        extra = _process_instruction(user_instruction, state=state)
        result.pop("human_feedback")  # 移除 NEED_INSTRUCTION 占位
        result.update(extra)

    # ---- 出口日志 ----
    fb = result.get("human_feedback", "?")
    logger.info(
        "[Debugger] 退出节点 | human_feedback={!r} | retry_count={} | new_code_len={}",
        fb[:80],
        result.get("retry_count", retry_count),
        len(result.get("generated_code", "")),
    )

    return result


# 别名，兼容 graph.py / Task 7 的 run(state) 约定
run = debugger_node

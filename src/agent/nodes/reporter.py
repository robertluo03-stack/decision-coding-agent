"""Reporter 节点：生成 Markdown 格式的最终执行报告。

支持的两种报告模式：
  - 成功报告（无 error，且非 ABORT）：标题 "执行报告"
  - 中止报告（human_feedback == "ABORT"）：标题 "任务中止报告"

报告结构：
  1. 任务描述
  2. 执行计划
  3. 执行结果
  4. 结果分析（LLM 深度分析，失败时规则回退）
  5. 错误信息与调试记录（有 error 或 ABORT 时出现）
  附录 — 生成代码、图表链接、工作区路径
"""

import os
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.agent.state import AgentState
from src.agent.nodes.prompts.loader import load_prompt


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def reporter_node(state: AgentState) -> dict:
    """汇总全流程信息，生成 Markdown 报告并写入 reports/ 目录。

    输入:
        state["user_query"]        — str，用户原始需求
        state["plan"]              — List[str]，执行计划
        state["generated_code"]    — str，生成的代码
        state["execution_result"]  — str | None，stdout
        state["error"]             — str | None，错误信息
        state["retry_count"]       — int，重试次数
        state["human_feedback"]    — str | None，人在回路反馈
        state["workspace_path"]    — str，工作区路径
        state["file_path"]         — str | None，临时文件路径

    输出:
        {"final_report": "完整 Markdown 报告字符串"}

    副作用:
        将报告写入 workspace/reports/report_<timestamp>.md

    Args:
        state: 当前（最终）AgentState

    Returns:
        包含 final_report 的 partial state
    """
    is_aborted = state.get("human_feedback") == "ABORT"
    has_error = bool(state.get("error"))

    # ---- 入口日志 ----
    logger.info(
        "[Reporter] 进入节点 | is_aborted={} | has_error={} | retry_count={} | plan_steps={} | code_len={}",
        is_aborted,
        has_error,
        state.get("retry_count", 0),
        len(state.get("plan", [])),
        len(state.get("generated_code", "")),
    )

    report = _build_report(state, is_aborted=is_aborted, has_error=has_error)
    filepath = _write_report(state, report)

    # ---- 出口日志 ----
    logger.info(
        "[Reporter] 退出节点 | report_len={} | file_path={}",
        len(report),
        str(filepath),
    )

    print(f"[Reporter] 报告已写入: {filepath}")
    return {"final_report": report}


# ---------------------------------------------------------------------------
# 报告构建
# ---------------------------------------------------------------------------

def _build_report(
    state: AgentState,
    *,
    is_aborted: bool = False,
    has_error: bool = False,
) -> str:
    """构建 Markdown 报告内容。

    报告结构：
        1. 标题与元信息（时间、状态）
        2. 原始需求
        3. 执行计划
        4. 执行结果（如存在）
        5. 结果分析（LLM 深度分析 + 规则回退）
        6. 错误信息 & 调试记录（如存在）
        附录（生成代码、图表链接、工作区路径）

    Args:
        state: 当前 AgentState
        is_aborted: 是否为人中止
        has_error: 是否有执行错误

    Returns:
        Markdown 格式的报告字符串
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 标题 ----
    if is_aborted:
        title = "# 任务中止报告"
        status_icon = "🛑"
        status_text = "用户中止"
    elif has_error:
        title = "# 执行报告"
        status_icon = "⚠️"
        status_text = "执行异常"
    else:
        title = "# 执行报告"
        status_icon = "✅"
        status_text = "执行成功"

    lines = [
        title,
        "",
        f"**生成时间**: {now}",
        f"**状态**: {status_icon} {status_text}",
        "",
        "---",
        "",
        "## 1. 任务描述",
        "",
    ]

    # ---- 原始需求 ----
    query = state.get("user_query", "")
    if query:
        lines.append(f"> {query}")
    else:
        lines.append("> *(用户未提供需求)*")
    lines.append("")

    # ---- 执行计划 ----
    lines.append("## 2. 执行计划")
    lines.append("")
    plan = state.get("plan", [])
    if plan:
        for step in plan:
            lines.append(f"- {step}")
    else:
        lines.append("- *(无执行计划)*")
    lines.append("")

    # ---- 执行结果 ----
    exec_result = state.get("execution_result")
    if exec_result:
        lines.append("## 3. 执行结果")
        lines.append("")
        lines.append("```")
        lines.append(exec_result)
        lines.append("```")
        lines.append("")

    # ---- 结果分析（LLM 深度分析） ----
    analysis = _generate_analysis_with_llm(state, is_aborted=is_aborted, has_error=has_error)
    lines.append("## 4. 结果分析")
    lines.append("")
    lines.append(analysis)
    lines.append("")

    # ---- 错误信息 & 调试记录 ----
    error = state.get("error")
    retry_count = state.get("retry_count", 0)
    human_feedback = state.get("human_feedback")

    if error or is_aborted:
        lines.append("## 5. 错误信息与调试记录")
        lines.append("")

    if error:
        lines.append("### 错误详情")
        lines.append("")
        lines.append("```")
        lines.append(error)
        lines.append("```")
        lines.append("")

    # 调试记录（重试次数 + 人在回路反馈）
    debug_parts = []
    debug_parts.append(f"- **重试次数**: {retry_count} / 2")

    if human_feedback:
        feedback_label = _format_feedback_label(human_feedback)
        debug_parts.append(f"- **人在回路反馈**: {feedback_label}")

    if is_aborted:
        debug_parts.append("- **结果**: 用户主动中止，未继续执行")
    elif error and retry_count >= 2:
        debug_parts.append("- **结果**: 已达最大重试次数，强制终止")

    if debug_parts:
        lines.append("### 调试记录")
        lines.append("")
        lines.extend(debug_parts)
        lines.append("")

    # ---- 附录（代码 + 图表 + 文件路径） ----
    lines.append("---")
    lines.append("")
    lines.append("## 附录")
    lines.append("")

    # 生成代码（放在附录中）
    lines.append("### 生成代码")
    lines.append("")
    lines.append("```python")
    code = state.get("generated_code", "")
    if code:
        lines.append(code)
    else:
        lines.append("# (无代码)")
    lines.append("```")
    lines.append("")

    # 工作区 & 文件路径
    lines.append(f"- **工作区**: `{state.get('workspace_path', 'N/A')}`")
    lines.append(f"- **临时执行文件**: `{state.get('file_path', 'N/A')}`")
    lines.append(f"- **报告文件**: `workspace/reports/{'fail' if is_aborted else 'report'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md`")

    # ---- 图表文件检测 ----
    chart_links = _detect_chart_files(state)
    if chart_links:
        lines.append("")
        lines.append("### 生成的图表")
        lines.append("")
        for link in chart_links:
            lines.append(f"- {link}")
    lines.append("")

    return "\n".join(lines)


def _format_feedback_label(feedback: str) -> str:
    """将 human_feedback 内部编码转为可读标签。

    Args:
        feedback: human_feedback 字符串

    Returns:
        人类可读的标签
    """
    if feedback.startswith("AI_FIX:"):
        return "接受 AI 修复"
    if feedback.startswith("USER_FIX:"):
        return f"用户自定义修复: {feedback[len('USER_FIX:'):]}"
    if feedback == "ABORT":
        return "中止执行"
    if feedback == "SKIP":
        return "跳过当前步骤"
    return feedback  # 未识别的直接原文显示


# ---------------------------------------------------------------------------
# LLM 结果分析
# ---------------------------------------------------------------------------


def _generate_analysis_with_llm(
    state: AgentState,
    *,
    is_aborted: bool = False,
    has_error: bool = False,
) -> str:
    """使用 DeepSeek API 对执行结果进行深度分析。

    基于用户需求、执行计划、执行结果，生成包含逻辑链的专业分析报告。

    Args:
        state: 当前 AgentState
        is_aborted: 是否人中止
        has_error: 是否有执行错误

    Returns:
        Markdown 格式的分析文本（3-5 段）
    """
    query = state.get("user_query", "")
    plan = state.get("plan", [])
    exec_result = state.get("execution_result", "")
    error = state.get("error", "")

    # 构建用户消息
    user_message_parts = []
    user_message_parts.append(f"用户需求: {query}")
    user_message_parts.append("")
    user_message_parts.append("执行计划:")
    for i, step in enumerate(plan, 1):
        user_message_parts.append(f"  {i}. {step}")
    user_message_parts.append("")

    if is_aborted:
        user_message_parts.append(f"执行状态: 用户主动中止")
        user_message_parts.append(f"错误信息: {error}")
    elif has_error:
        user_message_parts.append(f"执行状态: 执行异常")
        user_message_parts.append(f"错误信息: {error}")
    else:
        user_message_parts.append("执行状态: 成功")

    if exec_result:
        user_message_parts.append("")
        user_message_parts.append("执行输出:")
        user_message_parts.append("```")
        # 截取前 3000 字符，避免 token 超限
        truncated = exec_result[:3000]
        if len(exec_result) > 3000:
            truncated += "\n... (输出已截断)"
        user_message_parts.append(truncated)
        user_message_parts.append("```")

    user_message = "\n".join(user_message_parts)

    # 尝试调用 LLM
    try:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY 未设置")

        from langchain_deepseek import ChatDeepSeek

        llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=api_key,
            temperature=0.3,
            request_timeout=120,
            max_retries=2,
        )

        messages = [
            {"role": "system", "content": load_prompt("reporter_analysis.md")},
            {"role": "user", "content": user_message},
        ]

        response = llm.invoke(messages)
        content = response.content.strip()
        logger.info("[Reporter] LLM 分析完成 | analysis_len={}", len(content))
        return content

    except Exception as exc:
        logger.warning("[Reporter] LLM 分析失败，回退到规则摘要 | error={}", exc)
        return _generate_fallback_analysis(state, is_aborted=is_aborted, has_error=has_error)


def _generate_fallback_analysis(
    state: AgentState,
    *,
    is_aborted: bool = False,
    has_error: bool = False,
) -> str:
    """LLM 不可用时的规则回退分析。

    Args:
        state: 当前 AgentState
        is_aborted: 是否人中止
        has_error: 是否执行异常

    Returns:
        简短的 Markdown 分析文本
    """
    query = state.get("user_query", "")
    plan = state.get("plan", [])
    exec_result = state.get("execution_result", "")
    error = state.get("error", "")
    retry_count = state.get("retry_count", 0)

    parts = []

    # 总体评估
    if is_aborted:
        parts.append("### 总体评估")
        parts.append("")
        parts.append(f"任务已于重试 {retry_count} 次后被中止。错误原因：{error[:200] if error else '未知'}。建议检查输入数据或调整需求后重试。")
    elif has_error:
        parts.append("### 总体评估")
        parts.append("")
        parts.append(f"任务执行异常，经过 {retry_count} 次重试后仍未成功。")
        if error:
            parts.append(f"错误：{error[:300]}")
    else:
        parts.append("### 总体评估")
        parts.append("")
        parts.append(f"任务执行成功，共完成 {len(plan)} 个步骤。")
        if exec_result:
            # 尝试提取关键指标
            result_text = exec_result[:2000]
            lines_count = len(result_text.split("\n"))
            parts.append(f"输出共 {lines_count} 行，详细结果见上方执行输出。")

    parts.append("")
    parts.append("### 说明")
    parts.append("")
    parts.append("*(此为规则生成的简短摘要。设置 DEEPSEEK_API_KEY 环境变量可获得 LLM 深度分析。)*")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 图表文件检测
# ---------------------------------------------------------------------------


def _detect_chart_files(state: AgentState) -> list[str]:
    """检测 workspace/reports/charts/ 下的 HTML 图表文件。

    为每个找到的 .html 文件生成 Markdown 链接，用于附录中引用。

    Args:
        state: AgentState（用于获取 workspace_path）

    Returns:
        格式为 `[文件名](charts/<文件名>.html)` 的 Markdown 链接列表，
        未找到任何图表时返回空列表。
    """
    workspace = Path(state.get("workspace_path", "."))
    chart_dir = workspace / "reports" / "charts"

    if not chart_dir.is_dir():
        return []

    html_files = sorted(chart_dir.glob("*.html"))
    if not html_files:
        return []

    links: list[str] = []
    for f in html_files:
        name = f.stem
        links.append(f"- [{name}](charts/{f.name})")

    return links


# ---------------------------------------------------------------------------
# 文件写入
# ---------------------------------------------------------------------------


def _write_report(state: AgentState, report: str) -> Path:
    """将报告写入 workspace/reports/ 目录。

    文件命名规则：
      - 执行成功/异常（非 ABORT）→ report_<timestamp>.md
      - 中止执行（ABORT）         → fail_<timestamp>.md

    自动创建 reports/ 目录（如不存在）。

    Args:
        state: AgentState（用于获取 workspace_path 和 human_feedback）
        report: Markdown 报告内容

    Returns:
        写入的文件绝对路径
    """
    workspace = Path(state.get("workspace_path", "."))
    report_dir = workspace / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    is_aborted = state.get("human_feedback") == "ABORT"
    prefix = "fail" if is_aborted else "report"
    filename = f"{prefix}_{ts}.md"
    filepath = report_dir / filename

    filepath.write_text(report, encoding="utf-8")
    return filepath.resolve()


# 别名，兼容 graph.py / Task 7 的 run(state) 约定
run = reporter_node

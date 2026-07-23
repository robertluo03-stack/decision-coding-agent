"""Benchmark 结果验证器。

validate_task_result(task, state, elapsed_seconds, workspace_path) → BenchmarkResult

两套关键词独立校验：
1. expected_keywords（结果词）：全部命中 ⇒ success
   — 任何正确完成任务的系统都应产出：数值、领域术语、数据引用。
2. template_keywords（机制词）：不计入 success，单独统计 template_hit_rate
   — 只有本项目模板/函数才会产出：函数名、模块名、属性名。

关键词匹配：不区分大小写，支持部分匹配（substring）。
浮点数宽松匹配：预期 "223" 匹配 "223.61"。
"""

from __future__ import annotations

import os
from pathlib import Path

from src.benchmark.models import BenchmarkResult, BenchmarkTask


def validate_task_result(
    task: BenchmarkTask,
    state: dict,
    elapsed_seconds: float,
    workspace_path: str,
) -> BenchmarkResult:
    """验证单次任务执行结果。

    Args:
        task: 原始任务定义。
        state: graph.invoke() 返回的最终 AgentState。
        elapsed_seconds: 总耗时（秒）。
        workspace_path: 工作区根路径（用于查找生成的报告/图表文件）。

    Returns:
        BenchmarkResult（completed, success, retry_count, error, keywords_found,
        template_keywords_found, report_path, needs_manual_review, aborted）。
    """
    final_report = state.get("final_report", "")
    execution_result = state.get("execution_result", "")
    error = state.get("error")
    human_feedback = state.get("human_feedback", "")

    # ── ABORT 判定（从 graph 最终状态，不靠文本猜测） ──
    is_aborted = human_feedback == "ABORT"

    # ── 失败报告路径检测（兜底：即使 human_feedback 未透传） ──
    ws = Path(workspace_path)
    reports_dir = ws / "reports"
    if reports_dir.exists():
        fail_files = list(reports_dir.glob("fail_*.md"))
        if fail_files:
            is_aborted = True

    # ── completed: 有 final_report 或无错误的 execution_result ──
    completed = bool(final_report) or bool(execution_result)

    # ── 合并所有输出文本用于关键词搜索 ──
    output_text = f"{execution_result} {final_report}".lower()

    # ── 结果词匹配（expected_keywords） ──
    keywords_found: list[str] = []
    for kw in task.expected_keywords:
        found = _keyword_found(output_text, kw)
        if found:
            keywords_found.append(kw)

    all_result_found = len(keywords_found) == len(task.expected_keywords)

    # ── 机制词匹配（template_keywords）—— 不计入 success ──
    template_found: list[str] = []
    for kw in task.template_keywords:
        found = _keyword_found(output_text, kw)
        if found:
            template_found.append(kw)

    # ── success: completed + 所有结果词命中 + 非 ABORT（失败否决） ──
    success = completed and all_result_found and not is_aborted

    # ── 检查报告/图表文件 ──
    report_path = _find_generated_files(workspace_path, task)

    return BenchmarkResult(
        task_id=task.id,
        success=success,
        completed=completed,
        aborted=is_aborted,
        retry_count=state.get("retry_count", 0),
        elapsed_seconds=elapsed_seconds,
        error=str(error) if error else None,
        output_keywords_found=keywords_found,
        template_keywords_found=template_found,
        expected_keywords=task.expected_keywords,
        report_path=report_path,
        needs_manual_review=task.needs_manual_review,
    )


def _keyword_found(output_text: str, keyword: str) -> bool:
    """检查关键词是否在输出中出现（不区分大小写，部分匹配）。

    浮点数宽松匹配：预期"223"匹配实际"223.61"——只要 keyword 是输出中某词的子串。
    反向亦然：如果输出中包含 keyword 的子串，也认为匹配（如 "1.64" 匹配 "1.6449"）。

    Args:
        output_text: 输出文本（会自动转小写）。
        keyword: 预期关键词。

    Returns:
        是否匹配。
    """
    text_lower = output_text.lower()
    kw_lower = keyword.lower()
    if kw_lower in text_lower:
        return True
    # 浮点数宽松匹配：keyword 是数字，检查输出中是否有以此开头的数字
    if _is_numeric_keyword(kw_lower):
        # 检查输出中是否有数字以此关键词为前缀（如 "223" → "223.61"）
        # 反向：输出中的浮点数字若以 keyword 开头则匹配
        import re
        for num in re.findall(r'\d+\.?\d*', text_lower):
            if num.startswith(kw_lower) or kw_lower.startswith(num):
                return True
    return False


def _is_numeric_keyword(keyword: str) -> bool:
    """判断关键词是否为纯数值（整数或浮点数）。

    Args:
        keyword: 小写关键词。

    Returns:
        是否为数值关键词。
    """
    try:
        float(keyword)
        return True
    except ValueError:
        return False


def _find_generated_files(workspace_path: str, task: BenchmarkTask) -> str | None:
    """查找任务生成的报告/图表文件。

    Args:
        workspace_path: 工作区根路径。
        task: 任务定义。

    Returns:
        找到的第一个报告文件路径，或 None。
    """
    ws = Path(workspace_path)
    reports_dir = ws / "reports"
    if not reports_dir.exists():
        return None

    # 按 mtime 倒序，取最新
    report_files = sorted(
        reports_dir.glob("report_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if report_files:
        return str(report_files[0])

    # 失败报告
    fail_files = sorted(
        reports_dir.glob("fail_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if fail_files:
        return str(fail_files[0])

    return None

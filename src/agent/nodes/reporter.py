"""Reporter 节点：生成 Markdown 格式的最终报告。"""

from datetime import datetime
from pathlib import Path

from loguru import logger

from src.agent.state import AgentState


def reporter_node(state: AgentState) -> dict:
    """汇总全流程信息，生成 Markdown 报告并写入 reports/。

    Args:
        state: 最终的 AgentState

    Returns:
        包含 final_report 的 partial state
    """
    is_aborted = state.get("human_feedback") == "ABORT"
    success = not state.get("error") and not is_aborted

    report = _build_report(state, success)
    filepath = _write_report(state, report)

    logger.info(f"Report written to: {filepath}")
    return {"final_report": report}


def _build_report(state: AgentState, success: bool) -> str:
    """构建 Markdown 报告内容。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_icon = "✅" if success else "❌"
    status_text = "执行成功" if success else "执行失败"

    lines = [
        f"# DecisionCoder 执行报告",
        "",
        f"**生成时间**: {now}",
        f"**状态**: {status_icon} {status_text}",
        "",
        "---",
        "",
        "## 1. 原始需求",
        "",
        f"> {state['user_query']}",
        "",
        "## 2. 执行计划",
        "",
    ]

    for step in state.get("plan", []):
        lines.append(f"- {step}")

    lines.extend([
        "",
        "## 3. 生成代码",
        "",
        "```python",
        state.get("generated_code", "(无代码)"),
        "```",
        "",
    ])

    # 执行结果
    if state.get("execution_result"):
        lines.extend([
            "## 4. 执行结果",
            "",
            "```",
            state["execution_result"],
            "```",
            "",
        ])

    # 错误信息
    if state.get("error"):
        lines.extend([
            "## ⚠️ 错误信息",
            "",
            "```",
            state["error"],
            "```",
            "",
            f"- 重试次数: {state.get('retry_count', 0)} / 2",
        ])
        if state.get("human_feedback") == "ABORT":
            lines.append("- 用户选择中止执行")

    # 工作区信息
    lines.extend([
        "",
        "---",
        "",
        f"**工作区**: `{state.get('workspace_path', 'N/A')}`",
        f"**临时文件**: `{state.get('file_path', 'N/A')}`",
    ])

    return "\n".join(lines)


def _write_report(state: AgentState, report: str) -> Path:
    """将报告写入 workspace/reports/ 目录。"""
    ws = Path(state["workspace_path"])
    report_dir = ws / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{ts}.md"
    filepath = report_dir / filename
    filepath.write_text(report, encoding="utf-8")

    return filepath

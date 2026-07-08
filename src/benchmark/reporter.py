"""Benchmark 报告生成器。

ReportGenerator — 从 MetricsCollector 生成 Markdown + HTML 报告。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.benchmark.metrics import MetricsCollector


class ReportGenerator:
    """Benchmark 报告生成器。

    用法:
        gen = ReportGenerator()
        gen.generate_md(collector, "results/report.md")
        gen.generate_html(collector, "results/report.html")
    """

    def generate_md(self, collector: MetricsCollector, output_path: str) -> str:
        """生成 Markdown 报告并写入文件。

        Args:
            collector: MetricsCollector（已收集全部结果）。
            output_path: 输出文件路径（.md）。

        Returns:
            生成的 Markdown 内容字符串。
        """
        metrics = collector.compute()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines: list[str] = []
        lines.append("# DecisionCoder Benchmark 报告")
        lines.append("")
        lines.append(f"**执行时间**: {now}  ")
        lines.append(f"**任务总数**: {metrics['total']}  ")
        lines.append(f"**完成率**: {_pct(metrics['completion_rate'])} ({metrics['completed']}/{metrics['total']})  ")
        lines.append(f"**成功率**: {_pct(metrics['success_rate'])} ({metrics['succeeded']}/{metrics['total']})  ")
        lines.append(f"**平均重试次数**: {metrics['avg_retry_count']}  ")
        lines.append(f"**平均耗时**: {metrics['avg_elapsed_seconds']}s  ")
        lines.append("")

        # ── 分类统计 ──
        lines.append("## 分类统计")
        lines.append("")
        lines.append("| 类别 | 任务数 | 完成率 | 成功率 | 平均重试 |")
        lines.append("|------|--------|--------|--------|----------|")
        for cat, stats in metrics.get("category_breakdown", {}).items():
            cat_label = "数据分析" if cat == "data_analysis" else "代码生成" if cat == "code_generation" else cat
            lines.append(
                f"| {cat_label} | {stats['count']} | "
                f"{_pct(stats['success_rate'])} | "
                f"{_pct(stats['completion_rate'])} | "
                f"{stats['avg_retry_count']} |"
            )
        lines.append("")

        # ── 任务明细 ──
        lines.append("## 任务明细")
        lines.append("")
        lines.append("| ID | 类别 | 状态 | 耗时 | 重试 | 验证 |")
        lines.append("|----|------|------|------|------|------|")
        for detail in metrics["task_details"]:
            task_id = detail["task_id"]
            category = "数据分析" if task_id.startswith("BA") else "代码生成"
            if detail["success"]:
                status = "✅ 成功"
            elif detail["completed"]:
                status = "❌ 失败"
            else:
                status = "⏱ 超时"
            elapsed = f"{detail['elapsed_seconds']}s"
            retry = str(detail["retry_count"])
            keywords_found = detail.get("output_keywords_found", [])
            total_kw = detail.get("expected_total", len(keywords_found))
            if detail["success"]:
                verify = f"关键词命中 {len(keywords_found)}/{total_kw}"
            elif detail.get("error"):
                err = str(detail["error"])[:40]
                verify = _escape_pipe(err)
            else:
                verify = "未通过"
            lines.append(
                f"| {task_id} | {category} | {status} | {elapsed} | {retry} | {verify} |"
            )
        lines.append("")

        # ── 失败任务错误摘要 ──
        lines.append("## 失败任务错误摘要")
        lines.append("")
        failed = [d for d in metrics["task_details"] if not d["success"]]
        if failed:
            for d in failed:
                err = d.get("error")
                if err:
                    lines.append(f"- **{d['task_id']}**: {_escape_pipe(str(err)[:200])}")
                else:
                    keywords_found = d.get("output_keywords_found", [])
                    missing = [w for w in (d.get("expected_keywords", [])) if w not in keywords_found]
                    lines.append(f"- **{d['task_id']}**: 关键词未命中 — 缺失: {', '.join(missing) if missing else '未知'}")
        else:
            lines.append("无失败任务。")
        lines.append("")

        md_content = "\n".join(lines)

        # 写入文件
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return md_content

    def generate_html(self, collector: MetricsCollector, output_path: str) -> str:
        """生成 HTML 报告并写入文件。

        在 Markdown 基础上增加：
        - 成功率进度条（绿色 div）
        - 状态颜色标签
        - 内联 CSS，无外部框架依赖

        Args:
            collector: MetricsCollector。
            output_path: 输出文件路径（.html）。

        Returns:
            生成的 HTML 内容字符串。
        """
        metrics = collector.compute()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        success_pct = round(metrics["success_rate"] * 100)
        completion_pct = round(metrics["completion_rate"] * 100)

        parts: list[str] = []
        parts.append("<!DOCTYPE html>")
        parts.append('<html lang="zh-CN">')
        parts.append("<head>")
        parts.append('<meta charset="UTF-8">')
        parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        parts.append("<title>DecisionCoder Benchmark 报告</title>")
        parts.append("<style>")
        parts.append(self._css())
        parts.append("</style>")
        parts.append("</head>")
        parts.append("<body>")

        # ── 头部 ──
        parts.append('<div class="container">')
        parts.append("<h1>DecisionCoder Benchmark 报告</h1>")
        parts.append(f'<p class="meta">执行时间: {now}</p>')

        # ── 总览卡片 ──
        parts.append('<div class="cards">')
        parts.append(self._card("任务总数", str(metrics["total"]), "#4a90d9"))
        parts.append(self._card("完成率", f"{completion_pct}%", "#27ae60" if completion_pct >= 80 else "#e67e22"))
        parts.append(self._card("成功率", f"{success_pct}%", "#27ae60" if success_pct >= 80 else "#e74c3c"))
        parts.append(self._card("平均重试", str(metrics["avg_retry_count"]), "#8e44ad"))
        parts.append(self._card("平均耗时", f"{metrics['avg_elapsed_seconds']}s", "#2c3e50"))
        parts.append("</div>")

        # ── 成功率进度条 ──
        parts.append('<div class="progress-section">')
        parts.append('<div class="progress-label">成功率</div>')
        parts.append('<div class="progress-bar">')
        bar_color = "#27ae60" if success_pct >= 80 else "#e67e22" if success_pct >= 50 else "#e74c3c"
        parts.append(
            f'<div class="progress-fill" style="width: {success_pct}%; background: {bar_color};">'
            f"{success_pct}%</div>"
        )
        parts.append("</div></div>")

        # ── 分类统计表格 ──
        parts.append("<h2>分类统计</h2>")
        parts.append("<table>")
        parts.append("<thead><tr><th>类别</th><th>任务数</th><th>完成率</th><th>成功率</th><th>平均重试</th></tr></thead>")
        parts.append("<tbody>")
        for cat, stats in metrics.get("category_breakdown", {}).items():
            cat_label = "数据分析" if cat == "data_analysis" else "代码生成" if cat == "code_generation" else cat
            parts.append(
                f"<tr><td>{cat_label}</td><td>{stats['count']}</td>"
                f"<td>{_pct(stats['completion_rate'])}</td>"
                f"<td>{_pct(stats['success_rate'])}</td>"
                f"<td>{stats['avg_retry_count']}</td></tr>"
            )
        parts.append("</tbody></table>")

        # ── 任务明细表格 ──
        parts.append("<h2>任务明细</h2>")
        parts.append("<table>")
        parts.append("<thead><tr><th>ID</th><th>类别</th><th>状态</th><th>耗时</th><th>重试</th><th>验证</th></tr></thead>")
        parts.append("<tbody>")
        for detail in metrics["task_details"]:
            task_id = detail["task_id"]
            category = "数据分析" if task_id.startswith("BA") else "代码生成"
            if detail["success"]:
                status = '<span class="badge success">✅ 成功</span>'
            elif detail["completed"]:
                status = '<span class="badge fail">❌ 失败</span>'
            else:
                status = '<span class="badge timeout">⏱ 超时</span>'
            elapsed = f"{detail['elapsed_seconds']}s"
            retry = str(detail["retry_count"])
            keywords_found = detail.get("output_keywords_found", [])
            if detail["success"]:
                verify = f"关键词命中 {len(keywords_found)}"
            elif detail.get("error"):
                verify = str(detail["error"])[:60].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            else:
                verify = "未通过"
            parts.append(
                f"<tr><td>{task_id}</td><td>{category}</td><td>{status}</td>"
                f"<td>{elapsed}</td><td>{retry}</td><td>{verify}</td></tr>"
            )
        parts.append("</tbody></table>")

        # ── 失败摘要 ──
        parts.append("<h2>失败任务错误摘要</h2>")
        failed = [d for d in metrics["task_details"] if not d["success"]]
        if failed:
            parts.append('<ul class="error-list">')
            for d in failed:
                err = d.get("error")
                safe_err = str(err)[:200].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if err else "关键词未命中"
                parts.append(f"<li><strong>{d['task_id']}</strong>: {safe_err}</li>")
            parts.append("</ul>")
        else:
            parts.append("<p>无失败任务。</p>")

        parts.append("</div>")  # .container
        parts.append("</body>")
        parts.append("</html>")

        html_content = "\n".join(parts)

        # 写入文件
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return html_content

    def _css(self) -> str:
        """返回内联 CSS 样式。"""
        return """
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f6fa; color: #2c3e50; padding: 20px; }
            .container { max-width: 960px; margin: 0 auto; }
            h1 { font-size: 24px; margin-bottom: 8px; }
            .meta { color: #7f8c8d; margin-bottom: 24px; }
            .cards { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
            .card { flex: 1; min-width: 140px; background: #fff; border-radius: 8px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            .card .value { font-size: 28px; font-weight: 700; }
            .card .label { font-size: 13px; color: #7f8c8d; margin-top: 4px; }
            .progress-section { margin-bottom: 24px; }
            .progress-label { font-size: 14px; margin-bottom: 6px; font-weight: 600; }
            .progress-bar { background: #ecf0f1; border-radius: 8px; height: 28px; overflow: hidden; }
            .progress-fill { height: 100%; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 700; font-size: 13px; transition: width 0.5s; }
            h2 { font-size: 18px; margin: 24px 0 12px; border-bottom: 2px solid #3498db; padding-bottom: 6px; }
            table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            th { background: #3498db; color: #fff; padding: 10px 12px; text-align: left; font-size: 13px; }
            td { padding: 8px 12px; font-size: 13px; border-bottom: 1px solid #ecf0f1; }
            tr:last-child td { border-bottom: none; }
            .badge { padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
            .badge.success { background: #d5f5e3; color: #27ae60; }
            .badge.fail { background: #fadbd8; color: #e74c3c; }
            .badge.timeout { background: #fdebd0; color: #e67e22; }
            .error-list { background: #fff; border-radius: 8px; padding: 16px 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            .error-list li { padding: 6px 0; font-size: 13px; border-bottom: 1px solid #ecf0f1; }
            .error-list li:last-child { border-bottom: none; }
        """

    def _card(self, label: str, value: str, color: str) -> str:
        """生成单个指标卡片 HTML。

        Args:
            label: 指标名称。
            value: 指标值。
            color: 值颜色。

        Returns:
            HTML 卡片字符串。
        """
        return (
            f'<div class="card">'
            f'<div class="value" style="color: {color};">{value}</div>'
            f'<div class="label">{label}</div>'
            f"</div>"
        )


def _pct(rate: float) -> str:
    """小数 → 百分数字符串。0.8 → "80%"

    Args:
        rate: 0-1 之间的小数。

    Returns:
        百分数字符串。
    """
    return f"{round(rate * 100)}%"


def _escape_pipe(text: str) -> str:
    """转义 Markdown 表格中的 | 字符。

    Args:
        text: 原始文本。

    Returns:
        转义后的文本。
    """
    return text.replace("|", "\\|").replace("\n", " ")

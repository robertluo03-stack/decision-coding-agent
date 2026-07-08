"""测试 Benchmark 报告生成与 Rich 集成。

覆盖：
- Markdown 报告生成（结构 + 指标）
- HTML 报告生成（结构 + 进度条）
- JSONL → 报告生成
- Runner use_ui 集成 mock
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.benchmark.models import BenchmarkResult
from src.benchmark.metrics import MetricsCollector
from src.benchmark.reporter import ReportGenerator


# ── 测试夹具 ──────────────────────────────────────────────


def _build_collector(n: int = 10) -> MetricsCollector:
    """构建一个含有 n 个混合结果的 MetricsCollector。"""
    mc = MetricsCollector()
    for i in range(n):
        task_id = f"BA-{i + 1:02d}" if i < 5 else f"CG-{i + 1 - 5:02d}"
        category = "data_analysis" if i < 5 else "code_generation"
        success = i < 8  # 前 8 个成功，后 2 个失败
        completed = i < 9  # 第 9 个超时
        r = BenchmarkResult(
            task_id=task_id,
            success=success,
            completed=completed,
            retry_count=0 if success else 1,
            elapsed_seconds=10.0 + i * 2,
            error=None if success else ("Timeout" if not completed else "KeyError: 'missing'"),
            output_keywords_found=["kw1", "kw2", "kw3"] if success else ["kw1"],
        )
        r.category = category  # type: ignore[attr-defined]
        mc.record(r)
    return mc


# ── 报告生成测试 ──────────────────────────────────────────


class TestMarkdownReport:
    """Markdown 报告生成。"""

    def test_generate_md_structure(self) -> None:
        """验证 Markdown 包含标题和必要章节。"""
        collector = _build_collector(5)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            md = gen.generate_md(collector, str(path))

            assert path.exists()
            assert "# DecisionCoder Benchmark 报告" in md
            assert "## 分类统计" in md
            assert "## 任务明细" in md
            assert "## 失败任务错误摘要" in md
            assert "**任务总数**: 5" in md

    def test_generate_md_metrics(self) -> None:
        """验证完成率/成功率数字正确。"""
        collector = _build_collector(10)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            md = gen.generate_md(collector, str(path))

            # 8/10 成功 = 80%
            assert "80%" in md
            # 9/10 完成 = 90%
            assert "90%" in md
            # 任务总数
            assert "10" in md

    def test_generate_md_task_details(self) -> None:
        """验证任务明细包含每个任务。"""
        collector = _build_collector(10)  # 10 个任务确保有失败
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            md = gen.generate_md(collector, str(path))

            assert "BA-01" in md
            assert "CG-01" in md
            # 成功/失败状态（后 2 个失败/超时）
            assert "✅ 成功" in md
            assert ("❌ 失败" in md or "⏱ 超时" in md)

    def test_generate_md_with_zero_results(self) -> None:
        """空收集器不报错。"""
        mc = MetricsCollector()
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            md = gen.generate_md(mc, str(path))
            assert "0" in md
            assert "无失败任务" in md

    def test_generate_md_creates_parent_dir(self) -> None:
        """自动创建父目录。"""
        collector = _build_collector(1)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "nested" / "report.md"
            gen.generate_md(collector, str(path))
            assert path.exists()


class TestHTMLReport:
    """HTML 报告生成。"""

    def test_generate_html_structure(self) -> None:
        """验证 HTML 包含完整结构。"""
        collector = _build_collector(3)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.html"
            html = gen.generate_html(collector, str(path))

            assert path.exists()
            assert "<!DOCTYPE html>" in html
            assert "<html" in html
            assert "<head>" in html
            assert "<body>" in html
            assert "<table>" in html
            assert "</html>" in html

    def test_generate_html_has_progress_bar(self) -> None:
        """验证成功率进度条存在。"""
        collector = _build_collector(5)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.html"
            html = gen.generate_html(collector, str(path))

            assert "progress-bar" in html
            assert "progress-fill" in html
            assert "width:" in html

    def test_generate_html_has_cards(self) -> None:
        """验证指标卡片存在。"""
        collector = _build_collector(3)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.html"
            html = gen.generate_html(collector, str(path))

            assert "class=\"card\"" in html
            assert "class=\"value\"" in html

    def test_generate_html_status_badges(self) -> None:
        """验证状态颜色标签。"""
        collector = _build_collector(10)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.html"
            html = gen.generate_html(collector, str(path))

            assert "badge success" in html
            # 后 2 个失败
            assert "badge fail" in html or "badge timeout" in html

    def test_generate_html_error_summary(self) -> None:
        """验证错误摘要存在。"""
        collector = _build_collector(10)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.html"
            html = gen.generate_html(collector, str(path))

            assert "失败任务错误摘要" in html
            assert "CG-01" in html  # 失败任务


class TestJSONLToReport:
    """JSONL → 报告端到端。"""

    def test_report_from_jsonl(self) -> None:
        """写临时 JSONL → 生成 MD + HTML。"""
        # 构造 JSONL
        records = [
            {"task_id": "BA-01", "success": True, "completed": True,
             "retry_count": 0, "elapsed_seconds": 12.5, "error": None,
             "output_keywords_found": ["kw1", "kw2"], "report_path": None},
            {"task_id": "CG-01", "success": False, "completed": True,
             "retry_count": 1, "elapsed_seconds": 45.0,
             "error": "KeyError: 'column'",
             "output_keywords_found": ["kw1"], "report_path": None},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "benchmark_test.jsonl"
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

            # 模拟 report 子命令流程
            collector = MetricsCollector()
            for r in records:
                br = BenchmarkResult(
                    task_id=r["task_id"],
                    success=r["success"],
                    completed=r["completed"],
                    retry_count=r["retry_count"],
                    elapsed_seconds=r["elapsed_seconds"],
                    error=r["error"],
                    output_keywords_found=r["output_keywords_found"],
                )
                br.category = "data_analysis" if r["task_id"].startswith("BA") else "code_generation"  # type: ignore[attr-defined]
                collector.record(br)

            gen = ReportGenerator()
            md_path = str(Path(tmpdir) / "report.md")
            html_path = str(Path(tmpdir) / "report.html")

            gen.generate_md(collector, md_path)
            gen.generate_html(collector, html_path)

            # 验证文件存在且非空
            assert Path(md_path).exists()
            assert Path(html_path).exists()
            assert Path(md_path).stat().st_size > 100
            assert Path(html_path).stat().st_size > 500

            # MD 验证
            with open(md_path, encoding="utf-8") as f:
                md = f.read()
            assert "BA-01" in md
            assert "CG-01" in md
            assert "✅ 成功" in md
            assert "KeyError" in md

            # HTML 验证
            with open(html_path, encoding="utf-8") as f:
                html = f.read()
            assert "<html" in html
            assert "BA-01" in html
            assert "KeyError" in html


class TestRunnerWithUIMock:
    """Runner use_ui 参数 mock 测试。"""

    def test_runner_use_ui_false_default(self) -> None:
        """默认 use_ui=False，不创建 UI。"""
        from src.benchmark.runner import BenchmarkRunner
        from src.benchmark.models import BenchmarkTask

        task = BenchmarkTask(
            id="T-01", category="code_generation",
            query="test", expected_keywords=["ok"], timeout=1,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner([task], workspace_path=tmpdir, output_dir=tmpdir)
            mock_state = {"execution_result": "ok", "final_report": "", "error": None, "retry_count": 0}
            with patch("src.agent.graph.run", return_value=mock_state):
                collector = runner.run_all(use_ui=False)
            metrics = collector.compute()
            assert metrics["total"] == 1
            assert metrics["success_rate"] == 1.0

    def test_runner_with_ui_does_not_crash(self) -> None:
        """use_ui=True 时 Runner 不崩溃（即使无真正的终端）。"""
        from src.benchmark.runner import BenchmarkRunner
        from src.benchmark.models import BenchmarkTask

        task = BenchmarkTask(
            id="T-01", category="code_generation",
            query="test", expected_keywords=["ok"], timeout=1,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner([task], workspace_path=tmpdir, output_dir=tmpdir)
            mock_state = {"execution_result": "ok", "final_report": "", "error": None, "retry_count": 0}
            mock_ui = MagicMock()
            mock_ui._is_tty = False

            with patch.object(runner, "_init_ui", return_value=mock_ui):
                with patch("src.agent.graph.run", return_value=mock_state):
                    collector = runner.run_all(use_ui=True)

            metrics = collector.compute()
            assert metrics["total"] == 1
            # 验证 UI 方法被调用
            assert mock_ui.stop.called
            assert mock_ui.log.called

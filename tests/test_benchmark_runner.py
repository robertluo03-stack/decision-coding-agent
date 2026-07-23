"""测试 Benchmark 执行引擎。

覆盖：
- 验证器关键词匹配逻辑
- Runner 初始化 + mock 执行
- 超时处理
- 异常捕获
- JSONL 输出
- 环境清理
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.benchmark.validators import (
    _keyword_found,
    _is_numeric_keyword,
    _find_generated_files,
    validate_task_result,
)
from src.benchmark.runner import BenchmarkRunner, BenchmarkTimeoutError
from src.benchmark.metrics import MetricsCollector
from src.benchmark.reporter import ReportGenerator


# ── 测试夹具 ──────────────────────────────────────────────

@pytest.fixture
def sample_task_analysis() -> BenchmarkTask:
    return BenchmarkTask(
        id="BA-TEST",
        category="data_analysis",
        query="分析 sales.csv 并给出统计摘要",
        expected_keywords=["sales", "均值", "标准差"],
        timeout=5,
        data_files=["sales.csv"],
    )


@pytest.fixture
def sample_task_codegen() -> BenchmarkTask:
    return BenchmarkTask(
        id="CG-TEST",
        category="code_generation",
        query="计算 EOQ：年需求 1000，订货成本 50，持有成本 2",
        expected_keywords=["EOQ", "223"],
        timeout=5,
    )


# ── 验证器测试 ────────────────────────────────────────────


class TestKeywordMatching:
    """关键词匹配逻辑。"""

    def test_exact_match(self) -> None:
        assert _keyword_found("hello world sales 均值", "sales") is True
        assert _keyword_found("hello world sales 均值", "均值") is True

    def test_case_insensitive(self) -> None:
        assert _keyword_found("EOQ=223.61", "eoq") is True
        assert _keyword_found("SELECT count(*)", "select") is True

    def test_substring_match(self) -> None:
        """部分匹配：关键词是输出子串。"""
        assert _keyword_found("bar_chart generated", "bar") is True

    def test_numeric_relaxed_match(self) -> None:
        """浮点数宽松匹配：'223' 匹配 '223.61'。"""
        assert _keyword_found("EOQ = 223.61", "223") is True

    def test_numeric_partial_prefix(self) -> None:
        """'1.64' 匹配 '1.6449'。"""
        assert _keyword_found("Z = 1.6449", "1.64") is True

    def test_keyword_not_found(self) -> None:
        assert _keyword_found("完全无关的输出内容", "EOQ") is False

    def test_is_numeric_helper(self) -> None:
        assert _is_numeric_keyword("223") is True
        assert _is_numeric_keyword("1.64") is True
        assert _is_numeric_keyword("eoq") is False
        assert _is_numeric_keyword("abc") is False


class TestValidateTaskResult:
    """validate_task_result 端到端测试。"""

    def test_success_result(self, sample_task_analysis: BenchmarkTask) -> None:
        state = {
            "execution_result": "sales 统计：均值 100，标准差 20\n分析完成",
            "final_report": "报告：sales 分析……",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_task_result(
                sample_task_analysis, state, 3.5, tmpdir
            )
            assert result.task_id == "BA-TEST"
            assert result.success is True
            assert result.completed is True
            assert result.retry_count == 0
            assert result.elapsed_seconds == 3.5
            assert result.error is None
            assert set(result.output_keywords_found) == {"sales", "均值", "标准差"}

    def test_partial_keywords(self, sample_task_analysis: BenchmarkTask) -> None:
        """只命中部分关键词 → success=False。"""
        state = {
            "execution_result": "sales 统计：平均值 100",
            "final_report": "",
            "error": None,
            "retry_count": 0,
        }
        result = validate_task_result(sample_task_analysis, state, 1.0, ".")
        assert result.completed is True
        assert result.success is False
        assert len(result.output_keywords_found) < len(sample_task_analysis.expected_keywords)

    def test_error_state(self, sample_task_codegen: BenchmarkTask) -> None:
        state = {
            "execution_result": None,
            "final_report": None,
            "error": "ModuleNotFoundError: No module named 'xxx'",
            "retry_count": 0,
        }
        result = validate_task_result(sample_task_codegen, state, 5.0, ".")
        assert result.completed is False
        assert result.success is False
        assert result.error is not None

    def test_retry_count_forwarded(self, sample_task_codegen: BenchmarkTask) -> None:
        state = {
            "execution_result": "EOQ=200",
            "final_report": "",
            "error": None,
            "retry_count": 2,
        }
        result = validate_task_result(sample_task_codegen, state, 10.0, ".")
        assert result.retry_count == 2

    def test_numeric_relaxed_in_validate(self) -> None:
        """验证器中浮点数宽松匹配生效。"""
        task = BenchmarkTask(
            id="CG-TEST",
            category="code_generation",
            query="EOQ",
            expected_keywords=["EOQ", "223"],
        )
        state = {
            "execution_result": "EOQ = 223.60679774997897",
            "final_report": "",
            "error": None,
            "retry_count": 0,
        }
        result = validate_task_result(task, state, 1.0, ".")
        assert result.success is True
        assert "223" in result.output_keywords_found


class TestFindGeneratedFiles:
    """_find_generated_files 测试。"""

    def test_finds_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            reports = Path(tmpdir) / "reports"
            reports.mkdir()
            (reports / "report_20260708_120000.md").write_text("# report")
            time.sleep(0.01)
            (reports / "report_20260708_120001.md").write_text("# report2")

            task = BenchmarkTask(id="X", category="data_analysis", query="", expected_keywords=[])
            found = _find_generated_files(tmpdir, task)
            assert found is not None
            assert "report_20260708_120001" in found  # latest

    def test_no_reports_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            task = BenchmarkTask(id="X", category="data_analysis", query="", expected_keywords=[])
            found = _find_generated_files(tmpdir, task)
            assert found is None

    def test_finds_fail_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            reports = Path(tmpdir) / "reports"
            reports.mkdir()
            (reports / "fail_20260708_120000.md").write_text("# fail")

            task = BenchmarkTask(id="X", category="data_analysis", query="", expected_keywords=[])
            found = _find_generated_files(tmpdir, task)
            assert found is not None
            assert "fail" in found


# ── Runner 测试 ───────────────────────────────────────────


class TestBenchmarkRunner:
    """BenchmarkRunner 执行引擎测试。"""

    @pytest.fixture
    def sample_tasks(self) -> list[BenchmarkTask]:
        return [
            BenchmarkTask(
                id="CG-01", category="code_generation",
                query="计算 EOQ", expected_keywords=["EOQ"], timeout=5,
            ),
        ]

    def test_runner_init(self, sample_tasks: list[BenchmarkTask]) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(
                sample_tasks, workspace_path=tmpdir, output_dir=tmpdir
            )
            assert len(runner.tasks) == 1
            assert runner.workspace_path == str(Path(tmpdir).resolve())

    def test_run_single_mock_success(self, sample_tasks: list[BenchmarkTask]) -> None:
        """mock graph.run 返回成功 state。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "报告内容",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(sample_tasks, workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                state, elapsed = runner.run_single(sample_tasks[0])
                assert state["execution_result"] == "EOQ = 223.61"
                assert elapsed >= 0

    def test_run_single_mock_error(self, sample_tasks: list[BenchmarkTask]) -> None:
        """mock graph 抛异常，验证 error 被记录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(sample_tasks, workspace_path=tmpdir, output_dir=tmpdir)

            def raise_exc(*args, **kwargs):
                raise RuntimeError("LLM API error")

            with patch("src.agent.graph.run", side_effect=raise_exc):
                state, elapsed = runner.run_single(sample_tasks[0])
                assert "error" in state
                assert "LLM API error" in str(state["error"])

    def test_run_single_timeout(self) -> None:
        """超时任务 → state.error 包含 timeout + completed=False。"""
        task = BenchmarkTask(
            id="TO-01", category="code_generation",
            query="sleep task", expected_keywords=["ok"], timeout=2,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner([task], workspace_path=tmpdir, output_dir=tmpdir)

            def slow_run(*args, **kwargs):
                time.sleep(10)
                return {"execution_result": "done"}

            with patch("src.agent.graph.run", side_effect=slow_run):
                state, elapsed = runner.run_single(task)
                assert "BenchmarkTimeoutError" in str(state.get("error", ""))
                assert elapsed >= 2.0

    def test_run_all_mock(self, sample_tasks: list[BenchmarkTask]) -> None:
        """run_all mock 执行后 collector 有正确记录。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "报告内容",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(sample_tasks, workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                collector = runner.run_all()

            metrics = collector.compute()
            assert metrics["total"] == 1
            assert metrics["completion_rate"] == 1.0
            assert metrics["success_rate"] == 1.0

    def test_jsonl_output(self, sample_tasks: list[BenchmarkTask]) -> None:
        """run_all 后 JSONL 文件存在且每行可解析。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "报告内容",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(sample_tasks, workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                runner.run_all()

            # 检查 JSONL 文件
            jsonl_files = list(Path(tmpdir).glob("benchmark_*.jsonl"))
            assert len(jsonl_files) == 1

            with open(jsonl_files[0], encoding="utf-8") as f:
                lines = f.read().strip().split("\n")
            assert len(lines) == 1

            record = json.loads(lines[0])
            assert record["task_id"] == "CG-01"
            assert record["success"] is True
            assert record["completed"] is True

    def test_environment_cleanup(self) -> None:
        """任务前清理逻辑正确。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            # 创建假临时文件
            src_dir = ws / "src"
            src_dir.mkdir()
            (src_dir / "_dc_exec_abc123.py").write_text("print(1)")
            (src_dir / "_dc_exec_def456.py").write_text("print(2)")

            # 创建假报告
            reports_dir = ws / "reports"
            reports_dir.mkdir()
            (reports_dir / "report_old.md").write_text("# old")

            task = BenchmarkTask(
                id="X", category="data_analysis", query="", expected_keywords=[]
            )
            runner = BenchmarkRunner([task], workspace_path=str(ws), output_dir=tmpdir)
            runner._cleanup_workspace()

            # 临时文件应被删除
            exec_files = list(src_dir.glob("_dc_exec_*.py"))
            assert len(exec_files) == 0

            # 报告目录应被删除
            assert not reports_dir.exists()

    def test_cleanup_handles_missing_dirs(self) -> None:
        """清理时不存在 src/ 或 reports/ 目录不报错。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            task = BenchmarkTask(
                id="X", category="data_analysis", query="", expected_keywords=[]
            )
            runner = BenchmarkRunner([task], workspace_path=tmpdir, output_dir=tmpdir)
            # 不抛异常即为通过
            runner._cleanup_workspace()

    def test_jsonl_write_is_thread_safe(self) -> None:
        """JSONL 追加使用锁保护，并发写入不损坏文件。"""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(
                [], workspace_path=tmpdir, output_dir=tmpdir
            )
            # 确保 JSONL 文件已创建
            runner._jsonl_path.write_text("")

            errors: list[Exception] = []

            def write_many(start: int) -> None:
                for i in range(start, start + 20):
                    try:
                        r = BenchmarkResult(
                            task_id=f"T-{i}",
                            success=True,
                            completed=True,
                            retry_count=0,
                            elapsed_seconds=float(i),
                        )
                        runner._append_jsonl(r)
                    except Exception as e:
                        errors.append(e)

            threads = [
                threading.Thread(target=write_many, args=(i * 20,))
                for i in range(3)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0

            # 验证文件完整性
            with open(runner._jsonl_path, encoding="utf-8") as f:
                lines = f.read().strip().split("\n")
            assert len(lines) == 60  # 3 * 20
            for line in lines:
                record = json.loads(line)
                assert "task_id" in record


# ── 失败否决测试（Feature: ABORT → success=False） ──


class TestFailureVeto:
    """失败否决：ABORT 或 fail_*.md → success 必须为 False。"""

    def test_abort_human_feedback_vetoes_success(self) -> None:
        """结果词全中但 human_feedback=="ABORT" 时 success=False。"""
        task = BenchmarkTask(
            id="BA-TEST",
            category="data_analysis",
            query="分析数据",
            expected_keywords=["sales", "均值", "标准差"],
        )
        state = {
            "execution_result": "sales 统计：均值 100，标准差 20\n分析完成",
            "final_report": "报告：sales 分析……",
            "error": None,
            "retry_count": 1,
            "human_feedback": "ABORT",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_task_result(task, state, 5.0, tmpdir)
            # completed 仍为 True（有输出），但 ABORT 否决了 success
            assert result.completed is True
            assert result.success is False
            assert result.aborted is True
            # 关键词仍然全中
            assert set(result.output_keywords_found) == {"sales", "均值", "标准差"}

    def test_fail_report_vetoes_success(self) -> None:
        """即使 human_feedback 未透传，存在 fail_*.md 也应判定 aborted → success=False。"""
        task = BenchmarkTask(
            id="CG-TEST",
            category="code_generation",
            query="计算 EOQ",
            expected_keywords=["EOQ", "223"],
        )
        state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "结果分析中……",
            "error": None,
            "retry_count": 0,
            "human_feedback": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 fail_*.md 模拟 ABORT 场景
            reports_dir = Path(tmpdir) / "reports"
            reports_dir.mkdir()
            (reports_dir / "fail_20260723_120000.md").write_text("# 任务中止报告")
            result = validate_task_result(task, state, 3.0, tmpdir)
            assert result.completed is True
            assert result.success is False
            assert result.aborted is True

    def test_happy_path_unaffected(self) -> None:
        """无 ABORT、无 fail_*.md → 原来的 success 逻辑不变。"""
        task = BenchmarkTask(
            id="CG-TEST",
            category="code_generation",
            query="计算 EOQ",
            expected_keywords=["EOQ", "223"],
        )
        state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "报告",
            "error": None,
            "retry_count": 0,
            "human_feedback": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_task_result(task, state, 2.0, tmpdir)
            assert result.completed is True
            assert result.success is True
            assert result.aborted is False

    def test_aborted_field_in_jsonl(self) -> None:
        """JSONL 记录应包含 aborted 和 git_commit 字段。"""
        task = BenchmarkTask(
            id="CG-01", category="code_generation",
            query="计算 EOQ", expected_keywords=["EOQ"], timeout=5,
        )
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "报告内容",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner([task], workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                runner.run_all()

            jsonl_files = list(Path(tmpdir).glob("benchmark_*.jsonl"))
            assert len(jsonl_files) == 1
            with open(jsonl_files[0], encoding="utf-8") as f:
                record = json.loads(f.readline())
            assert "aborted" in record
            assert record["aborted"] is False
            assert "git_commit" in record
            # git_commit 应为非空（在有 git 的仓库中）
            assert isinstance(record["git_commit"], str)

    def test_aborted_shows_in_report(self) -> None:
        """Markdown/HTML 报告应展示 aborted 和 archive_path 字段。"""
        mc = MetricsCollector()
        r = BenchmarkResult(
            task_id="BA-01", success=False, completed=True,
            aborted=True, retry_count=1, elapsed_seconds=30.0,
            error="KeyError: 'col'", output_keywords_found=["sales"],
            archive_path="/tmp/archives/BA-01/run1",
        )
        mc.record(r)
        gen = ReportGenerator()
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = str(Path(tmpdir) / "report.md")
            md = gen.generate_md(mc, md_path)
            # 中止标记
            assert "🛑" in md
            # 归档路径
            assert "/tmp/archives/BA-01/run1" in md
            # HTML 同理
            html_path = str(Path(tmpdir) / "report.html")
            html = gen.generate_html(mc, html_path)
            assert "🛑" in html
            assert "/tmp/archives/BA-01/run1" in html


# ── 归档持久化测试 ──


class TestArtifactArchive:
    """归档目录在清理后仍保留报告文件。"""

    def test_archive_preserves_files_after_cleanup(self) -> None:
        """_archive_artifacts 复制报告 → _cleanup_workspace 删除后归档仍存在。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir) / "workspace"
            reports_dir = ws / "reports"
            reports_dir.mkdir(parents=True)
            charts_dir = reports_dir / "charts"
            charts_dir.mkdir(parents=True)

            # 创建模拟产出
            (reports_dir / "report_20260723_120000.md").write_text("# report")
            (charts_dir / "chart_bar.html").write_text("<html>bar</html>")

            arch_dir = Path(tmpdir) / "results" / "artifacts"
            arch_dir.mkdir(parents=True)

            task = BenchmarkTask(
                id="BA-TEST", category="data_analysis",
                query="分析", expected_keywords=["x"],
            )
            runner = BenchmarkRunner([task], workspace_path=str(ws), output_dir=str(Path(tmpdir) / "results"))
            # 手动设 batch_id 避免 git 依赖
            runner.batch_id = "20260723_test_nogit"
            runner._artifact_base = arch_dir / runner.batch_id

            archive_path = runner._archive_artifacts(task, run_index=1)
            assert archive_path is not None
            assert Path(archive_path).exists()

            # 验证归档文件存在
            assert (Path(archive_path) / "report_20260723_120000.md").exists()
            assert (Path(archive_path) / "charts" / "chart_bar.html").exists()

            # 清理原始 workspace 的 reports
            runner._cleanup_workspace()
            assert not reports_dir.exists()  # 源已删除

            # 但归档目录中的文件仍在（稍等以确保文件系统同步）
            assert (Path(archive_path) / "report_20260723_120000.md").exists()
            assert (Path(archive_path) / "charts" / "chart_bar.html").exists()

    def test_archive_handles_empty_reports(self) -> None:
        """无产出时 _archive_artifacts 返回 None 不报错。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir) / "workspace"
            ws.mkdir()
            task = BenchmarkTask(
                id="X", category="data_analysis", query="", expected_keywords=[],
            )
            runner = BenchmarkRunner([task], workspace_path=str(ws), output_dir=str(Path(tmpdir) / "results"))
            runner.batch_id = "test"
            runner._artifact_base = Path(tmpdir) / "results" / "artifacts" / runner.batch_id

            result = runner._archive_artifacts(task, run_index=1)
            assert result is None

    def test_manifest_written_on_run_all(self) -> None:
        """run_all 结束后写入 manifest.json。"""
        mock_state = {
            "execution_result": "ok",
            "final_report": "report",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            task = BenchmarkTask(
                id="CG-01", category="code_generation",
                query="test", expected_keywords=["ok"], timeout=5,
            )
            runner = BenchmarkRunner([task], workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                runner.run_all()

            manifest_path = runner._artifact_base / "manifest.json"
            assert manifest_path.exists()

            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

            assert "batch_id" in manifest
            assert "git_commit" in manifest
            assert "git_dirty" in manifest
            assert "tasks" in manifest
            assert "arm_config" in manifest
            assert "metrics_summary" in manifest
            assert len(manifest["tasks"]) == 1
            assert manifest["tasks"][0]["id"] == "CG-01"


# ── 批次共享与一致性测试 ──


class TestBatchIdSharing:
    """batch_id 共享与 JSONL 追加模式测试。"""

    def test_run_both_shares_batch_id(self) -> None:
        """--both 双臂共享同一 batch_id、同一 JSONL、同一 artifact_base。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "报告内容",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            task = BenchmarkTask(
                id="CG-01", category="code_generation",
                query="计算 EOQ", expected_keywords=["EOQ"], timeout=5,
            )
            runner = BenchmarkRunner([task], workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                runner.run_both(repeat=1)

            # 验证只用了一个 JSONL
            jsonl_files = sorted(Path(tmpdir).glob("benchmark_*.jsonl"))
            assert len(jsonl_files) == 1

            # 验证一个 JSONL 包含两条记录（两臂各一）
            with open(jsonl_files[0], encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            assert len(records) == 2
            arms = sorted(r["arm"] for r in records)
            assert arms == ["routing_off", "routing_on"]

            # 验证只有一个 artifact 批次目录
            artifact_dirs = sorted(Path(tmpdir).glob("artifacts/*"))
            assert len(artifact_dirs) == 1

    def test_run_both_jsonl_not_deleted_between_arms(self) -> None:
        """第二个 arm 的 run_all 不会删除第一个 arm 的 JSONL 记录。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "报告内容",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks = [
                BenchmarkTask(
                    id="CG-01", category="code_generation",
                    query="计算 EOQ", expected_keywords=["EOQ"], timeout=5,
                ),
                BenchmarkTask(
                    id="CG-02", category="code_generation",
                    query="预测需求", expected_keywords=["预测"], timeout=5,
                ),
            ]
            runner = BenchmarkRunner(tasks, workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                runner.run_both(repeat=1)

            # 应该有 4 条记录（2 tasks × 2 arms）
            jsonl_files = sorted(Path(tmpdir).glob("benchmark_*.jsonl"))
            assert len(jsonl_files) == 1
            with open(jsonl_files[0], encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            assert len(records) == 4


class TestConsistencyRate:
    """consistency_rate 显示测试。"""

    def test_consistency_none_when_repeat_one(self) -> None:
        """repeat=1 时 consistency_rate 为 None（不适用）。"""
        mc = MetricsCollector()
        r1 = BenchmarkResult(
            task_id="CG-01", success=True, completed=True,
            elapsed_seconds=5.0, numeric_value=223.61, arm="routing_on",
        )
        r2 = BenchmarkResult(
            task_id="CG-01", success=True, completed=True,
            elapsed_seconds=6.0, numeric_value=223.61, arm="routing_off",
        )
        mc.record(r1)
        mc.record(r2)
        metrics = mc.compute()
        # 每组只有 1 个值 → 不足以计算一致率
        assert metrics["consistency_rate"] is None

    def test_consistency_computed_when_repeat_two(self) -> None:
        """repeat=2 时同一组有 2 个值 → 可计算一致率。"""
        mc = MetricsCollector()
        r1 = BenchmarkResult(
            task_id="CG-01", success=True, completed=True,
            elapsed_seconds=5.0, numeric_value=223.61, arm="routing_on", run_index=1,
        )
        r2 = BenchmarkResult(
            task_id="CG-01", success=True, completed=True,
            elapsed_seconds=6.0, numeric_value=223.61, arm="routing_on", run_index=2,
        )
        mc.record(r1)
        mc.record(r2)
        metrics = mc.compute()
        assert metrics["consistency_rate"] is not None
        assert metrics["consistency_rate"] == 1.0  # same value

    def test_consistency_zero_when_no_numeric_values(self) -> None:
        """无任何 numeric_value 时 consistency_rate 为 None。"""
        mc = MetricsCollector()
        r1 = BenchmarkResult(
            task_id="BA-01", success=True, completed=True,
            elapsed_seconds=3.0, numeric_value=None, arm="routing_on", run_index=1,
        )
        r2 = BenchmarkResult(
            task_id="BA-01", success=True, completed=True,
            elapsed_seconds=4.0, numeric_value=None, arm="routing_on", run_index=2,
        )
        mc.record(r1)
        mc.record(r2)
        metrics = mc.compute()
        assert metrics["consistency_rate"] is None

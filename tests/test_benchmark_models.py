"""测试 Benchmark 任务集与指标收集器。

覆盖：
- get_default_tasks() 10 个任务验证
- 5+5 分类正确性
- MetricsCollector 空 / 单 / 多结果计算
- BenchmarkTask 参数校验
"""

from __future__ import annotations

import pytest

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.benchmark.tasks import get_default_tasks
from src.benchmark.metrics import MetricsCollector


class TestBenchmarkTasks:
    """默认任务集验证。"""

    def test_task_count(self) -> None:
        """get_default_tasks() 返回恰好 10 个任务。"""
        tasks = get_default_tasks()
        assert len(tasks) == 10

    def test_task_categories(self) -> None:
        """5 个 data_analysis + 5 个 code_generation。"""
        tasks = get_default_tasks()
        analysis = [t for t in tasks if t.category == "data_analysis"]
        code_gen = [t for t in tasks if t.category == "code_generation"]
        assert len(analysis) == 5
        assert len(code_gen) == 5

    def test_task_ids_unique(self) -> None:
        """所有任务 ID 唯一。"""
        tasks = get_default_tasks()
        ids = [t.id for t in tasks]
        assert len(ids) == len(set(ids))

    def test_task_id_prefix(self) -> None:
        """数据分析类以 BA- 开头，代码生成类以 CG- 开头。"""
        tasks = get_default_tasks()
        for t in tasks:
            if t.category == "data_analysis":
                assert t.id.startswith("BA-"), f"{t.id} should start with BA-"
            else:
                assert t.id.startswith("CG-"), f"{t.id} should start with CG-"

    def test_all_tasks_have_expected_keywords(self) -> None:
        """每个任务都有 3-5 个 expected_keywords。"""
        tasks = get_default_tasks()
        for t in tasks:
            assert 3 <= len(t.expected_keywords) <= 5, (
                f"{t.id}: expected_keywords count={len(t.expected_keywords)} out of range"
            )

    def test_all_timeouts_positive(self) -> None:
        """所有任务 timeout > 0。"""
        tasks = get_default_tasks()
        for t in tasks:
            assert t.timeout > 0, f"{t.id}: timeout={t.timeout}"

    def test_analysis_tasks_have_data_files(self) -> None:
        """数据分析类任务都声明了 data_files（非 None）。"""
        tasks = get_default_tasks()
        for t in tasks:
            if t.category == "data_analysis":
                assert t.data_files is not None, (
                    f"{t.id}: analysis task must have data_files"
                )
                assert len(t.data_files) >= 1

    def test_code_gen_queries_have_params(self) -> None:
        """代码生成类任务的 query 包含明确参数（避免 LLM 意图模糊）。"""
        tasks = get_default_tasks()
        code_gen = [t for t in tasks if t.category == "code_generation"]
        for t in code_gen:
            # 至少包含数字或数据文件名，确保参数明确
            query = t.query
            has_numbers = any(c.isdigit() for c in query)
            has_filename = ".csv" in query
            assert has_numbers or has_filename, (
                f"{t.id}: query must contain explicit parameters, got: {query[:80]}"
            )


class TestBenchmarkModels:
    """数据模型独立测试。"""

    def test_task_creation(self) -> None:
        """BenchmarkTask dataclass 字段正确。"""
        task = BenchmarkTask(
            id="T-01",
            category="data_analysis",
            query="test query",
            expected_keywords=["a", "b"],
            timeout=30,
            data_files=["test.csv"],
        )
        assert task.id == "T-01"
        assert task.category == "data_analysis"
        assert task.timeout == 30
        assert task.data_files == ["test.csv"]

    def test_task_default_values(self) -> None:
        """默认参数：timeout=60, data_files=None。"""
        task = BenchmarkTask(
            id="T-02",
            category="code_generation",
            query="test",
            expected_keywords=["x"],
        )
        assert task.timeout == 60
        assert task.data_files is None

    def test_result_creation(self) -> None:
        """BenchmarkResult dataclass 字段正确。"""
        result = BenchmarkResult(
            task_id="T-01",
            success=True,
            completed=True,
            retry_count=0,
            elapsed_seconds=3.5,
            error=None,
            output_keywords_found=["a", "b"],
            report_path="/tmp/report.md",
        )
        assert result.success is True
        assert result.completed is True
        assert result.retry_count == 0
        assert result.elapsed_seconds == 3.5
        assert result.error is None

    def test_result_default_values(self) -> None:
        """默认值正确。"""
        result = BenchmarkResult(task_id="X")
        assert result.success is False
        assert result.completed is False
        assert result.output_keywords_found == []


class TestMetricsCollector:
    """指标收集器计算正确性。"""

    def test_empty_metrics(self) -> None:
        """空收集器：全部指标为 0。"""
        mc = MetricsCollector()
        metrics = mc.compute()
        assert metrics["total"] == 0
        assert metrics["completion_rate"] == 0.0
        assert metrics["success_rate"] == 0.0
        assert metrics["avg_retry_count"] == 0.0
        assert metrics["avg_elapsed_seconds"] == 0.0
        assert metrics["category_breakdown"] == {}
        assert metrics["task_details"] == []

    def test_single_result(self) -> None:
        """单个成功结果。"""
        mc = MetricsCollector()
        mc.record(
            BenchmarkResult(
                task_id="T-01",
                success=True,
                completed=True,
                retry_count=0,
                elapsed_seconds=5.0,
            )
        )
        metrics = mc.compute()
        assert metrics["total"] == 1
        assert metrics["completion_rate"] == 1.0
        assert metrics["success_rate"] == 1.0
        assert metrics["avg_retry_count"] == 0.0
        assert metrics["avg_elapsed_seconds"] == 5.0
        assert len(metrics["task_details"]) == 1

    def test_metrics_compute_mixed(self) -> None:
        """混合结果：2 成功 + 1 失败 → 指标计算正确。"""
        mc = MetricsCollector()
        mc.record(
            BenchmarkResult(
                task_id="A-01", success=True, completed=True,
                retry_count=0, elapsed_seconds=2.0,
            )
        )
        mc.record(
            BenchmarkResult(
                task_id="A-02", success=True, completed=True,
                retry_count=1, elapsed_seconds=5.0,
            )
        )
        mc.record(
            BenchmarkResult(
                task_id="C-01", success=False, completed=False,
                retry_count=2, elapsed_seconds=10.0,
            )
        )

        # 注入 category 字段（BenchmarkResult 不存储 category，由外部注入供 compute() 分组使用）
        mc.results[0].category = "data_analysis"
        mc.results[1].category = "data_analysis"
        mc.results[2].category = "code_generation"

        metrics = mc.compute()
        assert metrics["total"] == 3
        assert metrics["completion_rate"] == round(2 / 3, 2)  # 0.67
        assert metrics["success_rate"] == round(2 / 3, 2)  # 0.67
        assert metrics["avg_retry_count"] == 1.0  # (0 + 1 + 2) / 3 = 1.0
        assert metrics["avg_elapsed_seconds"] == round((2.0 + 5.0 + 10.0) / 3, 2)

        # category breakdown
        assert "data_analysis" in metrics["category_breakdown"]
        assert "code_generation" in metrics["category_breakdown"]
        da = metrics["category_breakdown"]["data_analysis"]
        assert da["count"] == 2
        assert da["success_rate"] == 1.0
        cg = metrics["category_breakdown"]["code_generation"]
        assert cg["count"] == 1
        assert cg["success_rate"] == 0.0

        # task details
        assert len(metrics["task_details"]) == 3
        assert metrics["task_details"][0]["task_id"] == "A-01"

    def test_all_two_decimal_places(self) -> None:
        """所有 rate / avg 指标保留 2 位小数。"""
        mc = MetricsCollector()
        mc.record(
            BenchmarkResult(
                task_id="T-01", success=True, completed=True,
                retry_count=1, elapsed_seconds=3.333,
            )
        )
        mc.record(
            BenchmarkResult(
                task_id="T-02", success=False, completed=True,
                retry_count=0, elapsed_seconds=1.111,
            )
        )
        mc.record(
            BenchmarkResult(
                task_id="T-03", success=False, completed=False,
                retry_count=2, elapsed_seconds=5.555,
            )
        )

        metrics = mc.compute()
        # 验证所有浮点数最多 2 位小数
        for key in ["completion_rate", "success_rate", "avg_retry_count", "avg_elapsed_seconds"]:
            val = metrics[key]
            # round(x, 2) then multiply by 100 ensures no floating point drift
            assert val == round(val, 2), f"{key}={val} has >2 decimal places"
            # 确保小数点后最多 2 位
            s = f"{val:.10f}"
            decimal_part = s.split(".")[1] if "." in s else ""
            non_zero_count = len(decimal_part.rstrip("0"))
            assert non_zero_count <= 2, f"{key}={val} has too many decimal places: {s}"

    def test_category_breakdown_includes_all(self) -> None:
        """category_breakdown 包含所有类别。"""
        mc = MetricsCollector()
        mc.record(
            BenchmarkResult(
                task_id="A-01", success=True, completed=True,
                retry_count=0, elapsed_seconds=1.0,
            )
        )
        mc.record(
            BenchmarkResult(
                task_id="C-01", success=False, completed=True,
                retry_count=1, elapsed_seconds=2.0,
            )
        )
        mc.results[0].category = "data_analysis"
        mc.results[1].category = "code_generation"

        metrics = mc.compute()
        bd = metrics["category_breakdown"]
        assert "data_analysis" in bd
        assert "code_generation" in bd
        # 每个类别有 5 个字段
        for cat in bd:
            assert "count" in bd[cat]
            assert "success_rate" in bd[cat]
            assert "completion_rate" in bd[cat]
            assert "avg_retry_count" in bd[cat]
            assert "avg_elapsed_seconds" in bd[cat]

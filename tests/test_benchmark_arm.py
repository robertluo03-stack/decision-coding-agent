"""测试 Benchmark Arm 支持（实验对照）。

验证：
- arm 参数设置/恢复环境变量
- run_all 双 arm 模式执行
- consistency rate 计算
- token tracker 集成
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.benchmark.runner import BenchmarkRunner
from src.benchmark.metrics import MetricsCollector


@pytest.fixture
def sample_tasks() -> list[BenchmarkTask]:
    return [
        BenchmarkTask(
            id="CG-01", category="code_generation",
            query="计算 EOQ", expected_keywords=["EOQ", "223"], timeout=5,
        ),
        BenchmarkTask(
            id="CG-02", category="code_generation",
            query="预测需求", expected_keywords=["预测"], timeout=5,
        ),
    ]


class TestArmEnvToggle:
    """环境变量切换测试。"""

    def test_routing_off_sets_env(self) -> None:
        """routing_off arm 设置 DECISIONCODER_NO_ROUTING=true。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(
                [], workspace_path=tmpdir, output_dir=tmpdir,
                arm="routing_off",
            )
            runner._toggle_env_for_arm("routing_off")
            assert os.environ.get("DECISIONCODER_NO_ROUTING") == "true"

    def test_routing_on_clears_env(self) -> None:
        """routing_on arm 清除 DECISIONCODER_NO_ROUTING。"""
        os.environ["DECISIONCODER_NO_ROUTING"] = "true"
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(
                [], workspace_path=tmpdir, output_dir=tmpdir,
                arm="routing_on",
            )
            runner._toggle_env_for_arm("routing_on")
            assert "DECISIONCODER_NO_ROUTING" not in os.environ
        os.environ.pop("DECISIONCODER_NO_ROUTING", None)  # 清理


class TestRunnerArm:
    """Runner arm 参数测试。"""

    def test_arm_defaults_to_routing_on(self, sample_tasks: list[BenchmarkTask]) -> None:
        """默认 arm 为 routing_on。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(sample_tasks, workspace_path=tmpdir, output_dir=tmpdir)
            assert runner.arm == "routing_on"

    def test_arm_stored_in_results(self, sample_tasks: list[BenchmarkTask]) -> None:
        """run_all 后结果中 arm 字段正确。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "report",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(
                sample_tasks, workspace_path=tmpdir, output_dir=tmpdir,
                arm="routing_off", repeat=1,
            )
            with patch("src.agent.graph.run", return_value=mock_state):
                collector = runner.run_all()

            metrics = collector.compute()
            for detail in metrics["task_details"]:
                assert detail["arm"] == "routing_off"

    def test_run_index_in_results(self, sample_tasks: list[BenchmarkTask]) -> None:
        """repeat=2 时 run_index 为 1 和 2。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "report",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(
                sample_tasks, workspace_path=tmpdir, output_dir=tmpdir,
                repeat=2,
            )
            with patch("src.agent.graph.run", return_value=mock_state):
                collector = runner.run_all()

            metrics = collector.compute()
            run_indices = sorted({d["run_index"] for d in metrics["task_details"]})
            assert run_indices == [1, 2]
            # 2 tasks × 2 repeats = 4 results
            assert metrics["total"] == 4

    def test_numeric_value_in_results(self, sample_tasks: list[BenchmarkTask]) -> None:
        """结果中包含提取的数值。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "report",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(sample_tasks, workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                collector = runner.run_all()

            metrics = collector.compute()
            cg01_results = [d for d in metrics["task_details"] if d["task_id"] == "CG-01"]
            for r in cg01_results:
                assert r.get("numeric_value") is not None
                assert abs(r["numeric_value"] - 223.61) < 0.1

    def test_token_usage_in_results(self, sample_tasks: list[BenchmarkTask]) -> None:
        """结果中包含 token 用量。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "report",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(sample_tasks, workspace_path=tmpdir, output_dir=tmpdir)
            with patch("src.agent.graph.run", return_value=mock_state):
                collector = runner.run_all()

            metrics = collector.compute()
            for detail in metrics["task_details"]:
                assert "token_usage" in detail


class TestConsistencyRate:
    """一致率计算测试。"""

    def test_consistency_rate_with_numeric_results(self) -> None:
        """有数值结果时计算一致率。"""
        collector = MetricsCollector()
        # 3 次 EOQ 执行，结果一致
        for i in range(3):
            r = BenchmarkResult(
                task_id="CG-01", success=True, completed=True,
                arm="routing_on", run_index=i + 1,
                numeric_value=223.61 + (i - 1) * 0.5,  # 222.61, 223.11, 223.61
            )
            collector.record(r)

        metrics = collector.compute()
        # 都在 ±5% 内
        assert metrics["consistency_rate"] > 0.8

    def test_consistency_zero_when_no_numeric(self) -> None:
        """无数值结果时一致率为 None（不适用）。"""
        collector = MetricsCollector()
        for i in range(3):
            r = BenchmarkResult(
                task_id="BA-01", success=True, completed=True,
                arm="routing_on", run_index=i + 1,
            )
            collector.record(r)

        metrics = collector.compute()
        assert metrics["consistency_rate"] is None


class TestRunBoth:
    """run_both 双臂对照测试。"""

    def test_run_both_executes_both_arms(self, sample_tasks: list[BenchmarkTask]) -> None:
        """run_both 执行两个 arm。"""
        mock_state = {
            "execution_result": "EOQ = 223.61",
            "final_report": "report",
            "error": None,
            "retry_count": 0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(
                sample_tasks, workspace_path=tmpdir, output_dir=tmpdir,
                repeat=1,
            )
            with patch("src.agent.graph.run", return_value=mock_state):
                collector = runner.run_both(repeat=1)

            metrics = collector.compute()
            # 2 tasks × 2 arms = 4 results
            assert metrics["total"] == 4

            arm_breakdown = metrics.get("arm_breakdown", {})
            assert "routing_on" in arm_breakdown
            assert "routing_off" in arm_breakdown
            assert arm_breakdown["routing_on"]["count"] == 2
            assert arm_breakdown["routing_off"]["count"] == 2

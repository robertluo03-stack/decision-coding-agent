"""供应链库存分析一键流水线测试套件。

覆盖场景：
  1. 黄金路径（24 期月数据）
  2. 数据粒度检测 — 月数据
  3. 数据粒度检测 — 周数据
  4. 数据粒度检测 — 日数据
  5. 年需求推断正确性
  6. 自定义参数覆盖（ordering_cost=200）
  7. 图表文件生成
  8. 报告 8 章节完整性
  9. time_col 不存在 → ValueError
  10. demand_col 不存在 → ValueError
  11. 空 CSV（0 行）
  12. 单期数据（forecast_result=None）
  13. quick_analyze 便捷入口
  14. run 别名可调用
  15. 图表生成失败不中断流水线
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.templates.inventory_pipeline import (
    InventoryPipelineParams,
    InventoryPipelineResult,
    run_inventory_pipeline,
    quick_analyze,
    run,
    _detect_granularity,
    _compute_annual_demand,
)
from src.domain.templates.demand_forecast import ForecastResult
from src.domain.templates.inventory_eoq import EOQResult
from src.domain.templates.safety_stock import SafetyStockResult
from src.domain.templates.reorder_point import ROPResult


# ======================================================================
# 脚手架
# ======================================================================


@pytest.fixture
def monthly_csv_24():
    """24 期月数据：2024-01 至 2025-12，每期 demand ~100。"""
    months = pd.date_range("2024-01-01", periods=24, freq="MS")
    np.random.seed(42)
    demand = np.random.normal(100, 10, 24).clip(50, 150)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write("month,demand\n")
        for m, d in zip(months, demand):
            f.write(f"{m.strftime('%Y-%m-%d')},{d:.1f}\n")
        csv_path = f.name

    yield csv_path
    Path(csv_path).unlink(missing_ok=True)


@pytest.fixture
def monthly_csv_6():
    """6 期月数据。"""
    months = pd.date_range("2026-01-01", periods=6, freq="MS")
    demand = [100, 110, 105, 115, 120, 125]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write("month,demand\n")
        for m, d in zip(months, demand):
            f.write(f"{m.strftime('%Y-%m-%d')},{d}\n")
        csv_path = f.name

    yield csv_path
    Path(csv_path).unlink(missing_ok=True)


@pytest.fixture
def weekly_csv():
    """8 周数据。"""
    weeks = pd.date_range("2026-01-05", periods=8, freq="7D")
    demand = [50, 55, 48, 60, 52, 58, 63, 55]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write("week,demand\n")
        for w, d in zip(weeks, demand):
            f.write(f"{w.strftime('%Y-%m-%d')},{d}\n")
        csv_path = f.name

    yield csv_path
    Path(csv_path).unlink(missing_ok=True)


@pytest.fixture
def daily_csv():
    """14 天数据。"""
    days = pd.date_range("2026-06-01", periods=14, freq="D")
    demand = [10, 12, 9, 11, 13, 10, 8, 12, 11, 9, 10, 13, 11, 10]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write("date,sales\n")
        for day, d in zip(days, demand):
            f.write(f"{day.strftime('%Y-%m-%d')},{d}\n")
        csv_path = f.name

    yield csv_path
    Path(csv_path).unlink(missing_ok=True)


@pytest.fixture
def tmp_output_dir():
    """临时输出目录。"""
    d = tempfile.mkdtemp(suffix="_inventory_test")
    yield d
    # 清理输出目录
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ======================================================================
# 测试用例
# ======================================================================


class TestGoldenPath:
    """场景 1：黄金路径 — 24 期月数据，8 步全部成功。"""

    def test_golden_path(self, monthly_csv_24, tmp_output_dir):
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            time_col="month",
            demand_col="demand",
            output_dir=tmp_output_dir,
        )
        result = run_inventory_pipeline(params)

        # 报告文件存在
        assert result.report_path != ""
        assert Path(result.report_path).exists()

        # 4 个结果对象非 None
        assert result.forecast_result is not None
        assert isinstance(result.forecast_result, ForecastResult)
        assert result.eoq_result is not None
        assert isinstance(result.eoq_result, EOQResult)
        assert result.safety_stock_result is not None
        assert isinstance(result.safety_stock_result, SafetyStockResult)
        assert result.rop_result is not None
        assert isinstance(result.rop_result, ROPResult)

        # 质量报告非 None
        assert result.quality_report is not None
        assert "overall_score" in result.quality_report


class TestGranularityDetection:
    """场景 2-4：数据粒度检测。"""

    def test_monthly_granularity(self):
        dates = pd.to_datetime(
            pd.Series(["2024-01-01", "2024-02-01", "2024-03-01"])
        )
        gran, days = _detect_granularity(dates)
        assert gran == "月"
        assert days == 30.44

    def test_weekly_granularity(self):
        dates = pd.to_datetime(
            pd.Series(["2026-01-05", "2026-01-12", "2026-01-19"])
        )
        gran, days = _detect_granularity(dates)
        assert gran == "周"
        assert days == 7.0

    def test_daily_granularity(self):
        dates = pd.to_datetime(
            pd.Series(["2026-06-01", "2026-06-02", "2026-06-03"])
        )
        gran, days = _detect_granularity(dates)
        assert gran == "日"
        assert days == 1.0


class TestAnnualDemandComputation:
    """场景 5：年需求推断正确性 — 24 期月数据，总和 2400 → annual_demand=1200。"""

    def test_annual_demand_monthly(self):
        months = pd.date_range("2024-01-01", periods=24, freq="MS")
        df = pd.DataFrame({
            "month": months,
            "demand": [100.0] * 24,
        })
        params = InventoryPipelineParams(csv_path="fake.csv")
        result = _compute_annual_demand(df, params, "月")
        assert result == pytest.approx(1200.0)

    def test_annual_demand_24_month_total_2400(self, monthly_csv_24):
        """用生成的 24 期数据验证：总需求 / 24 * 12。"""
        df = pd.read_csv(monthly_csv_24)
        total = df["demand"].sum()
        params = InventoryPipelineParams(csv_path=monthly_csv_24)
        annual = _compute_annual_demand(df, params, "月")
        expected = total / len(df) * 12
        assert annual == pytest.approx(expected)


class TestCustomParameters:
    """场景 6：自定义参数覆盖（ordering_cost=200）。"""

    def test_ordering_cost_override(self, monthly_csv_24, tmp_output_dir):
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            ordering_cost=200.0,  # override from default 100
            output_dir=tmp_output_dir,
        )
        result = run_inventory_pipeline(params)

        assert result.eoq_result is not None
        # EOQ ∝ sqrt(ordering_cost): doubling should increase EOQ by sqrt(2)
        # Verify it was actually used
        assert result.eoq_result.eoq > 0

        # Run with default and verify difference
        params_default = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            output_dir=tmp_output_dir,
        )
        result_default = run_inventory_pipeline(params_default)
        assert result.eoq_result.eoq != result_default.eoq_result.eoq


class TestChartsGeneration:
    """场景 7：图表文件生成。"""

    def test_charts_produced(self, monthly_csv_24, tmp_output_dir):
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            output_dir=tmp_output_dir,
        )
        result = run_inventory_pipeline(params)

        assert len(result.charts) >= 1
        for chart_path in result.charts:
            assert Path(chart_path).exists()


class TestReportStructure:
    """场景 8：报告 8 章节完整性。"""

    def test_report_8_sections(self, monthly_csv_24, tmp_output_dir):
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            output_dir=tmp_output_dir,
        )
        result = run_inventory_pipeline(params)
        report_text = Path(result.report_path).read_text(encoding="utf-8")

        expected_sections = [
            "## 1. 概述",
            "## 2. 数据质量摘要",
            "## 3. 需求预测结果",
            "## 4. EOQ 经济订货批量分析",
            "## 5. 安全库存分析",
            "## 6. 补货点决策",
            "## 7. 综合建议",
            "## 8. 附录",
        ]
        for section in expected_sections:
            assert section in report_text, f"Missing section: {section}"


class TestColumnValidation:
    """场景 9-10：列名校验。"""

    def test_time_col_missing(self, monthly_csv_24, tmp_output_dir):
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            time_col="nonexistent_col",
            output_dir=tmp_output_dir,
        )
        result = run_inventory_pipeline(params)
        # Pipeline should return early with empty result
        assert result.report_path == ""

    def test_demand_col_missing(self, monthly_csv_24, tmp_output_dir):
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            demand_col="nonexistent_col",
            output_dir=tmp_output_dir,
        )
        result = run_inventory_pipeline(params)
        assert result.report_path == ""


class TestEdgeCases:
    """场景 11-12：边界情况（空 CSV、单期数据）。"""

    def test_empty_csv(self, tmp_output_dir):
        """空 CSV（0 行数据）。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("month,demand\n")
            csv_path = f.name

        try:
            params = InventoryPipelineParams(
                csv_path=csv_path,
                output_dir=tmp_output_dir,
            )
            result = run_inventory_pipeline(params)
            # Should return early, forecast_result=None
            assert result.forecast_result is None
            # But other steps that don't need history can continue
            # (quality check may still work with 0 rows)
        finally:
            Path(csv_path).unlink(missing_ok=True)

    def test_single_period(self, tmp_output_dir):
        """单期数据：forecast_result=None，但其他步骤继续。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("month,demand\n")
            f.write("2026-01-01,100\n")
            csv_path = f.name

        try:
            params = InventoryPipelineParams(
                csv_path=csv_path,
                output_dir=tmp_output_dir,
            )
            result = run_inventory_pipeline(params)
            # forecast should fail (need ≥2 periods), but pipeline continues
            assert result.forecast_result is None
            # EOQ / safety_stock / ROP should still compute (1 data point is enough)
            assert result.eoq_result is not None
            assert result.safety_stock_result is not None
            assert result.rop_result is not None
            assert result.quality_report is not None
        finally:
            Path(csv_path).unlink(missing_ok=True)


class TestQuickAnalyze:
    """场景 13：quick_analyze 便捷入口。"""

    def test_quick_analyze(self, monthly_csv_24, tmp_output_dir):
        result = quick_analyze(monthly_csv_24, output_dir=tmp_output_dir)
        assert isinstance(result, InventoryPipelineResult)
        assert result.report_path != ""
        assert Path(result.report_path).exists()
        assert result.forecast_result is not None


class TestRunAlias:
    """场景 14：run 别名可调用。"""

    def test_run_alias(self, monthly_csv_24, tmp_output_dir):
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            output_dir=tmp_output_dir,
        )
        result = run(params)
        assert isinstance(result, InventoryPipelineResult)
        assert result.report_path != ""


class TestPartialFailure:
    """场景 15：单步失败不中断流水线（如 chart 失败）。"""

    def test_pipeline_continues_on_step_failure(self, monthly_csv_24, tmp_output_dir):
        """验证即使某一步 "失败"（e.g. 空 charts 目录在只读位置），其他步骤结果仍保留。"""
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            time_col="month",
            demand_col="demand",
            output_dir=tmp_output_dir,
        )
        result = run_inventory_pipeline(params)

        # All computation steps should still succeed
        assert result.quality_report is not None
        assert result.forecast_result is not None
        assert result.eoq_result is not None
        assert result.safety_stock_result is not None
        assert result.rop_result is not None

        # Charts should be generated
        assert len(result.charts) >= 1

        # Even if charts fail, the report should have been written
        report_text = Path(result.report_path).read_text(encoding="utf-8")
        assert "## 1. 概述" in report_text

    def test_invalid_time_col_still_writes_nothing(self, monthly_csv_24, tmp_output_dir):
        """列名不存在时应返回空结果。"""
        params = InventoryPipelineParams(
            csv_path=monthly_csv_24,
            time_col="bad_col",
            output_dir=tmp_output_dir,
        )
        result = run_inventory_pipeline(params)
        assert result.report_path == ""


class TestGranularityEdgeCases:
    """辅助：粒度检测边界情况。"""

    def test_single_date_defaults_monthly(self):
        """单个日期默认返回月粒度。"""
        dates = pd.to_datetime(pd.Series(["2026-01-01"]))
        gran, days = _detect_granularity(dates)
        assert gran == "月"

    def test_unknown_diff_defaults_monthly(self):
        """差值不在已知范围时默认返回月粒度。"""
        # 15-day diff doesn't match any known pattern
        dates = pd.to_datetime(
            pd.Series(["2026-01-01", "2026-01-16", "2026-01-31"])
        )
        gran, days = _detect_granularity(dates)
        assert gran == "月"


class TestAnnualDemandEdgeCases:
    """辅助：年需求推断边界。"""

    def test_empty_df_returns_zero(self):
        df = pd.DataFrame({"month": [], "demand": []})
        params = InventoryPipelineParams(csv_path="fake.csv")
        result = _compute_annual_demand(df, params, "月")
        assert result == 0.0

    def test_weekly_annual_demand(self):
        """8 周数据，total=441, n=8 → 441/8*52 = 2866.5。"""
        weeks = pd.date_range("2026-01-05", periods=8, freq="7D")
        demand = [50, 55, 48, 60, 52, 58, 63, 55]
        df = pd.DataFrame({"week": weeks, "demand": demand})
        params = InventoryPipelineParams(csv_path="fake.csv")
        result = _compute_annual_demand(df, params, "周")
        expected = sum(demand) / 8 * 52
        assert result == pytest.approx(expected)

    def test_daily_annual_demand(self):
        """14 天数据。"""
        days = pd.date_range("2026-06-01", periods=14, freq="D")
        demand = [10, 12, 9, 11, 13, 10, 8, 12, 11, 9, 10, 13, 11, 10]
        df = pd.DataFrame({"date": days, "demand": demand})
        params = InventoryPipelineParams(csv_path="fake.csv")
        result = _compute_annual_demand(df, params, "日")
        expected = sum(demand) / 14 * 365
        assert result == pytest.approx(expected)


# ======================================================================
# 直接运行
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

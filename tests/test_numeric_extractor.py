"""测试数值结果提取器。

验证 extract_numeric_value 和 compute_consistency 的正确性。
"""

from __future__ import annotations

import math

import pytest

from src.benchmark.numeric_extractor import extract_numeric_value, compute_consistency


class TestExtractNumericValue:
    """extract_numeric_value 测试。"""

    def test_eoq_standard(self) -> None:
        """CG-01: 标准 EOQ 输出。"""
        val = extract_numeric_value("CG-01", "EOQ = 223.61, 年订货次数 = 4.47")
        assert val is not None
        assert math.isclose(val, 223.61, rel_tol=0.001)

    def test_eoq_chinese(self) -> None:
        """CG-01: 中文 EOQ 输出。"""
        val = extract_numeric_value("CG-01", "经济订货批量(EOQ) = 223.61")
        assert val is not None
        assert math.isclose(val, 223.61, rel_tol=0.001)

    def test_eoq_adv(self) -> None:
        """ADV-01: 对抗任务 EOQ 输出。"""
        val = extract_numeric_value("ADV-01", "EOQ计算结果: 223.60679774997897 件")
        assert val is not None
        assert math.isclose(val, 223.606, rel_tol=0.01)

    def test_eoq_fallback_line(self) -> None:
        """CG-01: 回退到包含'span>EOQ' 的行中提取数值。"""
        val = extract_numeric_value("CG-01", "最优订货批量 = 223.61 件\n年总成本 = 447.21")
        assert val is not None
        assert math.isclose(val, 223.61, rel_tol=0.001)

    def test_forecast(self) -> None:
        """CG-02: 需求预测输出。"""
        val = extract_numeric_value("CG-02", "forecasts: [144.9, 147.8, 150.7]\nMAPE: 10.84%")
        assert val is not None
        assert math.isclose(val, 144.9, rel_tol=0.01)

    def test_forecast_chinese(self) -> None:
        """CG-02: 中文预测输出。"""
        val = extract_numeric_value("CG-02", "预测值: [120.5, 125.3, 130.1]")
        assert val is not None
        assert math.isclose(val, 120.5, rel_tol=0.01)

    def test_safety_stock(self) -> None:
        """CG-03: 安全库存输出。"""
        val = extract_numeric_value("CG-03", "安全库存 = 46.52\nZ值 = 1.6449")
        assert val is not None
        assert math.isclose(val, 46.52, rel_tol=0.01)

    def test_safety_stock_english(self) -> None:
        """CG-03: 英文安全库存输出。"""
        val = extract_numeric_value("CG-03", "safety_stock = 46.52")
        assert val is not None
        assert math.isclose(val, 46.52, rel_tol=0.01)

    def test_reorder_point(self) -> None:
        """CG-04: 补货点输出。"""
        val = extract_numeric_value("CG-04", "补货点 = 250.0\nlead_time_demand = 200")
        assert val is not None
        assert math.isclose(val, 250.0, rel_tol=0.01)

    def test_reorder_point_english(self) -> None:
        """CG-04: 英文补货点输出。"""
        val = extract_numeric_value("CG-04", "ROP = 250.0\nreorder_point = 250.0")
        assert val is not None
        assert math.isclose(val, 250.0, rel_tol=0.01)

    def test_non_numeric_task(self) -> None:
        """BA/非数值任务返回 None。"""
        assert extract_numeric_value("BA-01", "均值 100，标准差 20") is None
        assert extract_numeric_value("BA-03", "图表已生成") is None
        assert extract_numeric_value("CG-05", "pipeline 完成") is None
        assert extract_numeric_value("ADV-06", "回文检查完成") is None
        assert extract_numeric_value("ADV-07", "最终价格 190") is None

    def test_empty_input(self) -> None:
        """空输出返回 None。"""
        assert extract_numeric_value("CG-01", "") is None
        assert extract_numeric_value("CG-01", None) is None  # type: ignore[arg-type]

    def test_no_match_in_output(self) -> None:
        """输出中无可匹配的数值模式。"""
        val = extract_numeric_value("CG-01", "计算完成，没有错误")
        assert val is None


class TestComputeConsistency:
    """compute_consistency 测试。"""

    def test_all_consistent(self) -> None:
        """三个值都在 ±5% 内。"""
        values = [223.61, 224.01, 220.15]
        consistent, mean_val = compute_consistency(values)
        assert consistent == 3  # 全部一致
        assert mean_val is not None

    def test_all_inconsistent(self) -> None:
        """三个值差异 >5%。"""
        values = [200.0, 300.0, 250.0]
        consistent, mean_val = compute_consistency(values)
        assert consistent < 3  # 不一致
        assert mean_val is not None

    def test_mixed_with_none(self) -> None:
        """含 None 的混合列表。"""
        values = [223.61, None, 225.0]
        consistent, mean_val = compute_consistency(values)
        assert consistent == 2  # 两个有效值互为一致
        assert mean_val is not None

    def test_all_none(self) -> None:
        """全部为 None。"""
        values = [None, None, None]
        consistent, mean_val = compute_consistency(values)
        assert consistent == 0
        assert mean_val is None

    def test_empty_list(self) -> None:
        """空列表。"""
        consistent, mean_val = compute_consistency([])
        assert consistent == 0
        assert mean_val is None

    def test_exact_same_values(self) -> None:
        """完全相同的值——全部一致。"""
        values = [100.0, 100.0, 100.0]
        consistent, _ = compute_consistency(values)
        assert consistent == 3

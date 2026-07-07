"""安全库存模板单元测试。

覆盖：3 种公式 / Z 分位数 / 服务水平标准化 / 边界条件 / run 别名。
"""

import math

import pytest
from scipy.stats import norm

from src.domain.templates.safety_stock import (
    SafetyStockParams,
    SafetyStockResult,
    calculate_safety_stock,
    quick_safety_stock,
    run,
    _normalize_service_level,
    _compute_z_score,
)


# ============================================================================
# 1. 常见 95% 服务水平 + 需求波动 → 情况 A
# ============================================================================


def test_case_a_95_service_level():
    """95% 服务水平 + 需求波动 + 提前期固定 → Z≈1.645，公式 A。"""
    # SS = 1.645 * 20 * sqrt(2) = 1.645 * 20 * 1.4142 ≈ 46.52
    params = SafetyStockParams(
        avg_demand=100, demand_std=20, lead_time=2, service_level=0.95
    )
    result = calculate_safety_stock(params)

    expected_z = round(float(norm.ppf(0.95)), 4)
    assert result.z_score == expected_z  # ≈ 1.6449
    assert math.isclose(result.safety_stock, round(expected_z * 20 * math.sqrt(2), 2), rel_tol=1e-9)
    assert result.service_level == 0.95
    assert "情况 A" in result.formula_used
    assert result.reorder_point_component == 200.0  # 100 × 2
    assert any("提前期固定" in a for a in result.assumptions)


# ============================================================================
# 2. 99% 服务水平
# ============================================================================


def test_99_service_level():
    """99% 服务水平 → Z≈2.326。"""
    params = SafetyStockParams(
        avg_demand=100, demand_std=15, lead_time=3, service_level=0.99
    )
    result = calculate_safety_stock(params)

    expected_z = round(float(norm.ppf(0.99)), 4)  # ≈ 2.3263
    assert result.z_score == expected_z
    # SS = z * 15 * sqrt(3) ≈ 2.3263 * 15 * 1.7321 ≈ 60.44
    expected_ss = expected_z * 15 * math.sqrt(3)
    assert math.isclose(result.safety_stock, round(expected_ss, 2), rel_tol=1e-6)


# ============================================================================
# 3. 90% 服务水平
# ============================================================================


def test_90_service_level():
    """90% 服务水平 → Z≈1.28。"""
    params = SafetyStockParams(
        avg_demand=200, demand_std=50, lead_time=1, service_level=0.90
    )
    result = calculate_safety_stock(params)

    expected_z = round(float(norm.ppf(0.90)), 4)  # ≈ 1.2816
    assert result.z_score == expected_z
    # SS = z * 50 * sqrt(1) = z * 50
    assert math.isclose(result.safety_stock, round(expected_z * 50, 2), rel_tol=1e-6)


# ============================================================================
# 4. 输入 95（而非 0.95）→ 正确标准化
# ============================================================================


def test_service_level_normalization_95_as_percent():
    """输入 95（而非 0.95）→ 正确标准化为 0.95。"""
    params = SafetyStockParams(
        avg_demand=100, demand_std=20, lead_time=2, service_level=95
    )
    result = calculate_safety_stock(params)

    assert result.service_level == 0.95  # normalized
    expected_z = round(float(norm.ppf(0.95)), 4)
    assert result.z_score == expected_z


def test_normalize_service_level_function():
    """_normalize_service_level 单元测试。"""
    assert _normalize_service_level(95) == 0.95
    assert _normalize_service_level(0.95) == 0.95
    assert math.isclose(_normalize_service_level(99.9), 0.999, rel_tol=1e-9)
    assert _normalize_service_level(0.90) == 0.90
    assert _normalize_service_level(1.0) == 1.0
    # boundary: exactly 1 → stays 1 (not divided)
    assert _normalize_service_level(1.0) == 1.0


# ============================================================================
# 5. 需求波动 + 提前期波动 → 情况 C
# ============================================================================


def test_case_c_both_variable():
    """需求与提前期皆波动 → 公式 C（平方和开根）。"""
    # avg=100, std_d=20, lt=2, std_lt=0.5, sl=0.95
    # SS = Z * sqrt(lt * std_d^2 + avg^2 * std_lt^2)
    #    = 1.6449 * sqrt(2 * 400 + 10000 * 0.25)
    #    = 1.6449 * sqrt(800 + 2500)
    #    = 1.6449 * sqrt(3300)
    #    = 1.6449 * 57.4456 ≈ 94.49
    params = SafetyStockParams(
        avg_demand=100, demand_std=20, lead_time=2,
        lead_time_std=0.5, service_level=0.95,
    )
    result = calculate_safety_stock(params)

    assert "情况 C" in result.formula_used
    z = round(float(norm.ppf(0.95)), 4)
    expected_ss = z * math.sqrt(2 * (20 ** 2) + (100 ** 2) * (0.5 ** 2))
    assert math.isclose(result.safety_stock, round(expected_ss, 2), rel_tol=1e-6)
    assert any("需求与提前期均存在不确定" in a for a in result.assumptions)


# ============================================================================
# 6. 仅提前期波动（demand_std=0）→ 情况 B
# ============================================================================


def test_case_b_lead_time_variability_only():
    """demand_std=0, lead_time_std>0 → 公式 B。"""
    # SS = Z * avg_demand * sigma_lt
    #    = 1.6449 * 100 * 0.5 = 82.24
    params = SafetyStockParams(
        avg_demand=100, demand_std=0, lead_time=2,
        lead_time_std=0.5, service_level=0.95,
    )
    result = calculate_safety_stock(params)

    assert "情况 B" in result.formula_used
    z = round(float(norm.ppf(0.95)), 4)
    expected_ss = z * 100 * 0.5
    assert math.isclose(result.safety_stock, round(expected_ss, 2), rel_tol=1e-6)
    assert any("需求完全确定" in a for a in result.assumptions)


# ============================================================================
# 7. 完全确定（两个 std 都为 0）→ safety_stock=0
# ============================================================================


def test_both_certain():
    """需求与提前期均无波动 → safety_stock=0。"""
    params = SafetyStockParams(
        avg_demand=50, demand_std=0, lead_time=1,
        lead_time_std=0, service_level=0.95,
    )
    result = calculate_safety_stock(params)

    assert result.safety_stock == 0.0
    assert "安全库存为 0" in result.formula_used
    assert result.reorder_point_component == 50.0  # 50 × 1


# ============================================================================
# 8. 零标准差边界 — 不报错，正常计算
# ============================================================================


def test_zero_std_boundary():
    """demand_std=0 且 lead_time_std=0（默认值）→ 不报错，SS=0。"""
    params = SafetyStockParams(
        avg_demand=30, demand_std=0, lead_time=3, service_level=0.90
    )
    result = calculate_safety_stock(params)
    assert result.safety_stock == 0.0


# ============================================================================
# 9. avg_demand=0 → ValueError
# ============================================================================


def test_avg_demand_zero():
    """avg_demand=0 → ValueError。"""
    params = SafetyStockParams(
        avg_demand=0, demand_std=10, lead_time=2, service_level=0.95
    )
    with pytest.raises(ValueError, match="平均需求必须 > 0"):
        calculate_safety_stock(params)


# ============================================================================
# 10. service_level=0 → ValueError
# ============================================================================


def test_service_level_zero():
    """service_level=0 → ValueError。"""
    params = SafetyStockParams(
        avg_demand=100, demand_std=10, lead_time=1, service_level=0
    )
    with pytest.raises(ValueError, match="服务水平必须在"):
        calculate_safety_stock(params)


# ============================================================================
# 11. service_level=150 → ValueError
# ============================================================================


def test_service_level_too_high():
    """service_level=150 → ValueError。"""
    params = SafetyStockParams(
        avg_demand=100, demand_std=10, lead_time=1, service_level=150
    )
    with pytest.raises(ValueError, match="服务水平必须在"):
        calculate_safety_stock(params)


# ============================================================================
# 12. 负标准差 → ValueError
# ============================================================================


def test_negative_demand_std():
    """demand_std 为负 → ValueError。"""
    params = SafetyStockParams(
        avg_demand=100, demand_std=-5, lead_time=2, service_level=0.95
    )
    with pytest.raises(ValueError, match="需求标准差不能为负"):
        calculate_safety_stock(params)


def test_negative_lead_time_std():
    """lead_time_std 为负 → ValueError。"""
    params = SafetyStockParams(
        avg_demand=100, demand_std=10, lead_time=2,
        lead_time_std=-0.5, service_level=0.95,
    )
    with pytest.raises(ValueError, match="提前期标准差不能为负"):
        calculate_safety_stock(params)


# ============================================================================
# 13. run 别名可调用
# ============================================================================


def test_run_alias():
    """run 别名可调用 — run(params) == calculate_safety_stock(params)。"""
    params = SafetyStockParams(
        avg_demand=100, demand_std=20, lead_time=2, service_level=0.95
    )
    r1 = calculate_safety_stock(params)
    r2 = run(params)

    assert r1.safety_stock == r2.safety_stock
    assert r1.z_score == r2.z_score
    assert r1.service_level == r2.service_level
    assert r1.formula_used == r2.formula_used
    assert r1.reorder_point_component == r2.reorder_point_component


# ============================================================================
# 附加：quick_safety_stock 便捷入口
# ============================================================================


def test_quick_safety_stock():
    """quick_safety_stock 便捷入口正常工作。"""
    result = quick_safety_stock(avg_demand=500, demand_std=100, lead_time=4, service_level=95)

    assert result.safety_stock > 0
    assert result.service_level == 0.95
    assert result.reorder_point_component == 2000.0  # 500 × 4
    assert "情况 A" in result.formula_used  # lead_time_std defaults to 0


# ============================================================================
# 附加：Z 分位数直接计算
# ============================================================================


def test_compute_z_score():
    """_compute_z_score 直接计算验证。"""
    # Use known values
    z_90 = _compute_z_score(0.90)
    z_95 = _compute_z_score(0.95)
    z_99 = _compute_z_score(0.99)

    assert math.isclose(z_90, 1.2816, abs_tol=0.01)
    assert math.isclose(z_95, 1.6449, abs_tol=0.01)
    assert math.isclose(z_99, 2.3263, abs_tol=0.01)


# ============================================================================
# 附加：lead_time=0 边界
# ============================================================================


def test_lead_time_zero():
    """lead_time=0 边界 — 不报错，结果有意义。"""
    params = SafetyStockParams(
        avg_demand=100, demand_std=20, lead_time=0, service_level=0.95
    )
    result = calculate_safety_stock(params)

    # SS = z * 20 * sqrt(0) = 0 (since sqrt(0)=0, but our formula is Case A)
    assert result.safety_stock == 0.0
    assert result.reorder_point_component == 0.0

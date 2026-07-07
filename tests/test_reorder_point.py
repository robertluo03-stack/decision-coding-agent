"""补货点（ROP）模板单元测试。

覆盖：核心公式 / EOQ 组合 / 复合接口 / 规则建议 / 边界条件 / run 别名。
"""

import pytest

from src.domain.templates.reorder_point import (
    ROPParams,
    ROPResult,
    calculate,
    from_eoq_and_safety_stock,
    run,
)


# ============================================================================
# 1. 正常计算 ROP
# ============================================================================


def test_normal_rop():
    """正常计算 ROP — rop = lead_time_demand + safety_stock。"""
    params = ROPParams(avg_demand=100, lead_time=2, safety_stock=50)
    result = calculate(params)

    assert result.lead_time_demand == 200.0  # 100 × 2
    assert result.reorder_point == 250.0     # 200 + 50
    assert result.safety_stock == 50.0


# ============================================================================
# 2. ROP 含 EOQ
# ============================================================================


def test_rop_with_eoq():
    """ROP 含 EOQ — eoq 字段正确传递。"""
    params = ROPParams(avg_demand=100, lead_time=2, safety_stock=50, eoq=224)
    result = calculate(params)

    assert result.eoq == 224.0
    assert result.reorder_point == 250.0


# ============================================================================
# 3. ROP 不含 EOQ
# ============================================================================


def test_rop_without_eoq():
    """ROP 不含 EOQ — eoq = None。"""
    params = ROPParams(avg_demand=100, lead_time=2, safety_stock=50)
    result = calculate(params)

    assert result.eoq is None


# ============================================================================
# 4. safety_stock = 0
# ============================================================================


def test_safety_stock_zero():
    """safety_stock=0 — rop = lead_time_demand，建议含风险提示。"""
    params = ROPParams(avg_demand=80, lead_time=3, safety_stock=0, eoq=200)
    result = calculate(params)

    assert result.reorder_point == 240.0  # 80 × 3 + 0
    assert result.safety_stock == 0.0
    assert "安全库存为 0" in result.suggestion
    assert "建议评估需求波动风险" in result.suggestion


# ============================================================================
# 5. 复合接口 from_eoq_and_safety_stock
# ============================================================================


def test_from_eoq_and_safety_stock():
    """复合接口 — 正确使用 EOQResult 和 SafetyStockResult 构建 ROP。"""
    from src.domain.templates.inventory_eoq import calculate as calc_eoq, EOQParams
    from src.domain.templates.safety_stock import calculate_safety_stock, SafetyStockParams

    eoq = calc_eoq(EOQParams(annual_demand=1200, ordering_cost=50, holding_cost=2))
    ss = calculate_safety_stock(
        SafetyStockParams(avg_demand=100, demand_std=20, lead_time=2, service_level=95)
    )

    rop = from_eoq_and_safety_stock(
        avg_demand=100, lead_time=2, eoq_result=eoq, safety_stock_result=ss
    )

    assert rop.lead_time_demand == 200.0  # 100 × 2
    assert rop.safety_stock > 0  # from SS calc
    assert rop.eoq is not None  # from EOQ calc
    assert rop.reorder_point == rop.lead_time_demand + rop.safety_stock
    assert "(ROP, Q)" in rop.suggestion


# ============================================================================
# 6. suggestion 包含补货点数字
# ============================================================================


def test_suggestion_contains_rop_value():
    """suggestion 包含 reorder_point 的整数值。"""
    params = ROPParams(avg_demand=150, lead_time=2, safety_stock=30)
    result = calculate(params)

    assert "330" in result.suggestion  # 150×2 + 30 = 330 → int
    assert "提前期平均消耗 300" in result.suggestion
    assert "安全库存 30" in result.suggestion


# ============================================================================
# 7. suggestion 含 EOQ 时提到订货量
# ============================================================================


def test_suggestion_with_eoq_mentions_order_quantity():
    """suggestion 含 EOQ 时提到订货量和 (ROP, Q) 策略。"""
    params = ROPParams(avg_demand=100, lead_time=2, safety_stock=50, eoq=224)
    result = calculate(params)

    assert "224" in result.suggestion
    assert "(ROP, Q)" in result.suggestion


# ============================================================================
# 8. suggestion 无 EOQ 时建议结合 EOQ
# ============================================================================


def test_suggestion_without_eoq_recommends_eoq():
    """suggestion 无 EOQ 时建议结合 EOQ。"""
    params = ROPParams(avg_demand=100, lead_time=2, safety_stock=50)
    result = calculate(params)

    assert "EOQ" in result.suggestion
    assert "建议结合 EOQ 模型确定最优订货量" in result.suggestion


# ============================================================================
# 9. 零提前期
# ============================================================================


def test_zero_lead_time():
    """零提前期 — lead_time_demand=0, rop=safety_stock。"""
    params = ROPParams(avg_demand=100, lead_time=0, safety_stock=50)
    result = calculate(params)

    assert result.lead_time_demand == 0.0
    assert result.reorder_point == 50.0  # only safety stock


# ============================================================================
# 10. 负 safety_stock → ValueError
# ============================================================================


def test_negative_safety_stock():
    """负 safety_stock → ValueError。"""
    params = ROPParams(avg_demand=100, lead_time=2, safety_stock=-10)
    with pytest.raises(ValueError, match="安全库存不能为负"):
        calculate(params)


# ============================================================================
# 11. run 别名可调用
# ============================================================================


def test_run_alias():
    """run 别名可调用 — run(params) == calculate(params)。"""
    params = ROPParams(avg_demand=200, lead_time=2, safety_stock=60, eoq=300)
    r1 = calculate(params)
    r2 = run(params)

    assert r1.reorder_point == r2.reorder_point
    assert r1.lead_time_demand == r2.lead_time_demand
    assert r1.safety_stock == r2.safety_stock
    assert r1.eoq == r2.eoq
    assert r1.suggestion == r2.suggestion


# ============================================================================
# 附加：avg_demand=0 → ValueError
# ============================================================================


def test_avg_demand_zero():
    """avg_demand=0 → ValueError。"""
    params = ROPParams(avg_demand=0, lead_time=2, safety_stock=10)
    with pytest.raises(ValueError, match="平均需求必须 > 0"):
        calculate(params)


# ============================================================================
# 附加：负 lead_time → ValueError
# ============================================================================


def test_negative_lead_time():
    """负 lead_time → ValueError。"""
    params = ROPParams(avg_demand=100, lead_time=-1, safety_stock=10)
    with pytest.raises(ValueError, match="提前期不能为负"):
        calculate(params)


# ============================================================================
# 附加：from_eoq_and_safety_stock 仅 EOQ（无 SS）
# ============================================================================


def test_from_eoq_only():
    """from_eoq_and_safety_stock 仅传入 EOQ 结果（无 SS）— safety_stock 默认为 0。"""
    from src.domain.templates.inventory_eoq import calculate as calc_eoq, EOQParams

    eoq = calc_eoq(EOQParams(annual_demand=1200, ordering_cost=50, holding_cost=2))

    rop = from_eoq_and_safety_stock(
        avg_demand=50, lead_time=4, eoq_result=eoq, safety_stock_result=None
    )

    assert rop.lead_time_demand == 200.0
    assert rop.safety_stock == 0.0
    assert rop.reorder_point == 200.0
    assert rop.eoq is not None
    assert "安全库存为 0" in rop.suggestion
    assert "建议评估需求波动风险" in rop.suggestion


# ============================================================================
# 附加：from_eoq_and_safety_stock 仅 SS（无 EOQ）
# ============================================================================


def test_from_ss_only():
    """from_eoq_and_safety_stock 仅传入 SS 结果（无 EOQ）— eoq=None。"""
    from src.domain.templates.safety_stock import calculate_safety_stock, SafetyStockParams

    ss = calculate_safety_stock(
        SafetyStockParams(avg_demand=80, demand_std=15, lead_time=3, service_level=90)
    )

    rop = from_eoq_and_safety_stock(
        avg_demand=80, lead_time=3, eoq_result=None, safety_stock_result=ss
    )

    assert rop.lead_time_demand == 240.0
    assert rop.safety_stock > 0
    assert rop.eoq is None
    assert "建议结合 EOQ" in rop.suggestion


# ============================================================================
# 附加：suggestion 完整结构验证
# ============================================================================


def test_suggestion_complete_structure():
    """suggestion 完整结构：触发条件 + 订货量 + 组成 + 策略建议。"""
    params = ROPParams(avg_demand=100, lead_time=2, safety_stock=50, eoq=224)
    result = calculate(params)

    assert "当库存降至" in result.suggestion
    assert "时触发补货" in result.suggestion
    assert "提前期平均消耗" in result.suggestion
    assert "安全库存" in result.suggestion
    assert "(ROP, Q)" in result.suggestion
    # 应以句号结尾
    assert result.suggestion.endswith("。")


# ============================================================================
# 附加：大数值
# ============================================================================


def test_large_values():
    """大数值 — 不溢出，正常计算。"""
    params = ROPParams(
        avg_demand=50000, lead_time=4, safety_stock=12000, eoq=30000
    )
    result = calculate(params)

    assert result.lead_time_demand == 200000.0
    assert result.reorder_point == 212000.0
    assert result.eoq == 30000.0
    assert len(result.suggestion) > 0

"""参数提取器单元测试。

覆盖：数值提取 / 参数名匹配 / 模板定向提取 / 缺失参数检测 / 边界条件。
"""

import pytest

from src.domain.param_extractor import (
    extract_params,
    extract_params_for_template,
    describe_missing_params,
    run,
    _find_all_numbers,
    _lookup_param_name,
    PARAM_ALIASES,
)
from src.domain.template_matcher import TemplateType


# ============================================================================
# 1. 中文 EOQ 三参数
# ============================================================================


def test_extract_eoq_chinese():
    """'年需求1000，订货成本50，持有成本2' → 3 个参数全对。"""
    result = extract_params("年需求1000，订货成本50，持有成本2")
    assert result["annual_demand"] == 1000.0
    assert result["ordering_cost"] == 50.0
    assert result["holding_cost"] == 2.0


# ============================================================================
# 2. 英文别名识别
# ============================================================================


def test_extract_english_aliases():
    """'annual demand 1000, ordering cost 50' → 英文别名识别。"""
    result = extract_params("annual demand 1000, ordering cost 50")
    assert result["annual_demand"] == 1000.0
    assert result["ordering_cost"] == 50.0


# ============================================================================
# 3. 服务水平 95%（百分比识别）
# ============================================================================


def test_extract_service_level_percent():
    """'服务水平 95%' → service_level=95.0。"""
    result = extract_params("服务水平 95%")
    assert result["service_level"] == 95.0


# ============================================================================
# 4. 服务水平 0.95（小数）
# ============================================================================


def test_extract_service_level_decimal():
    """'服务水平 0.95' → service_level=0.95。"""
    result = extract_params("服务水平 0.95")
    assert result["service_level"] == 0.95


# ============================================================================
# 5. 平均需求 + 标准差
# ============================================================================


def test_extract_avg_demand_and_std():
    """'平均需求 100，标准差 20' → avg_demand + demand_std。"""
    result = extract_params("平均需求 100，标准差 20")
    assert result["avg_demand"] == 100.0
    assert result["demand_std"] == 20.0


# ============================================================================
# 6. 提前期
# ============================================================================


def test_extract_lead_time():
    """'提前期 2 周' → lead_time=2.0。"""
    result = extract_params("提前期 2 周")
    assert result["lead_time"] == 2.0


def test_extract_leadtime_combo():
    """'leadtime 3' → lead_time=3.0。"""
    result = extract_params("leadtime 3")
    assert result["lead_time"] == 3.0


# ============================================================================
# 7. 订货费 + 库存持有成本
# ============================================================================


def test_extract_ordering_and_holding_cost_variants():
    """'订货费 100，库存持有成本 5' → ordering_cost + holding_cost。"""
    result = extract_params("订货费 100，库存持有成本 5")
    assert result["ordering_cost"] == 100.0
    assert result["holding_cost"] == 5.0


# ============================================================================
# 8. 多参数混合提取
# ============================================================================


def test_extract_mixed_params():
    """'需求 500 成本 30' → 正确映射各值到对应参数。"""
    result = extract_params("需求 500 成本 30")
    assert result["annual_demand"] == 500.0
    # '成本' alone doesn't match — it doesn't appear in aliases directly
    # 'ordering_cost' aliases: "订货成本", "订购成本", etc.
    # 'holding_cost' aliases: "持有成本", "库存成本", etc.
    # '成本' alone is not specific enough to match


# ============================================================================
# 9. 无数字的 query
# ============================================================================


def test_extract_no_numbers():
    """无数字的 query → 空 dict。"""
    result = extract_params("帮我分析一下数据")
    assert result == {}


# ============================================================================
# 10. 数字无前导参数名
# ============================================================================


def test_extract_number_no_context():
    """数字无前导参数名 → 不提取（空 dict）。"""
    result = extract_params("给我看看 1000 和 50")
    assert result == {}  # no parameter name near the numbers


# ============================================================================
# 11. 小数识别
# ============================================================================


def test_extract_decimal():
    """'持有成本 2.5' → 2.5。"""
    result = extract_params("持有成本 2.5")
    assert result["holding_cost"] == 2.5


# ============================================================================
# 12. extract_params_for_template — 只提取 EOQ 相关参数
# ============================================================================


def test_extract_for_eoq_template():
    """extract_params_for_template EOQ — 只提取 EOQ 相关参数。"""
    result = extract_params_for_template(
        "年需求1000 订货成本50 持有成本2 服务水平95 提前期 2",
        TemplateType.EOQ,
    )
    assert "annual_demand" in result
    assert "ordering_cost" in result
    assert "holding_cost" in result
    assert "service_level" not in result  # not EOQ-related
    assert "lead_time" not in result       # not EOQ-related


# ============================================================================
# 13. describe_missing_params — 全缺 → 3 个
# ============================================================================


def test_describe_missing_all_eoq():
    """describe_missing_params EOQ 全缺 → 列出 3 个缺失参数。"""
    missing = describe_missing_params(TemplateType.EOQ, {})
    assert len(missing) == 3
    assert "年需求量" in missing
    assert "订货成本" in missing
    assert "持有成本" in missing


# ============================================================================
# 14. describe_missing_params — 缺 1 个
# ============================================================================


def test_describe_missing_one():
    """describe_missing_params EOQ 缺 1 个 → 列出 1 个缺失参数。"""
    extracted = {"annual_demand": 1000.0, "ordering_cost": 50.0}
    missing = describe_missing_params(TemplateType.EOQ, extracted)
    assert len(missing) == 1
    assert "持有成本" in missing


def test_describe_missing_none():
    """describe_missing_params — 无缺失 → 空列表。"""
    extracted = {
        "annual_demand": 1000.0,
        "ordering_cost": 50.0,
        "holding_cost": 2.0,
    }
    missing = describe_missing_params(TemplateType.EOQ, extracted)
    assert missing == []


# ============================================================================
# 15. 中文逗号分隔
# ============================================================================


def test_extract_chinese_comma():
    """中文逗号分隔 — 正常提取。"""
    result = extract_params("年需求1200，订货成本60，持有成本3")
    assert result["annual_demand"] == 1200.0
    assert result["ordering_cost"] == 60.0
    assert result["holding_cost"] == 3.0


# ============================================================================
# 16. 含"万"单位 — 只提取数字部分
# ============================================================================


def test_extract_with_wan_unit():
    """含'万'单位 — 只提取数字部分（如 '1'）。"""
    result = extract_params("年需求 1 万")
    # The number "1" appears, "万" is not part of it
    # "需求" is an alias for annual_demand
    assert "annual_demand" in result
    assert result["annual_demand"] == 1.0  # Just the number, not "10000"


# ============================================================================
# 17. 同一参数多次出现 → 取第一次
# ============================================================================


def test_extract_duplicate_params():
    """同一参数多次出现 → 取第一个出现的值。"""
    result = extract_params("需求 100 需求 200")
    assert result["annual_demand"] == 100.0  # first occurrence wins


# ============================================================================
# 18. run 别名可调用
# ============================================================================


def test_run_alias():
    """run 别名可调用 — run(query) == extract_params(query)。"""
    r1 = extract_params("年需求1000，订货成本50")
    r2 = run("年需求1000，订货成本50")
    assert r1 == r2


# ============================================================================
# 附加：_find_all_numbers 单元测试
# ============================================================================


def test_find_all_numbers_integers():
    """_find_all_numbers — 整数值提取。"""
    nums = _find_all_numbers("abc 123 def 456")
    assert len(nums) >= 2
    values = [v for _, v, _ in nums]
    assert 123.0 in values
    assert 456.0 in values


def test_find_all_numbers_decimal():
    """_find_all_numbers — 小数值提取。"""
    nums = _find_all_numbers("价格 12.99 元")
    values = [v for _, v, _ in nums]
    assert 12.99 in values


def test_find_all_numbers_percent():
    """_find_all_numbers — 百分比提取。"""
    nums = _find_all_numbers("服务水平 95% 需要")
    for _, v, is_pct in nums:
        if v == 95.0:
            assert is_pct


# ============================================================================
# 附加：_lookup_param_name 单元测试
# ============================================================================


def test_lookup_param_name_match():
    """_lookup_param_name — 匹配'年需求' → 'annual_demand'。"""
    assert _lookup_param_name("年需求") == "annual_demand"


def test_lookup_param_name_no_match():
    """_lookup_param_name — 不匹配无关文本。"""
    assert _lookup_param_name("xyz测试") is None


# ============================================================================
# 附加：PARAM_ALIASES 完整性
# ============================================================================


def test_param_aliases_all_templates():
    """所有必填参数的模板别名均有覆盖。"""
    # EOQ params
    assert "annual_demand" in PARAM_ALIASES
    assert "ordering_cost" in PARAM_ALIASES
    assert "holding_cost" in PARAM_ALIASES
    # Safety stock params
    assert "avg_demand" in PARAM_ALIASES
    assert "demand_std" in PARAM_ALIASES
    assert "lead_time" in PARAM_ALIASES
    assert "service_level" in PARAM_ALIASES
    # ROP params
    assert "safety_stock" in PARAM_ALIASES


# ============================================================================
# 附加：FORECAST 模板必填参数为空（history 无法从文本提取）
# ============================================================================


def test_describe_missing_forecast():
    """FORECAST 必填参数为空 — describe_missing_params 返回 []。"""
    missing = describe_missing_params(TemplateType.FORECAST, {})
    assert missing == []


# ============================================================================
# 附加：UNKNOWN 模板必填参数为空
# ============================================================================


def test_describe_missing_unknown():
    """UNKNOWN 必填参数为空。"""
    missing = describe_missing_params(TemplateType.UNKNOWN, {"x": 1.0})
    assert missing == []


# ============================================================================
# 附加：SAFETY_STOCK 必填参数
# ============================================================================


def test_describe_missing_safety_stock():
    """SAFETY_STOCK 必填参数检查。"""
    missing = describe_missing_params(TemplateType.SAFETY_STOCK, {})
    # avg_demand, demand_std, lead_time, service_level
    assert len(missing) == 4


# ============================================================================
# 附加：REORDER_POINT 必填参数
# ============================================================================


def test_describe_missing_reorder_point():
    """REORDER_POINT 必填参数检查。"""
    missing = describe_missing_params(TemplateType.REORDER_POINT, {})
    # avg_demand, lead_time, safety_stock
    assert len(missing) == 3

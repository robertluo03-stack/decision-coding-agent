"""模板匹配器单元测试。

覆盖：6 种模板类型 / 精确匹配 / UNKNOWN 兜底 / 混合关键词 / 边界。
"""

import pytest

from src.domain.template_matcher import (
    TemplateType,
    MatchResult,
    match_template,
    match_with_fallback,
    run,
    KEYWORDS,
    _score_query,
)


# ============================================================================
# 1. EOQ 匹配
# ============================================================================


def test_match_eoq():
    """'帮我算 EOQ，年需求 1000' → EOQ。"""
    result = match_template("帮我算 EOQ，年需求 1000")
    assert result.template_type == TemplateType.EOQ
    assert result.confidence > 0
    assert "eoq" in [kw.lower() for kw in result.matched_keywords]


def test_match_eoq_chinese():
    """'经济订货批量' → EOQ（中文关键词）。"""
    result = match_template("经济订货批量")
    assert result.template_type == TemplateType.EOQ
    assert result.confidence >= 2.5


# ============================================================================
# 2. FORECAST 匹配
# ============================================================================


def test_match_forecast():
    """'预测一下下月需求' → FORECAST。"""
    result = match_template("预测一下下月需求")
    assert result.template_type == TemplateType.FORECAST
    assert result.confidence > 0


def test_match_forecast_trend():
    """'需求预测 趋势分析' → FORECAST。"""
    result = match_template("需求预测 趋势分析")
    assert result.template_type == TemplateType.FORECAST


# ============================================================================
# 3. SAFETY_STOCK 匹配
# ============================================================================


def test_match_safety_stock():
    """'安全库存怎么定，服务水平 95%' → SAFETY_STOCK。"""
    result = match_template("安全库存怎么定，服务水平 95%")
    assert result.template_type == TemplateType.SAFETY_STOCK
    assert result.confidence > 0


def test_match_buffer_stock():
    """'buffer stock 计算' → SAFETY_STOCK。"""
    result = match_template("buffer stock 计算")
    assert result.template_type == TemplateType.SAFETY_STOCK


# ============================================================================
# 4. REORDER_POINT 匹配
# ============================================================================


def test_match_reorder_point():
    """'库存降到多少要补货' → REORDER_POINT。"""
    result = match_template("库存降到多少要补货")
    assert result.template_type == TemplateType.REORDER_POINT


def test_match_reorder_english():
    """'reorder point 是多少' → REORDER_POINT。"""
    result = match_template("reorder point 是多少")
    assert result.template_type == TemplateType.REORDER_POINT


# ============================================================================
# 5. DATA_ANALYSIS 匹配
# ============================================================================


def test_match_data_analysis():
    """'分析这个销售数据' → DATA_ANALYSIS。"""
    result = match_template("分析这个销售数据")
    assert result.template_type == TemplateType.DATA_ANALYSIS


# ============================================================================
# 6. UNKNOWN 兜底
# ============================================================================


def test_match_unknown():
    """'毫无关系的query xyz123' → UNKNOWN。"""
    result = match_template("毫无关系的query xyz123")
    assert result.template_type == TemplateType.UNKNOWN
    assert result.confidence == 0.0


def test_match_empty_string():
    """空字符串 → UNKNOWN。"""
    result = match_template("")
    assert result.template_type == TemplateType.UNKNOWN


# ============================================================================
# 7. 混合关键词 → 最高分者胜出
# ============================================================================


def test_mixed_keywords():
    """'EOQ 和安全库存' → 最高分者。"""
    result = match_template("EOQ 和安全库存")
    assert result.template_type in (TemplateType.EOQ, TemplateType.SAFETY_STOCK)
    # Should not be UNKNOWN
    assert result.template_type != TemplateType.UNKNOWN


# ============================================================================
# 8. 大小写不敏感
# ============================================================================


def test_case_insensitive():
    """'EOQ' vs 'eoq' → 相同匹配。"""
    r_upper = match_template("EOQ")
    r_lower = match_template("eoq")
    assert r_upper.template_type == r_lower.template_type
    assert r_upper.confidence == r_lower.confidence


# ============================================================================
# 9. match_with_fallback
# ============================================================================


def test_match_with_fallback_known():
    """匹配已知模板 → 正常返回。"""
    result = match_with_fallback("帮我算安全库存")
    assert result.template_type == TemplateType.SAFETY_STOCK


def test_match_with_fallback_unknown():
    """匹配未知 → matched_keywords 含模板推荐列表。"""
    result = match_with_fallback("xyzzy")
    assert result.template_type == TemplateType.UNKNOWN
    assert len(result.matched_keywords) > 0  # fallback templates


# ============================================================================
# 10. run 别名
# ============================================================================


def test_run_alias():
    """run 别名可调用 — run(query) == match_template(query)。"""
    r1 = match_template("帮我算 EOQ")
    r2 = run("帮我算 EOQ")
    assert r1.template_type == r2.template_type
    assert r1.confidence == r2.confidence


# ============================================================================
# 附加：all_scores 包含所有类型
# ============================================================================


def test_all_scores_complete():
    """all_scores 包含所有 5 种模板类型的打分。"""
    result = match_template("EOQ")
    for ttype in (TemplateType.EOQ, TemplateType.FORECAST, TemplateType.SAFETY_STOCK,
                  TemplateType.REORDER_POINT, TemplateType.DATA_ANALYSIS):
        assert ttype in result.all_scores, f"Missing {ttype} in all_scores"


# ============================================================================
# 附加：matched_keywords 准确性
# ============================================================================


def test_matched_keywords_accurate():
    """matched_keywords 准确反映命中的关键词。"""
    result = match_template("经济订货批量计算")
    assert result.template_type == TemplateType.EOQ
    assert "经济订货" in result.matched_keywords
    assert "批量" in result.matched_keywords


# ============================================================================
# 附加：_score_query 单元测试
# ============================================================================


def test_score_query():
    """_score_query 手动测试。"""
    score, matched = _score_query("eoq 计算", [("eoq", 2.0), ("计算", 0.5)])
    assert score == 2.5  # eoq + 计算
    assert "eoq" in matched
    assert "计算" in matched


def test_score_query_duplicate():
    """同一关键词多次出现只计一次。"""
    score, _ = _score_query("eoq eoq eoq", [("eoq", 2.0)])
    assert score == 2.0  # not 6.0


# ============================================================================
# 附加：所有枚举值在 KEYWORDS 中
# ============================================================================


def test_all_template_types_have_keywords():
    """除 UNKNOWN 外，所有 TemplateType 在 KEYWORDS 中都有定义。"""
    for ttype in TemplateType:
        if ttype == TemplateType.UNKNOWN:
            continue
        assert ttype in KEYWORDS, f"TemplateType {ttype} missing from KEYWORDS"
        assert len(KEYWORDS[ttype]) > 0, f"TemplateType {ttype} has empty keywords"

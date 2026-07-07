"""供应链优化报告增强器测试套件。

覆盖场景：
  1. 全部规则触发（极端数据）
  2. 短历史（history_length=3）
  3. 长历史（history_length=24）
  4. 高 MAPE（30%）
  5. 低 MAPE（5%）
  6. 高 EOQ（>1000）
  7. 低安全库存比（<5%）
  8. 高安全库存比（>50%）
  9. 情况 A 公式
  10. 情况 C 公式
  11. 有异常值
  12. enhance_report 插入位置正确
  13. 空 info（全部 None/0）
  14. run 别名可调用
"""

import sys
import tempfile
from pathlib import Path

import pytest

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.report_enhancer import (
    EnhancerInput,
    EnhancedSections,
    enhance_report,
    build_enhancer_input,
    enhance_from_pipeline,
    run,
    _generate_assumptions,
    _generate_limitations,
    _generate_recommendations,
    _insert_enhanced_sections,
    _check,
    _format_template,
    _eval_math_expression,
)


# ======================================================================
# 脚手架
# ======================================================================


def build_base_report() -> str:
    """构建一个最小 8 章节省 baseline 报告（类似 inventory_pipeline 输出）。"""
    return "\n".join([
        "# 供应链库存优化分析报告",
        "",
        "## 1. 概述",
        "基于 24 期历史数据...",
        "",
        "## 2. 数据质量摘要",
        "综合评分：95/100",
        "",
        "## 3. 需求预测结果",
        "使用方法：Holt 双参数线性趋势",
        "",
        "## 4. EOQ 经济订货批量分析",
        "EOQ：223.61 件",
        "",
        "## 5. 安全库存分析",
        "安全库存量：46.52",
        "",
        "## 6. 补货点决策",
        "补货点：250",
        "",
        "## 7. 综合建议",
        "基于以上分析，建议采用 (ROP, Q) 库存策略。",
        "",
        "## 8. 附录",
        "### 分析图表",
        "![demand_trend](charts/demand_trend.html)",
        "### 分析参数配置表",
        "| 参数 | 值 |",
        "|------|-----|",
        "",
    ])


# ======================================================================
# 场景 1-10：规则触发测试
# ======================================================================


class TestAllRulesTriggered:
    """场景 1：极端数据 —— 所有条件规则都应触发。"""

    def test_all_rules_triggered(self):
        info = EnhancerInput(
            history_length=3,
            forecast_method="Holt 双参数线性趋势",
            mape=35.0,
            eoq=1500.0,
            annual_demand=10000.0,
            safety_stock=600.0,
            safety_stock_ratio=0.60,
            rop=800.0,
            lead_time=2.0,
            service_level=0.95,
            formula_used="情况 C — 需求与提前期皆波动",
            outlier_count=15,
            missing_ratio=0.12,
        )
        assumptions = _generate_assumptions(info)
        limitations = _generate_limitations(info)
        recommendations = _generate_recommendations(info)

        assert len(assumptions) >= 3, f"Expected ≥3 assumptions, got {len(assumptions)}: {assumptions}"
        assert len(limitations) >= 3, f"Expected ≥3 limitations, got {len(limitations)}: {limitations}"
        assert len(recommendations) >= 3, f"Expected ≥3 recommendations, got {len(recommendations)}: {recommendations}"


class TestShortHistory:
    """场景 2：短历史（history_length=3）→ limitations 含"数据量较少"。"""

    def test_short_history(self):
        info = EnhancerInput(history_length=3)
        limitations = _generate_limitations(info)
        assert any("数据量较少" in l for l in limitations), limitations


class TestLongHistory:
    """场景 3：长历史（history_length=24）→ limitations 不含"数据量"。"""

    def test_long_history(self):
        info = EnhancerInput(history_length=24)
        limitations = _generate_limitations(info)
        assert not any("数据量较少" in l or "数据量有限" in l for l in limitations), limitations


class TestHighMAPE:
    """场景 4：高 MAPE=30 → limitations 含"误差较大"。"""

    def test_high_mape(self):
        info = EnhancerInput(history_length=12, mape=30.0)
        limitations = _generate_limitations(info)
        assert any("误差较大" in l for l in limitations), limitations


class TestLowMAPE:
    """场景 5：低 MAPE=5 → recommendations 含"降低安全库存"。"""

    def test_low_mape(self):
        info = EnhancerInput(history_length=12, mape=5.0)
        recommendations = _generate_recommendations(info)
        printed = [r for r in recommendations if "预测精度良好" in r and "降低安全库存" in r]
        assert len(printed) >= 1, f"Expected recommendation about lowering safety stock, got: {recommendations}"


class TestHighEOQ:
    """场景 6：高 EOQ=2000 → recommendations 含"分批采购"。"""

    def test_high_eoq(self):
        info = EnhancerInput(eoq=2000.0)
        recommendations = _generate_recommendations(info)
        assert any("分批采购" in r for r in recommendations), recommendations


class TestLowSafetyStockRatio:
    """场景 7：低安全库存比 <5% → recommendations 含"设置偏激进"。"""

    def test_low_ss_ratio(self):
        info = EnhancerInput(safety_stock_ratio=0.03)
        recommendations = _generate_recommendations(info)
        assert any("偏激进" in r for r in recommendations), recommendations


class TestHighSafetyStockRatio:
    """场景 8：高安全库存比 >50% → recommendations 含"VMI 模式"。"""

    def test_high_ss_ratio(self):
        info = EnhancerInput(safety_stock_ratio=0.60)
        recommendations = _generate_recommendations(info)
        assert any("VMI" in r for r in recommendations), recommendations


class TestFormulaCaseA:
    """场景 9：情况 A 公式 → assumptions 含"提前期固定"。"""

    def test_formula_case_a(self):
        info = EnhancerInput(formula_used="情况 A — 仅需求波动（提前期固定）：SS = Z × σ_d × √LT = 1.6449 × 20 × √2")
        assumptions = _generate_assumptions(info)
        assert any("提前期固定" in a for a in assumptions), assumptions


class TestFormulaCaseC:
    """场景 10：情况 C 公式 → assumptions 含"两者均存在波动"。"""

    def test_formula_case_c(self):
        info = EnhancerInput(formula_used="情况 C — 需求与提前期皆波动：SS = Z × √(LT × σ_d² + d̄² × σ_LT²)")
        assumptions = _generate_assumptions(info)
        assert any("均存在波动" in a or "两者皆" in a for a in assumptions), assumptions


class TestOutliers:
    """场景 11：有异常值 → limitations 含"异常值"。"""

    def test_outliers(self):
        info = EnhancerInput(outlier_count=10)
        limitations = _generate_limitations(info)
        assert any("异常值" in l for l in limitations), limitations


# ======================================================================
# 场景 12：报告插入位置
# ======================================================================


class TestReportInsertion:
    """场景 12：enhance_report 插入位置正确。"""

    def test_section_insertion(self):
        base = build_base_report()
        info = EnhancerInput(
            history_length=24, forecast_method="Holt 双参数线性趋势", mape=8.5,
            eoq=223.6, safety_stock=46.5, safety_stock_ratio=0.15,
            rop=250.0, lead_time=2.0, service_level=0.95,
        )
        enhanced = enhance_report(base, info)

        # 原第 7 章占位已被替换
        assert "## 7." not in enhanced or "## 7. 模型假设" in enhanced

        # 新章节存在
        assert "## 7. 模型假设" in enhanced
        assert "## 8. 局限性与风险提示" in enhanced
        assert "## 9. 业务建议" in enhanced
        assert "## 10. 附录" in enhanced

        # 原占位符不应存在（整行含"综合建议"且不含"本章..." 的情况）
        lines = enhanced.split("\n")
        old_section7 = [l for l in lines if l.strip() == "## 7. 综合建议"]
        assert len(old_section7) == 0, "原 '## 7. 综合建议' 应被替换"

    def test_no_section7_inserts_at_end(self):
        """如果原始报告没有第 7 章，则追加到末尾。"""
        base = "# 供应链库存优化分析报告\n\n## 1. 概述\n\n数据较少"
        info = EnhancerInput(history_length=3)
        enhanced = enhance_report(base, info)
        assert "## 7. 模型假设" in enhanced
        assert "## 8. 局限性与风险提示" in enhanced
        assert "## 9. 业务建议" in enhanced


# ======================================================================
# 场景 13：空 info
# ======================================================================


class TestEmptyInfo:
    """场景 13：空 info（全部 None/0）—— 不报错，返回基础假设 + 通用建议。"""

    def test_empty_info_no_error(self):
        info = EnhancerInput()
        assumptions = _generate_assumptions(info)
        limitations = _generate_limitations(info)
        recommendations = _generate_recommendations(info)

        # 基础假设始终包含
        assert len(assumptions) >= 2  # 正态分布 + 历史代表未来
        # 模型局限性始终包含
        assert len(limitations) >= 3  # EOQ局限 + 安全库存概率 + 供应链中断
        # 通用建议始终包含
        assert len(recommendations) >= 2  # 监控看板 + ERP/WMS

    def test_empty_info_enhance_report(self):
        base = build_base_report()
        info = EnhancerInput()
        enhanced = enhance_report(base, info)
        assert isinstance(enhanced, str)
        assert len(enhanced) > len(base)


# ======================================================================
# 场景 14：run 别名
# ======================================================================


class TestRunAlias:
    """场景 14：run 别名可调用。"""

    def test_run_alias(self):
        base = build_base_report()
        info = EnhancerInput(history_length=24)
        enhanced = run(base, info)
        assert isinstance(enhanced, str)
        assert "## 7. 模型假设" in enhanced


# ======================================================================
# 辅助函数单元测试
# ======================================================================


class TestCheckFunction:
    """_check 条件匹配器单元测试。"""

    def test_is_not_none(self):
        info = EnhancerInput(mape=5.0)
        assert _check("mape is not None", info) is True
        assert _check("eoq is not None", info) is False

    def test_is_none(self):
        info = EnhancerInput()
        assert _check("eoq is None", info) is True
        assert _check("history_length is None", info) is False

    def test_contains(self):
        info = EnhancerInput(forecast_method="Holt 双参数线性趋势")
        assert _check("forecast_method contains 'Holt'", info) is True
        assert _check("forecast_method contains 'SES'", info) is False

    def test_contains_none(self):
        info = EnhancerInput()
        assert _check("forecast_method contains 'Holt'", info) is False

    def test_gt(self):
        info = EnhancerInput(mape=30.0)
        assert _check("mape > 20", info) is True
        assert _check("mape > 50", info) is False

    def test_lt(self):
        info = EnhancerInput(history_length=3)
        assert _check("history_length < 6", info) is True
        assert _check("history_length < 2", info) is False

    def test_gte_lte(self):
        info = EnhancerInput(history_length=8, mape=15.0)
        assert _check("history_length >= 6", info) is True
        assert _check("mape <= 20", info) is True
        assert _check("mape <= 10", info) is False

    def test_compound_and(self):
        info = EnhancerInput(history_length=8, mape=15.0)
        assert _check("history_length >= 6 and history_length < 12", info) is True


class TestFormatTemplate:
    """_format_template 测试。"""

    def test_format_with_spec(self):
        info = EnhancerInput(mape=8.523)
        result = _format_template("MAPE={mape:.1f}%", info)
        assert result == "MAPE=8.5%"

    def test_format_percent(self):
        info = EnhancerInput(missing_ratio=0.125)
        result = _format_template("缺失率 {missing_ratio:.1%}", info)
        assert result == "缺失率 12.5%"

    def test_format_int(self):
        info = EnhancerInput(history_length=24)
        result = _format_template("{history_length} 期", info)
        assert result == "24 期"


class TestEvalMathExpression:
    """_eval_math_expression 测试。"""

    def test_simple_division(self):
        info = EnhancerInput(annual_demand=1200.0)
        result = _eval_math_expression("annual_demand / 12", info)
        assert result == pytest.approx(100.0)

    def test_compound_expression(self):
        info = EnhancerInput(annual_demand=1200.0)
        result = _eval_math_expression("annual_demand / 12 * 3", info)
        assert result == pytest.approx(300.0)

    def test_with_lead_time(self):
        info = EnhancerInput(lead_time=2.0, annual_demand=1200.0)
        result = _eval_math_expression("lead_time * annual_demand / 12 * 0.5", info)
        assert result == pytest.approx(100.0)


class TestBuildEnhancerInput:
    """build_enhancer_input 测试。"""

    def test_from_pipeline_result(self):
        """用 mock pipeline result 测试 build_enhancer_input。"""
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.quality_report = {
            "total_rows": 24,
            "total_columns": 2,
            "columns": [
                {"name": "month", "missing_rate": 0.0, "missing_level": "low", "outlier_count": 0},
                {"name": "demand", "missing_rate": 0.05, "missing_level": "low", "outlier_count": 3},
            ],
            "overall_score": 90,
        }
        mock.forecast_result = MagicMock()
        mock.forecast_result.method_used = "Holt 双参数线性趋势"
        mock.forecast_result.mape = 8.5
        mock.eoq_result = MagicMock()
        mock.eoq_result.eoq = 223.61
        mock.safety_stock_result = MagicMock()
        mock.safety_stock_result.safety_stock = 46.52
        mock.safety_stock_result.service_level = 0.95
        mock.safety_stock_result.formula_used = "情况 A — 仅需求波动（提前期固定）"
        mock.rop_result = MagicMock()
        mock.rop_result.reorder_point = 250.0
        mock.rop_result.lead_time_demand = 200.0
        mock.rop_result.safety_stock = 46.52

        info = build_enhancer_input(mock)

        assert info.history_length == 24
        assert info.forecast_method == "Holt 双参数线性趋势"
        assert info.mape == 8.5
        assert info.eoq == 223.61
        assert info.safety_stock == 46.52
        assert info.service_level == 0.95
        assert info.formula_used == "情况 A — 仅需求波动（提前期固定）"
        assert info.rop == 250.0
        assert info.outlier_count == 3
        assert info.missing_ratio == pytest.approx(0.025)

    def test_empty_pipeline_result(self):
        """空 pipeline result 不报错。"""
        from unittest.mock import MagicMock
        mock = MagicMock()
        mock.quality_report = None
        mock.forecast_result = None
        mock.eoq_result = None
        mock.safety_stock_result = None
        mock.rop_result = None

        info = build_enhancer_input(mock)
        assert isinstance(info, EnhancerInput)
        assert info.history_length == 0


class TestEnhancedSectionsDataclass:
    """EnhancedSections 数据模型测试。"""

    def test_default_factory(self):
        sections = EnhancedSections()
        assert sections.assumptions == []
        assert sections.limitations == []
        assert sections.recommendations == []

    def test_with_content(self):
        sections = EnhancedSections(
            assumptions=["假设1"],
            limitations=["局限1"],
            recommendations=["建议1"],
        )
        assert len(sections.assumptions) == 1
        assert len(sections.limitations) == 1
        assert len(sections.recommendations) == 1


# ======================================================================
# 直接运行
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

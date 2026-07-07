"""领域优化模板层 — EOQ, 安全库存, 需求预测, 数据质量检测, 图表模板, Text-to-SQL。"""

# ---------------------------------------------------------------------------
# Week 3 现有导出（向后兼容）
# ---------------------------------------------------------------------------

try:
    from src.domain.data_quality import run_quality_check
except ImportError:
    run_quality_check = None  # type: ignore[assignment]

try:
    from src.domain.chart_templates import (
        bar_chart,
        line_chart,
        histogram_chart,
        scatter_chart,
        heatmap_chart,
    )
except ImportError:
    bar_chart = None  # type: ignore[assignment]
    line_chart = None  # type: ignore[assignment]
    histogram_chart = None  # type: ignore[assignment]
    scatter_chart = None  # type: ignore[assignment]
    heatmap_chart = None  # type: ignore[assignment]

try:
    from src.domain.text_to_sql import run_text_to_sql
except ImportError:
    run_text_to_sql = None  # type: ignore[assignment]

try:
    from src.domain.templates.data_analysis import run_analysis
except ImportError:
    run_analysis = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Week 4 新增：需求预测 (Day 1)
# ---------------------------------------------------------------------------

try:
    from src.domain.templates.demand_forecast import (
        forecast,
        auto_forecast,
        ForecastParams,
        ForecastResult,
    )
except ImportError:
    forecast = None  # type: ignore[assignment]
    auto_forecast = None  # type: ignore[assignment]
    ForecastParams = None  # type: ignore[assignment]
    ForecastResult = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Week 4 新增：安全库存 (Day 2)
# ---------------------------------------------------------------------------

try:
    from src.domain.templates.safety_stock import (
        calculate_safety_stock,
        quick_safety_stock,
        SafetyStockParams,
        SafetyStockResult,
    )
except ImportError:
    calculate_safety_stock = None  # type: ignore[assignment]
    quick_safety_stock = None  # type: ignore[assignment]
    SafetyStockParams = None  # type: ignore[assignment]
    SafetyStockResult = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Week 4 新增：补货点 (Day 3)
# ---------------------------------------------------------------------------

try:
    from src.domain.templates.reorder_point import (
        calculate as calculate_rop,
        ROPParams,
        ROPResult,
        from_eoq_and_safety_stock,
    )
except ImportError:
    calculate_rop = None  # type: ignore[assignment]
    ROPParams = None  # type: ignore[assignment]
    ROPResult = None  # type: ignore[assignment]
    from_eoq_and_safety_stock = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Week 4 新增：模板匹配与参数提取 (Day 4)
# ---------------------------------------------------------------------------

try:
    from src.domain.template_matcher import (
        match_template,
        match_with_fallback,
        MatchResult,
        TemplateType,
    )
except ImportError:
    match_template = None  # type: ignore[assignment]
    match_with_fallback = None  # type: ignore[assignment]
    MatchResult = None  # type: ignore[assignment]
    TemplateType = None  # type: ignore[assignment]

try:
    from src.domain.param_extractor import (
        extract_params,
        extract_params_for_template,
        describe_missing_params,
    )
except ImportError:
    extract_params = None  # type: ignore[assignment]
    extract_params_for_template = None  # type: ignore[assignment]
    describe_missing_params = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 公开符号
# ---------------------------------------------------------------------------

__all__ = [
    # Week 3
    "run_quality_check",
    "bar_chart",
    "line_chart",
    "histogram_chart",
    "scatter_chart",
    "heatmap_chart",
    "run_text_to_sql",
    "run_analysis",
    # Week 4 — 需求预测
    "forecast",
    "auto_forecast",
    "ForecastParams",
    "ForecastResult",
    # Week 4 — 安全库存
    "calculate_safety_stock",
    "quick_safety_stock",
    "SafetyStockParams",
    "SafetyStockResult",
    # Week 4 — 补货点
    "calculate_rop",
    "ROPParams",
    "ROPResult",
    "from_eoq_and_safety_stock",
    # Week 4 — 模板匹配与参数提取
    "match_template",
    "match_with_fallback",
    "MatchResult",
    "TemplateType",
    "extract_params",
    "extract_params_for_template",
    "describe_missing_params",
]

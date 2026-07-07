"""模板匹配器（意图分类）。

通过多关键词加权打分对用户自然语言 query 进行模板匹配，
零 LLM 调用，纯规则驱动。

支持 5 种模板类型 + UNKNOWN 兜底：
- EOQ（经济订货批量）
- FORECAST（需求预测）
- SAFETY_STOCK（安全库存）
- REORDER_POINT（补货点）
- DATA_ANALYSIS（一键数据分析）
- UNKNOWN（无法匹配）

使用方式:
    from src.domain.template_matcher import match_template
    result = match_template("帮我算 EOQ，年需求 1000")
    print(result.template_type)  # TemplateType.EOQ
"""

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# 意图分类枚举
# ---------------------------------------------------------------------------


class TemplateType(Enum):
    EOQ = "eoq"                          # 经济订货批量
    FORECAST = "forecast"                # 需求预测
    SAFETY_STOCK = "safety_stock"        # 安全库存
    REORDER_POINT = "reorder_point"      # 补货点
    DATA_ANALYSIS = "data_analysis"      # 一键数据分析
    UNKNOWN = "unknown"                  # 无法匹配


# ---------------------------------------------------------------------------
# 输出结构
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    """模板匹配结果。

    Attributes:
        template_type: 匹配到的模板类型
        confidence: 置信度分数（最高关键词权重累计）
        matched_keywords: 实际命中的关键词列表
        all_scores: 所有模板类型的完整打分（用于调试）
    """
    template_type: TemplateType
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    all_scores: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 关键词与权重配置
# ---------------------------------------------------------------------------

# Each entry: (keyword, weight)
# More specific keywords get higher weights
KEYWORDS: dict[TemplateType, list[tuple[str, float]]] = {
    TemplateType.EOQ: [
        ("订货批量", 2.5), ("经济订货", 2.5), ("eoq", 2.0), ("订货", 2.0),
        ("订货成本", 2.0), ("持有成本", 2.0), ("批量", 1.5), ("最优订货", 1.5),
        ("order cost", 2.0), ("holding cost", 2.0), ("order", 1.0),
        ("订购量", 1.5), ("补货量", 1.0),
    ],
    TemplateType.FORECAST: [
        ("需求预测", 2.5), ("预测需求", 2.5), ("预测", 2.0), ("forecast", 2.0),
        ("forecasting", 2.0), ("指数平滑", 1.5), ("移动平均", 1.5),
        ("趋势分析", 1.5), ("趋势", 1.0), ("平滑", 1.0),
    ],
    TemplateType.SAFETY_STOCK: [
        ("安全库存", 2.5), ("库存安全", 2.0), ("safety", 1.5),
        ("服务水平", 2.0), ("service level", 2.0), ("缓冲库存", 2.0),
        ("buffer stock", 2.0), ("buffer", 1.0), ("缺货", 1.0),
        ("z值", 1.0), ("z score", 1.0),
    ],
    TemplateType.REORDER_POINT: [
        ("补货点", 2.5), ("订货点", 2.5), ("再订货", 2.0),
        ("reorder point", 2.0), ("reorder", 1.5), ("rop", 2.0),
        ("补货", 1.5), ("库存降到", 1.5), ("触发订货", 1.5),
        ("再订货点", 2.5),
    ],
    TemplateType.DATA_ANALYSIS: [
        ("数据分析", 2.0), ("一键分析", 2.0), ("分析", 1.5),
        ("analysis", 1.5), ("质量检查", 1.5), ("统计", 1.0),
        ("报表", 1.0), ("可视化", 1.0), ("图表", 1.0), ("数据报告", 1.5),
    ],
}

# Minimum confidence threshold to return a match (below → UNKNOWN)
_CONFIDENCE_THRESHOLD = 1.5

# Templates listed in the fallback recommendation
_FALLBACK_TEMPLATES = ["EOQ（经济订货批量）", "需求预测", "安全库存", "补货点", "一键数据分析"]


# ---------------------------------------------------------------------------
# 匹配算法
# ---------------------------------------------------------------------------


def _score_query(query: str, keywords: list[tuple[str, float]]) -> tuple[float, list[str]]:
    """对 query 按关键词列表打分。

    每个关键词在 query 中出现一次则累加对应权重，
    多次出现也只计一次。

    Args:
        query: 用户查询字符串（已小写化）
        keywords: [(关键词, 权重), ...] 列表

    Returns:
        (总分, 命中的关键词列表)
    """
    score = 0.0
    matched: list[str] = []
    for kw, weight in keywords:
        if kw in query:
            score += weight
            matched.append(kw)
    return score, matched


def match_template(query: str) -> MatchResult:
    """对用户自然语言 query 进行模板匹配。

    算法：
      1. query 小写化
      2. 对每个 TemplateType 的关键词列表分别打分
      3. 取最高分者；若最高分 < 阈值则返回 UNKNOWN
      4. 若多个同分 → 取第一个（按 Enum 定义顺序）

    Args:
        query: 用户自然语言查询

    Returns:
        MatchResult 包含 template_type / confidence / matched_keywords / all_scores

    Example:
        >>> r = match_template("帮我算 EOQ，年需求 1000")
        >>> r.template_type
        <TemplateType.EOQ: 'eoq'>
    """
    query_lower = query.lower().strip()

    all_scores: dict[TemplateType, float] = {}
    all_matched: dict[TemplateType, list[str]] = {}

    for ttype, kws in KEYWORDS.items():
        score, matched = _score_query(query_lower, kws)
        all_scores[ttype] = round(score, 2)
        all_matched[ttype] = matched

    # Find best match
    best_type = max(all_scores, key=lambda k: all_scores[k])
    best_score = all_scores[best_type]

    if best_score < _CONFIDENCE_THRESHOLD:
        return MatchResult(
            template_type=TemplateType.UNKNOWN,
            confidence=0.0,
            matched_keywords=[],
            all_scores=all_scores,
        )

    # Tie-breaking: prefer more specific keywords (higher count of matches)
    tied = [t for t, s in all_scores.items() if s == best_score]
    if len(tied) > 1:
        # Pick the one with more matched keywords (more specific intent)
        best_type = max(tied, key=lambda t: len(all_matched[t]))

    return MatchResult(
        template_type=best_type,
        confidence=best_score,
        matched_keywords=all_matched[best_type],
        all_scores=all_scores,
    )


# ---------------------------------------------------------------------------
# 兜底匹配
# ---------------------------------------------------------------------------


def match_with_fallback(query: str) -> MatchResult:
    """匹配 + 兜底：UNKNOWN 时返回推荐的可用模板列表。

    当正常匹配返回 UNKNOWN 时，将可用模板列表写入
    matched_keywords 字段供调用方展示。

    Args:
        query: 用户自然语言查询

    Returns:
        MatchResult（若 UNKNOWN，matched_keywords 含推荐模板名）
    """
    result = match_template(query)

    if result.template_type == TemplateType.UNKNOWN:
        result.matched_keywords = _FALLBACK_TEMPLATES

    return result


# 导出别名（与其他模块保持一致的可调用接口）
run = match_template

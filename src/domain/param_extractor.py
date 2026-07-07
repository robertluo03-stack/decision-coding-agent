"""参数提取器。

从自然语言 query 中提取 (参数名, 数值) 对。
基于正则表达式匹配数值 + 前向语境匹配参数别名，
零 LLM 调用，纯规则驱动。

使用方式:
    from src.domain.param_extractor import extract_params
    params = extract_params("年需求1000，订货成本50，持有成本2")
    print(params)  # {"annual_demand": 1000.0, "ordering_cost": 50.0, "holding_cost": 2.0}
"""

import re
from typing import Any

from src.domain.template_matcher import TemplateType


# ---------------------------------------------------------------------------
# 参数别名配置
# ---------------------------------------------------------------------------

# Map canonical param name → list of aliases (ordered: more specific first)
PARAM_ALIASES: dict[str, list[str]] = {
    # ---- EOQ ----
    "annual_demand": [
        "年需求量", "年需求", "annual demand", "年消耗", "需求量",
        "需求", "demand", "年用量",
    ],
    "ordering_cost": [
        "订货成本", "订购成本", "order cost", "ordering cost",
        "每次订货", "订货费", "订购费", "订购费用",
    ],
    "holding_cost": [
        "持有成本", "库存成本", "存储成本", "holding cost",
        "storage cost", "库存持有", "持有费率", "持有费用",
    ],
    "unit_cost": [
        "单价", "unit cost", "单位成本", "价格",
    ],

    # ---- 安全库存 ----
    "avg_demand": [
        "平均需求量", "平均需求", "avg demand", "平均消耗",
        "月均需求", "日均需求",
    ],
    "demand_std": [
        "需求标准差", "demand std", "需求波动", "标准差", "σ",
        "需求方差",
    ],
    "lead_time": [
        "提前期", "lead time", "交货期", "供货期", "leadtime",
        "提前时间",
    ],
    "lead_time_std": [
        "提前期标准差", "lead time std", "提前期波动",
    ],
    "service_level": [
        "服务水平", "service level", "服务率", "满足率", "目标服务水平",
    ],

    # ---- 预测 ----
    "periods": [
        "预测期数", "periods", "预测几期", "未来几期", "期数",
    ],
    "alpha": [
        "平滑系数", "alpha", "α", "平滑常数",
    ],
    "window": [
        "窗口", "window", "移动窗口",
    ],

    # ---- 补货点 ----
    "safety_stock": [
        "安全库存", "safety stock", "安全库存量", "ss",
    ],
}


# ---------------------------------------------------------------------------
# 模板 → 必填参数映射
# ---------------------------------------------------------------------------

_REQUIRED_PARAMS: dict[TemplateType, list[str]] = {
    TemplateType.EOQ: ["annual_demand", "ordering_cost", "holding_cost"],
    TemplateType.SAFETY_STOCK: ["avg_demand", "demand_std", "lead_time", "service_level"],
    TemplateType.REORDER_POINT: ["avg_demand", "lead_time", "safety_stock"],
    TemplateType.FORECAST: [],   # history cannot be extracted from NL text
    TemplateType.DATA_ANALYSIS: [],
    TemplateType.UNKNOWN: [],
}


# Template-param relevance: which params are relevant for a given template
_TEMPLATE_RELEVANT_PARAMS: dict[TemplateType, set[str]] = {
    TemplateType.EOQ: {"annual_demand", "ordering_cost", "holding_cost", "unit_cost"},
    TemplateType.SAFETY_STOCK: {
        "avg_demand", "demand_std", "lead_time", "lead_time_std", "service_level",
    },
    TemplateType.REORDER_POINT: {"avg_demand", "lead_time", "safety_stock"},
    TemplateType.FORECAST: {"periods", "alpha", "window"},
    TemplateType.DATA_ANALYSIS: set(),
    TemplateType.UNKNOWN: set(),
}


# Parameter display names for Chinese descriptions
_PARAM_DISPLAY_NAMES: dict[str, str] = {
    "annual_demand": "年需求量",
    "ordering_cost": "订货成本",
    "holding_cost": "持有成本",
    "avg_demand": "平均需求",
    "demand_std": "需求标准差",
    "lead_time": "提前期",
    "service_level": "服务水平",
    "safety_stock": "安全库存量",
    "lead_time_std": "提前期标准差",
    "unit_cost": "单价",
    "periods": "预测期数",
    "alpha": "平滑系数",
    "window": "窗口大小",
}


# ---------------------------------------------------------------------------
# 数值提取正则
# ---------------------------------------------------------------------------

# Patterns for extracting numeric values (ordered: try specific before general)
_INTEGER_PATTERN = re.compile(r'(\d+)')
_DECIMAL_PATTERN = re.compile(r'(\d+\.\d+)')
_PERCENT_PATTERN = re.compile(r'(\d+\.?\d*)\s*%')
_PERCENT_PATTERN_CN = re.compile(r'(\d+\.?\d*)\s*百分之')  # unlikely but comprehensive


def _find_all_numbers(text: str) -> list[tuple[int, float, bool]]:
    """从文本中提取所有数值，返回 [(位置, 数值, 是否百分比), ...]。

    解析优先级：小数 > 整数。百分号独立处理。

    Args:
        text: 原始文本

    Returns:
        列表，每项为 (char_position, value, is_percentage)
    """
    found: list[tuple[int, float, bool]] = []
    seen_positions: set[int] = set()

    # 1. Decimals first (most specific)
    for m in _DECIMAL_PATTERN.finditer(text):
        pos = m.start()
        if pos in seen_positions:
            continue
        val = float(m.group(1))
        is_pct = pos + len(m.group(0)) < len(text) and text[pos + len(m.group(0))] == '%'
        found.append((pos, val, is_pct))
        seen_positions.add(pos)

    # 2. Percentage patterns (may contain integers or decimals)
    for m in _PERCENT_PATTERN.finditer(text):
        pos = m.start()
        if pos in seen_positions:
            continue
        val = float(m.group(1))
        found.append((pos, val, True))
        seen_positions.add(pos)

    # 3. Integers (for positions not already captured)
    for m in _INTEGER_PATTERN.finditer(text):
        pos = m.start()
        if pos in seen_positions:
            # Check if this integer is part of a decimal already captured
            continue
        # Skip if this integer is part of a decimal (e.g., "2.5" — "2" shouldn't match separately)
        if pos > 0 and text[pos - 1] == '.':
            continue
        val = float(m.group(1))
        is_pct = (
            pos + len(m.group(0)) < len(text) and
            text[pos + len(m.group(0))] in ('%', '％')
        )
        found.append((pos, val, is_pct))
        seen_positions.add(pos)

    return sorted(found, key=lambda x: x[0])  # sort by position


def _lookup_param_name(context: str) -> str | None:
    """在上下文字符串中查找参数别名。

    优先匹配离数值最近的别名（距离 = context末尾到alias末尾的距离），
    距离相同时取更长的别名（更具体）。

    Args:
        context: 数值前的上下文字符串（已小写化）

    Returns:
        标准参数名字符串，或 None（未找到匹配）
    """
    best_distance = float("inf")
    best_length = -1
    best_name: str | None = None

    for canon_name, aliases in PARAM_ALIASES.items():
        for alias in aliases:
            pos = context.rfind(alias)
            if pos == -1:
                continue
            # distance from alias-end to context-end (lower = closer to number)
            distance = len(context) - (pos + len(alias))
            if distance < best_distance:
                best_distance = distance
                best_length = len(alias)
                best_name = canon_name
            elif distance == best_distance and len(alias) > best_length:
                # Same distance → prefer longer (more specific) alias
                best_length = len(alias)
                best_name = canon_name

    return best_name


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


def extract_params(query: str) -> dict[str, float]:
    """从自然语言中提取数值参数。

    算法：
      1. 正则扫描所有数值（整数/小数/百分比）
      2. 对每个数值，取前 15 个字符作为上下文窗口
      3. 在上下文中匹配参数别名（取最长匹配）
      4. 将别名映射到标准参数名
      5. 同一参数多次出现 → 取第一次出现的值

    Args:
        query: 用户自然语言查询

    Returns:
        {标准参数名: 数值} 字典

    Example:
        >>> extract_params("年需求1000，订货成本50，持有成本2")
        {'annual_demand': 1000.0, 'ordering_cost': 50.0, 'holding_cost': 2.0}
        >>> extract_params("服务水平 95%")
        {'service_level': 95.0}
    """
    query_lower = query.lower()
    numbers = _find_all_numbers(query)

    result: dict[str, float] = {}

    for pos, value, is_pct in numbers:
        # Backward context window: ~15 chars before the number
        ctx_start = max(0, pos - 15)
        ctx = query_lower[ctx_start:pos]

        canon_name = _lookup_param_name(ctx)

        if canon_name is not None:
            final_value = value  # keep percentage as-is (95% → 95.0, handled by template)
            # Only set if not already extracted (first occurrence wins)
            if canon_name not in result:
                result[canon_name] = final_value

    return result


# ---------------------------------------------------------------------------
# 模板定向提取
# ---------------------------------------------------------------------------


def extract_params_for_template(
    query: str, template_type: TemplateType
) -> dict[str, float]:
    """结合模板类型，只提取该模板相关的参数。

    先通用提取，再按模板过滤不相关参数。

    Args:
        query: 用户自然语言查询
        template_type: 目标模板类型

    Returns:
        过滤后的 {标准参数名: 数值} 字典

    Example:
        >>> extract_params_for_template("年需求1000 服务水平95%", TemplateType.EOQ)
        {'annual_demand': 1000.0}
    """
    all_params = extract_params(query)
    relevant = _TEMPLATE_RELEVANT_PARAMS.get(template_type, set())

    if not relevant:
        return all_params

    return {k: v for k, v in all_params.items() if k in relevant}


# ---------------------------------------------------------------------------
# 必填参数检查
# ---------------------------------------------------------------------------


def describe_missing_params(
    template_type: TemplateType, extracted: dict[str, float]
) -> list[str]:
    """返回缺失的必填参数列表（中文描述，用于提示用户）。

    Args:
        template_type: 目标模板类型
        extracted: 已提取的参数

    Returns:
        缺失参数的中文描述列表；若无缺失返回空列表

    Example:
        >>> describe_missing_params(TemplateType.EOQ, {"annual_demand": 1000})
        ['订货成本', '持有成本']
    """
    required = _REQUIRED_PARAMS.get(template_type, [])
    missing: list[str] = []

    for param_name in required:
        if param_name not in extracted:
            display = _PARAM_DISPLAY_NAMES.get(param_name, param_name)
            missing.append(display)

    return missing


# 导出别名（与其他模块保持一致的可调用接口）
run = extract_params

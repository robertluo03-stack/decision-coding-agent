"""安全库存计算模板（服务水平法）。

基于概率需求理论，计算在给定服务水平下的安全库存（Safety Stock）。
支持三种不确定场景：
- 情况 A：需求波动 + 提前期固定
- 情况 B：需求固定 + 提前期波动
- 情况 C：两者皆波动（最一般形式）

Z 分位数通过 scipy.stats.norm.ppf 精确计算。

使用方式:
    from src.domain.templates.safety_stock import calculate_safety_stock, SafetyStockParams
    result = calculate_safety_stock(SafetyStockParams(
        avg_demand=100, demand_std=20, lead_time=2, service_level=0.95
    ))
    print(result.safety_stock)  # 安全库存量
"""

import math
from dataclasses import dataclass, field

from scipy.stats import norm


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class SafetyStockParams:
    """安全库存计算参数。

    Attributes:
        avg_demand: 平均需求量（单位时间的需求，如月均需求 100 件）
        demand_std: 需求标准差（≥0，0 表示需求确定无波动）
        lead_time: 平均提前期（≥0，时间单位与需求一致，如 2 个月）
        lead_time_std: 提前期标准差（≥0，默认 0 表示提前期固定）
        service_level: 目标服务水平（支持 0.95 或 95 两种输入，内部统一为 0-1）
    """
    avg_demand: float
    demand_std: float
    lead_time: float
    lead_time_std: float = 0.0
    service_level: float = 0.95


@dataclass
class SafetyStockResult:
    """安全库存计算结果。

    Attributes:
        safety_stock: 安全库存量（保留 2 位小数）
        reorder_point_component: 再订货点 = avg_demand × lead_time（仅提前期内预期需求）
        z_score: 对应服务水平的标准正态分位数
        service_level: 标准化后的服务水平（0-1 之间）
        formula_used: 使用的公式中文描述
        assumptions: 计算假设说明列表
    """
    safety_stock: float
    reorder_point_component: float
    z_score: float
    service_level: float
    formula_used: str
    assumptions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def _validate_params(params: SafetyStockParams) -> None:
    """校验安全库存参数，不合法时抛出 ValueError。"""
    if params.avg_demand <= 0:
        raise ValueError("平均需求必须 > 0")

    if params.demand_std < 0:
        raise ValueError("需求标准差不能为负")

    if params.lead_time < 0:
        raise ValueError("提前期不能为负")

    if params.lead_time_std < 0:
        raise ValueError("提前期标准差不能为负")

    if params.service_level <= 0 or params.service_level > 100:
        raise ValueError("服务水平必须在 (0, 100] 之间")


# ---------------------------------------------------------------------------
# 服务水平标准化
# ---------------------------------------------------------------------------


def _normalize_service_level(raw: float) -> float:
    """将服务水平标准化到 (0, 1) 区间。

    - raw > 1 时视为百分数（如 95 → 0.95）
    - raw 在 (0, 1] 时保持不变

    Args:
        raw: 原始服务水平值

    Returns:
        标准化后的服务水平（0-1 之间）
    """
    if raw > 1:
        return raw / 100.0
    return raw


# ---------------------------------------------------------------------------
# Z 分位数计算
# ---------------------------------------------------------------------------


def _compute_z_score(service_level: float) -> float:
    """通过 scipy.stats.norm.ppf 计算标准正态分位数。

    Args:
        service_level: 标准化后的服务水平（0-1 之间）

    Returns:
        Z 分位数（保留 4 位小数）
    """
    return round(float(norm.ppf(service_level)), 4)


# ---------------------------------------------------------------------------
# 核心公式
# ---------------------------------------------------------------------------


def _safe_sqrt(value: float) -> float:
    """sqrt 安全包装：极小负数截断为 0（避免浮点舍入误差导致 math domain error）。"""
    return math.sqrt(max(0.0, value))


def calculate_safety_stock(params: SafetyStockParams) -> SafetyStockResult:
    """安全库存计算主入口。

    根据需求和提前期的不确定性特征，自动选择正确的公式：

    - 两者均无波动 → 安全库存 = 0
    - 仅需求波动（情况 A） → SS = Z × σ_demand × √lead_time
    - 仅提前期波动（情况 B） → SS = Z × avg_demand × σ_lead_time
    - 两者皆波动（情况 C） → SS = Z × √(lead_time × σ_demand² + avg_demand² × σ_lead_time²)

    Args:
        params: 安全库存参数（SafetyStockParams 实例）

    Returns:
        SafetyStockResult 包含安全库存量、Z 分数、公式说明等

    Raises:
        ValueError: 参数校验不通过

    Example:
        >>> p = SafetyStockParams(avg_demand=100, demand_std=20, lead_time=2, service_level=95)
        >>> r = calculate_safety_stock(p)
        >>> print(r.safety_stock)  # ≈ 46.52
    """
    _validate_params(params)

    # Normalize service level (95 → 0.95)
    sl_normalized = _normalize_service_level(params.service_level)
    z = _compute_z_score(sl_normalized)

    avg_d = params.avg_demand
    std_d = params.demand_std
    lt = params.lead_time
    std_lt = params.lead_time_std

    assumptions: list[str] = ["假设需求服从正态分布"]

    # Determine which formula to use
    if std_d == 0.0 and std_lt == 0.0:
        # Both certain — no safety stock needed
        ss = 0.0
        formula = "需求与提前期均无波动，安全库存为 0"
        assumptions.append("需求与提前期完全确定")

    elif std_lt == 0.0:
        # Case A: demand variability only, lead time fixed
        ss = z * std_d * _safe_sqrt(lt)
        formula = f"情况 A — 仅需求波动（提前期固定）：SS = Z × σ_d × √LT = {z:.4f} × {std_d} × √{lt}"
        assumptions.append("提前期固定（无波动）")

    elif std_d == 0.0:
        # Case B: lead time variability only, demand fixed
        ss = z * avg_d * std_lt
        formula = f"情况 B — 仅提前期波动（需求固定）：SS = Z × d̄ × σ_LT = {z:.4f} × {avg_d} × {std_lt}"
        assumptions.append("需求完全确定（无波动）")

    else:
        # Case C: both demand and lead time vary
        var_component = lt * (std_d ** 2) + (avg_d ** 2) * (std_lt ** 2)
        ss = z * _safe_sqrt(var_component)
        formula = (
            f"情况 C — 需求与提前期皆波动："
            f"SS = Z × √(LT × σ_d² + d̄² × σ_LT²) = "
            f"{z:.4f} × √({lt} × {std_d}² + {avg_d}² × {std_lt}²)"
        )
        assumptions.append("需求与提前期均存在不确定性")

    # Reorder point component = lead time demand (不含安全库存)
    rop_component = avg_d * lt

    return SafetyStockResult(
        safety_stock=round(ss, 2),
        reorder_point_component=round(rop_component, 2),
        z_score=z,
        service_level=round(sl_normalized, 4),
        formula_used=formula,
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------


def quick_safety_stock(
    avg_demand: float,
    demand_std: float,
    lead_time: float,
    service_level: float = 0.95,
) -> SafetyStockResult:
    """便捷入口：固定提前期场景的最常用调用方式。

    仅传入平均需求、需求标准差、提前期、服务水平四个核心参数，
    默认为情况 A（需求波动 + 提前期固定）。

    Args:
        avg_demand: 平均需求量
        demand_std: 需求标准差
        lead_time: 平均提前期
        service_level: 目标服务水平（0.95 或 95）

    Returns:
        SafetyStockResult

    Example:
        >>> r = quick_safety_stock(100, 20, 2, 0.95)
        >>> print(r.safety_stock)  # ≈ 46.52
    """
    return calculate_safety_stock(
        SafetyStockParams(
            avg_demand=avg_demand,
            demand_std=demand_std,
            lead_time=lead_time,
            lead_time_std=0.0,
            service_level=service_level,
        )
    )


# 导出别名（与其他模板保持一致的可调用接口）
run = calculate_safety_stock

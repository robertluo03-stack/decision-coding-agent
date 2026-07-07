"""补货点（ROP）计算模板。

ROP（Reorder Point）是库存管理中的关键决策参数，定义为：
    ROP = 提前期平均需求 + 安全库存 = avg_demand × lead_time + safety_stock

本模板将 EOQ（经济订货批量）和安全库存作为可选输入组合，
是供应链库存三件套（EOQ + SS + ROP）的自然收尾。

提供复合接口 `from_eoq_and_safety_stock`，展示模板间协作。

使用方式:
    from src.domain.templates.reorder_point import calculate, ROPParams
    result = calculate(ROPParams(avg_demand=100, lead_time=2, safety_stock=46.52))
    print(result.reorder_point)  # 补货点
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class ROPParams:
    """补货点计算参数。

    Attributes:
        avg_demand: 平均需求量（单位时间）
        lead_time: 平均提前期（≥0）
        safety_stock: 安全库存量（≥0）
        eoq: 经济订货批量（可选，若提供则一并输出建议）
    """
    avg_demand: float
    lead_time: float
    safety_stock: float = 0.0
    eoq: float | None = None


@dataclass
class ROPResult:
    """补货点计算结果。

    Attributes:
        reorder_point: 补货点 = lead_time_demand + safety_stock
        lead_time_demand: 提前期平均需求 = avg_demand × lead_time
        safety_stock: 安全库存量
        eoq: 经济订货批量（若输入提供）
        suggestion: 规则化生成的中文业务建议
    """
    reorder_point: float
    lead_time_demand: float
    safety_stock: float
    eoq: float | None = None
    suggestion: str = ""


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def _validate_params(params: ROPParams) -> None:
    """校验补货点参数，不合法时抛出 ValueError。"""
    if params.avg_demand <= 0:
        raise ValueError("平均需求必须 > 0")

    if params.lead_time < 0:
        raise ValueError("提前期不能为负")

    if params.safety_stock < 0:
        raise ValueError("安全库存不能为负")


# ---------------------------------------------------------------------------
# 规则化业务建议生成
# ---------------------------------------------------------------------------


def _generate_suggestion(result: ROPResult) -> str:
    """基于计算结果生成规则化的中文业务建议。

    零 LLM，纯 if-else 规则驱动。

    Args:
        result: 已填充数值的 ROPResult（不含 suggestion）

    Returns:
        中文建议字符串
    """
    parts: list[str] = []

    # Core: when to reorder
    parts.append(f"当库存降至 {result.reorder_point:.0f} 时触发补货")

    # EOQ info
    if result.eoq is not None:
        parts.append(f"每次订货量为 {result.eoq:.0f}")
    else:
        parts.append("建议结合 EOQ 模型确定最优订货量")

    # Composition
    parts.append(
        f"其中提前期平均消耗 {result.lead_time_demand:.0f}，"
        f"安全库存 {result.safety_stock:.0f}"
    )

    suggestion = "；".join(parts) + "。"

    # Extended rules
    if result.safety_stock == 0:
        suggestion += "（当前安全库存为 0，建议评估需求波动风险）"

    if result.eoq is not None:
        suggestion += "建议采用 (ROP, Q) 库存策略。"

    return suggestion


# ---------------------------------------------------------------------------
# 核心公式
# ---------------------------------------------------------------------------


def calculate(params: ROPParams) -> ROPResult:
    """补货点计算主入口。

    核心公式：
        ROP = avg_demand × lead_time + safety_stock

    Args:
        params: 补货点参数（ROPParams 实例）

    Returns:
        ROPResult 包含 reorder_point / lead_time_demand / suggestion 等

    Raises:
        ValueError: 参数校验不通过

    Example:
        >>> p = ROPParams(avg_demand=100, lead_time=2, safety_stock=50, eoq=224)
        >>> r = calculate(p)
        >>> print(r.reorder_point)  # 250
        >>> print(r.suggestion)     # 当库存降至 250 时触发补货...
    """
    _validate_params(params)

    lead_time_demand = params.avg_demand * params.lead_time
    rop = lead_time_demand + params.safety_stock

    # Build result (suggestion calculated after assembly)
    result = ROPResult(
        reorder_point=round(rop, 2),
        lead_time_demand=round(lead_time_demand, 2),
        safety_stock=params.safety_stock,
        eoq=round(params.eoq, 2) if params.eoq is not None else None,
    )

    result.suggestion = _generate_suggestion(result)
    return result


# ---------------------------------------------------------------------------
# 复合接口：模板间协作
# ---------------------------------------------------------------------------


def from_eoq_and_safety_stock(
    avg_demand: float,
    lead_time: float,
    eoq_result: "EOQResult | None" = None,  # type: ignore[name-defined]  # noqa: F821
    safety_stock_result: "SafetyStockResult | None" = None,  # type: ignore[name-defined]  # noqa: F821
) -> ROPResult:
    """从 EOQ 和安全库存结果直接构建 ROP。

    展示模板间的协作关系——EOQ 提供最优订货量，
    安全库存提供缓冲水平，ROP 将两者整合为补货决策。

    Args:
        avg_demand: 平均需求量（应与 SS 参数一致）
        lead_time: 平均提前期（应与 SS 参数一致）
        eoq_result: EOQ 计算结果（EOQResult 实例，可选）
        safety_stock_result: 安全库存计算结果（SafetyStockResult 实例，可选）

    Returns:
        ROPResult

    Raises:
        ValueError: 若传入无效结果

    Example:
        >>> from src.domain.templates.inventory_eoq import calculate as calc_eoq, EOQParams
        >>> from src.domain.templates.safety_stock import calculate_safety_stock, SafetyStockParams
        >>> eoq = calc_eoq(EOQParams(annual_demand=1200, ordering_cost=50, holding_cost=2))
        >>> ss = calculate_safety_stock(SafetyStockParams(avg_demand=100, demand_std=20, lead_time=2))
        >>> rop = from_eoq_and_safety_stock(avg_demand=100, lead_time=2, eoq_result=eoq, safety_stock_result=ss)
    """
    ss_value = 0.0
    if safety_stock_result is not None:
        ss_value = safety_stock_result.safety_stock

    eoq_value = None
    if eoq_result is not None:
        eoq_value = eoq_result.eoq

    return calculate(
        ROPParams(
            avg_demand=avg_demand,
            lead_time=lead_time,
            safety_stock=ss_value,
            eoq=eoq_value,
        )
    )


# 导出别名（与其他模板保持一致的可调用接口）
run = calculate

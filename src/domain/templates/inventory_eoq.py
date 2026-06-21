"""EOQ 经济订货批量模板。

EOQ = sqrt(2 * D * S / H)
- D: 年需求量
- S: 每次订货成本
- H: 单位持有成本
"""

import math
from dataclasses import dataclass


@dataclass
class EOQParams:
    annual_demand: float
    ordering_cost: float
    holding_cost: float


@dataclass
class EOQResult:
    eoq: float
    annual_orders: float
    total_ordering_cost: float
    total_holding_cost: float
    total_cost: float


def calculate(params: EOQParams) -> EOQResult:
    """计算经济订货批量。"""
    D = params.annual_demand
    S = params.ordering_cost
    H = params.holding_cost

    if D <= 0 or S <= 0 or H <= 0:
        raise ValueError(f"All parameters must be positive: D={D}, S={S}, H={H}")

    eoq = math.sqrt(2 * D * S / H)
    annual_orders = D / eoq
    total_ordering_cost = annual_orders * S
    total_holding_cost = (eoq / 2) * H

    return EOQResult(
        eoq=round(eoq, 2),
        annual_orders=round(annual_orders, 2),
        total_ordering_cost=round(total_ordering_cost, 2),
        total_holding_cost=round(total_holding_cost, 2),
        total_cost=round(total_ordering_cost + total_holding_cost, 2),
    )

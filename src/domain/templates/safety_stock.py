"""安全库存计算模板（服务水平法）。

SS = z * σ_d * sqrt(LT)
- z: 标准正态分布的分位数（对应服务水平）
- σ_d: 需求标准差
- LT: 提前期
"""

import math
from dataclasses import dataclass
from typing import Optional


# 服务水平 → Z 值映射表
SERVICE_LEVEL_Z = {
    0.90: 1.282,
    0.95: 1.645,
    0.97: 1.881,
    0.98: 2.054,
    0.99: 2.326,
    0.995: 2.576,
    0.999: 3.090,
}


@dataclass
class SafetyStockParams:
    demand_std: float       # 需求标准差
    lead_time: float        # 提前期（与标准差同单位）
    service_level: float    # 目标服务水平 (0.90 ~ 0.999)
    avg_demand: float = 0   # 平均需求（可选，用于ROP计算）


@dataclass
class SafetyStockResult:
    z_score: float
    safety_stock: float
    reorder_point: Optional[float]  # ROP = avg_demand * LT + SS


def calculate(params: SafetyStockParams) -> SafetyStockResult:
    """计算安全库存水平。"""
    if params.service_level not in SERVICE_LEVEL_Z:
        # 找最接近的服务水平
        closest = min(
            SERVICE_LEVEL_Z.keys(),
            key=lambda k: abs(k - params.service_level),
        )
        z = SERVICE_LEVEL_Z[closest]
    else:
        z = SERVICE_LEVEL_Z[params.service_level]

    ss = z * params.demand_std * math.sqrt(params.lead_time)

    rop = None
    if params.avg_demand > 0:
        rop = params.avg_demand * params.lead_time + ss

    return SafetyStockResult(
        z_score=round(z, 3),
        safety_stock=round(ss, 2),
        reorder_point=round(rop, 2) if rop is not None else None,
    )

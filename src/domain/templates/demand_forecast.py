"""需求预测模板 — 移动平均 + 指数平滑。"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ForecastParams:
    historical_demand: List[float]
    method: str = "both"           # "moving_avg" | "exp_smooth" | "both"
    window: int = 3                # 移动平均窗口
    alpha: float = 0.3             # 指数平滑系数
    forecast_periods: int = 1      # 预测未来期数


@dataclass
class ForecastResult:
    method: str
    fitted_values: List[Optional[float]]
    forecast: List[float]
    mape: Optional[float] = None   # 平均绝对百分比误差


def moving_average(data: List[float], window: int, periods: int = 1) -> ForecastResult:
    """移动平均法。"""
    fitted = []
    for i in range(len(data)):
        if i < window - 1:
            fitted.append(None)
        else:
            avg = sum(data[i - window + 1:i + 1]) / window
            fitted.append(round(avg, 2))

    # 预测：用最后 window 个值的平均
    last_avg = sum(data[-window:]) / window
    forecast = [round(last_avg, 2)] * periods

    # 计算 MAPE
    mape = _calc_mape(data, fitted, window - 1)

    return ForecastResult(
        method=f"移动平均 (window={window})",
        fitted_values=fitted,
        forecast=forecast,
        mape=mape,
    )


def exponential_smoothing(
    data: List[float], alpha: float, periods: int = 1
) -> ForecastResult:
    """一次指数平滑法。"""
    fitted = [data[0]]
    for i in range(1, len(data)):
        forecast = alpha * data[i] + (1 - alpha) * fitted[-1]
        fitted.append(round(forecast, 2))

    last = fitted[-1]
    forecast = [round(last, 2)] * periods

    mape = _calc_mape(data, fitted, 0)

    return ForecastResult(
        method=f"指数平滑 (alpha={alpha})",
        fitted_values=fitted,
        forecast=forecast,
        mape=mape,
    )


def forecast(params: ForecastParams) -> List[ForecastResult]:
    """执行预测，返回所有请求的方法结果。"""
    results = []
    data = params.historical_demand

    if params.method in ("moving_avg", "both"):
        results.append(moving_average(data, params.window, params.forecast_periods))

    if params.method in ("exp_smooth", "both"):
        results.append(
            exponential_smoothing(data, params.alpha, params.forecast_periods)
        )

    return results


def _calc_mape(
    actual: List[float], fitted: List[float], start_idx: int
) -> Optional[float]:
    """计算 MAPE（从 start_idx 开始，跳过 fitted 中的 None）。"""
    errors = []
    for i in range(start_idx, len(actual)):
        if fitted[i] is not None and actual[i] != 0:
            errors.append(abs((actual[i] - fitted[i]) / actual[i]))
    if not errors:
        return None
    return round(sum(errors) / len(errors) * 100, 2)

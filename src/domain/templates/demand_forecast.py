"""需求预测模板。

提供 4 种时序预测方法 + 自动方法选择：
- SMA（简单移动平均）
- WMA（加权移动平均）
- SES（单指数平滑）
- Holt（双参数线性趋势）

纯 Python 实现，仅依赖 math 标准库。

使用方式:
    from src.domain.templates.demand_forecast import forecast, ForecastParams
    result = forecast(ForecastParams(history=[100, 120, 110, 130], method="ses", periods=3))
    print(result.forecasts)  # 未来 3 期预测值
"""

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class ForecastParams:
    """需求预测参数。

    Attributes:
        history: 历史需求数据序列（至少 2 个数据点）
        method: 预测方法，可选: sma, wma, ses, holt, auto
        periods: 要预测的未来期数（≥1）
        alpha: SES/Holt 的平滑系数，范围 (0, 1)
        beta: Holt 的趋势平滑系数，范围 (0, 1)
        window: SMA/WMA 的窗口大小
    """
    history: list[float]
    method: str = "auto"
    periods: int = 1
    alpha: float = 0.3
    beta: float = 0.1
    window: int = 3


@dataclass
class ForecastResult:
    """需求预测结果。

    Attributes:
        forecasts: 预测结果序列（长度 = periods）
        mae: 平均绝对误差（in-sample 回测）
        rmse: 均方根误差（in-sample 回测）
        mape: 平均绝对百分比误差（百分数，如 5.2 表示 5.2%）
        method_used: 实际使用的方法名
        model_params: 实际使用的模型参数
    """
    forecasts: list[float]
    mae: float
    rmse: float
    mape: float
    method_used: str
    model_params: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------

_VALID_METHODS = frozenset({"sma", "wma", "ses", "holt", "auto"})


def _validate_params(params: ForecastParams, resolved_method: str) -> None:
    """校验预测参数，不合法时抛出 ValueError。"""
    if len(params.history) < 2:
        raise ValueError("历史数据至少需要 2 个数据点")

    if params.method not in _VALID_METHODS:
        raise ValueError(
            f"不支持的方法: {params.method}，可选: sma, wma, ses, holt, auto"
        )

    if params.periods < 1:
        raise ValueError("预测期数必须 ≥ 1")

    if not (0 < params.alpha < 1):
        raise ValueError("平滑系数 alpha 必须在 (0, 1) 之间")

    if not (0 < params.beta < 1):
        raise ValueError("平滑系数 beta 必须在 (0, 1) 之间")


# ---------------------------------------------------------------------------
# 自动方法选择
# ---------------------------------------------------------------------------


def _auto_select_method(history: list[float]) -> str:
    """基于历史数据特征自动选择最优预测方法。

    规则（优先级从高到低）：
      1. 历史数据长度 < 4 → SMA（数据太少，简单平均最稳妥）
      2. 末尾 30% 呈单调趋势（连续 ≥3 期间向变化）→ Holt
      3. 否则 → SES

    Args:
        history: 历史需求数据序列

    Returns:
        方法名字符串（"sma" / "ses" / "holt"）
    """
    if len(history) < 4:
        return "sma"

    # Examine tail ~30% for monotonic trend
    tail_size = max(4, math.ceil(len(history) * 0.3))
    tail = history[-tail_size:]
    diffs = [tail[i + 1] - tail[i] for i in range(len(tail) - 1)]

    # Check for 3+ consecutive same-sign differences
    consecutive = 1
    for i in range(1, len(diffs)):
        same_direction = (diffs[i] > 0 and diffs[i - 1] > 0) or (
            diffs[i] < 0 and diffs[i - 1] < 0
        )
        if same_direction:
            consecutive += 1
            if consecutive >= 3:
                return "holt"
        else:
            consecutive = 1

    return "ses"


# ---------------------------------------------------------------------------
# 误差计算
# ---------------------------------------------------------------------------


def _compute_errors(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """从 (实际值, 预测值) 对列表中计算 MAE / RMSE / MAPE。

    MAPE 处理：实际值为 0 时该点跳过；若无有效点则返回 float('inf')。

    Args:
        pairs: [(actual, predicted), ...] 列表

    Returns:
        (mae, rmse, mape) 三元组，均已 round 到 2 位小数
    """
    if not pairs:
        return 0.0, 0.0, float("inf")

    n = len(pairs)
    abs_errors = [abs(a - p) for a, p in pairs]
    mae = sum(abs_errors) / n

    sq_errors = [(a - p) ** 2 for a, p in pairs]
    rmse = math.sqrt(sum(sq_errors) / n)

    # MAPE: skip zero-actual points
    mape_pairs = [
        abs(a - p) / abs(a) for a, p in pairs if a != 0.0
    ]
    if mape_pairs:
        mape = sum(mape_pairs) / len(mape_pairs) * 100
    else:
        mape = float("inf")

    return round(mae, 2), round(rmse, 2), round(mape, 2) if mape != float("inf") else float("inf")


# ---------------------------------------------------------------------------
# 预测算法
# ---------------------------------------------------------------------------


def _sma_forecast(
    history: list[float], window: int, periods: int
) -> tuple[list[float], float, float, float]:
    """简单移动平均法。

    one-step-ahead: F_t = mean(A_{t-window}, ..., A_{t-1})
    """
    n = len(history)
    pairs: list[tuple[float, float]] = []

    for i in range(window, n):
        predicted = sum(history[i - window : i]) / window
        pairs.append((history[i], predicted))

    # Future forecast: mean of last window observations
    last_avg = sum(history[-window:]) / window
    forecasts = [last_avg] * periods

    mae, rmse, mape = _compute_errors(pairs)
    return forecasts, mae, rmse, mape


def _wma_forecast(
    history: list[float], window: int, periods: int
) -> tuple[list[float], float, float, float]:
    """加权移动平均法。

    线性递增权重：最近一期权重 = window / sum(1..window)，最远一期 = 1 / sum(1..window)。
    例 window=3 → 权重 [1/6, 2/6, 3/6]。
    """
    n = len(history)
    # Pre-compute weights: [1, 2, ..., window] / sum(1..window)
    weight_sum = window * (window + 1) / 2  # sum of 1..window
    weights = [(i + 1) / weight_sum for i in range(window)]  # oldest → newest

    pairs: list[tuple[float, float]] = []

    for i in range(window, n):
        window_data = history[i - window : i]
        predicted = sum(w * v for w, v in zip(weights, window_data))
        pairs.append((history[i], predicted))

    # Future forecast: weighted mean of last window observations
    last_data = history[-window:]
    last_wma = sum(w * v for w, v in zip(weights, last_data))
    forecasts = [last_wma] * periods

    mae, rmse, mape = _compute_errors(pairs)
    return forecasts, mae, rmse, mape


def _ses_forecast(
    history: list[float], alpha: float, periods: int
) -> tuple[list[float], float, float, float]:
    """单指数平滑法（Simple Exponential Smoothing）。

    初始化: S_0 = A_0
    one-step-ahead: F_t = S_{t-1}
    更新: S_t = α·A_t + (1-α)·S_{t-1}
    """
    n = len(history)
    level = history[0]
    pairs: list[tuple[float, float]] = []

    for i in range(1, n):
        predicted = level  # one-step-ahead forecast
        pairs.append((history[i], predicted))
        level = alpha * history[i] + (1 - alpha) * level

    # Future forecast: last smoothed level (constant)
    forecasts = [level] * periods

    mae, rmse, mape = _compute_errors(pairs)
    return forecasts, mae, rmse, mape


def _holt_forecast(
    history: list[float], alpha: float, beta: float, periods: int
) -> tuple[list[float], float, float, float]:
    """Holt 双参数线性趋势法。

    初始化: L_1 = A_1, T_1 = A_2 - A_1
    one-step-ahead: F_t = L_{t-1} + T_{t-1}
    更新:
      L_t = α·A_t + (1-α)·(L_{t-1} + T_{t-1})
      T_t = β·(L_t - L_{t-1}) + (1-β)·T_{t-1}
    未来预测: F_{n+h} = L_n + h·T_n
    """
    n = len(history)
    level = history[0]          # L_1
    trend = history[1] - history[0]  # T_1 = A_2 - A_1

    pairs: list[tuple[float, float]] = []

    for i in range(1, n):
        predicted = level + trend  # one-step-ahead forecast
        pairs.append((history[i], predicted))
        new_level = alpha * history[i] + (1 - alpha) * (level + trend)
        trend = beta * (new_level - level) + (1 - beta) * trend
        level = new_level

    # Future forecasts: F_{n+h} = L_n + h·T_n  for h = 1, 2, ..., periods
    forecasts = [level + (h + 1) * trend for h in range(periods)]

    mae, rmse, mape = _compute_errors(pairs)
    return forecasts, mae, rmse, mape


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


# Map method name → (forecast_fn, model_params_keys)
_METHOD_REGISTRY = {
    "sma": (_sma_forecast, ("window",)),
    "wma": (_wma_forecast, ("window",)),
    "ses": (_ses_forecast, ("alpha",)),
    "holt": (_holt_forecast, ("alpha", "beta")),
}


def forecast(params: ForecastParams) -> ForecastResult:
    """需求预测主入口。

    根据 params.method 选择对应算法执行预测，返回包含预测值
    和 in-sample 回测误差指标的 ForecastResult。

    Args:
        params: 预测参数（ForecastParams 实例）

    Returns:
        ForecastResult 包含 forecasts / mae / rmse / mape 等字段

    Raises:
        ValueError: 参数校验不通过

    Example:
        >>> p = ForecastParams(history=[100,120,110,130,140], method="ses", periods=2)
        >>> r = forecast(p)
        >>> print(r.forecasts)  # 未来 2 期预测
    """
    # Resolve method
    if params.method == "auto":
        resolved = _auto_select_method(params.history)
    else:
        resolved = params.method

    # Validate
    _validate_params(params, resolved)

    # Auto-degrade window if needed
    window = params.window
    if window > len(params.history):
        window = len(params.history)

    # Dispatch
    fn, param_keys = _METHOD_REGISTRY[resolved]
    kwargs: dict = {}
    for key in param_keys:
        if key == "window":
            kwargs["window"] = window
        elif key == "alpha":
            kwargs["alpha"] = params.alpha
        elif key == "beta":
            kwargs["beta"] = params.beta

    forecasts_list, mae, rmse, mape = fn(
        params.history, **kwargs, periods=params.periods
    )

    # Build model_params
    model_params: dict = {}
    for key in param_keys:
        if key == "window":
            model_params["window"] = window
        elif key == "alpha":
            model_params["alpha"] = params.alpha
        elif key == "beta":
            model_params["beta"] = params.beta

    # Human-readable method name
    method_names = {
        "sma": "简单移动平均 (SMA)",
        "wma": "加权移动平均 (WMA)",
        "ses": "单指数平滑 (SES)",
        "holt": "Holt 双参数线性趋势",
    }

    return ForecastResult(
        forecasts=forecasts_list,
        mae=mae,
        rmse=rmse,
        mape=mape,
        method_used=method_names.get(resolved, resolved),
        model_params=model_params,
    )


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------


def auto_forecast(history: list[float], periods: int = 1) -> ForecastResult:
    """便捷入口：自动选择最优方法进行预测。

    等价于 forecast(ForecastParams(history=history, method="auto", periods=periods))。

    Args:
        history: 历史需求数据序列
        periods: 要预测的未来期数

    Returns:
        ForecastResult

    Example:
        >>> r = auto_forecast([100, 120, 130, 150], periods=2)
        >>> print(r.method_used)  # 自动选择的方法
    """
    return forecast(
        ForecastParams(history=history, method="auto", periods=periods)
    )


# 导出别名（与其他模板保持一致的可调用接口）
run = forecast

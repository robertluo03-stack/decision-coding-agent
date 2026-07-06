"""需求预测模板单元测试。

覆盖：4 种算法 / 自动方法选择 / 误差计算 / 边界条件 / run 别名。
"""

import math
import pytest

from src.domain.templates.demand_forecast import (
    ForecastParams,
    ForecastResult,
    forecast,
    auto_forecast,
    run,
    _auto_select_method,
)


# ============================================================================
# 1. SMA 正常使用
# ============================================================================


def test_sma_basic():
    """SMA 正常 6 期历史，预测 3 期 — 预测值 = 最后 window 期平均值。"""
    history = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    params = ForecastParams(history=history, method="sma", window=3, periods=3)
    result = forecast(params)

    expected_avg = (40.0 + 50.0 + 60.0) / 3  # = 50.0
    assert result.forecasts == [expected_avg] * 3
    assert result.method_used == "简单移动平均 (SMA)"
    assert result.model_params == {"window": 3}


# ============================================================================
# 2. WMA 权重正确性验证
# ============================================================================


def test_wma_weights():
    """WMA window=3 加权正确 — 手工计算验证。"""
    # Use simple data where we can hand-calculate:
    # history = [10, 20, 30, 40, 50, 60], window=3
    # weights = [1/6, 2/6, 3/6]
    # one-step-ahead for i=3 (value=40): predicted = 1/6*10 + 2/6*20 + 3/6*30 = 1.67+6.67+15 = 23.33...
    # one-step-ahead for i=4 (value=50): predicted = 1/6*20 + 2/6*30 + 3/6*40 = 3.33+10+20 = 33.33...
    # one-step-ahead for i=5 (value=60): predicted = 1/6*30 + 2/6*40 + 3/6*50 = 5+13.33+25 = 43.33...
    # forecast = 1/6*40 + 2/6*50 + 3/6*60 = 6.67+16.67+30 = 53.33...
    history = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    params = ForecastParams(history=history, method="wma", window=3, periods=2)
    result = forecast(params)

    w1, w2, w3 = 1 / 6, 2 / 6, 3 / 6
    expected_forecast = w1 * 40.0 + w2 * 50.0 + w3 * 60.0  # 53.333...

    assert len(result.forecasts) == 2
    for f in result.forecasts:
        assert math.isclose(f, expected_forecast, rel_tol=1e-9)

    assert result.method_used == "加权移动平均 (WMA)"
    assert result.model_params == {"window": 3}


# ============================================================================
# 3. SES 单指数平滑 — 公式手工验证
# ============================================================================


def test_ses_formula():
    """SES alpha=0.3 单期预测 — 公式手算验证。"""
    # history = [100, 120]
    # level_0 = 100
    # i=1: predicted = level = 100, actual=120, level = 0.3*120 + 0.7*100 = 106
    # forecast = [106] * periods
    history = [100.0, 120.0]
    params = ForecastParams(history=history, method="ses", alpha=0.3, periods=1)
    result = forecast(params)

    expected_level = 0.3 * 120.0 + 0.7 * 100.0  # = 106.0
    assert result.forecasts == [expected_level]
    assert result.method_used == "单指数平滑 (SES)"


# ============================================================================
# 4. Holt 双参数线性趋势
# ============================================================================


def test_holt_trend():
    """Holt 线性趋势数据 — 预测值应体现递增趋势。"""
    # Strictly increasing data
    history = [100.0, 120.0, 140.0, 160.0, 180.0]
    params = ForecastParams(
        history=history, method="holt", alpha=0.3, beta=0.1, periods=3
    )
    result = forecast(params)

    assert len(result.forecasts) == 3
    # Forecasts should be increasing (since data trends up)
    for i in range(1, len(result.forecasts)):
        assert result.forecasts[i] > result.forecasts[i - 1], (
            f"Expected increasing forecasts, got {result.forecasts}"
        )

    assert result.method_used == "Holt 双参数线性趋势"
    assert result.model_params == {"alpha": 0.3, "beta": 0.1}


# ============================================================================
# 5. auto 方法选择 — 趋势数据 → holt
# ============================================================================


def test_auto_trend_selects_holt():
    """auto 方法选择 — 趋势数据末尾连续递增 → holt。"""
    # End portion is steadily increasing: last 30% has consecutive same-direction diffs
    history = [10.0, 12.0, 11.0, 13.0, 15.0, 18.0, 22.0, 27.0, 33.0, 40.0]
    # tail (30% of 10 ≈ 3, max(4, 3)=4): [27, 33, 40]? let's compute:
    # tail_size = max(4, ceil(10*0.3)) = max(4, 3) = 4
    # tail = [22, 27, 33, 40], diffs = [5, 6, 7] → 3 consecutive positive → holt
    params = ForecastParams(history=history, method="auto", periods=2)
    result = forecast(params)

    assert result.method_used == "Holt 双参数线性趋势"


# ============================================================================
# 6. auto 方法选择 — 平稳数据 → ses
# ============================================================================


def test_auto_stable_selects_ses():
    """auto 方法选择 — 平稳数据（无长趋势）→ ses。"""
    # Data oscillates without 3+ consecutive same-direction changes in tail
    history = [100.0, 105.0, 98.0, 102.0, 97.0, 103.0, 99.0]
    params = ForecastParams(history=history, method="auto", periods=2)
    result = forecast(params)

    assert result.method_used == "单指数平滑 (SES)"


# ============================================================================
# 7. auto 方法选择 — 短数据 → sma
# ============================================================================


def test_auto_short_selects_sma():
    """auto 方法选择 — 数据点 < 4 → sma。"""
    history = [100.0, 120.0, 110.0]  # len=3 < 4
    assert _auto_select_method(history) == "sma"

    params = ForecastParams(history=history, method="auto", periods=1)
    result = forecast(params)
    assert result.method_used == "简单移动平均 (SMA)"


# ============================================================================
# 8. MAE / RMSE / MAPE 计算正确性
# ============================================================================


def test_error_metrics():
    """MAE / RMSE / MAPE 计算正确性 — 手工计算验证。"""
    # SMA window=2, history=[10, 20, 30, 40]
    # one-step-ahead:
    #   i=2 (value=30): predicted = mean(10,20) = 15, error = 15
    #   i=3 (value=40): predicted = mean(20,30) = 25, error = 15
    # MAE = (15+15)/2 = 15
    # RMSE = sqrt((225+225)/2) = sqrt(225) = 15
    # MAPE = (|15/30| + |15/40|) / 2 * 100 = (0.5+0.375)/2*100 = 43.75
    history = [10.0, 20.0, 30.0, 40.0]
    params = ForecastParams(history=history, method="sma", window=2, periods=1)
    result = forecast(params)

    assert math.isclose(result.mae, 15.0, rel_tol=1e-9)
    assert math.isclose(result.rmse, 15.0, rel_tol=1e-9)
    expected_mape = (abs(15 / 30) + abs(15 / 40)) / 2 * 100  # 43.75
    assert math.isclose(result.mape, expected_mape, rel_tol=1e-9)


# ============================================================================
# 9. 边界 — 恰好 2 个数据点
# ============================================================================


def test_boundary_two_points():
    """边界 — 恰好 2 个数据点，不报错且正常预测。"""
    history = [50.0, 60.0]
    params = ForecastParams(history=history, method="sma", window=2, periods=1)
    result = forecast(params)

    assert len(result.forecasts) == 1
    assert result.forecasts[0] == 55.0  # mean of 50 and 60


# ============================================================================
# 10. 边界 — history 为空
# ============================================================================


def test_boundary_empty_history():
    """边界 — history 为空列表 → ValueError。"""
    params = ForecastParams(history=[], method="sma", periods=1)
    with pytest.raises(ValueError, match="历史数据至少需要 2 个数据点"):
        forecast(params)


# ============================================================================
# 11. 边界 — 非法 method
# ============================================================================


def test_boundary_invalid_method():
    """边界 — 非法 method → ValueError 含可选方法列表。"""
    params = ForecastParams(history=[10, 20], method="arima", periods=1)
    with pytest.raises(ValueError, match="不支持的方法"):
        forecast(params)


# ============================================================================
# 12. 边界 — alpha 超出范围
# ============================================================================


def test_boundary_alpha_out_of_range():
    """边界 — alpha=1.5 → ValueError。"""
    params = ForecastParams(history=[10, 20, 30], method="ses", alpha=1.5, periods=1)
    with pytest.raises(ValueError, match="alpha"):
        forecast(params)


# ============================================================================
# 13. 边界 — window > len(history) 自动降级
# ============================================================================


def test_boundary_window_degrades():
    """边界 — window > len(history) → window 自动降级为 len(history)。"""
    history = [10.0, 20.0, 30.0]
    # window=10 > 3 → should degrade to window=3
    params = ForecastParams(history=history, method="sma", window=10, periods=1)
    result = forecast(params)

    # Should not error; window degrades to 3
    assert result.model_params["window"] == 3
    assert result.forecasts[0] == 20.0  # mean of all 3


# ============================================================================
# 14. 边界 — MAPE 含零值不过除零
# ============================================================================


def test_boundary_mape_zero_handling():
    """MAPE 含零值 — 零值点跳过，不除零。"""
    # history=[0, 10, 0, 20], SMA window=2
    # one-step-ahead:
    #   i=2 (actual=0): predicted = mean(0,10) = 5 → error=5, actual=0 → SKIP for MAPE
    #   i=3 (actual=20): predicted = mean(10,0) = 5 → error=15, actual=20 → MAPE = 15/20 = 0.75
    # MAE = (5+15)/2 = 10
    # MAPE = 15/20 * 100 = 75.0 (only one valid point)
    history = [0.0, 10.0, 0.0, 20.0]
    params = ForecastParams(history=history, method="sma", window=2, periods=1)
    result = forecast(params)

    assert math.isclose(result.mae, 10.0, rel_tol=1e-9)
    assert math.isclose(result.mape, 75.0, rel_tol=1e-9)
    # rmse: sqrt((25+225)/2) = sqrt(125) ≈ 11.18 (rounded to 2dp)
    assert math.isclose(result.rmse, round(math.sqrt(125), 2), rel_tol=1e-9)

    # Verify no inf when there's at least one non-zero actual
    assert not math.isinf(result.mape)


# ============================================================================
# 15. run 别名可调用
# ============================================================================


def test_run_alias():
    """run 别名可调用 — run(params) == forecast(params)。"""
    params = ForecastParams(
        history=[100.0, 120.0, 130.0], method="sma", window=2, periods=1
    )
    r1 = forecast(params)
    r2 = run(params)

    assert r1.forecasts == r2.forecasts
    assert r1.mae == r2.mae
    assert r1.rmse == r2.rmse
    assert r1.mape == r2.mape
    assert r1.method_used == r2.method_used
    assert r1.model_params == r2.model_params


# ============================================================================
# 附加：auto_forecast 便捷入口
# ============================================================================


def test_auto_forecast_convenience():
    """auto_forecast() 便捷入口正常工作。"""
    result = auto_forecast([100.0, 120.0, 130.0, 150.0], periods=2)

    assert len(result.forecasts) == 2
    assert isinstance(result.method_used, str)
    assert result.model_params
    assert result.mae >= 0
    assert result.rmse >= 0


# ============================================================================
# 附加：多种 method 显式指定
# ============================================================================


@pytest.mark.parametrize(
    "method,expected_label",
    [
        ("sma", "简单移动平均 (SMA)"),
        ("wma", "加权移动平均 (WMA)"),
        ("ses", "单指数平滑 (SES)"),
        ("holt", "Holt 双参数线性趋势"),
    ],
)
def test_all_methods_integration(method, expected_label):
    """所有 4 种方法均可正常执行。"""
    history = [100.0, 120.0, 115.0, 130.0, 140.0, 150.0]
    params = ForecastParams(history=history, method=method, periods=3)
    result = forecast(params)

    assert len(result.forecasts) == 3
    assert result.method_used == expected_label
    assert result.mae >= 0
    assert result.rmse >= 0

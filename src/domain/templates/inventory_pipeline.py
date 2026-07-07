"""供应链库存分析一键流水线。

将数据读取 → 质量检查 → 需求预测 → EOQ → 安全库存 → 补货点 → 图表 → 报告
封装为一条调用，用户只需指定 CSV 路径即可获得完整库存优化分析报告。

使用方式:
    from src.domain.templates.inventory_pipeline import run_inventory_pipeline, InventoryPipelineParams
    result = run_inventory_pipeline(InventoryPipelineParams(
        csv_path="data/inventory_demand.csv",
        time_col="month", demand_col="demand",
    ))
    print(result.report_path)
"""

from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from src.domain.data_quality import run_quality_check
from src.domain.chart_templates import line_chart, bar_chart
from src.domain.templates.demand_forecast import auto_forecast, ForecastResult
from src.domain.templates.inventory_eoq import calculate as calc_eoq, EOQParams, EOQResult
from src.domain.templates.safety_stock import (
    calculate_safety_stock,
    SafetyStockParams,
    SafetyStockResult,
)
from src.domain.templates.reorder_point import calculate as calc_rop, ROPParams, ROPResult


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class InventoryPipelineParams:
    """供应链库存分析流水线参数。

    Attributes:
        csv_path: 库存数据 CSV 路径（相对 workspace/data/）
        time_col: 时间列名
        demand_col: 需求列名
        ordering_cost: 每次订货成本（默认 100）
        holding_cost_rate: 年持有成本率（默认 20%）
        unit_cost: 单位成本（默认 10）
        service_level: 服务水平（默认 95%，支持 95 或 0.95 两种格式）
        lead_time: 提前期（默认 1 个月）
        forecast_periods: 预测未来期数
        output_dir: 报告输出目录
    """
    csv_path: str
    time_col: str = "month"
    demand_col: str = "demand"
    ordering_cost: float = 100.0
    holding_cost_rate: float = 0.2
    unit_cost: float = 10.0
    service_level: float = 95.0
    lead_time: float = 1.0
    forecast_periods: int = 3
    output_dir: str = "reports/"


@dataclass
class InventoryPipelineResult:
    """供应链库存分析流水线结果。

    Attributes:
        report_path: 生成的 Markdown 报告路径
        forecast_result: 需求预测结果
        eoq_result: EOQ 计算结果
        safety_stock_result: 安全库存计算结果
        rop_result: 补货点计算结果
        quality_report: 数据质量报告
        charts: 生成的图表路径列表
    """
    report_path: str
    forecast_result: Optional[ForecastResult] = None
    eoq_result: Optional[EOQResult] = None
    safety_stock_result: Optional[SafetyStockResult] = None
    rop_result: Optional[ROPResult] = None
    quality_report: Optional[dict] = None
    charts: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 数据粒度检测
# ---------------------------------------------------------------------------


def _detect_granularity(dates: pd.Series) -> tuple[str, float]:
    """检测时间序列的数据粒度。

    计算相邻时间点的差值中位数（天数），匹配对应粒度。

    Args:
        dates: pd.Series（datetime 类型）

    Returns:
        (granularity_str, days_per_period) 二元组

    Example:
        >>> s = pd.to_datetime(pd.Series(["2026-01-01", "2026-02-01", "2026-03-01"]))
        >>> _detect_granularity(s)
        ("月", 30.44)
    """
    sorted_dates = dates.dropna().sort_values()
    if len(sorted_dates) < 2:
        return ("月", 30.44)

    diffs = sorted_dates.diff().dropna().dt.total_seconds() / 86400.0
    median_diff = float(diffs.median())

    if 28 <= median_diff <= 33:
        return ("月", 30.44)
    elif 6 <= median_diff <= 8:
        return ("周", 7.0)
    elif 0.9 <= median_diff <= 1.1:
        return ("日", 1.0)
    else:
        return ("月", 30.44)  # default to monthly


# ---------------------------------------------------------------------------
# 年需求推断
# ---------------------------------------------------------------------------


def _compute_annual_demand(
    df: pd.DataFrame, params: InventoryPipelineParams, granularity: str
) -> float:
    """根据数据粒度和历史数据推断年化需求。

    Args:
        df: 历史数据 DataFrame
        params: 流水线参数（用于获取 demand_col）
        granularity: 数据粒度（"月" / "周" / "日"）

    Returns:
        年化需求量（float，≥0）

    Example:
        >>> df = pd.DataFrame({"demand": [100]*24})
        >>> _compute_annual_demand(df, InventoryPipelineParams("test.csv"), "月")
        1200.0
    """
    total_demand = float(df[params.demand_col].sum())
    n = len(df)
    if n == 0:
        return 0.0

    if granularity == "月":
        return total_demand / n * 12
    elif granularity == "周":
        return total_demand / n * 52
    elif granularity == "日":
        return total_demand / n * 365
    else:
        return total_demand / n * 12  # default: monthly


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------


def _build_inventory_report(
    result: InventoryPipelineResult,
    params: InventoryPipelineParams,
    df: pd.DataFrame,
) -> str:
    """生成 8 章节 Markdown 分析报告。

    Args:
        result: 流水线执行结果
        params: 流水线参数
        df: 原始数据 DataFrame

    Returns:
        完整 Markdown 文本
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = len(df)
    m = params.forecast_periods

    lines: list[str] = []

    # ---- 1. 概述 ----
    lines.append("# 供应链库存优化分析报告")
    lines.append("")
    lines.append("## 1. 概述")
    lines.append("")
    lines.append(f"- 分析时间：{now_str}")
    lines.append(f"- 数据文件：{params.csv_path}")
    lines.append(f"- 数据点数：{n}")
    lines.append("")
    lines.append(f"基于 {n} 期历史数据，预测未来 {m} 期需求，生成最优库存策略。")
    lines.append("")

    # ---- 2. 数据质量摘要 ----
    lines.append("## 2. 数据质量摘要")
    lines.append("")
    if result.quality_report:
        qr = result.quality_report
        lines.append(f"- 综合评分：{qr['overall_score']}/100")
        missing_cols = [c for c in qr["columns"] if c["missing_rate"] > 0]
        lines.append(f"- 存在缺失值的列数：{len(missing_cols)}")
        if missing_cols:
            for c in missing_cols:
                lines.append(
                    f"  - `{c['name']}`：缺失率 {c['missing_rate']:.1%}"
                    f"（{c['missing_level']}）"
                )
        total_outliers = sum(c["outlier_count"] for c in qr["columns"])
        lines.append(f"- 异常值总数：{total_outliers}")
        if qr["recommendations"]:
            lines.append("- 修复建议：")
            for rec in qr["recommendations"][:5]:
                lines.append(f"  - {rec}")
    else:
        lines.append("（数据质量检查未执行）")
    lines.append("")

    # ---- 3. 需求预测结果 ----
    lines.append("## 3. 需求预测结果")
    lines.append("")
    if result.forecast_result:
        fr = result.forecast_result
        lines.append(f"- 使用方法：{fr.method_used}")
        lines.append(f"- 预测期数：{m}")
        lines.append(
            f"- 预测值：{', '.join(f'{v:.2f}' for v in fr.forecasts)}"
        )
        lines.append(f"- MAE：{fr.mae}")
        lines.append(f"- RMSE：{fr.rmse}")
        lines.append(f"- MAPE：{fr.mape}%")
        if fr.model_params:
            lines.append(f"- 模型参数：{fr.model_params}")
    else:
        lines.append("（需求预测未执行或失败）")
    lines.append("")

    # ---- 4. EOQ ----
    lines.append("## 4. EOQ 经济订货批量分析")
    lines.append("")
    if result.eoq_result:
        er = result.eoq_result
        # Recompute annual demand for display
        dates = pd.to_datetime(df[params.time_col], errors="coerce")
        gran, _ = _detect_granularity(dates)
        annual_d = _compute_annual_demand(df, params, gran)
        holding_cost = params.unit_cost * params.holding_cost_rate
        lines.append(f"- 年需求量：{annual_d:.0f}")
        lines.append(f"- 每次订货成本：{params.ordering_cost}")
        lines.append(f"- 单位持有成本：{holding_cost:.2f}")
        lines.append(f"- EOQ：{er.eoq} 件")
        lines.append(f"- 年订货次数：{er.annual_orders} 次")
        lines.append(f"- 年订货总成本：{er.total_ordering_cost}")
        lines.append(f"- 年持有总成本：{er.total_holding_cost}")
        lines.append(f"- 年库存总成本：{er.total_cost}")
    else:
        lines.append("（EOQ 计算未执行或失败）")
    lines.append("")

    # ---- 5. 安全库存分析 ----
    lines.append("## 5. 安全库存分析")
    lines.append("")
    if result.safety_stock_result:
        ss = result.safety_stock_result
        lines.append(f"- 目标服务水平：{ss.service_level:.2%}")
        lines.append(f"- Z 值：{ss.z_score}")
        lines.append(f"- 安全库存量：{ss.safety_stock}")
        lines.append(f"- 使用公式：{ss.formula_used}")
    else:
        lines.append("（安全库存计算未执行或失败）")
    lines.append("")

    # ---- 6. 补货点决策 ----
    lines.append("## 6. 补货点决策")
    lines.append("")
    if result.rop_result:
        rp = result.rop_result
        lines.append(f"- 补货点：{rp.reorder_point}")
        lines.append(f"- 提前期平均需求：{rp.lead_time_demand}")
        lines.append(f"- 业务建议：{rp.suggestion}")
    else:
        lines.append("（补货点计算未执行或失败）")
    lines.append("")

    # ---- 7. 综合建议 ----
    lines.append("## 7. 综合建议")
    lines.append("")
    if result.rop_result is not None and result.eoq_result is not None:
        lines.append(
            f"基于以上分析，建议采用 (ROP, Q) 库存策略："
            f"当库存降至 **{result.rop_result.reorder_point:.0f}** 时触发补货，"
            f"每次订货量为 **{result.eoq_result.eoq:.0f}** 件。"
        )
    else:
        lines.append("基于以上分析，建议采用 (ROP, Q) 库存策略。")
    lines.append("")

    # ---- 8. 附录 ----
    lines.append("## 8. 附录")
    lines.append("")
    lines.append("### 分析图表")
    lines.append("")
    if result.charts:
        for chart_path in result.charts:
            chart_name = Path(chart_path).stem
            lines.append(f"![{chart_name}]({chart_path})")
    else:
        lines.append("（无图表）")
    lines.append("")
    lines.append("### 分析参数配置表")
    lines.append("")
    lines.append("| 参数 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| csv_path | {params.csv_path} |")
    lines.append(f"| time_col | {params.time_col} |")
    lines.append(f"| demand_col | {params.demand_col} |")
    lines.append(f"| ordering_cost | {params.ordering_cost} |")
    lines.append(f"| holding_cost_rate | {params.holding_cost_rate} |")
    lines.append(f"| unit_cost | {params.unit_cost} |")
    lines.append(f"| service_level | {params.service_level}% |")
    lines.append(f"| lead_time | {params.lead_time} |")
    lines.append(f"| forecast_periods | {params.forecast_periods} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 内部辅助：从 DataFrame 推断年度需求与平均月需求
# ---------------------------------------------------------------------------


def _infer_demand_context(
    df: pd.DataFrame, params: InventoryPipelineParams
) -> tuple[str, float, float, float]:
    """一次性推断数据粒度、年需求、月均需求、需求标准差。

    Args:
        df: 历史数据 DataFrame
        params: 流水线参数

    Returns:
        (granularity, annual_demand, avg_monthly_demand, demand_std) 四元组
    """
    dates = pd.to_datetime(df[params.time_col], errors="coerce")
    granularity, _ = _detect_granularity(dates)
    annual_demand = _compute_annual_demand(df, params, granularity)
    avg_monthly = annual_demand / 12.0
    demand_std = float(df[params.demand_col].std())
    return granularity, annual_demand, avg_monthly, demand_std


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run_inventory_pipeline(
    params: InventoryPipelineParams,
) -> InventoryPipelineResult:
    """供应链库存分析一键流水线主入口。

    8 步流水线（严格顺序）：
      1. 读取 CSV + 列名校验
      2. 数据质量检查
      3. 需求预测
      4. EOQ 计算
      5. 安全库存计算
      6. 补货点计算
      7. 图表生成
      8. 报告生成

    每步有 try/except 包裹，单步失败不影响后续步骤。

    Args:
        params: 流水线参数（InventoryPipelineParams 实例）

    Returns:
        InventoryPipelineResult 包含报告路径、各项计算结果和图表路径

    Example:
        >>> p = InventoryPipelineParams("data/demand.csv")
        >>> result = run_inventory_pipeline(p)
        >>> print(result.report_path)
    """
    logger.info(f"开始库存分析流水线: {params.csv_path}")

    result = InventoryPipelineResult(report_path="")

    # Ensure output directories exist
    Path(params.output_dir).mkdir(parents=True, exist_ok=True)
    charts_dir = str(Path(params.output_dir) / "charts")
    Path(charts_dir).mkdir(parents=True, exist_ok=True)

    # ---- Step 1: 读取 CSV ----
    logger.info("Step 1/8: 读取 CSV...")
    df: pd.DataFrame
    try:
        df = pd.read_csv(params.csv_path)
        if params.time_col not in df.columns:
            available = ", ".join(str(c) for c in df.columns)
            raise ValueError(
                f"time_col '{params.time_col}' 不存在，可用列: {available}"
            )
        if params.demand_col not in df.columns:
            available = ", ".join(str(c) for c in df.columns)
            raise ValueError(
                f"demand_col '{params.demand_col}' 不存在，可用列: {available}"
            )
        logger.info(f"CSV 已加载: {len(df)} 行, {len(df.columns)} 列")
    except Exception as e:
        logger.error(f"Step 1 失败: {e}")
        return result  # 无数据则无法继续

    # Pre-compute shared demand context (granularity, annual, monthly avg, std)
    gran, annual_d, avg_monthly, demand_std = _infer_demand_context(df, params)

    # ---- Step 2: 数据质量检查 ----
    logger.info("Step 2/8: 数据质量检查...")
    try:
        result.quality_report = run_quality_check(df)
        logger.info(
            f"质量评分: {result.quality_report['overall_score']}/100"
        )
    except Exception as e:
        logger.error(f"Step 2 失败: {e}")

    # ---- Step 3: 需求预测 ----
    logger.info("Step 3/8: 需求预测...")
    try:
        history = df[params.demand_col].tolist()
        if len(history) >= 2:
            result.forecast_result = auto_forecast(
                history, periods=params.forecast_periods
            )
            logger.info(f"预测值: {result.forecast_result.forecasts}")
        else:
            logger.warning(
                f"历史数据不足，需要 ≥2 期，实际 {len(history)} 期"
            )
    except Exception as e:
        logger.error(f"Step 3 失败: {e}")

    # ---- Step 4: EOQ 计算 ----
    logger.info("Step 4/8: EOQ 经济订货批量...")
    try:
        holding_cost = params.unit_cost * params.holding_cost_rate
        result.eoq_result = calc_eoq(
            EOQParams(
                annual_demand=annual_d,
                ordering_cost=params.ordering_cost,
                holding_cost=holding_cost,
            )
        )
        logger.info(
            f"EOQ: {result.eoq_result.eoq} "
            f"(粒度={gran}, 年需求={annual_d:.0f}, 持有成本={holding_cost:.2f})"
        )
    except Exception as e:
        logger.error(f"Step 4 失败: {e}")

    # ---- Step 5: 安全库存计算 ----
    logger.info("Step 5/8: 安全库存计算...")
    try:
        result.safety_stock_result = calculate_safety_stock(
            SafetyStockParams(
                avg_demand=avg_monthly,
                demand_std=demand_std,
                lead_time=params.lead_time,
                service_level=params.service_level,
            )
        )
        logger.info(
            f"安全库存: {result.safety_stock_result.safety_stock}"
        )
    except Exception as e:
        logger.error(f"Step 5 失败: {e}")

    # ---- Step 6: 补货点计算 ----
    logger.info("Step 6/8: 补货点计算...")
    try:
        ss_val = (
            result.safety_stock_result.safety_stock
            if result.safety_stock_result is not None
            else 0.0
        )
        eoq_val = (
            result.eoq_result.eoq
            if result.eoq_result is not None
            else None
        )
        result.rop_result = calc_rop(
            ROPParams(
                avg_demand=avg_monthly,
                lead_time=params.lead_time,
                safety_stock=ss_val,
                eoq=eoq_val,
            )
        )
        logger.info(f"补货点: {result.rop_result.reorder_point}")
    except Exception as e:
        logger.error(f"Step 6 失败: {e}")

    # ---- Step 7: 图表生成 ----
    logger.info("Step 7/8: 图表生成...")
    charts: list[str] = []

    # 需求趋势图
    try:
        trend_path = str(Path(charts_dir) / "demand_trend.html")
        line_chart(
            df, params.time_col, params.demand_col,
            "历史需求趋势", trend_path,
        )
        charts.append(trend_path)
        logger.info(f"需求趋势图: {trend_path}")
    except Exception as e:
        logger.error(f"需求趋势图生成失败: {e}")

    # 库存参数对比图
    try:
        categories: list[str] = []
        values: list[float] = []
        if result.eoq_result is not None:
            categories.append("EOQ")
            values.append(result.eoq_result.eoq)
        if result.safety_stock_result is not None:
            categories.append("安全库存")
            values.append(result.safety_stock_result.safety_stock)
        if result.rop_result is not None:
            categories.append("补货点")
            values.append(result.rop_result.reorder_point)

        if categories:
            df_comp = pd.DataFrame({"指标": categories, "数量": values})
            comp_path = str(Path(charts_dir) / "inventory_params.html")
            bar_chart(df_comp, "指标", "数量", "库存参数对比", comp_path)
            charts.append(comp_path)
            logger.info(f"参数对比图: {comp_path}")
    except Exception as e:
        logger.error(f"参数对比图生成失败: {e}")

    result.charts = charts

    # ---- Step 8: 报告生成 ----
    logger.info("Step 8/8: 报告生成...")
    try:
        report_md = _build_inventory_report(result, params, df)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"report_inventory_{timestamp}.md"
        report_path = str(Path(params.output_dir) / report_filename)
        Path(report_path).write_text(report_md, encoding="utf-8")
        result.report_path = report_path
        logger.info(f"报告已写入: {report_path}")
    except Exception as e:
        logger.error(f"Step 8 失败: {e}")

    logger.info(
        f"流水线完成。报告: {result.report_path}, "
        f"图表: {len(result.charts)} 个"
    )
    return result


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------


def quick_analyze(
    csv_path: str, output_dir: str = "reports/"
) -> InventoryPipelineResult:
    """便捷入口：使用全部默认值一键分析。

    Args:
        csv_path: CSV 数据文件路径
        output_dir: 报告输出目录

    Returns:
        InventoryPipelineResult
    """
    return run_inventory_pipeline(
        InventoryPipelineParams(csv_path=csv_path, output_dir=output_dir)
    )


# 导出别名（与项目约定一致）
run = run_inventory_pipeline

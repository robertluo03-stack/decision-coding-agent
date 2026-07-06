"""一键数据分析领域模板。

将数据读取 → 质量检查 → EDA 统计 → 图表生成 → 报告写入 封装为一条调用，
用户只需指定文件路径即可获得完整 Markdown 分析报告。

使用方式:
    from src.domain.templates.data_analysis import run_analysis
    report_path = run_analysis("data/sales.csv", output_dir="reports/")
    print(f"分析报告已生成: {report_path}")
"""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.domain.data_quality import run_quality_check
from src.domain.chart_templates import bar_chart, line_chart


# ---------------------------------------------------------------------------
# 内部 EDA 统计引擎
# ---------------------------------------------------------------------------


def _compute_eda_summary(df: pd.DataFrame) -> dict:
    """对 DataFrame 执行基础 EDA 统计。

    生成包含各数值列统计量和类别列唯一值计数的摘要 dict。

    Args:
        df: 输入 DataFrame

    Returns:
        {
            "numeric_stats": {col: {count, mean, std, min, 25%, 50%, 75%, max}},
            "categorical_overview": {col: unique_count},
            "total_rows": int,
            "total_columns": int,
        }
    """
    total_rows = len(df)
    total_cols = len(df.columns)

    numeric_stats: dict = {}
    categorical_overview: dict = {}

    for col in df.columns:
        series = df[col]

        if pd.api.types.is_numeric_dtype(series):
            desc = series.describe()
            numeric_stats[col] = {
                "count": int(desc["count"]),
                "mean": round(float(desc["mean"]), 2),
                "std": round(float(desc["std"]), 2),
                "min": round(float(desc["min"]), 2),
                "25%": round(float(desc["25%"]), 2),
                "50%": round(float(desc["50%"]), 2),
                "75%": round(float(desc["75%"]), 2),
                "max": round(float(desc["max"]), 2),
            }
        else:
            categorical_overview[col] = {
                "unique_count": int(series.nunique()),
                "most_common": str(series.mode().iloc[0]) if len(series.mode()) > 0 else "N/A",
            }

    return {
        "numeric_stats": numeric_stats,
        "categorical_overview": categorical_overview,
        "total_rows": total_rows,
        "total_columns": total_cols,
    }


# ---------------------------------------------------------------------------
# 规则化结论生成
# ---------------------------------------------------------------------------


def _generate_conclusions(
    quality_report: dict,
    eda_summary: dict,
) -> list[str]:
    """基于数据质量和 EDA 结果，生成规则化中文结论与建议。

    不调用 LLM，全部通过 if-else 规则生成。

    Args:
        quality_report: run_quality_check 返回报告
        eda_summary:    _compute_eda_summary 返回摘要

    Returns:
        中文结论字符串列表（3-6 条）
    """
    conclusions: list[str] = []

    # ---- 总体评分 ----
    score = quality_report.get("overall_score", 100)
    if score >= 90:
        conclusions.append(f"✅ 数据质量评分 {score}/100，数据整体质量良好，可直接用于分析。")
    elif score >= 70:
        conclusions.append(f"⚠️ 数据质量评分 {score}/100，存在一定质量问题，建议在分析前做数据清洗。")
    else:
        conclusions.append(f"❌ 数据质量评分 {score}/100，质量问题较多，强烈建议先进行数据清洗再深入分析。")

    # ---- 缺失值 ----
    total_rows = quality_report.get("total_rows", 0)
    high_missing_cols = [
        c for c in quality_report.get("columns", [])
        if c.get("missing_level") == "high"
    ]
    if high_missing_cols:
        names = "、".join(c["name"] for c in high_missing_cols)
        conclusions.append(
            f"列「{names}」缺失率超过 20%，建议评估该列的业务价值后决定是否保留或填充。"
        )

    # ---- 异常值 ----
    outlier_cols = [
        c for c in quality_report.get("columns", [])
        if c.get("outlier_count", 0) > 0
    ]
    if outlier_cols:
        total_outliers = sum(c["outlier_count"] for c in outlier_cols)
        conclusions.append(
            f"检测到 {total_outliers} 个异常值（涉及 {len(outlier_cols)} 列），"
            f"建议核查是否为录入错误或业务特例。"
        )

    # ---- 重复行 ----
    dup_rate = quality_report.get("duplicate_rate", 0)
    if dup_rate > 0.05:
        conclusions.append(
            f"数据集中重复行占比 {dup_rate:.1%}，建议使用 drop_duplicates() 去重后再分析。"
        )

    # ---- 数值分布 ----
    numeric_stats = eda_summary.get("numeric_stats", {})
    for col_name, stats in numeric_stats.items():
        # 高方差列
        mean_val = stats["mean"]
        std_val = stats["std"]
        if mean_val != 0 and std_val / abs(mean_val) > 1.0:
            conclusions.append(
                f"列「{col_name}」变异系数（CV）较大（均值={mean_val:.1f}，标准差={std_val:.1f}），"
                f"数据波动大，建议按维度（区域/产品）分组分析。"
            )
            break  # 只报最显著的一列

    # ---- 类别分布 ----
    cat_overview = eda_summary.get("categorical_overview", {})
    for col_name, info in cat_overview.items():
        if info["unique_count"] > 20:
            conclusions.append(
                f"类别列「{col_name}」具有 {info['unique_count']} 个唯一值，"
                f"分组分析时建议聚焦 Top 10 类别。"
            )
            break

    # ---- 兜底 ----
    if len(conclusions) < 2:
        conclusions.append("数据基本正常，可进一步按业务需求做专题分析。")

    return conclusions


# ---------------------------------------------------------------------------
# 时间列自动检测
# ---------------------------------------------------------------------------


def _detect_time_column(df: pd.DataFrame) -> str | None:
    """自动检测 DataFrame 中最可能的日期/时间列。

    优先级：列名含 date/time/日期 → dtype 为 datetime → 字符串列尝试 pd.to_datetime

    Args:
        df: 输入 DataFrame

    Returns:
        列名字符串，或 None（未找到）
    """
    # 1. 按列名
    for col in df.columns:
        name_lower = str(col).lower()
        if any(kw in name_lower for kw in ("date", "time", "日期", "时间")):
            return col

    # 2. 按 dtype
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col

    # 3. 尝试解析前 5 个非空值
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            sample = df[col].dropna().head(5)
            if len(sample) > 0:
                try:
                    pd.to_datetime(sample)
                    return col
                except (ValueError, TypeError):
                    pass

    return None


def _detect_category_column(df: pd.DataFrame) -> str | None:
    """自动检测 DataFrame 中最适合做类别分组的列。

    优先选择低基数（2-20 个唯一值）的字符串/类别列。

    Args:
        df: 输入 DataFrame

    Returns:
        列名字符串，或 None（未找到合适的类别列）
    """
    best_col = None
    best_unique = 0

    for col in df.columns:
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            continue
        n_unique = series.nunique()
        if 2 <= n_unique <= 20 and n_unique > best_unique:
            best_col = col
            best_unique = n_unique

    return best_col


def _detect_value_column(df: pd.DataFrame) -> str | None:
    """自动检测 DataFrame 中最适合做 Y 轴的数值列。

    优先选择名称含"销量/收入/金额/数量/volume/price/sales/qty/amount"的列。

    Args:
        df: 输入 DataFrame

    Returns:
        列名字符串，或 None（回退到第一个数值列）
    """
    # 按名称关键词匹配
    keywords = ("销量", "收入", "金额", "数量", "volume", "price", "sales",
                "qty", "amount", "单价", "成本", "库存", "cost")
    for col in df.columns:
        name_lower = str(col).lower()
        if pd.api.types.is_numeric_dtype(df[col]):
            if any(kw in name_lower or kw in str(col) for kw in keywords):
                return col

    # 回退：取第一个数值列
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            return col

    return None


# ---------------------------------------------------------------------------
# Markdown 报告生成
# ---------------------------------------------------------------------------


def _build_analysis_report(
    file_path: str,
    df: pd.DataFrame,
    quality_report: dict,
    eda_summary: dict,
    chart_paths: list[str],
    conclusions: list[str],
) -> str:
    """构建完整的 Markdown 数据分析报告。

    Args:
        file_path:      原始数据文件路径
        df:             数据 DataFrame
        quality_report: 质量检查报告
        eda_summary:     EDA 摘要
        chart_paths:     生成的图表路径列表
        conclusions:    规则化结论列表

    Returns:
        Markdown 格式的完整报告字符串
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_rows = len(df)
    total_cols = len(df.columns)

    lines = [
        "# 数据分析报告",
        "",
        f"**生成时间**: {now}",
        f"**数据文件**: `{file_path}`",
        "",
        "---",
        "",
        "## 1. 数据概览",
        "",
        f"| 属性 | 值 |",
        f"|------|----|",
        f"| 文件 | `{Path(file_path).name}` |",
        f"| 行数 | {total_rows:,} |",
        f"| 列数 | {total_cols} |",
        f"| 列名 | {', '.join(str(c) for c in df.columns)} |",
        "",
        "### 前 5 行预览",
        "",
    ]

    # 前 5 行预览（手动构建 Markdown 表，避免依赖 tabulate）
    preview_df = df.head(5)
    if not preview_df.empty:
        cols = list(preview_df.columns)
        lines.append("| " + " | ".join(str(c) for c in cols) + " |")
        lines.append("|" + "|".join("------" for _ in cols) + "|")
        for _, row in preview_df.iterrows():
            vals = [str(v) if not pd.isna(v) else "" for v in row]
            lines.append("| " + " | ".join(vals) + " |")
    lines.append("")

    # ---- 2. 数据质量 ----
    lines.append("---")
    lines.append("")
    lines.append("## 2. 数据质量检查")
    lines.append("")

    score = quality_report.get("overall_score", "N/A")
    lines.append(f"**综合评分**: {score}/100")
    lines.append("")

    # 质量表
    columns_info = quality_report.get("columns", [])
    if columns_info:
        lines.append("| 列名 | 类型 | 缺失率 | 风险等级 | 异常值数 | 类型冲突 |")
        lines.append("|------|------|--------|---------|---------|---------|")
        for c in columns_info:
            lines.append(
                f"| {c['name']} | {c['dtype']} | {c['missing_rate']:.1%} "
                f"| {c['missing_level']} | {c['outlier_count']} "
                f"| {'⚠️ 是' if c.get('type_conflict') else '否'} |"
            )
        lines.append("")

    # 修复建议
    recommendations = quality_report.get("recommendations", [])
    if recommendations:
        lines.append("### 修复建议")
        lines.append("")
        for rec in recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    # ---- 3. 统计摘要 ----
    lines.append("---")
    lines.append("")
    lines.append("## 3. 统计摘要")
    lines.append("")

    numeric_stats = eda_summary.get("numeric_stats", {})
    if numeric_stats:
        for col_name, stats in numeric_stats.items():
            lines.append(f"### {col_name}")
            lines.append("")
            lines.append("| 指标 | 值 |")
            lines.append("|------|----|")
            for key in ("count", "mean", "std", "min", "25%", "50%", "75%", "max"):
                label_map = {
                    "count": "样本数", "mean": "均值", "std": "标准差",
                    "min": "最小值", "25%": "25%分位", "50%": "中位数",
                    "75%": "75%分位", "max": "最大值",
                }
                lines.append(f"| {label_map.get(key, key)} | {stats[key]} |")
            lines.append("")

    cat_overview = eda_summary.get("categorical_overview", {})
    if cat_overview:
        lines.append("### 类别列概况")
        lines.append("")
        lines.append("| 列名 | 唯一值数 | 最常见值 |")
        lines.append("|------|---------|---------|")
        for col_name, info in cat_overview.items():
            lines.append(f"| {col_name} | {info['unique_count']} | {info['most_common']} |")
        lines.append("")

    # ---- 4. 可视化图表 ----
    if chart_paths:
        lines.append("---")
        lines.append("")
        lines.append("## 4. 可视化图表")
        lines.append("")
        for cp in chart_paths:
            # 转为相对路径便于 Markdown 链接
            name = Path(cp).stem
            rel_path = Path(cp).name
            lines.append(f"- [{name}](charts/{rel_path})")
        lines.append("")

    # ---- 5. 结论与建议 ----
    lines.append("---")
    lines.append("")
    lines.append("## 5. 结论与建议")
    lines.append("")
    for i, c in enumerate(conclusions, 1):
        lines.append(f"{i}. {c}")
    lines.append("")

    # ---- 附录 ----
    lines.append("---")
    lines.append("")
    lines.append("## 附录")
    lines.append("")
    lines.append(f"- 生成工具: DecisionCoder 一键分析模板")
    lines.append(f"- 分析引擎: data_quality + EDA + Plotly 图表")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run_analysis(
    file_path: str,
    output_dir: str = "reports/",
    target_columns: list[str] | None = None,
    time_column: str | None = None,
) -> str:
    """一键数据分析：读取 → 质量检查 → EDA → 图表 → 报告。

    内部流水线：
      1. 读取 CSV/Excel
      2. run_quality_check → 质量报告
      3. _compute_eda_summary → 统计摘要
      4. 自动生成 2 张核心图表（折线图 + 柱状图）
      5. 规则化结论生成
      6. 写入 Markdown 报告

    Args:
        file_path:      数据文件路径（CSV 或 Excel）
        output_dir:     输出目录（相对路径，如 "reports/"）
        target_columns: 可选，指定分析的目标列列表
        time_column:    可选，指定时间列名（不指定则自动检测）

    Returns:
        生成的 Markdown 报告文件路径

    Example:
        >>> from src.domain.templates.data_analysis import run_analysis
        >>> report = run_analysis("data/sales.csv")
        >>> print(f"报告: {report}")
    """
    # ---- 1. 读取数据 ----
    file_lower = file_path.lower()
    if file_lower.endswith(".csv"):
        df = pd.read_csv(file_path)
    elif file_lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {file_path}，仅支持 CSV/Excel")

    # ---- 2. 数据质量检查 ----
    quality_report = run_quality_check(df)

    # ---- 3. EDA 统计摘要 ----
    eda_summary = _compute_eda_summary(df)

    # ---- 4. 自动生成图表 ----
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    chart_dir = out / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    chart_paths: list[str] = []

    # 4a. 时间折线图（如存在时间列）
    tc = time_column or _detect_time_column(df)
    vc_time = _detect_value_column(df)
    if tc and vc_time and tc in df.columns and vc_time in df.columns:
        # 对时间列做解析 + 按时间聚合
        df_time = df.copy()
        try:
            df_time[tc] = pd.to_datetime(df_time[tc])
            df_agg = df_time.groupby(tc)[vc_time].sum().reset_index()
            chart_path = str(chart_dir / f"chart_line_trend_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
            line_chart(df_agg, x_col=tc, y_col=vc_time, title=f"{vc_time}时间趋势", output_path=chart_path)
            chart_paths.append(chart_path)
        except Exception:
            pass  # 图表生成失败不阻断整体流程

    # 4b. 类别柱状图（如存在合适类别列）
    cat_col = _detect_category_column(df)
    vc_bar = _detect_value_column(df)
    if cat_col and vc_bar and cat_col in df.columns and vc_bar in df.columns and cat_col != tc:
        try:
            df_agg = df.groupby(cat_col)[vc_bar].sum().reset_index()
            chart_path = str(chart_dir / f"chart_bar_compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
            bar_chart(df_agg, x_col=cat_col, y_col=vc_bar, title=f"各{cat_col}{vc_bar}对比", output_path=chart_path)
            chart_paths.append(chart_path)
        except Exception:
            pass

    # ---- 5. 结论生成 ----
    conclusions = _generate_conclusions(quality_report, eda_summary)

    # ---- 6. 构建报告 ----
    report_content = _build_analysis_report(
        file_path=file_path,
        df=df,
        quality_report=quality_report,
        eda_summary=eda_summary,
        chart_paths=chart_paths,
        conclusions=conclusions,
    )

    # ---- 7. 写入报告 ----
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = out / f"analysis_{ts}.md"
    report_path.write_text(report_content, encoding="utf-8")

    return str(report_path.resolve())

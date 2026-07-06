"""图表模板模块 — 提供 5 种 Plotly 交互式图表生成函数。

每个函数签名一致：
    Args:
        df:          pandas DataFrame，数据源
        x_col:       X 轴列名
        y_col:       Y 轴列名
        title:       图表标题（中文）
        output_path: HTML 输出路径（相对或绝对）

    Returns:
        str: 写入的 HTML 文件路径（同 output_path）

约定：
    - 输出目录不存在时自动创建
    - 图表尺寸 900×600
    - 使用 plotly.io.write_html 输出完整 HTML（含 JS CDN）
    - 不依赖 kaleido（禁止静态图片导出）
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

_CHART_WIDTH = 900
_CHART_HEIGHT = 600


def _ensure_output_dir(output_path: str) -> None:
    """确保输出目录存在，不存在则自动创建。

    Args:
        output_path: 输出文件路径
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 5 种图表模板
# ---------------------------------------------------------------------------


def bar_chart(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    output_path: str,
) -> str:
    """类别对比柱状图。

    适用场景：不同类别（产品/区域/部门）的指标对比。

    Args:
        df:          数据源
        x_col:       类别列名（X 轴）
        y_col:       数值列名（Y 轴）
        title:       图表标题
        output_path: HTML 输出路径

    Returns:
        HTML 文件路径
    """
    _ensure_output_dir(output_path)

    fig = go.Figure(
        data=[go.Bar(x=df[x_col], y=df[y_col], marker_color="#1f77b4")],
    )

    fig.update_layout(
        title=title,
        xaxis_title=x_col,
        yaxis_title=y_col,
        width=_CHART_WIDTH,
        height=_CHART_HEIGHT,
        template="plotly_white",
    )

    pio.write_html(fig, file=output_path, auto_open=False)
    return output_path


def line_chart(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    output_path: str,
) -> str:
    """时间序列折线图。

    适用场景：随时间变化的趋势（销量/收入/库存）。

    Args:
        df:          数据源
        x_col:       时间/顺序列名（X 轴）
        y_col:       数值列名（Y 轴）
        title:       图表标题
        output_path: HTML 输出路径

    Returns:
        HTML 文件路径
    """
    _ensure_output_dir(output_path)

    fig = go.Figure(
        data=[
            go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="lines",
                line=dict(color="#1f77b4", width=2),
                marker=dict(size=6),
            ),
        ],
    )

    fig.update_layout(
        title=title,
        xaxis_title=x_col,
        yaxis_title=y_col,
        width=_CHART_WIDTH,
        height=_CHART_HEIGHT,
        template="plotly_white",
    )

    pio.write_html(fig, file=output_path, auto_open=False)
    return output_path


def histogram_chart(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    output_path: str,
) -> str:
    """数值分布直方图。

    适用场景：查看数值列的分布形态（价格分布/销量分布）。

    Note:
        y_col 在本图中用作可选的分组/颜色字段；
        如果 y_col 为空或不在 df.columns 中，仅按 x_col 绘制分布。

    Args:
        df:          数据源
        x_col:       数值列名（X 轴）
        y_col:       可选分组列名（color）；传空字符串则不分色
        title:       图表标题
        output_path: HTML 输出路径

    Returns:
        HTML 文件路径
    """
    _ensure_output_dir(output_path)

    # y_col 有值时用作颜色分组；否则仅单色直方图
    color_col = y_col if y_col and y_col in df.columns else None

    fig = px.histogram(
        df,
        x=x_col,
        color=color_col,
        nbins=30,
        title=title,
        width=_CHART_WIDTH,
        height=_CHART_HEIGHT,
        template="plotly_white",
    )

    fig.update_layout(
        xaxis_title=x_col,
        yaxis_title="频数",
    )

    pio.write_html(fig, file=output_path, auto_open=False)
    return output_path


def scatter_chart(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    output_path: str,
) -> str:
    """相关性散点图。

    适用场景：两个数值变量之间的关系（价格 vs 销量）。

    Args:
        df:          数据源
        x_col:       X 轴数值列名
        y_col:       Y 轴数值列名
        title:       图表标题
        output_path: HTML 输出路径

    Returns:
        HTML 文件路径
    """
    _ensure_output_dir(output_path)

    fig = go.Figure(
        data=[
            go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="markers",
                marker=dict(size=8, color="#1f77b4", opacity=0.6),
            ),
        ],
    )

    fig.update_layout(
        title=title,
        xaxis_title=x_col,
        yaxis_title=y_col,
        width=_CHART_WIDTH,
        height=_CHART_HEIGHT,
        template="plotly_white",
    )

    pio.write_html(fig, file=output_path, auto_open=False)
    return output_path


def heatmap_chart(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    output_path: str,
) -> str:
    """相关性矩阵热力图。

    适用场景：展示多列数值变量的两两相关系数。

    Note:
        x_col 和 y_col 在本图中不直接对应轴——
        函数自动对 df 的数值列计算相关系数矩阵。
        如需指定特定列，请在传入前对 df 做列筛选。

    Args:
        df:          数据源（将自动选取数值列计算 corr）
        x_col:       未直接使用（保留签名一致性）
        y_col:       未直接使用（保留签名一致性）
        title:       图表标题
        output_path: HTML 输出路径

    Returns:
        HTML 文件路径
    """
    _ensure_output_dir(output_path)

    # 选取数值列计算相关性矩阵
    numeric_df = df.select_dtypes(include=["number"])
    if numeric_df.empty:
        # 无数值列：生成空图但保留标题
        fig = go.Figure()
        fig.update_layout(
            title=f"{title}（无数值列，无法计算相关性）",
            width=_CHART_WIDTH,
            height=_CHART_HEIGHT,
            template="plotly_white",
        )
        pio.write_html(fig, file=output_path, auto_open=False)
        return output_path

    corr = numeric_df.corr(numeric_only=True)

    fig = px.imshow(
        corr,
        text_auto=".2f",
        color_continuous_scale="RdBu_r",
        zmin=-1,
        zmax=1,
        title=title,
        width=_CHART_WIDTH,
        height=_CHART_HEIGHT,
        template="plotly_white",
        aspect="auto",
    )

    fig.update_layout(
        xaxis_title="",
        yaxis_title="",
    )

    pio.write_html(fig, file=output_path, auto_open=False)
    return output_path

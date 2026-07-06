"""图表模板模块测试套件。

覆盖场景：
  1. bar_chart: 基本柱状图
  2. line_chart: 基本折线图
  3. histogram_chart: 基本直方图
  4. scatter_chart: 基本散点图
  5. heatmap_chart: 相关性热力图
  6. 空数据 DataFrame（不崩溃）
  7. 单列数据
  8. 大数据量（>10k 点，验证性能）
  9. 中文标题/轴标签
  10. 输出目录自动创建
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.chart_templates import (
    bar_chart,
    line_chart,
    histogram_chart,
    scatter_chart,
    heatmap_chart,
)


# ======================================================================
# 脚手架 — 临时输出目录
# ======================================================================


@pytest.fixture
def tmp_output_dir():
    """在系统临时目录下创建测试专用输出目录，测试后清理。"""
    with tempfile.TemporaryDirectory(prefix="chart_test_") as tmpdir:
        yield tmpdir


# ======================================================================
# 场景 1：柱状图
# ======================================================================


def test_bar_chart_basic(tmp_output_dir):
    """基本柱状图：类别 vs 数值，输出文件存在且可读。"""
    df = pd.DataFrame({
        "产品": ["A", "B", "C", "D"],
        "销量": [100, 200, 150, 80],
    })
    out = Path(tmp_output_dir) / "bar_basic.html"
    result = bar_chart(df, x_col="产品", y_col="销量", title="产品销量对比", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    assert out.stat().st_size > 0

    # 验证 HTML 包含关键内容
    content = out.read_text(encoding="utf-8")
    assert "产品销量对比" in content
    assert "Plotly" in content or "plotly" in content


# ======================================================================
# 场景 2：折线图
# ======================================================================


def test_line_chart_basic(tmp_output_dir):
    """时间序列折线图：日期 vs 数值。"""
    dates = pd.date_range("2026-01-01", periods=10, freq="ME")
    df = pd.DataFrame({
        "月份": dates,
        "收入": [1200, 1350, 1100, 1600, 1500, 1700, 1800, 1750, 1900, 2000],
    })
    out = Path(tmp_output_dir) / "line_basic.html"
    result = line_chart(df, x_col="月份", y_col="收入", title="月度收入趋势", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "月度收入趋势" in content


# ======================================================================
# 场景 3：直方图
# ======================================================================


def test_histogram_chart_basic(tmp_output_dir):
    """数值分布直方图。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "价格": np.random.normal(100, 15, 200),
    })
    out = Path(tmp_output_dir) / "hist_basic.html"
    result = histogram_chart(df, x_col="价格", y_col="", title="价格分布直方图", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "价格分布直方图" in content


def test_histogram_chart_with_color(tmp_output_dir):
    """直方图带颜色分组。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "价格": np.random.normal(100, 15, 200),
        "类别": np.random.choice(["A", "B", "C"], 200),
    })
    out = Path(tmp_output_dir) / "hist_color.html"
    result = histogram_chart(df, x_col="价格", y_col="类别", title="分品类价格分布", output_path=str(out))

    assert result == str(out)
    assert out.exists()


# ======================================================================
# 场景 4：散点图
# ======================================================================


def test_scatter_chart_basic(tmp_output_dir):
    """相关性散点图。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "广告费": np.random.uniform(100, 1000, 100),
        "销量": np.random.uniform(50, 500, 100),
    })
    out = Path(tmp_output_dir) / "scatter_basic.html"
    result = scatter_chart(df, x_col="广告费", y_col="销量", title="广告 vs 销量", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "广告 vs 销量" in content


# ======================================================================
# 场景 5：热力图
# ======================================================================


def test_heatmap_chart_basic(tmp_output_dir):
    """相关性热力图。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "A": np.random.normal(0, 1, 100),
        "B": np.random.normal(0, 1, 100),
        "C": np.random.normal(0, 1, 100),
        "D": np.random.normal(0, 1, 100),
    })
    out = Path(tmp_output_dir) / "heatmap_basic.html"
    result = heatmap_chart(df, x_col="", y_col="", title="变量相关性矩阵", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "变量相关性矩阵" in content


def test_heatmap_chart_no_numeric(tmp_output_dir):
    """热力图：无数字列时不崩溃。"""
    df = pd.DataFrame({
        "类别": ["X", "Y", "Z"],
        "名称": ["foo", "bar", "baz"],
    })
    out = Path(tmp_output_dir) / "heatmap_empty.html"
    result = heatmap_chart(df, x_col="", y_col="", title="空相关性矩阵", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "空相关性矩阵" in content


# ======================================================================
# 场景 6：空数据
# ======================================================================


def test_bar_chart_empty_dataframe(tmp_output_dir):
    """空 DataFrame 柱状图：应生成 HTML 不崩溃。"""
    df = pd.DataFrame({"产品": pd.Series([], dtype=str), "销量": pd.Series([], dtype=int)})
    out = Path(tmp_output_dir) / "bar_empty.html"
    result = bar_chart(df, x_col="产品", y_col="销量", title="空数据测试", output_path=str(out))

    assert result == str(out)
    assert out.exists()


def test_line_chart_empty_dataframe(tmp_output_dir):
    """空 DataFrame 折线图：不崩溃。"""
    df = pd.DataFrame({"日期": pd.Series([], dtype="datetime64[ns]"), "值": pd.Series([], dtype=float)})
    out = Path(tmp_output_dir) / "line_empty.html"
    result = line_chart(df, x_col="日期", y_col="值", title="空折线图", output_path=str(out))

    assert result == str(out)
    assert out.exists()


# ======================================================================
# 场景 7：单列数据
# ======================================================================


def test_bar_chart_single_row(tmp_output_dir):
    """单行数据柱状图：正常生成。"""
    df = pd.DataFrame({"产品": ["A"], "销量": [100]})
    out = Path(tmp_output_dir) / "bar_single.html"
    result = bar_chart(df, x_col="产品", y_col="销量", title="单行柱状图", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "单行柱状图" in content


def test_scatter_chart_single_point(tmp_output_dir):
    """单点散点图：正常生成。"""
    df = pd.DataFrame({"X": [5.0], "Y": [10.0]})
    out = Path(tmp_output_dir) / "scatter_single.html"
    result = scatter_chart(df, x_col="X", y_col="Y", title="单点散点图", output_path=str(out))

    assert result == str(out)
    assert out.exists()


# ======================================================================
# 场景 8：大数据量（>10k 点）
# ======================================================================


def test_line_chart_large_data(tmp_output_dir):
    """大数据量折线图（10k 点）：1 秒内完成。"""
    import time

    df = pd.DataFrame({
        "t": range(10_000),
        "v": np.sin(np.linspace(0, 10 * np.pi, 10_000)),
    })
    out = Path(tmp_output_dir) / "line_large.html"
    start = time.perf_counter()
    result = line_chart(df, x_col="t", y_col="v", title="大数据量折线图", output_path=str(out))
    elapsed = time.perf_counter() - start

    assert result == str(out)
    assert out.exists()
    assert elapsed < 5.0, f"大数据量图表生成超时：{elapsed:.2f}s"


# ======================================================================
# 场景 9：中文标题/轴标签
# ======================================================================


def test_chinese_title_and_labels(tmp_output_dir):
    """中文标题、轴标签、图例应正确出现在 HTML 中。"""
    df = pd.DataFrame({
        "月份": ["一月", "二月", "三月", "四月", "五月"],
        "销售额（万元）": [50, 65, 70, 60, 80],
    })
    out = Path(tmp_output_dir) / "bar_chinese.html"
    result = bar_chart(
        df,
        x_col="月份",
        y_col="销售额（万元）",
        title="2026 年第一季度销售报告",
        output_path=str(out),
    )

    assert result == str(out)
    content = out.read_text(encoding="utf-8")
    assert "2026 年第一季度销售报告" in content
    assert "月份" in content
    assert "销售额（万元）" in content


def test_line_chart_chinese(tmp_output_dir):
    """折线图中文内容验证。"""
    dates = pd.date_range("2026-01-01", periods=6, freq="ME")
    df = pd.DataFrame({"日期": dates, "库存周转率": [4.2, 3.8, 4.5, 4.1, 3.9, 4.3]})
    out = Path(tmp_output_dir) / "line_chinese.html"
    result = line_chart(df, x_col="日期", y_col="库存周转率", title="库存周转率趋势分析", output_path=str(out))

    assert result == str(out)
    content = out.read_text(encoding="utf-8")
    assert "库存周转率趋势分析" in content
    assert "库存周转率" in content


# ======================================================================
# 场景 10：输出目录自动创建
# ======================================================================


def test_output_dir_auto_create(tmp_output_dir):
    """输出目录不存在时自动创建。"""
    nested = Path(tmp_output_dir) / "deeply" / "nested" / "dir"
    out = nested / "chart.html"
    # 确保目录不存在
    assert not nested.exists()

    df = pd.DataFrame({"X": [1, 2, 3], "Y": [4, 5, 6]})
    result = line_chart(df, x_col="X", y_col="Y", title="自动建目录", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    assert nested.exists()


# ======================================================================
# 场景 11：histogram 带空 y_col 参数
# ======================================================================


def test_histogram_chart_empty_ycol(tmp_output_dir):
    """histogram 传入空字符串 y_col：退化为单色直方图。"""
    df = pd.DataFrame({"值": np.random.randn(50)})
    out = Path(tmp_output_dir) / "hist_noy.html"
    result = histogram_chart(df, x_col="值", y_col="", title="单色直方图", output_path=str(out))

    assert result == str(out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "单色直方图" in content


# ======================================================================
# 场景 12：heatmap 含 NaN 的 corr 矩阵
# ======================================================================


def test_heatmap_chart_with_nan(tmp_output_dir):
    """含 NaN 的数据集，corr 计算不崩溃。"""
    df = pd.DataFrame({
        "A": [1.0, 2.0, np.nan, 4.0, 5.0],
        "B": [5.0, np.nan, 3.0, 2.0, 1.0],
        "C": [1.0, 2.0, 3.0, 4.0, 5.0],
    })
    out = Path(tmp_output_dir) / "heatmap_nan.html"
    result = heatmap_chart(df, x_col="", y_col="", title="含 NaN 相关性", output_path=str(out))

    assert result == str(out)
    assert out.exists()


# ======================================================================
# 场景 13：全部 5 种图表都返回正确的返回类型
# ======================================================================


def test_all_charts_return_type(tmp_output_dir):
    """所有 5 种图表返回的路径与 output_path 一致。"""
    df = pd.DataFrame({"X": [1, 2, 3], "Y": [4, 5, 6]})

    charts = [
        ("bar", bar_chart),
        ("line", line_chart),
        ("hist", lambda d, x, y, t, o: histogram_chart(d, x, y, t, o)),
        ("scatter", scatter_chart),
        ("heatmap", lambda d, x, y, t, o: heatmap_chart(d, x, y, t, o)),
    ]

    for name, fn in charts:
        out = str(Path(tmp_output_dir) / f"all_{name}.html")
        result = fn(df, "X", "Y", f"{name} 图表", out)
        assert result == out, f"{name}: 返回值与 output_path 不一致"
        assert Path(out).exists(), f"{name}: 文件未创建"

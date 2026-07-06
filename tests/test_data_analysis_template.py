"""一键数据分析模板测试套件。

覆盖场景：
  1. 黄金路径（完整分析 + 报告文件生成）
  2. 数据质量差（大量缺失值，验证报告仍生成 + 结论含警告）
  3. 空 DataFrame
  4. 仅数值列（无类别列，不生成柱状图但不崩溃）
  5. 中文列名
  6. 时间列自动检测
  7. 类别列自动检测
  8. 结论生成规则覆盖
  9. EDA 统计计算正确性
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.templates.data_analysis import (
    run_analysis,
    _compute_eda_summary,
    _generate_conclusions,
    _detect_time_column,
    _detect_category_column,
    _detect_value_column,
    _build_analysis_report,
)


# ======================================================================
# 脚手架
# ======================================================================


@pytest.fixture
def sample_csv():
    """创建测试用 CSV 文件。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write("date,sku,region,sales_volume,unit_price\n")
        f.write("2026-01-01,SKU-001,华北,100,25.5\n")
        f.write("2026-01-02,SKU-001,华北,120,25.5\n")
        f.write("2026-01-01,SKU-002,华东,80,30.0\n")
        f.write("2026-01-02,SKU-002,华东,95,30.0\n")
        f.write("2026-01-01,SKU-003,华南,200,15.0\n")
        f.write("2026-01-02,SKU-003,华南,180,15.0\n")
        csv_path = f.name

    yield csv_path
    Path(csv_path).unlink(missing_ok=True)


@pytest.fixture
def dirty_csv():
    """创建含大量缺失值的 CSV。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write("product,price,quantity\n")
        f.write("A,10.5,100\n")
        f.write("B,,200\n")
        f.write("C,15.0,\n")
        f.write("D,,80\n")
        f.write("E,8.99,\n")
        f.write("F,,\n")  # 全部缺失
        csv_path = f.name

    yield csv_path
    Path(csv_path).unlink(missing_ok=True)


@pytest.fixture
def chinese_csv():
    """创建含中文列名的 CSV。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
    ) as f:
        f.write("日期,产品,区域,销量,单价\n")
        f.write("2026-01-01,产品A,华北,100,25.5\n")
        f.write("2026-01-02,产品B,华东,80,30.0\n")
        f.write("2026-01-03,产品A,华南,120,25.5\n")
        f.write("2026-01-04,产品C,华北,95,40.0\n")
        csv_path = f.name

    yield csv_path
    Path(csv_path).unlink(missing_ok=True)


@pytest.fixture
def tmp_dir():
    """临时输出目录。"""
    with tempfile.TemporaryDirectory(prefix="analysis_test_") as tmp:
        yield tmp


# ======================================================================
# 场景 1：黄金路径 — 完整分析
# ======================================================================


def test_run_analysis_golden_path(sample_csv, tmp_dir):
    """正常数据 → 生成完整 Markdown 报告。"""
    report_path = run_analysis(sample_csv, output_dir=tmp_dir)

    assert Path(report_path).exists()
    content = Path(report_path).read_text(encoding="utf-8")

    # 验证报告结构
    assert "# 数据分析报告" in content
    assert "## 1. 数据概览" in content
    assert "## 2. 数据质量检查" in content
    assert "## 3. 统计摘要" in content
    assert "## 5. 结论与建议" in content

    # 验证数据内容
    assert "sales_volume" in content
    assert "unit_price" in content


# ======================================================================
# 场景 2：数据质量差
# ======================================================================


def test_run_analysis_dirty_data(dirty_csv, tmp_dir):
    """大量缺失 → 报告仍生成，结论含警告。"""
    report_path = run_analysis(dirty_csv, output_dir=tmp_dir)

    assert Path(report_path).exists()
    content = Path(report_path).read_text(encoding="utf-8")

    # 应有质量警告
    assert "## 2. 数据质量检查" in content
    # 综合评分应 < 100
    assert "数据质量评分" in content
    # 应有修复建议
    assert "缺失" in content


# ======================================================================
# 场景 3：空 DataFrame
# ======================================================================


def test_run_analysis_empty_csv(tmp_dir):
    """仅表头的空 CSV → 不崩溃，生成基本报告。"""
    csv_path = Path(tmp_dir) / "empty.csv"
    csv_path.write_text("col_a,col_b\n", encoding="utf-8")

    report_path = run_analysis(str(csv_path), output_dir=tmp_dir)

    assert Path(report_path).exists()
    content = Path(report_path).read_text(encoding="utf-8")
    assert "# 数据分析报告" in content


# ======================================================================
# 场景 4：仅数值列
# ======================================================================


def test_run_analysis_numeric_only(tmp_dir):
    """纯数值 DataFrame → 不生成类别图表但不崩溃。"""
    csv_path = Path(tmp_dir) / "numeric.csv"
    csv_path.write_text("a,b,c\n1.0,2.0,3.0\n4.0,5.0,6.0\n7.0,8.0,9.0\n", encoding="utf-8")

    report_path = run_analysis(str(csv_path), output_dir=tmp_dir)

    assert Path(report_path).exists()
    content = Path(report_path).read_text(encoding="utf-8")
    assert "## 3. 统计摘要" in content


# ======================================================================
# 场景 5：中文列名
# ======================================================================


def test_run_analysis_chinese_columns(chinese_csv, tmp_dir):
    """中文列名 CSV → 正常生成报告。"""
    report_path = run_analysis(chinese_csv, output_dir=tmp_dir)

    assert Path(report_path).exists()
    content = Path(report_path).read_text(encoding="utf-8")
    assert "## 1. 数据概览" in content
    assert "销量" in content


# ======================================================================
# 场景 6：时间列自动检测
# ======================================================================


def test_detect_time_column_by_name():
    """列名含 date → 自动识别。"""
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=3),
        "value": [1, 2, 3],
    })
    assert _detect_time_column(df) == "date"


def test_detect_time_column_by_chinese():
    """列名含 日期 → 自动识别。"""
    df = pd.DataFrame({
        "日期": ["2026-01-01", "2026-01-02"],
        "值": [1, 2],
    })
    assert _detect_time_column(df) == "日期"


def test_detect_time_column_none():
    """无日期列 → 返回 None。"""
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    assert _detect_time_column(df) is None


# ======================================================================
# 场景 7：类别列自动检测
# ======================================================================


def test_detect_category_column():
    """低基数字符串列 → 正确检测。"""
    df = pd.DataFrame({
        "region": ["华北", "华东", "华南", "华北", "华东"],
        "value": [1, 2, 3, 4, 5],
    })
    assert _detect_category_column(df) == "region"


def test_detect_category_column_none():
    """纯数值列 → 返回 None。"""
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    assert _detect_category_column(df) is None


# ======================================================================
# 场景 8：数值列自动检测
# ======================================================================


def test_detect_value_column_by_name():
    """列名含销量关键词 → 优先选中。"""
    df = pd.DataFrame({"a": [1.0], "销量": [100]})
    assert _detect_value_column(df) == "销量"


def test_detect_value_column_fallback():
    """无关键词 → 回退到第一数值列。"""
    df = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]})
    assert _detect_value_column(df) == "x"


# ======================================================================
# 场景 9：EDA 统计计算正确性
# ======================================================================


def test_eda_summary_numeric():
    """数值列统计量正确。"""
    df = pd.DataFrame({"price": [10.0, 20.0, 30.0]})
    summary = _compute_eda_summary(df)

    assert "price" in summary["numeric_stats"]
    stats = summary["numeric_stats"]["price"]
    assert stats["mean"] == 20.0
    assert stats["min"] == 10.0
    assert stats["max"] == 30.0
    assert stats["count"] == 3


def test_eda_summary_categorical():
    """类别列唯一值计数正确。"""
    df = pd.DataFrame({"cat": ["A", "B", "A", "C"]})
    summary = _compute_eda_summary(df)

    assert "cat" in summary["categorical_overview"]
    assert summary["categorical_overview"]["cat"]["unique_count"] == 3


# ======================================================================
# 场景 10：结论生成 — 高质量数据
# ======================================================================


def test_generate_conclusions_high_quality():
    """评分 ≥ 90 → 正面结论。"""
    quality = {
        "overall_score": 95,
        "total_rows": 100,
        "columns": [],
        "duplicate_rate": 0.0,
        "recommendations": [],
    }
    eda = {"numeric_stats": {}, "categorical_overview": {}}
    conclusions = _generate_conclusions(quality, eda)

    assert any("良好" in c for c in conclusions)
    assert len(conclusions) >= 1


def test_generate_conclusions_low_quality():
    """评分 < 70 → 严重警告。"""
    quality = {
        "overall_score": 45,
        "total_rows": 100,
        "columns": [
            {"name": "col_a", "dtype": "str", "missing_rate": 0.35,
             "missing_level": "high", "outlier_count": 10, "type_conflict": True},
        ],
        "duplicate_rate": 0.15,
        "recommendations": ["建议去重"],
    }
    eda = {"numeric_stats": {}, "categorical_overview": {}}
    conclusions = _generate_conclusions(quality, eda)

    assert any("清洗" in c or "质量" in c for c in conclusions)


# ======================================================================
# 场景 11：图表生成（golden path 带图表）
# ======================================================================


def test_run_analysis_generates_charts(sample_csv, tmp_dir):
    """正常数据应生成时间折线图。"""
    report_path = run_analysis(sample_csv, output_dir=tmp_dir)
    content = Path(report_path).read_text(encoding="utf-8")

    # 检查是否有图表链接
    assert "## 4. 可视化图表" in content
    # 时间列 date 应被检测并生成折线图
    assert "chart_line_trend" in content or "chart_bar" in content

    # 验证 HTML 文件实际存在
    chart_dir = Path(tmp_dir) / "charts"
    html_files = list(chart_dir.glob("*.html")) if chart_dir.exists() else []
    assert len(html_files) >= 1, f"未生成图表文件，chart_dir={chart_dir}"


# ======================================================================
# 场景 12：_build_analysis_report 结构完整性
# ======================================================================


def test_build_report_structure():
    """_build_analysis_report 生成的 Markdown 结构完整。"""
    df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    quality = {
        "overall_score": 100, "columns": [],
        "duplicate_rate": 0.0, "recommendations": [],
    }
    eda = {"numeric_stats": {}, "categorical_overview": {}}
    charts = ["reports/charts/test.html"]
    conclusions = ["测试结论"]

    report = _build_analysis_report("test.csv", df, quality, eda, charts, conclusions)

    assert "# 数据分析报告" in report
    assert "## 1. 数据概览" in report
    assert "## 2. 数据质量检查" in report
    assert "## 3. 统计摘要" in report
    assert "## 4. 可视化图表" in report
    assert "## 5. 结论与建议" in report
    assert "test.html" in report
    assert "测试结论" in report


# ======================================================================
# 场景 13：不支持的文件格式
# ======================================================================


def test_unsupported_file_format():
    """非 CSV/Excel 文件 → ValueError。"""
    with pytest.raises(ValueError, match="不支持"):
        run_analysis("data/test.json", output_dir="/tmp")

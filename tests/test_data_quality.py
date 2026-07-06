"""数据质量检测模块测试套件。

覆盖场景：
  1. 正常数据（无问题）
  2. 高缺失率（一列 50% 缺失）
  3. 异常值（数值列含极值 99999）
  4. 混合类型（同一列含 "123" 和 "abc"）
  5. 重复行（10% 重复）
  6. 空 DataFrame
  7. 类别列低频异常值
  8. sales.csv 真实数据检出率验证
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.data_quality import run_quality_check


# ======================================================================
# 场景 1：正常数据（无问题）
# ======================================================================

def test_normal_data_no_issues():
    """正常数据应返回 high score，无异常值、无缺失。"""
    df = pd.DataFrame({
        "product": ["A", "B", "C", "D", "E"],
        "price": [10.5, 20.0, 15.75, 8.99, 12.50],
        "quantity": [100, 200, 150, 80, 120],
    })
    report = run_quality_check(df)

    assert report["total_rows"] == 5
    assert report["total_columns"] == 3
    assert report["overall_score"] >= 95
    assert report["duplicate_rows"] == 0
    assert report["duplicate_rate"] == 0.0

    for col in report["columns"]:
        assert col["missing_rate"] == 0.0
        assert col["missing_level"] == "low"
        assert col["outlier_count"] == 0
        assert col["outlier_examples"] == []
        assert col["type_conflict"] is False


# ======================================================================
# 场景 2：高缺失率
# ======================================================================

def test_high_missing_rate():
    """一列 50% 缺失应被标记为 high level，score 显著降低。"""
    df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5, 6],
        "value": [10.0, None, 30.0, None, 50.0, None],  # 50% missing
    })
    report = run_quality_check(df)

    col_value = next(c for c in report["columns"] if c["name"] == "value")
    assert col_value["missing_rate"] == pytest.approx(0.5, abs=0.01)
    assert col_value["missing_level"] == "high"

    assert report["overall_score"] < 90  # 应有扣分
    assert any("缺失率" in r for r in report["recommendations"])


# ======================================================================
# 场景 3：异常值（数值列含极值）
# ======================================================================

def test_outlier_detection_numeric():
    """IQR 法应检出 99999 为异常值。"""
    np.random.seed(42)
    normal_data = np.random.normal(100, 10, 50).tolist()
    # 注入 3 个极端异常值
    outlier_data = normal_data + [99999, -100, 99999]

    df = pd.DataFrame({"score": outlier_data})
    report = run_quality_check(df)

    col_score = next(c for c in report["columns"] if c["name"] == "score")
    assert col_score["outlier_count"] >= 3  # 至少检出 3 个
    # 异常值示例应包含极端值
    assert any(abs(v) > 1000 for v in col_score["outlier_examples"])


# ======================================================================
# 场景 4：混合类型（同一列含数值和字符串）
# ======================================================================

def test_mixed_type_detection():
    """含 "123" 和 "abc" 的 object 列应被标记为 mixed。"""
    df = pd.DataFrame({
        "raw_field": ["123", "456", "abc", "789", "def"],
    })
    report = run_quality_check(df)

    col_raw = next(c for c in report["columns"] if c["name"] == "raw_field")
    assert col_raw["type_conflict"] is True
    assert any("混合类型" in r or "mixed" in r.lower() for r in report["recommendations"])


# ======================================================================
# 场景 5：重复行（10% 重复）
# ======================================================================

def test_duplicate_rows():
    """10 行中 1 行重复应被正确检出。"""
    base = pd.DataFrame({
        "x": [1, 2, 3, 4, 5, 6, 7, 8, 9],
        "y": [10, 20, 30, 40, 50, 60, 70, 80, 90],
    })
    # 复制第 0 行追加 → 10% 重复
    dup_row = base.iloc[[0]]
    df = pd.concat([base, dup_row], ignore_index=True)

    report = run_quality_check(df)
    assert report["duplicate_rows"] == 1
    assert report["duplicate_rate"] == pytest.approx(0.1, abs=0.01)
    assert any("重复" in r for r in report["recommendations"])


# ======================================================================
# 场景 6：空 DataFrame
# ======================================================================

def test_empty_dataframe():
    """空 DataFrame 不应崩溃，report 字段完整。"""
    df = pd.DataFrame()
    report = run_quality_check(df)

    assert report["total_rows"] == 0
    assert report["total_columns"] == 0
    assert report["columns"] == []
    assert report["duplicate_rows"] == 0
    assert report["overall_score"] == 100  # 空数据无缺陷
    assert isinstance(report["recommendations"], list)


# ======================================================================
# 场景 7：类别列低频异常值
# ======================================================================

def test_categorical_rare_values():
    """出现次数 <= 2 的类别值应被标记为 suspicious 异常。"""
    df = pd.DataFrame({
        "region": ["华东"] * 20 + ["华南"] * 15 + ["西北"] * 2 + ["海外"],
    })
    report = run_quality_check(df)

    col_region = next(c for c in report["columns"] if c["name"] == "region")
    # 西北(2次) + 海外(1次) = 2 个低频类别的值
    assert col_region["outlier_count"] >= 1
    examples = col_region["outlier_examples"]
    assert "海外" in examples or "西北" in examples


# ======================================================================
# 场景 8：sales.csv 真实数据检出率验证
# ======================================================================

def test_sales_csv_detection_rate():
    """用 sales.csv 测试，验证检出人工注入的缺失值 + 异常值。

    sales.csv 包含：
      - ~10% 缺失值（sales_volume 列有 12 处空值，120 行中 ~10%）
      - 至少 4-5 个异常值（862, 1176, 1460, 1167, 1357 等在 sales_volume 和 unit_price 中）
    """
    csv_path = PROJECT_ROOT / "workspace" / "data" / "sales.csv"
    if not csv_path.exists():
        pytest.skip(f"sales.csv not found at {csv_path}")

    df = pd.read_csv(csv_path)
    report = run_quality_check(df)

    # 验证数据维度
    assert report["total_rows"] == 120
    assert report["total_columns"] == 5

    # 验证缺失值检出
    col_sales = next(c for c in report["columns"] if c["name"] == "sales_volume")
    # sales_volume 应有约 12 处缺失 (10%)
    assert col_sales["missing_rate"] >= 0.05, (
        f"Expected >=5% missing rate in sales_volume, got {col_sales['missing_rate']:.2%}"
    )
    assert col_sales["missing_level"] in ("medium", "high")

    # 验证异常值检出 — 至少检出 862, 1176, 1460, 1167, 1357 中的 4 个（80%）
    total_outliers = sum(c["outlier_count"] for c in report["columns"])
    assert total_outliers >= 4, (
        f"Expected >=4 outliers detected, got {total_outliers}"
    )

    # 验证综合评分 < 100（有质量问题）
    assert report["overall_score"] < 100

    # recommendations 应包含缺失值修复建议
    assert len(report["recommendations"]) > 0


# ======================================================================
# 场景 9：所有列均为正常的边界情况
# ======================================================================

def test_all_columns_clean():
    """全部列无缺失、无异常、无重复、无类型冲突时应为满分。"""
    df = pd.DataFrame({
        "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        "b": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    })
    report = run_quality_check(df)

    assert report["overall_score"] == 100
    for col in report["columns"]:
        assert col["outlier_count"] == 0
        assert col["missing_rate"] == 0.0
        assert col["type_conflict"] is False


# ======================================================================
# 场景 10：纯数值 DataFrame 包含缺失 + 异常值的综合场景
# ======================================================================

def test_combined_missing_and_outliers():
    """同时存在缺失值和异常值的综合检测。"""
    df = pd.DataFrame({
        "temperature": [25.0, 26.5, None, 24.0, 99.9, 25.5, None, 26.0, -50.0, 25.0],
        "humidity": [60, 62, 58, None, 61, 59, 60, 61, None, 63],
    })
    report = run_quality_check(df)

    # temperature 应检出异常值（99.9 和 -50.0）
    col_temp = next(c for c in report["columns"] if c["name"] == "temperature")
    assert col_temp["outlier_count"] >= 2
    assert col_temp["missing_rate"] == pytest.approx(0.2, abs=0.01)

    # humidity 应有缺失
    col_hum = next(c for c in report["columns"] if c["name"] == "humidity")
    assert col_hum["missing_rate"] == pytest.approx(0.2, abs=0.01)

    # 综合评分应被扣分
    assert report["overall_score"] < 80
    assert len(report["recommendations"]) >= 2

"""数据质量自动检测引擎。

提供 run_quality_check() 函数，对 pandas DataFrame 进行多维质量检测：
  - 缺失值检测（每列缺失率 + 风险等级）
  - 异常值检测（数值列 IQR 法 + 类别列低频异常）
  - 类型冲突检测（object 列混合类型识别）
  - 重复行检测
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Missing value detection
# ---------------------------------------------------------------------------


def _check_missing(df: pd.DataFrame) -> dict:
    """检测每列的缺失值情况。

    Args:
        df: 输入 DataFrame

    Returns:
        dict，key 为列名，value 为 {"count": int, "rate": float, "level": str}
    """
    result: dict = {}
    total_rows = len(df)
    for col in df.columns:
        missing_count = int(df[col].isnull().sum())
        rate = missing_count / total_rows if total_rows > 0 else 0.0
        if rate > 0.20:
            level = "high"
        elif rate >= 0.05:
            level = "medium"
        else:
            level = "low"
        result[col] = {"count": missing_count, "rate": round(rate, 4), "level": level}
    return result


# ---------------------------------------------------------------------------
# Outlier detection
# ---------------------------------------------------------------------------


def _check_outliers_numeric(series: pd.Series) -> dict:
    """IQR 法检测数值列的异常值。

    Args:
        series: 数值型 pandas Series

    Returns:
        {"count": int, "examples": list} — 异常值数量和代表性示例
    """
    clean = series.dropna()
    if len(clean) == 0:
        return {"count": 0, "examples": []}

    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    mask = (clean < lower) | (clean > upper)
    outlier_values = clean[mask]
    count = len(outlier_values)

    # 取最多 5 个示例，按偏离程度排序
    if count > 0:
        center = clean.median()
        deviations = (outlier_values - center).abs()
        top_indices = deviations.nlargest(min(5, count)).index
        examples = [round(float(outlier_values.loc[i]), 2) for i in top_indices]
    else:
        examples = []

    return {"count": count, "examples": examples}


def _check_outliers_categorical(series: pd.Series) -> dict:
    """频率异常检测类别列的 suspicious 值。

    出现次数 <= 2 的值标记为 suspicious。
    仅当列中至少存在一个高频值（出现 >2 次）时才进行检测，
    避免高基数列（如产品名/ID）下所有值都被误判为异常。

    Args:
        series: 类别型 pandas Series

    Returns:
        {"count": int, "examples": list}
    """
    clean = series.dropna()
    if len(clean) == 0:
        return {"count": 0, "examples": []}

    value_counts = clean.value_counts()

    # 仅当存在高频值（>2次）时才检测低频异常
    # 否则说明列本质上是高基数列（如产品名、ID），每个值都稀疏是正常的
    if (value_counts > 2).sum() == 0:
        return {"count": 0, "examples": []}
        return {"count": 0, "examples": []}

    rare_mask = value_counts <= 2
    rare_values = value_counts[rare_mask]
    count = len(rare_values)
    examples = list(rare_values.index[:5]) if count > 0 else []

    return {"count": count, "examples": examples}


def _check_outliers(df: pd.DataFrame) -> dict:
    """检测所有列的异常值。

    数值列使用 IQR 法，类别列（object/str/category）使用频率异常检测。

    Args:
        df: 输入 DataFrame

    Returns:
        dict，key 为列名，value 为 {"count": int, "examples": list}
    """
    result: dict = {}
    for col in df.columns:
        series = df[col]
        dtype = series.dtype
        # 判断是否为数值型
        if pd.api.types.is_numeric_dtype(dtype):
            result[col] = _check_outliers_numeric(series)
        elif pd.api.types.is_object_dtype(dtype) or pd.api.types.is_string_dtype(dtype) or isinstance(dtype, pd.CategoricalDtype):
            result[col] = _check_outliers_categorical(series)
        else:
            result[col] = {"count": 0, "examples": []}
    return result


# ---------------------------------------------------------------------------
# Type conflict detection
# ---------------------------------------------------------------------------


def _check_type_conflicts(df: pd.DataFrame) -> dict:
    """检测 object 列中的混合类型。

    对每列 object 尝试 pd.to_numeric(errors='coerce')，
    若部分成功、部分失败则标记为 mixed。

    Args:
        df: 输入 DataFrame

    Returns:
        dict，key 为列名，value 为 {"is_mixed": bool, "detail": str}
    """
    result: dict = {}
    for col in df.columns:
        series = df[col]
        is_mixed = False
        detail = "homogeneous"
        dtype_str = str(series.dtype)

        # 仅对 object 或 string 类型检查混合
        if pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
            clean = series.dropna()
            if len(clean) == 0:
                result[col] = {"is_mixed": False, "detail": "empty"}
                continue

            numeric_converted = pd.to_numeric(clean, errors="coerce")
            success_mask = numeric_converted.notna()
            success_count = success_mask.sum()
            total_count = len(clean)

            if 0 < success_count < total_count:
                is_mixed = True
                detail = (
                    f"mixed: {success_count}/{total_count} numeric, "
                    f"{total_count - success_count}/{total_count} non-numeric"
                )
            elif success_count == total_count:
                detail = "all numeric convertible"
            else:
                detail = "all non-numeric"
        else:
            detail = f"typed as {dtype_str}"

        result[col] = {"is_mixed": is_mixed, "detail": detail}
    return result


# ---------------------------------------------------------------------------
# Duplicate row detection
# ---------------------------------------------------------------------------


def _check_duplicates(df: pd.DataFrame) -> dict:
    """检测重复行。

    Args:
        df: 输入 DataFrame

    Returns:
        {"count": int, "rate": float, "indexes": list}
    """
    total_rows = len(df)
    dup_mask = df.duplicated(keep="first")
    dup_count = int(dup_mask.sum())
    dup_rate = dup_count / total_rows if total_rows > 0 else 0.0
    dup_indexes = [int(i) for i in df.index[dup_mask].tolist()[:5]]

    return {"count": dup_count, "rate": round(dup_rate, 4), "indexes": dup_indexes}


# ---------------------------------------------------------------------------
# Overall score computation
# ---------------------------------------------------------------------------


def _compute_score(
    missing_info: dict,
    outlier_info: dict,
    type_conflict_info: dict,
    dup_info: dict,
    total_rows: int,
    total_cols: int,
) -> int:
    """根据各维度检测结果计算综合质量评分。

    评分规则：
      - 起始 100 分
      - 缺失值扣分：high 每列 -15，medium 每列 -8，low 每列 -2
      - 异常值扣分：每 1% 异常值率 -1 分
      - 类型冲突扣分：每列 mixed -10
      - 重复行扣分：每 1% 重复率 -1 分
      - 最低 0 分

    Args:
        missing_info: _check_missing 返回结果
        outlier_info: _check_outliers 返回结果
        type_conflict_info: _check_type_conflicts 返回结果
        dup_info: _check_duplicates 返回结果
        total_rows: 总行数
        total_cols: 总列数

    Returns:
        0-100 的整数评分
    """
    score = 100.0

    # Missing values deduction
    for col_info in missing_info.values():
        level = col_info["level"]
        if level == "high":
            score -= 15
        elif level == "medium":
            score -= 8
        elif level == "low" and col_info["rate"] > 0:
            score -= 2

    # Outlier deduction
    total_outliers = sum(info["count"] for info in outlier_info.values())
    if total_rows > 0:
        outlier_pct = (total_outliers / total_rows) * 100
        score -= outlier_pct  # 1% per percentage point

    # Type conflict deduction
    mixed_cols = sum(1 for info in type_conflict_info.values() if info["is_mixed"])
    score -= mixed_cols * 10

    # Duplicate deduction
    dup_rate = dup_info["rate"]
    score -= dup_rate * 100  # 1% per percentage point

    return max(0, int(round(score)))


# ---------------------------------------------------------------------------
# Recommendation generation
# ---------------------------------------------------------------------------


def _generate_recommendations(
    columns: list[dict],
    missing_info: dict,
    outlier_info: dict,
    type_conflict_info: dict,
    dup_info: dict,
) -> list[str]:
    """根据检测结果生成中文修复建议。

    Args:
        columns: 已构建的列报告列表
        missing_info: 缺失值检测结果
        outlier_info: 异常值检测结果
        type_conflict_info: 类型冲突检测结果
        dup_info: 重复行检测结果

    Returns:
        中文建议字符串列表
    """
    recs: list[str] = []

    for col_entry in columns:
        name = col_entry["name"]
        # Missing value recommendations
        if col_entry["missing_level"] == "high":
            recs.append(
                f"列「{name}」缺失率高达 {col_entry['missing_rate']:.0%}，"
                f"建议评估该列是否可用，或考虑删除该列"
            )
        elif col_entry["missing_level"] == "medium":
            if pd.api.types.is_numeric_dtype(col_entry["dtype"]):
                recs.append(f"建议对「{name}」列的缺失值用中位数填充")
            else:
                recs.append(f"建议对「{name}」列的缺失值用众数填充")

        # Outlier recommendations
        if col_entry["outlier_count"] > 0:
            examples_str = "、".join(str(e) for e in col_entry.get("outlier_examples", [])[:3])
            recs.append(
                f"列「{name}」存在 {col_entry['outlier_count']} 个异常值"
                f"（如 {examples_str}），可能是录入错误，建议核查"
            )

    # Type conflict recommendations
    for col_name, info in type_conflict_info.items():
        if info["is_mixed"]:
            recs.append(
                f"列「{col_name}」包含混合类型数据（{info['detail']}），"
                f"建议统一格式后重新导入"
            )

    # Duplicate recommendations
    if dup_info["count"] > 0:
        recs.append(
            f"数据集中存在 {dup_info['count']} 行重复数据（占比 {dup_info['rate']:.1%}），"
            f"建议使用 drop_duplicates() 去重"
        )

    return recs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_quality_check(df: pd.DataFrame) -> dict:
    """对 DataFrame 执行全面的数据质量检测。

    检测维度：
      1. 缺失值 — 每列缺失率 + high/medium/low 风险等级
      2. 异常值 — 数值列 IQR 法 + 类别列低频 suspicious
      3. 类型冲突 — object 列中数值/非数值混合
      4. 重复行 — 完全重复的行

    Args:
        df: 待检测的 pandas DataFrame

    Returns:
        数据质量报告 dict:
        {
            "overall_score": int,       # 0-100 综合评分
            "total_rows": int,
            "total_columns": int,
            "columns": [               # 每列详细报告
                {
                    "name": str,
                    "dtype": str,
                    "missing_rate": float,
                    "missing_level": str,   # "high" | "medium" | "low"
                    "outlier_count": int,
                    "outlier_examples": list,
                    "type_conflict": bool,
                    "duplicate_count": int,
                }
            ],
            "duplicate_rows": int,
            "duplicate_rate": float,
            "recommendations": [str],  # 中文修复建议
        }

    Example:
        >>> import pandas as pd
        >>> from src.domain.data_quality import run_quality_check
        >>> df = pd.read_csv("data/sales.csv")
        >>> report = run_quality_check(df)
        >>> print(report["overall_score"])
    """
    total_rows = len(df)
    total_cols = len(df.columns)

    # ---- 1. Missing values ----
    missing_info = _check_missing(df)

    # ---- 2. Outliers ----
    outlier_info = _check_outliers(df)

    # ---- 3. Type conflicts ----
    type_conflict_info = _check_type_conflicts(df)

    # ---- 4. Duplicates ----
    dup_info = _check_duplicates(df)

    # ---- 5. Build per-column report ----
    columns_report: list[dict] = []
    for col in df.columns:
        series = df[col]
        dtype_str = str(series.dtype)

        col_entry: dict = {
            "name": col,
            "dtype": dtype_str,
            "missing_rate": missing_info[col]["rate"],
            "missing_level": missing_info[col]["level"],
            "outlier_count": outlier_info[col]["count"],
            "outlier_examples": outlier_info[col]["examples"],
            "type_conflict": type_conflict_info[col]["is_mixed"],
            "duplicate_count": dup_info["count"],
        }
        columns_report.append(col_entry)

    # ---- 6. Overall score ----
    overall_score = _compute_score(
        missing_info, outlier_info, type_conflict_info, dup_info,
        total_rows, total_cols,
    )

    # ---- 7. Recommendations ----
    recommendations = _generate_recommendations(
        columns_report, missing_info, outlier_info, type_conflict_info, dup_info,
    )

    return {
        "overall_score": overall_score,
        "total_rows": total_rows,
        "total_columns": total_cols,
        "columns": columns_report,
        "duplicate_rows": dup_info["count"],
        "duplicate_rate": dup_info["rate"],
        "recommendations": recommendations,
    }

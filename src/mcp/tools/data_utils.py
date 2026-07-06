"""数据类型推断辅助函数。

为 file_read_csv / file_read_excel 提供增强的类型检测能力：
- pandas dtype 到可读字符串的映射
- 百分比列检测
- 日期格式检测
- 混合类型检测
"""

import re
from typing import Any

import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# dtype 映射
# ---------------------------------------------------------------------------

# 常见日期格式正则（编译一次，复用）
_DATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),                   # YYYY-MM-DD
    re.compile(r"^\d{4}/\d{2}/\d{2}$"),                   # YYYY/MM/DD
    re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"), # YYYY-MM-DD HH:MM:SS
    re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$"), # YYYY/MM/DD HH:MM:SS
    re.compile(r"^\d{2}-\d{2}-\d{4}$"),                   # DD-MM-YYYY
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),                   # DD/MM/YYYY
    re.compile(r"^\d{4}\d{2}\d{2}$"),                     # YYYYMMDD
]

# 阈值：至少多少比例的非空值匹配日期格式才标记为 datetime
_DATETIME_MATCH_THRESHOLD = 0.7


def map_dtype_to_string(dtype: Any) -> str:
    """将 pandas dtype 映射为简洁的字符串标签。

    Args:
        dtype: pandas dtype 对象（如 np.dtype('int64')）

    Returns:
        简洁字符串，如 "int" / "float" / "str" / "datetime" / "bool" / "unknown"
    """
    dtype_str = str(dtype)

    if dtype_str.startswith("int") or dtype_str.startswith("uint"):
        return "int"
    elif dtype_str.startswith("float"):
        return "float"
    elif dtype_str.startswith("datetime"):
        return "datetime"
    elif dtype_str.startswith("bool"):
        return "bool"
    elif dtype_str in ("object", "str"):
        return "str"
    elif dtype_str.startswith("str") or dtype_str.startswith("String"):
        return "str"
    else:
        return "unknown"


def detect_percentage_column(series: pd.Series) -> bool:
    """检测字符串列中是否所有非空值都包含 '%' 符号。

    Args:
        series: pandas Series（通常为 object 类型）

    Returns:
        True 表示该列应为 percentage 类型
    """
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    # 所有非空值都必须包含 %
    return non_null.astype(str).str.contains("%").all()


def detect_datetime_column(series: pd.Series) -> bool:
    """检测字符串列中是否大部分非空值匹配常见日期格式。

    对每种预定义正则逐一尝试，取匹配比例最高的格式。

    Args:
        series: pandas Series（通常为 object 类型）

    Returns:
        True 表示该列应标记为 datetime 类型
    """
    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return False

    best_ratio = 0.0
    for pattern in _DATE_PATTERNS:
        match_count = non_null.str.match(pattern).sum()
        ratio = match_count / len(non_null)
        if ratio > best_ratio:
            best_ratio = ratio

    result = best_ratio >= _DATETIME_MATCH_THRESHOLD
    if result:
        logger.debug("检测到日期列: ratio={:.2%}", best_ratio)
    return result


def detect_mixed_column(series: pd.Series) -> bool:
    """检测列中是否同时包含数值和字符串（混合类型）。

    对 object 列尝试 pd.to_numeric(errors='coerce')：
    - 若部分值可转为数值、部分不可转，则标记为 mixed
    - 若全部可转或全部不可转，则不标记

    Args:
        series: pandas Series（通常为 object 类型）

    Returns:
        True 表示该列为 mixed 类型
    """
    non_null = series.dropna()
    if len(non_null) == 0:
        return False

    converted = pd.to_numeric(non_null, errors="coerce")
    nan_count_before = non_null.isna().sum()
    nan_count_after = converted.isna().sum()
    total = len(non_null)

    # 部分成功、部分失败 → mixed
    success_count = total - nan_count_after
    if 0 < success_count < total:
        logger.debug(
            "检测到混合类型列: total={}, numeric={}, str={}",
            total,
            success_count,
            total - success_count,
        )
        return True

    return False


def enhance_dtypes(df: pd.DataFrame) -> dict[str, str]:
    """对 DataFrame 的每一列进行增强类型推断。

    推断优先级（由高到低）：
      1. pandas 原生 datetime64 → "datetime"
      2. percentage 检测 → "percentage"
      3. 日期格式正则 → "datetime"
      4. 混合类型检测 → "mixed"
      5. 默认映射（int/float/bool/str/unknown）

    Args:
        df: pandas DataFrame（建议先调用 infer_objects() 后再传入）

    Returns:
        {"列名": "推断类型字符串", ...}
    """
    result: dict[str, str] = {}

    for col in df.columns:
        series = df[col]
        dtype_str = str(series.dtype)

        # 1. pandas 原生 datetime 类型 → 直接标记
        if dtype_str.startswith("datetime"):
            result[col] = "datetime"
            continue

        # 判断是否为类字符串列（pandas 3.0 StringDtype 或传统 object）
        is_string_col = dtype_str in ("object", "str") or dtype_str.startswith("str")

        # 2. percentage 检测（仅对字符串列）
        if is_string_col and detect_percentage_column(series):
            result[col] = "percentage"
            continue

        # 3. 日期格式正则检测（仅对字符串列）
        if is_string_col and detect_datetime_column(series):
            result[col] = "datetime"
            continue

        # 4. 混合类型检测（仅对字符串列）
        if is_string_col and detect_mixed_column(series):
            result[col] = "mixed"
            continue

        # 5. 默认映射
        result[col] = map_dtype_to_string(series.dtype)

    return result


def compute_missing_summary(df: pd.DataFrame) -> dict[str, int]:
    """计算每列的缺失值数量。

    Args:
        df: pandas DataFrame

    Returns:
        {"列名": 缺失值数量, ...}，仅包含有缺失值的列
    """
    missing: dict[str, int] = {}
    for col in df.columns:
        count = df[col].isna().sum()
        if count > 0:
            missing[col] = int(count)
    return missing

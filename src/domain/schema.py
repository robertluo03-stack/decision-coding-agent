"""领域模型 Schema 定义。

定义优化模板的输入输出数据结构。
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Union


class TemplateType(str, Enum):
    """支持的优化模板类型。"""
    EOQ = "inventory_eoq"
    SAFETY_STOCK = "safety_stock"
    DEMAND_FORECAST = "demand_forecast"


class DataFormat(str, Enum):
    """数据文件格式。"""
    CSV = "csv"
    EXCEL = "xlsx"
    JSON = "json"
    PARQUET = "parquet"


@dataclass
class ColumnInfo:
    """CSV/DataFrame 列信息。"""
    name: str
    dtype: str
    null_count: int = 0
    null_ratio: float = 0.0


@dataclass
class DataProfile:
    """数据质量概要。"""
    file_path: str
    format: DataFormat
    row_count: int
    column_count: int
    columns: List[ColumnInfo]
    total_missing: int
    missing_ratio: float

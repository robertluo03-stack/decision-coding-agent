"""Week 3 Day 1：file_read_csv / file_read_excel 测试。

覆盖：
1. 正常 CSV 读取 + 类型推断（int/float/str/datetime/percentage/mixed）
2. 正常 Excel 读取 + 多 sheet
3. 越权路径拦截（../../etc/passwd）
4. 缺失值标记
5. 未知 sheet 报错
6. preview_rows 参数
7. data_utils 单元测试
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.mcp.tools.data_utils import (  # noqa: E402
    compute_missing_summary,
    detect_datetime_column,
    detect_mixed_column,
    detect_percentage_column,
    enhance_dtypes,
    map_dtype_to_string,
)
from src.mcp.tools.file_tools import (  # noqa: E402
    file_read_csv,
    file_read_excel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_workspace():
    """创建临时工作区，包含 data/ 子目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        yield Path(tmpdir)


def _write_csv(workspace: Path, filename: str, content: str) -> Path:
    """在 workspace/data/ 下写入 CSV 文件。"""
    path = workspace / "data" / filename
    path.write_text(content, encoding="utf-8")
    return path


def _write_excel(workspace: Path, filename: str, df) -> Path:
    """在 workspace/data/ 下写入 Excel 文件。"""
    import pandas as pd
    path = workspace / "data" / filename
    if isinstance(df, pd.DataFrame):
        df.to_excel(str(path), index=False, engine="openpyxl")
    else:
        # dict of sheet_name -> DataFrame
        with pd.ExcelWriter(str(path), engine="openpyxl") as writer:
            for sheet_name, sheet_df in df.items():
                sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
    return path


# ---------------------------------------------------------------------------
# 1. file_read_csv — 正常读取 + 类型推断
# ---------------------------------------------------------------------------

class TestFileReadCsv:
    """file_read_csv() 正常功能测试。"""

    def test_basic_csv_int_float_str(self, temp_workspace):
        """基本 CSV：int / float / str 列类型推断。"""
        _write_csv(temp_workspace, "test.csv", "name,age,score\nAlice,30,95.5\nBob,25,88.0\nCharlie,35,72.3\n")
        result = json.loads(file_read_csv("data/test.csv", workspace=str(temp_workspace)))
        assert result["columns"] == ["name", "age", "score"]
        assert result["shape"] == [3, 3]
        assert result["dtypes"]["age"] == "int"
        assert result["dtypes"]["score"] == "float"
        assert result["dtypes"]["name"] == "str"
        assert len(result["preview"]) == 3

    def test_csv_with_datetime_column(self, temp_workspace):
        """日期列应被检测为 datetime。"""
        _write_csv(temp_workspace, "dates.csv",
                   "event,date\nMeeting,2024-01-15\nWorkshop,2024-03-20\nHoliday,2024-07-04\n")
        result = json.loads(file_read_csv("data/dates.csv", workspace=str(temp_workspace)))
        assert result["dtypes"]["date"] == "datetime"

    def test_csv_with_percentage_column(self, temp_workspace):
        """百分比列应被检测为 percentage。"""
        _write_csv(temp_workspace, "pct.csv", "item,rate\nA,50%\nB,75%\nC,100%\n")
        result = json.loads(file_read_csv("data/pct.csv", workspace=str(temp_workspace)))
        assert result["dtypes"]["rate"] == "percentage"

    def test_csv_mixed_column(self, temp_workspace):
        """混合类型列（数值 + 字符串共存）应标记为 mixed。"""
        _write_csv(temp_workspace, "mixed.csv", "id,value\n1,100\n2,abc\n3,200\n")
        result = json.loads(file_read_csv("data/mixed.csv", workspace=str(temp_workspace)))
        assert result["dtypes"]["value"] == "mixed"
        assert result["dtypes"]["id"] == "int"

    def test_csv_preview_rows(self, temp_workspace):
        """preview_rows 应控制预览行数。"""
        rows = "\n".join(f"value{i}" for i in range(100))
        _write_csv(temp_workspace, "big.csv", f"col\n{rows}\n")
        result_default = json.loads(file_read_csv("data/big.csv", workspace=str(temp_workspace)))
        assert len(result_default["preview"]) == 5
        result10 = json.loads(file_read_csv("data/big.csv", preview_rows=10, workspace=str(temp_workspace)))
        assert len(result10["preview"]) == 10
        # >1000 行也只返回指定预览行
        rows_2000 = "\n".join(f"value{i}" for i in range(2000))
        _write_csv(temp_workspace, "huge.csv", f"col\n{rows_2000}\n")
        result_huge = json.loads(file_read_csv("data/huge.csv", workspace=str(temp_workspace)))
        assert len(result_huge["preview"]) == 5

    def test_csv_missing_values(self, temp_workspace):
        """缺失值应被正确统计。"""
        _write_csv(temp_workspace, "missing.csv", "name,age,city\nAlice,30,NYC\nBob,,LA\n,,Chicago\n")
        result = json.loads(file_read_csv("data/missing.csv", workspace=str(temp_workspace)))
        assert "name" in result["missing_summary"]
        assert result["missing_summary"]["name"] == 1
        assert result["missing_summary"]["age"] == 2
        assert "city" not in result["missing_summary"] or result["missing_summary"].get("city", 0) == 0

    def test_empty_csv(self, temp_workspace):
        """空 CSV（只有 header，无数据行）。"""
        _write_csv(temp_workspace, "empty.csv", "col1,col2\n")
        result = json.loads(file_read_csv("data/empty.csv", workspace=str(temp_workspace)))
        assert result["columns"] == ["col1", "col2"]
        assert result["shape"] == [0, 2]
        assert result["preview"] == []


# ---------------------------------------------------------------------------
# 2. file_read_excel — 正常读取
# ---------------------------------------------------------------------------

class TestFileReadExcel:
    """file_read_excel() 正常功能测试。"""

    def test_basic_excel(self, temp_workspace):
        """基本 Excel 读取。"""
        import pandas as pd
        df = pd.DataFrame({"product": ["A", "B", "C"], "price": [10, 20, 30], "qty": [100, 200, 150]})
        _write_excel(temp_workspace, "products.xlsx", df)
        result = json.loads(file_read_excel("data/products.xlsx", workspace=str(temp_workspace)))
        assert result["columns"] == ["product", "price", "qty"]
        assert result["shape"] == [3, 3]
        assert result["dtypes"]["price"] == "int"
        assert result["dtypes"]["product"] == "str"

    def test_excel_with_sheet_name(self, temp_workspace):
        """指定 sheet 名称读取。"""
        import pandas as pd
        sheets = {
            "Summary": pd.DataFrame({"metric": ["total", "avg"], "value": [1000, 50]}),
            "Details": pd.DataFrame({"item": ["a", "b"], "qty": [10, 20]}),
        }
        _write_excel(temp_workspace, "multi.xlsx", sheets)
        result = json.loads(file_read_excel("data/multi.xlsx", sheet_name="Details", workspace=str(temp_workspace)))
        assert result["columns"] == ["item", "qty"]
        assert result["shape"] == [2, 2]

    def test_excel_with_sheet_index(self, temp_workspace):
        """指定 sheet 索引读取。"""
        import pandas as pd
        sheets = {
            "First": pd.DataFrame({"a": [1, 2]}),
            "Second": pd.DataFrame({"b": [3, 4]}),
        }
        _write_excel(temp_workspace, "sheets.xlsx", sheets)
        result0 = json.loads(file_read_excel("data/sheets.xlsx", sheet_name=0, workspace=str(temp_workspace)))
        assert result0["columns"] == ["a"]
        result1 = json.loads(file_read_excel("data/sheets.xlsx", sheet_name=1, workspace=str(temp_workspace)))
        assert result1["columns"] == ["b"]

    def test_excel_unknown_sheet_name(self, temp_workspace):
        """不存在的 sheet 名称应报错。"""
        import pandas as pd
        df = pd.DataFrame({"x": [1]})
        _write_excel(temp_workspace, "single.xlsx", df)
        with pytest.raises(ValueError, match="不存在"):
            file_read_excel("data/single.xlsx", sheet_name="NoSuchSheet", workspace=str(temp_workspace))

    def test_excel_out_of_range_index(self, temp_workspace):
        """超出范围的 sheet 索引应报错。"""
        import pandas as pd
        df = pd.DataFrame({"x": [1]})
        _write_excel(temp_workspace, "single2.xlsx", df)
        with pytest.raises(ValueError, match="不存在"):
            file_read_excel("data/single2.xlsx", sheet_name=99, workspace=str(temp_workspace))

    def test_excel_missing_values(self, temp_workspace):
        """Excel 缺失值检测。"""
        import pandas as pd
        import numpy as np
        df = pd.DataFrame({"name": ["Alice", "Bob", None], "score": [95, None, 72]})
        _write_excel(temp_workspace, "missing.xlsx", df)
        result = json.loads(file_read_excel("data/missing.xlsx", workspace=str(temp_workspace)))
        assert "name" in result["missing_summary"]
        assert result["missing_summary"]["name"] == 1
        assert result["missing_summary"]["score"] == 1


# ---------------------------------------------------------------------------
# 3. 路径安全检查
# ---------------------------------------------------------------------------

class TestPathSecurity:
    """越权路径拦截测试。"""

    def test_parent_directory_traversal_csv(self, temp_workspace):
        r"""../../etc/passwd 路径应被拦截。"""
        with pytest.raises(ValueError, match=r"\.\."):
            file_read_csv("../../etc/passwd", workspace=str(temp_workspace))

    def test_parent_directory_traversal_excel(self, temp_workspace):
        r"""Excel 越权路径应被拦截。"""
        with pytest.raises(ValueError, match=r"\.\."):
            file_read_excel("../../etc/passwd", workspace=str(temp_workspace))

    def test_absolute_path_outside_workspace(self, temp_workspace):
        """绝对路径在 workspace 外应被拦截。"""
        with pytest.raises(ValueError, match="工作区"):
            file_read_csv("/etc/passwd", workspace=str(temp_workspace))


# ---------------------------------------------------------------------------
# 4. data_utils 单元测试
# ---------------------------------------------------------------------------

class TestDataUtils:
    """类型推断辅助函数单元测试。"""

    def test_map_dtype_int(self):
        assert map_dtype_to_string("int64") == "int"

    def test_map_dtype_float(self):
        assert map_dtype_to_string("float64") == "float"

    def test_map_dtype_str(self):
        assert map_dtype_to_string("object") == "str"

    def test_map_dtype_datetime(self):
        assert map_dtype_to_string("datetime64[ns]") == "datetime"

    def test_map_dtype_bool(self):
        assert map_dtype_to_string("bool") == "bool"

    def test_detect_percentage(self):
        import pandas as pd
        s = pd.Series(["50%", "75%", "100%"])
        assert bool(detect_percentage_column(s)) is True

    def test_detect_percentage_mixed(self):
        import pandas as pd
        s = pd.Series(["50%", "75", "100%"])
        assert bool(detect_percentage_column(s)) is False

    def test_detect_datetime(self):
        import pandas as pd
        s = pd.Series(["2024-01-15", "2024-03-20", "2024-07-04"])
        assert bool(detect_datetime_column(s)) is True

    def test_detect_datetime_not_enough(self):
        import pandas as pd
        s = pd.Series(["2024-01-15", "hello", "world", "bye"])
        assert bool(detect_datetime_column(s)) is False

    def test_detect_mixed(self):
        import pandas as pd
        s = pd.Series(["100", "abc", "200"])
        assert bool(detect_mixed_column(s)) is True

    def test_detect_mixed_all_numeric(self):
        import pandas as pd
        s = pd.Series(["100", "200", "300"])
        assert bool(detect_mixed_column(s)) is False

    def test_compute_missing_summary(self):
        import pandas as pd
        import numpy as np
        df = pd.DataFrame({"a": [1, np.nan, 3], "b": [np.nan, np.nan, 3], "c": [1, 2, 3]})
        missing = compute_missing_summary(df)
        assert missing["a"] == 1
        assert missing["b"] == 2
        assert "c" not in missing

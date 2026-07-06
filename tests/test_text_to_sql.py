"""Text-to-SQL 引擎测试套件。

覆盖场景：
  1. Schema 提取（extract_schema）
  2. SQL 安全检查（check_sql_safety）
  3. SQL 清理（_clean_sql）
  4. DuckDB 执行（_execute_sql）
  5. 非法 SQL 拦截
  6. 空结果处理
  7. 摘要生成（_generate_summary）
  8. 完整端到端（mock LLM）
"""

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.text_to_sql import (
    check_sql_safety,
    extract_schema,
    _clean_sql,
    _execute_sql,
    _generate_summary,
    _build_sql_prompt,
    _infer_dtype,
    _call_llm_for_sql,
    run_text_to_sql,
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
def sample_csv_chinese():
    """创建含中文列名的测试 CSV。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
    ) as f:
        f.write("日期,产品,区域,销量,单价\n")
        f.write("2026-01-01,产品A,华北,100,25.5\n")
        f.write("2026-01-02,产品B,华东,80,30.0\n")
        csv_path = f.name

    yield csv_path
    Path(csv_path).unlink(missing_ok=True)


@pytest.fixture
def tmp_output_dir():
    """临时输出目录。"""
    with tempfile.TemporaryDirectory(prefix="tts_test_") as tmpdir:
        yield tmpdir


# ======================================================================
# 场景 1：_infer_dtype 类型推断
# ======================================================================


def test_infer_dtype_integer():
    """整数列 → INTEGER。"""
    s = pd.Series([1, 2, 3], name="count")
    assert _infer_dtype(s) == "INTEGER"


def test_infer_dtype_float():
    """浮点列 → DOUBLE。"""
    s = pd.Series([1.5, 2.3, 3.7], name="price")
    assert _infer_dtype(s) == "DOUBLE"


def test_infer_dtype_varchar():
    """字符串列 → VARCHAR。"""
    s = pd.Series(["a", "b", "c"], name="name")
    assert _infer_dtype(s) == "VARCHAR"


def test_infer_dtype_date_by_name():
    """名字含 date 的列 → DATE。"""
    s = pd.Series(["2026-01-01", "2026-01-02"], name="date")
    assert _infer_dtype(s) == "DATE"


# ======================================================================
# 场景 2：extract_schema 从 CSV 生成 DDL
# ======================================================================


def test_extract_schema_basic(sample_csv):
    """基本 CSV → DDL 包含所有列和类型。"""
    ddl = extract_schema(sample_csv, table_name="sales")

    assert "CREATE TABLE sales" in ddl
    assert "date" in ddl
    assert "sku" in ddl
    assert "region" in ddl
    assert "sales_volume" in ddl
    assert "unit_price" in ddl
    # 数值列应推断为整数/浮点
    assert "INTEGER" in ddl or "BIGINT" in ddl or "DOUBLE" in ddl


def test_extract_schema_chinese_columns(sample_csv_chinese):
    """中文列名 CSV → DDL 用双引号包裹列名。"""
    ddl = extract_schema(sample_csv_chinese, table_name="data")

    assert "CREATE TABLE data" in ddl
    assert '"日期"' in ddl
    assert '"产品"' in ddl
    assert '"销量"' in ddl


# ======================================================================
# 场景 3：check_sql_safety SQL 安全检查
# ======================================================================


def test_safe_select():
    """普通 SELECT 应通过安全检查。"""
    is_safe, reason = check_sql_safety("SELECT * FROM data")
    assert is_safe
    assert reason is None


def test_safe_select_with_aggregation():
    """含聚合的 SELECT 应通过。"""
    is_safe, reason = check_sql_safety(
        'SELECT region, AVG(sales_volume) FROM data GROUP BY region'
    )
    assert is_safe


def test_dangerous_drop_table():
    """DROP TABLE 应被拦截。"""
    is_safe, reason = check_sql_safety("DROP TABLE data")
    assert not is_safe
    assert "DROP" in reason


def test_dangerous_delete():
    """DELETE 应被拦截。"""
    is_safe, reason = check_sql_safety("DELETE FROM data WHERE id = 1")
    assert not is_safe
    assert "DELETE" in reason


def test_dangerous_update():
    """UPDATE 应被拦截。"""
    is_safe, reason = check_sql_safety("UPDATE data SET col = 1")
    assert not is_safe
    assert "UPDATE" in reason


def test_dangerous_insert():
    """INSERT 应被拦截。"""
    is_safe, reason = check_sql_safety("INSERT INTO data VALUES (1, 'a')")
    assert not is_safe
    assert "INSERT" in reason


def test_dangerous_alter():
    """ALTER TABLE 应被拦截。"""
    is_safe, reason = check_sql_safety("ALTER TABLE data ADD COLUMN x INT")
    assert not is_safe
    assert "ALTER" in reason


def test_non_select_prefix():
    """不以 SELECT 开头的查询应被拦截。"""
    is_safe, reason = check_sql_safety("WITH cte AS (SELECT 1) SELECT * FROM cte")
    assert not is_safe
    assert "仅允许 SELECT" in reason


# ======================================================================
# 场景 4：_clean_sql 清理 LLM 输出
# ======================================================================


def test_clean_sql_markdown_fence():
    """去除 ```sql ... ``` 包装。"""
    raw = "```sql\nSELECT * FROM data;\n```"
    assert _clean_sql(raw) == "SELECT * FROM data"


def test_clean_sql_generic_fence():
    """去除 ``` ... ``` 包装。"""
    raw = "```\nSELECT 1\n```"
    assert _clean_sql(raw) == "SELECT 1"


def test_clean_sql_trailing_semicolon():
    """去除末尾分号。"""
    assert _clean_sql("SELECT 1;") == "SELECT 1"


# ======================================================================
# 场景 5：DuckDB 执行
# ======================================================================


def test_execute_sql_simple_select(sample_csv):
    """基本 SELECT 查询执行成功。"""
    df, con = _execute_sql("SELECT * FROM data LIMIT 3", sample_csv, table_name="data")

    assert len(df) == 3
    assert "sku" in df.columns
    assert "sales_volume" in df.columns
    con.close()


def test_execute_sql_aggregation(sample_csv):
    """GROUP BY + AVG 聚合查询。"""
    df, con = _execute_sql(
        "SELECT region, AVG(sales_volume) AS avg_sales FROM data GROUP BY region",
        sample_csv,
        table_name="data",
    )

    assert len(df) == 3  # 华北 + 华东 + 华南
    assert "avg_sales" in df.columns
    con.close()


# ======================================================================
# 场景 6：_generate_summary 摘要生成
# ======================================================================


def test_generate_summary_multi_row():
    """多行结果 → 摘要含行数 + 前几行预览。"""
    df = pd.DataFrame({"region": ["华北", "华东"], "avg_sales": [110.0, 87.5]})
    summary = _generate_summary("各区域平均销量", "SELECT ...", df)

    assert "2 条" in summary
    assert "华北" in summary


def test_generate_summary_single_row():
    """单行结果 → 逐列展示值。"""
    df = pd.DataFrame({"total": [300]})
    summary = _generate_summary("总销量", "SELECT ...", df)

    assert "总销量" in summary
    assert "300" in summary


def test_generate_summary_empty():
    """空结果 → 未返回任何结果。"""
    df = pd.DataFrame()
    summary = _generate_summary("不存在的数据", "SELECT ...", df)

    assert "未返回任何结果" in summary


# ======================================================================
# 场景 7：_build_sql_prompt 结构验证
# ======================================================================


def test_build_sql_prompt_structure(sample_csv):
    """Prompt 应包含 schema DDL、问题、约束。"""
    ddl = extract_schema(sample_csv, table_name="sales")
    prompt = _build_sql_prompt("各区域平均销量？", ddl, table_name="sales")

    assert "CREATE TABLE sales" in prompt
    assert "各区域平均销量？" in prompt
    assert "SELECT 语句" in prompt or "SELECT" in prompt
    assert "DELETE" in prompt or "DROP" in prompt  # 安全约束


# ======================================================================
# 场景 8：execute_sql 列不存在时的错误
# ======================================================================


def test_execute_sql_nonexistent_column(sample_csv):
    """访问不存在的列应抛出 DuckDB BinderException（列在 view 中不存在）。"""
    import duckdb

    # duckdb 对列不存在的错误类型是 BinderException（不是 CatalogException）
    with pytest.raises(duckdb.BinderException):
        _execute_sql(
            "SELECT nonexistent_col FROM data",
            sample_csv,
            table_name="data",
        )


def test_execute_sql_syntax_error(sample_csv):
    """SQL 语法错误应抛出 ParserException。"""
    import duckdb

    with pytest.raises(duckdb.ParserException):
        _execute_sql(
            "SELECT * FRM data",
            sample_csv,
            table_name="data",
        )


# ======================================================================
# 场景 9：run_text_to_sql 端到端（mock LLM）
# ======================================================================


def test_run_text_to_sql_e2e_mock(sample_csv, tmp_output_dir, monkeypatch):
    """端到端流程：mock LLM 返回固定 SQL。"""

    def mock_call_llm(prompt_text, api_key=None):
        return "SELECT region, SUM(sales_volume) AS total_sales FROM data GROUP BY region"

    monkeypatch.setattr(
        "src.domain.text_to_sql._call_llm_for_sql", mock_call_llm
    )

    result = run_text_to_sql(
        query="各区域总销量是多少？",
        csv_path=sample_csv,
        output_dir=tmp_output_dir,
    )

    assert result["sql"] == "SELECT region, SUM(sales_volume) AS total_sales FROM data GROUP BY region"
    assert result["row_count"] == 3  # 华北 + 华东 + 华南
    assert "total_sales" in result["columns"]
    assert len(result["rows"]) == 3
    assert "华北" in result["summary"] or "1120" in result["summary"] or "110" in result["summary"]

    # 验证输出文件
    output_file = Path(tmp_output_dir) / "text_to_sql_result.json"
    assert output_file.exists()
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["question"] == "各区域总销量是多少？"


# ======================================================================
# 场景 10：危险 SQL 在 run_text_to_sql 中被拦截
# ======================================================================


def test_run_text_to_sql_blocks_dangerous(sample_csv, tmp_output_dir, monkeypatch):
    """端到端：mock LLM 返回 DROP TABLE，应被安全检查拦截。"""

    def mock_call_llm(prompt_text, api_key=None):
        return "DROP TABLE data"

    monkeypatch.setattr(
        "src.domain.text_to_sql._call_llm_for_sql", mock_call_llm
    )

    with pytest.raises(ValueError, match="SQL 安全检查拦截"):
        run_text_to_sql(
            query="删掉所有数据",
            csv_path=sample_csv,
            output_dir=tmp_output_dir,
        )


# ======================================================================
# 场景 11：check_sql_safety 不误杀合法 SQL
# ======================================================================


def test_safe_sql_patterns():
    """各种合法 SELECT 模式均应通过安全检查。"""
    safe_queries = [
        "SELECT * FROM data",
        "SELECT a, b FROM data WHERE a > 10",
        "SELECT region, COUNT(*) AS cnt FROM data GROUP BY region ORDER BY cnt DESC",
        "SELECT * FROM data WHERE date > '2026-01-01'",
        "SELECT DISTINCT region FROM data",
        "SELECT AVG(price) FROM data",
        "SELECT * FROM data LIMIT 10 OFFSET 5",
        "SELECT a, b, c FROM data WHERE a IN (1, 2, 3)",
        "SELECT CASE WHEN price > 100 THEN 'high' ELSE 'low' END FROM data",
    ]

    for sql in safe_queries:
        is_safe, reason = check_sql_safety(sql)
        assert is_safe, f"合法 SQL 被误拦截: {sql} → {reason}"


# ======================================================================
# 场景 12：中文列名 DuckDB 兼容性
# ======================================================================


def test_chinese_column_names_execute(sample_csv_chinese, tmp_output_dir, monkeypatch):
    """中文列名 CSV 在 DuckDB 中正确执行。"""

    def mock_call_llm(prompt_text, api_key=None):
        return 'SELECT "产品", "销量" FROM data'

    monkeypatch.setattr(
        "src.domain.text_to_sql._call_llm_for_sql", mock_call_llm
    )

    result = run_text_to_sql(
        query="查看所有产品和销量",
        csv_path=sample_csv_chinese,
        output_dir=tmp_output_dir,
    )

    assert result["row_count"] == 2
    assert "产品" in result["columns"]


# ======================================================================
# 场景 13：空 CSV（仅表头）
# ======================================================================


def test_empty_csv_header_only(tmp_output_dir, monkeypatch):
    """仅表头的 CSV 不崩溃。"""
    # 创建仅表头的临时 CSV
    csv_path = Path(tmp_output_dir) / "empty.csv"
    csv_path.write_text("date,sku,region,sales_volume\n", encoding="utf-8")

    def mock_call_llm(prompt_text, api_key=None):
        return "SELECT * FROM data"

    monkeypatch.setattr(
        "src.domain.text_to_sql._call_llm_for_sql", mock_call_llm
    )

    result = run_text_to_sql(
        query="查看所有数据",
        csv_path=str(csv_path),
        output_dir=tmp_output_dir,
    )

    assert result["row_count"] == 0

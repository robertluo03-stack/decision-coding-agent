"""Text-to-SQL 引擎 — 自然语言查询转 DuckDB SQL 并执行。

核心流程:
  1. 读取 CSV 前 100 行 → Schema 提取（列名 + 推断类型）
  2. 生成 DuckDB CREATE TABLE 语句作为 Prompt 上下文
  3. 将自然语言问题 + Schema 拼接为 LLM Prompt
  4. LLM 生成 DuckDB SQL
  5. SQL 安全检查（禁止 DDL/DML）
  6. DuckDB 内存模式执行 → pandas DataFrame
  7. 返回 {sql, result, summary}

使用方式:
    from src.domain.text_to_sql import run_text_to_sql
    result = run_text_to_sql("各区域平均销量是多少？", "data/sales.csv")
    print(result["summary"])
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


# ---------------------------------------------------------------------------
# 危险 SQL 关键字（正则 — SQL 不是 Python，不需要 AST）
# ---------------------------------------------------------------------------

_DANGEROUS_SQL_PATTERNS: list[tuple[str, str]] = [
    (r"\bDROP\b", "DROP — 删除表/视图/数据库"),
    (r"\bDELETE\b", "DELETE — 删除数据行"),
    (r"\bUPDATE\b", "UPDATE — 修改数据"),
    (r"\bINSERT\b", "INSERT — 插入数据"),
    (r"\bALTER\b", "ALTER — 修改表结构"),
    (r"\bCREATE\b", "CREATE — 创建表/视图"),
    (r"\bTRUNCATE\b", "TRUNCATE — 清空表"),
    (r"\bEXEC\b", "EXEC/EXECUTE — 执行动态 SQL"),
    (r"\bEXECUTE\b", "EXEC/EXECUTE — 执行动态 SQL"),
    (r"\bPRAGMA\b", "PRAGMA — 数据库配置"),
    (r"\bATTACH\b", "ATTACH — 附加数据库"),
    (r"\bDETACH\b", "DETACH — 分离数据库"),
]


def check_sql_safety(sql: str) -> tuple[bool, str | None]:
    """检查 SQL 是否安全（仅允许只读 SELECT 查询）。

    Args:
        sql: SQL 字符串

    Returns:
        (is_safe, reason) — 安全返回 (True, None)，危险返回 (False, 原因)
    """
    upper_sql = sql.strip().upper()

    # 必须是以 SELECT 开头的只读查询
    if not upper_sql.startswith("SELECT"):
        return (False, f"仅允许 SELECT 查询，当前 SQL 以 '{sql.strip()[:20]}...' 开头")

    # 检查危险关键字
    for pattern, description in _DANGEROUS_SQL_PATTERNS:
        if re.search(pattern, upper_sql):
            return (False, f"SQL 包含危险关键字: {description}")

    return (True, None)


# ---------------------------------------------------------------------------
# Schema 提取
# ---------------------------------------------------------------------------


def _infer_dtype(series: pd.Series) -> str:
    """将 pandas dtype 映射为 DuckDB 兼容的 SQL 类型名。

    Args:
        series: pandas Series

    Returns:
        DuckDB 类型字符串（VARCHAR / INTEGER / BIGINT / DOUBLE / DATE / BOOLEAN）
    """
    dtype_str = str(series.dtype)
    name_lower = series.name.lower() if series.name else ""

    # 日期列优先检测
    if "date" in name_lower or "time" in name_lower or "日期" in str(series.name):
        return "DATE"
    if "datetime" in dtype_str or pd.api.types.is_datetime64_any_dtype(series):
        return "DATE"

    # 数值列
    if pd.api.types.is_integer_dtype(series):
        # 检查值范围防溢出
        if series.max() > 2_147_483_647 or series.min() < -2_147_483_648:
            return "BIGINT"
        return "INTEGER"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE"

    # 布尔
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"

    # 默认字符串
    return "VARCHAR"


def extract_schema(csv_path: str, table_name: str = "data") -> str:
    """从 CSV 文件提取表结构，生成 DuckDB CREATE TABLE 语句。

    读取前 100 行 → 推断每列类型 → 生成建表 DDL。

    Args:
        csv_path:  CSV 文件路径（支持中文列名）
        table_name: 表名（默认 "data"）

    Returns:
        CREATE TABLE DDL 字符串
    """
    df = pd.read_csv(csv_path, nrows=100)

    col_defs: list[str] = []
    for col in df.columns:
        safe_col = f'"{col}"'  # DuckDB 双引号包裹保留中文列名
        dtype = _infer_dtype(df[col])
        col_defs.append(f"    {safe_col} {dtype}")

    ddl = f"CREATE TABLE {table_name} (\n" + ",\n".join(col_defs) + "\n);"
    return ddl


# ---------------------------------------------------------------------------
# LLM Prompt 构建
# ---------------------------------------------------------------------------


def _build_sql_prompt(question: str, schema_ddl: str, table_name: str = "data") -> str:
    """构建发送给 DeepSeek 的 Text-to-SQL Prompt。

    Args:
        question:   自然语言问题
        schema_ddl:  CREATE TABLE DDL
        table_name:  表名

    Returns:
        完整的 System + User Prompt 字符串
    """
    prompt = f"""你是一个 SQL 专家。根据以下表结构和用户问题，生成一条 DuckDB 兼容的 SQL SELECT 查询。

## 表结构

{schema_ddl}

## 约束

- **只生成 SELECT 语句**，禁止 DELETE / DROP / UPDATE / INSERT / ALTER / CREATE / TRUNCATE
- 使用标准 SQL 语法，DuckDB 兼容
- 如果问题涉及时间，使用 DuckDB 日期函数（如 EXTRACT(YEAR FROM "日期")、strftime）
- 列名用双引号包裹（如 "{list(json.loads(schema_ddl.replace('CREATE TABLE ...', ''))) if False else ''}"）
- 如果问题没有明确的聚合需求，默认 SELECT * LIMIT 20
- 表名为 `{table_name}`
- **只输出 SQL**，不要添加任何解释、注释或 Markdown 格式

## 用户问题

{question}

## SQL"""

    return prompt


# ---------------------------------------------------------------------------
# 自然语言摘要生成
# ---------------------------------------------------------------------------


def _generate_summary(question: str, sql: str, result_df: pd.DataFrame) -> str:
    """基于问题、SQL 和结果生成简短的自然语言摘要。

    不调用 LLM（避免额外 API 开销），用模板生成。

    Args:
        question:   原始自然语言问题
        sql:        执行的 SQL
        result_df:  查询结果 DataFrame

    Returns:
        中文摘要字符串
    """
    row_count = len(result_df)

    if row_count == 0:
        return f"查询 '{question[:50]}...' 未返回任何结果。"

    col_names = list(result_df.columns)

    if row_count == 1:
        # 单行结果：逐列列出值
        parts = [f"{col}: {result_df.iloc[0][col]}" for col in col_names[:10]]
        return f"{question} → " + "，".join(parts)

    # 多行结果：展示前 5 行
    preview_lines = []
    for i in range(min(5, row_count)):
        row_parts = [f"{col}={result_df.iloc[i][col]}" for col in col_names[:5]]
        preview_lines.append("  " + "，".join(row_parts))

    header = f"查询共返回 {row_count} 条结果。"
    if row_count > 5:
        preview_lines.append(f"  ...（还有 {row_count - 5} 条）")

    return header + "\n" + "\n".join(preview_lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


@dataclass
class TextToSQLResult:
    """Text-to-SQL 执行结果。"""
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    summary: str


def run_text_to_sql(
    query: str,
    csv_path: str,
    output_dir: str = "reports/",
    *,
    table_name: str = "data",
    api_key: str | None = None,
) -> dict:
    """执行 Text-to-SQL：自然语言 → SQL → DuckDB 执行 → 结果。

    完整流水线：
      1. 读取 CSV → 提取 Schema (CREATE TABLE DDL)
      2. 拼接 Prompt → 调用 DeepSeek API 生成 SQL
      3. SQL 安全检查（禁止 DDL/DML）
      4. DuckDB 内存模式执行 → pandas DataFrame
      5. 生成自然语言摘要
      6. 结果写入 output_dir/text_to_sql_result.json

    Args:
        query:      自然语言问题（如 "各区域平均销量是多少？"）
        csv_path:   数据文件路径（相对路径相对于项目根目录）
        output_dir: 结果输出目录（相对路径，如 "reports/"）
        table_name: DuckDB 表名（默认 "data"）
        api_key:    DeepSeek API Key（可选，默认从环境变量读取）

    Returns:
        {
            "sql": "SELECT ...",
            "columns": ["col1", "col2", ...],
            "rows": [{"col1": val, ...}, ...],
            "row_count": 42,
            "summary": "查询共返回 42 条结果..."
        }

    Raises:
        ValueError: SQL 不安全或 LLM 返回空 SQL 时抛出
        duckdb.CatalogException: 列/表不存在
        duckdb.ParserException: SQL 语法错误
    """
    # ---- 1. 提取 Schema ----
    schema_ddl = extract_schema(csv_path, table_name=table_name)

    # ---- 2. 生成 SQL（通过 DeepSeek API） ----
    prompt_text = _build_sql_prompt(query, schema_ddl, table_name=table_name)
    generated_sql = _call_llm_for_sql(prompt_text, api_key=api_key)

    # ---- 3. SQL 安全检查 ----
    is_safe, reason = check_sql_safety(generated_sql)
    if not is_safe:
        raise ValueError(f"SQL 安全检查拦截: {reason}")

    # ---- 4. DuckDB 执行 ----
    sql_clean = _clean_sql(generated_sql)
    result_df, con = _execute_sql(sql_clean, csv_path, table_name=table_name)

    # ---- 5. 生成摘要 ----
    summary = _generate_summary(query, sql_clean, result_df)

    # ---- 6. 结果写入 disk ----
    output_path = _write_result(
        query=query,
        sql=sql_clean,
        result_df=result_df,
        summary=summary,
        output_dir=output_dir,
    )

    # ---- 7. 构造返回 dict ----
    columns = list(result_df.columns)
    rows = result_df.to_dict(orient="records")

    return {
        "sql": sql_clean,
        "columns": columns,
        "rows": rows,
        "row_count": len(result_df),
        "summary": summary,
        "output_path": output_path,
    }


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _call_llm_for_sql(prompt_text: str, api_key: str | None = None) -> str:
    """调用 DeepSeek API 将自然语言转为 SQL。

    Args:
        prompt_text: 完整 Prompt（含系统指令 + 用户问题）
        api_key:     DeepSeek API Key

    Returns:
        生成的 SQL 字符串

    Raises:
        ValueError: LLM 返回空內容或 API Key 缺失
    """
    resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not resolved_key:
        raise ValueError("DEEPSEEK_API_KEY 未设置，无法生成 SQL")

    from langchain_deepseek import ChatDeepSeek

    llm = ChatDeepSeek(
        model="deepseek-chat",
        api_key=resolved_key,
        temperature=0.1,  # 低温度提高 SQL 正确率
        request_timeout=120,
        max_retries=2,
    )

    # System 角色设置指令，User 角色放完整 prompt
    messages = [
        {"role": "system", "content": "你是一个 SQL 专家。只输出 SQL 语句，不要任何解释或 Markdown。"},
        {"role": "user", "content": prompt_text},
    ]

    response = llm.invoke(messages)
    content = response.content.strip()

    if not content:
        raise ValueError("LLM 返回空 SQL，请重试或换一种问法")

    return content


def _clean_sql(raw_sql: str) -> str:
    """清理 LLM 生成的 SQL：去除 Markdown 包装和多余空白。

    Args:
        raw_sql: LLM 原始响应

    Returns:
        清理后的纯 SQL 字符串
    """
    # 移除 ```sql ... ``` 或 ``` ... ``` 包装
    sql = raw_sql.strip()
    for prefix in ("```sql", "```SQL", "```"):
        if sql.startswith(prefix):
            sql = sql[len(prefix):].strip()
            if sql.endswith("```"):
                sql = sql[:-3].strip()
            break

    # 移除末尾分号后的空白
    sql = sql.rstrip(";").strip()

    return sql


def _execute_sql(
    sql: str,
    csv_path: str,
    table_name: str = "data",
) -> tuple[pd.DataFrame, duckdb.DuckDBPyConnection]:
    """在 DuckDB 内存数据库中执行 SQL。

    Args:
        sql:        已清洗的 SQL
        csv_path:   CSV 文件路径
        table_name: 表名

    Returns:
        (result_df, connection) — 结果 DataFrame 和 DuckDB 连接

    Raises:
        duckdb.CatalogException: 列/表不存在
        duckdb.ParserException: SQL 语法错误
    """
    con = duckdb.connect()

    # 使用 read_csv_auto 自动推断类型并创建表
    abs_path = str(Path(csv_path).resolve())
    con.execute(
        f"CREATE OR REPLACE VIEW {table_name} AS "
        f"SELECT * FROM read_csv_auto('{abs_path}', header=true)"
    )

    result_df = con.execute(sql).df()
    return result_df, con


def _write_result(
    query: str,
    sql: str,
    result_df: pd.DataFrame,
    summary: str,
    output_dir: str,
) -> str:
    """将 Text-to-SQL 结果写入 JSON 文件。

    Args:
        query:     原始自然语言问题
        sql:       执行的 SQL
        result_df: 查询结果 DataFrame
        summary:   自然语言摘要
        output_dir: 输出目录

    Returns:
        写入的 JSON 文件路径
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    result_data = {
        "question": query,
        "sql": sql,
        "columns": list(result_df.columns),
        "rows": result_df.head(100).to_dict(orient="records"),
        "row_count": len(result_df),
        "summary": summary,
    }

    filepath = out / "text_to_sql_result.json"
    filepath.write_text(
        json.dumps(result_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return str(filepath.resolve())

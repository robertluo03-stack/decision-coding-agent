"""Text-to-SQL Demo — 绕过 LLM 直接展示完整 SQL 处理流程。

直接从 CSV 提取 Schema → SQL 安全检查 → DuckDB 执行 → 结果摘要，
展示 Text-to-SQL 引擎的核心组件，不需要 LLM / API Key。

Requires API Key: ❌ 不需要

用法:
    python examples/demo_text_to_sql.py
    python examples/demo_text_to_sql.py --csv workspace/data/sales.csv
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

# 确保能找到 src 包（从 examples/ 找项目根目录）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def main() -> None:
    """Text-to-SQL Demo 主入口。"""
    parser = argparse.ArgumentParser(description="Text-to-SQL Demo — 绕过 LLM 展示 SQL 处理流程")
    parser.add_argument("--csv", default="workspace/data/sales.csv", help="CSV 数据文件路径")
    args = parser.parse_args()

    csv_path: str = args.csv

    if not os.path.exists(csv_path):
        print(f"\n❌ 错误: 文件不存在 → {csv_path}")
        sys.exit(1)

    print("=" * 60)
    print("  Text-to-SQL 引擎 Demo")
    print("=" * 60)
    print(f"\n  数据源  : {csv_path}")
    print(f"  模式    : 绕过 LLM（纯 Python 展示）")
    print(f"  SQL     : 预生成 SELECT 语句")

    # ── Step 1: Schema 提取 ──
    print(f"\n{'─' * 60}")
    print("  Step 1 — Schema 提取 (extract_schema)")
    print(f"{'─' * 60}")

    try:
        from src.domain.text_to_sql import extract_schema
        schema_ddl = extract_schema(csv_path, table_name="sales")
        print(f"\n{schema_ddl}")
    except Exception as exc:
        print(f"\n❌ Schema 提取失败: {exc}")
        sys.exit(1)

    # ── Step 2: SQL 安全检查 ──
    print(f"\n{'─' * 60}")
    print("  Step 2 — SQL 安全检查 (check_sql_safety)")
    print(f"{'─' * 60}")

    # 使用预生成的安全 SQL
    sql_safe = 'SELECT region, AVG(sales_volume) AS avg_sales FROM sales GROUP BY region ORDER BY avg_sales DESC'

    try:
        from src.domain.text_to_sql import check_sql_safety
        is_safe, reason = check_sql_safety(sql_safe)
        print(f"\n  SQL: {sql_safe}")
        print(f"  安全  : {'✅ 通过' if is_safe else '❌ 拦截'}")
        if not is_safe:
            print(f"  原因: {reason}")
            sys.exit(1)
    except Exception as exc:
        print(f"\n❌ 安全检查异常: {exc}")
        sys.exit(1)

    # ── Step 2b: 展示危险 SQL 被拦截 ──
    sql_dangerous = "DROP TABLE sales; SELECT * FROM sales"
    is_safe_d, reason_d = check_sql_safety(sql_dangerous)
    print(f"\n  危险 SQL 测试: {sql_dangerous}")
    print(f"  拦截  : {'✅ 已拦截' if not is_safe_d else '❌ 漏报'}")
    if reason_d:
        print(f"  原因: {reason_d}")

    # ── Step 3: DuckDB 执行 ──
    print(f"\n{'─' * 60}")
    print("  Step 3 — DuckDB 执行 (_execute_sql)")
    print(f"{'─' * 60}")

    try:
        from src.domain.text_to_sql import _clean_sql, _execute_sql
        sql_clean = _clean_sql(sql_safe)
        result_df, con = _execute_sql(sql_clean, csv_path, table_name="sales")

        print(f"\n  查询结果 ({len(result_df)} 行 × {len(result_df.columns)} 列):\n")
        # Markdown 表格格式
        cols = list(result_df.columns)
        header = "| " + " | ".join(cols) + " |"
        sep = "|" + "|".join("------" for _ in cols) + "|"
        print(f"  {header}")
        print(f"  {sep}")
        for _, row in result_df.iterrows():
            row_str = "| " + " | ".join(str(row[col]) for col in cols) + " |"
            print(f"  {row_str}")

        con.close()
    except Exception as exc:
        print(f"\n❌ DuckDB 执行失败: {exc}")
        sys.exit(1)

    # ── Step 4: 结果摘要 ──
    print(f"\n{'─' * 60}")
    print("  Step 4 — 自然语言摘要 (_generate_summary)")
    print(f"{'─' * 60}")

    try:
        from src.domain.text_to_sql import _generate_summary
        summary = _generate_summary("各区域平均销量是多少？", sql_safe, result_df)
        print(f"\n  {summary}")
    except Exception as exc:
        print(f"\n❌ 摘要生成失败: {exc}")
        sys.exit(1)

    # ── 完成 ──
    print(f"\n{'=' * 60}")
    print("  Text-to-SQL Demo 完成 ✅")
    print(f"{'=' * 60}")
    print(f"\n  流程展示：")
    print(f"    ✅ Step 1 — Schema 提取（DDL 生成）")
    print(f"    ✅ Step 2 — SQL 安全检查（安全 + 危险各 1 例）")
    print(f"    ✅ Step 3 — DuckDB 内存执行（{len(result_df)} 行结果）")
    print(f"    ✅ Step 4 — 自然语言摘要生成")
    print(f"\n  完整流程（含 LLM）请调用:")
    print(f"    from src.domain.text_to_sql import run_text_to_sql")
    print(f"    result = run_text_to_sql('各区域平均销量？', '{csv_path}')")


if __name__ == "__main__":
    main()

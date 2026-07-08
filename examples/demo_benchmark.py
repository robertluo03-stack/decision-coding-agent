"""Benchmark Demo — mock 结果生成 + 报告生成，不调用真实 LLM。

模拟 10 个任务（7 成功 3 失败，含重试），
调用 ReportGenerator 生成 MD + HTML 报告。

用法:
    python examples/demo_benchmark.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 确保能找到 src 包（从 examples/ 找项目根目录）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def main() -> None:
    """Benchmark Demo 主入口。"""
    from src.benchmark.models import BenchmarkResult
    from src.benchmark.metrics import MetricsCollector
    from src.benchmark.reporter import ReportGenerator

    print("📊 Benchmark 报告 Demo")
    print("═" * 50)
    print("  模式: mock 数据（不调用 LLM）")
    print()

    # ── 构造 10 个 mock 结果 ──
    mock_data: list[dict] = [
        # 数据分析 5 个（4 成功 + 1 超时）
        {"task_id": "BA-01", "category": "data_analysis", "success": True, "completed": True,
         "retry_count": 0, "elapsed": 12.3, "error": None,
         "keywords": ["sales", "均值", "标准差", "销量"],
         "query": "分析 sales.csv"},
        {"task_id": "BA-02", "category": "data_analysis", "success": True, "completed": True,
         "retry_count": 0, "elapsed": 8.7, "error": None,
         "keywords": ["缺失值", "异常值", "评分", "数据质量"],
         "query": "检查 sales.csv 数据质量"},
        {"task_id": "BA-03", "category": "data_analysis", "success": True, "completed": True,
         "retry_count": 0, "elapsed": 15.1, "error": None,
         "keywords": ["图表", "bar", "html"],
         "query": "画柱状图"},
        {"task_id": "BA-04", "category": "data_analysis", "success": True, "completed": True,
         "retry_count": 0, "elapsed": 22.8, "error": None,
         "keywords": ["SELECT", "AVG", "区域"],
         "query": "Text-to-SQL 查询"},
        {"task_id": "BA-05", "category": "data_analysis", "success": False, "completed": False,
         "retry_count": 0, "elapsed": 60.0, "error": "BenchmarkTimeoutError: 任务超时（60s）",
         "keywords": [], "query": "一键分析 inventory.csv"},
        # 代码生成 5 个（3 成功 + 2 失败）
        {"task_id": "CG-01", "category": "code_generation", "success": True, "completed": True,
         "retry_count": 0, "elapsed": 6.2, "error": None,
         "keywords": ["EOQ", "223"],
         "query": "计算 EOQ"},
        {"task_id": "CG-02", "category": "code_generation", "success": True, "completed": True,
         "retry_count": 1, "elapsed": 18.5, "error": None,
         "keywords": ["预测", "MAPE"],
         "query": "需求预测"},
        {"task_id": "CG-03", "category": "code_generation", "success": True, "completed": True,
         "retry_count": 0, "elapsed": 4.9, "error": None,
         "keywords": ["安全库存", "Z", "1.64"],
         "query": "安全库存"},
        {"task_id": "CG-04", "category": "code_generation", "success": False, "completed": True,
         "retry_count": 1, "elapsed": 35.2,
         "error": "KeyError: 'column' — 代码生成的列名与模板结果字段不匹配",
         "keywords": ["补货点", "ROP"], "query": "补货点"},
        {"task_id": "CG-05", "category": "code_generation", "success": False, "completed": True,
         "retry_count": 2, "elapsed": 42.1,
         "error": "LLM API Error: Connection timeout after 3 retries",
         "keywords": ["pipeline"], "query": "inventory_pipeline"},
    ]

    # ── 构建 MetricsCollector ──
    collector = MetricsCollector()
    for d in mock_data:
        r = BenchmarkResult(
            task_id=d["task_id"],
            success=d["success"],
            completed=d["completed"],
            retry_count=d["retry_count"],
            elapsed_seconds=d["elapsed"],
            error=d["error"],
            output_keywords_found=d["keywords"],
        )
        r.category = d["category"]  # type: ignore[attr-defined]
        collector.record(r)

    metrics = collector.compute()
    print(f"  ✅ 已构造 {metrics['total']} 个 mock 结果")
    print(f"     完成率: {metrics['completion_rate']} ({metrics['completed']}/{metrics['total']})")
    print(f"     成功率: {metrics['success_rate']} ({metrics['succeeded']}/{metrics['total']})")
    print(f"     平均重试: {metrics['avg_retry_count']}")
    print(f"     平均耗时: {metrics['avg_elapsed_seconds']}s")
    print()

    # ── 生成报告 ──
    gen = ReportGenerator()
    output_dir = Path("results")
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / "demo_benchmark_report.md"
    html_path = output_dir / "demo_benchmark_report.html"

    gen.generate_md(collector, str(md_path))
    gen.generate_html(collector, str(html_path))

    print(f"📝 Markdown 报告: {md_path.resolve()}")
    print(f"🌐 HTML 报告:     {html_path.resolve()}")
    print()
    print(f"📏 MD 文件大小:  {md_path.stat().st_size} bytes")
    print(f"📏 HTML 文件大小: {html_path.stat().st_size} bytes")
    print()
    print("═" * 50)
    print("  Benchmark Demo 完成 ✅")
    print("═" * 50)
    print()
    print("  功能展示：")
    print("    ✅ MetricsCollector — 10 个 mock 结果")
    print("    ✅ ReportGenerator.generate_md — Markdown 报告")
    print("    ✅ ReportGenerator.generate_html — HTML（卡片+进度条+徽章）")
    print()
    print("  Benchmark 层文件:")
    print("    src/benchmark/models.py    — BenchmarkTask / BenchmarkResult")
    print("    src/benchmark/tasks.py     — get_default_tasks() 10 预定义任务")
    print("    src/benchmark/metrics.py   — MetricsCollector")
    print("    src/benchmark/runner.py    — BenchmarkRunner（执行引擎）")
    print("    src/benchmark/validators.py — validate_task_result")
    print("    src/benchmark/reporter.py  — ReportGenerator")
    print("    src/benchmark/__main__.py  — CLI（run / report）")
    print()


if __name__ == "__main__":
    main()

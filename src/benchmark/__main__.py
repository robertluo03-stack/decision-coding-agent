"""Benchmark CLI 入口。

用法:
    python -m benchmark run              # 运行全部 10 个任务，生成 MD+HTML 报告
    python -m benchmark run --rich       # 带 Rich 终端 UI
    python -m benchmark report <jsonl>   # 从已有 JSONL 生成报告（不重新执行）

环境变量:
    DEEPSEEK_API_KEY   DeepSeek API 密钥（run 时必须）
    WORKSPACE_PATH     工作区根目录（默认 ./workspace）
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    """Benchmark CLI 主入口。"""
    # ── 加载 .env ──
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("[警告] python-dotenv 未安装，跳过 .env 加载。")

    # ── 解析命令 ──
    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "run":
        _cmd_run()
    elif command == "report":
        _cmd_report()
    else:
        print(f"未知命令: {command}")
        _print_usage()
        sys.exit(1)


def _print_usage() -> None:
    """打印用法帮助。"""
    print("用法: python -m benchmark <command> [options]")
    print("")
    print("命令:")
    print("  run                 运行全部 10 个 benchmark 任务")
    print("  run --rich          带 Rich 终端 UI 运行")
    print("  report <jsonl_path> 从已有 JSONL 生成 MD + HTML 报告")
    print("")
    print("环境变量:")
    print("  DEEPSEEK_API_KEY    DeepSeek API 密钥（run 时必须）")
    print("  WORKSPACE_PATH      工作区根目录（默认 ./workspace）")


def _cmd_run() -> None:
    """执行 benchmark run 命令。"""
    # ── 检查 API Key ──
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("=" * 60)
        print("❌ 错误：DEEPSEEK_API_KEY 未设置")
        print("=" * 60)
        print("\n请通过以下方式之一设置：")
        print("  1. 创建 .env 文件并写入: DEEPSEEK_API_KEY=sk-xxxxx")
        print("  2. 设置环境变量: export DEEPSEEK_API_KEY=sk-xxxxx")
        sys.exit(1)

    use_rich = "--rich" in sys.argv

    # ── 工作区路径 ──
    workspace_path = os.environ.get("WORKSPACE_PATH", "workspace")
    ws = Path(workspace_path).resolve()
    (ws / "data").mkdir(parents=True, exist_ok=True)
    (ws / "reports").mkdir(parents=True, exist_ok=True)
    (ws / "src").mkdir(parents=True, exist_ok=True)
    workspace_path_abs = str(ws)

    # ── 加载任务 ──
    from src.benchmark.tasks import get_default_tasks
    from src.benchmark.runner import BenchmarkRunner

    tasks = get_default_tasks()
    print(f"📋 已加载 {len(tasks)} 个 benchmark 任务")
    print(f"📍 工作区: {workspace_path_abs}")
    if use_rich:
        print("🎨 Rich UI 模式")
    print()

    # ── 执行 ──
    runner = BenchmarkRunner(
        tasks=tasks,
        workspace_path=workspace_path_abs,
        output_dir="results/",
    )
    try:
        collector = runner.run_all(use_ui=use_rich)
    except KeyboardInterrupt:
        print("\n\n⚠️ Benchmark 被中断（Ctrl+C）")
        sys.exit(1)

    # ── 生成报告 ──
    _generate_reports(collector, runner.jsonl_path)

    # ── 最终指标 ──
    metrics = collector.compute()
    print("\n📊 分类统计:")
    for cat, stats in metrics.get("category_breakdown", {}).items():
        cat_label = "数据分析" if cat == "data_analysis" else "代码生成" if cat == "code_generation" else cat
        print(f"  {cat_label}: {stats['count']} 任务, "
              f"成功率 {stats['success_rate']}, "
              f"完成率 {stats['completion_rate']}")


def _cmd_report() -> None:
    """执行 benchmark report 命令 — 从 JSONL 生成报告。"""
    if len(sys.argv) < 3:
        print("用法: python -m benchmark report <jsonl_path>")
        print("示例: python -m benchmark report results/benchmark_20260708_120000.jsonl")
        sys.exit(1)

    jsonl_path = sys.argv[2]
    if not Path(jsonl_path).exists():
        print(f"❌ 文件不存在: {jsonl_path}")
        sys.exit(1)

    print(f"📄 读取 JSONL: {jsonl_path}")

    # ── 解析 JSONL → MetricsCollector ──
    from src.benchmark.models import BenchmarkResult
    from src.benchmark.metrics import MetricsCollector

    collector = MetricsCollector()
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            result = BenchmarkResult(
                task_id=record["task_id"],
                success=record.get("success", False),
                completed=record.get("completed", False),
                retry_count=record.get("retry_count", 0),
                elapsed_seconds=record.get("elapsed_seconds", 0.0),
                error=record.get("error"),
                output_keywords_found=record.get("output_keywords_found", []),
                report_path=record.get("report_path"),
            )
            collector.record(result)

    metrics = collector.compute()
    print(f"✅ 已加载 {metrics['total']} 条记录")
    print(f"   完成率: {metrics['completion_rate']}")
    print(f"   成功率: {metrics['success_rate']}")

    _generate_reports(collector, jsonl_path)


def _generate_reports(collector: object, source_path: str) -> None:
    """从 MetricsCollector 生成 MD + HTML 报告。

    Args:
        collector: MetricsCollector 实例。
        source_path: JSONL 路径（用于生成报告文件名）。
    """
    from src.benchmark.reporter import ReportGenerator

    gen = ReportGenerator()

    # 报告文件路径（基于 JSONL 文件名）
    base = str(Path(source_path).with_suffix(""))
    md_path = f"{base}_report.md"
    html_path = f"{base}_report.html"

    gen.generate_md(collector, md_path)
    print(f"\n📝 Markdown 报告: {md_path}")

    gen.generate_html(collector, html_path)
    print(f"🌐 HTML 报告: {html_path}")


if __name__ == "__main__":
    main()

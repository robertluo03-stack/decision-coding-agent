"""Benchmark CLI 入口。

用法:
    python -m benchmark run                       # 运行全部 10 个任务，生成 MD+HTML 报告
    python -m benchmark run --rich                # 带 Rich 终端 UI
    python -m benchmark run --arm routing_off     # 单臂 routing_off
    python -m benchmark run --arm routing_off --repeat 3  # routing_off 每任务重复 3 次
    python -m benchmark run --both                # 双臂对照（routing_on + routing_off，各 3 次）
    python -m benchmark run --both --adversarial   # 双臂 + 对抗任务集
    python -m benchmark report <jsonl>            # 从已有 JSONL 生成报告（不重新执行）

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
    print("  run                      运行全部 10 个 benchmark 任务")
    print("  run --rich               带 Rich 终端 UI 运行")
    print("  run --arm routing_off    单臂 routing_off（默认 routing_on）")
    print("  run --arm routing_off --repeat 3  重复运行 3 次")
    print("  run --both               双臂对照（routing_on + routing_off），各 3 次重复")
    print("  run --both --adversarial 双臂对照 + 对抗任务集（17 任务 / arm）")
    print("  report <jsonl_path>      从已有 JSONL 生成 MD + HTML 报告")
    print("")
    print("环境变量:")
    print("  DEEPSEEK_API_KEY               DeepSeek API 密钥（run 时必须）")
    print("  WORKSPACE_PATH                 工作区根目录（默认 ./workspace）")
    print("  DECISIONCODER_NO_ROUTING       实验对照开关（true/1/yes 跳过规则路由）")


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
    use_both = "--both" in sys.argv
    use_adversarial = "--adversarial" in sys.argv

    # ── 解析 --arm ──
    arm = "routing_on"
    if "--arm" in sys.argv:
        try:
            idx = sys.argv.index("--arm")
            arm = sys.argv[idx + 1]
            if arm not in ("routing_on", "routing_off"):
                print(f"❌ 无效的 arm 值: {arm}（应为 routing_on 或 routing_off）")
                sys.exit(1)
        except (IndexError, ValueError):
            print("❌ --arm 需要参数: routing_on 或 routing_off")
            sys.exit(1)

    # ── 解析 --repeat ──
    repeat = 1
    if "--repeat" in sys.argv:
        try:
            idx = sys.argv.index("--repeat")
            repeat = int(sys.argv[idx + 1])
            if repeat < 1:
                print("❌ --repeat 必须 >= 1")
                sys.exit(1)
        except (IndexError, ValueError):
            print("❌ --repeat 需要整数参数")
            sys.exit(1)

    # ── 工作区路径 ──
    workspace_path = os.environ.get("WORKSPACE_PATH", "workspace")
    ws = Path(workspace_path).resolve()
    (ws / "data").mkdir(parents=True, exist_ok=True)
    (ws / "reports").mkdir(parents=True, exist_ok=True)
    (ws / "src").mkdir(parents=True, exist_ok=True)
    workspace_path_abs = str(ws)

    # ── 加载任务 ──
    from src.benchmark.tasks import get_default_tasks, get_adversarial_tasks
    from src.benchmark.runner import BenchmarkRunner

    tasks = get_default_tasks()
    if use_adversarial:
        adv_tasks = get_adversarial_tasks()
        tasks.extend(adv_tasks)

    total_runs = len(tasks) * repeat * (2 if use_both else 1)
    print(f"📋 已加载 {len(tasks)} 个 benchmark 任务（+{len(get_adversarial_tasks()) if not use_adversarial else 0} 对抗）")
    print(f"📍 工作区: {workspace_path_abs}")
    print(f"🔬 Arm: {'both' if use_both else arm}")
    print(f"🔁 重复次数: {repeat}")
    print(f"📊 预计总执行次数: {total_runs}")
    if use_rich:
        print("🎨 Rich UI 模式")
    print()

    # ── 执行 ──
    try:
        if use_both:
            # 双臂对照
            runner = BenchmarkRunner(
                tasks=tasks,
                workspace_path=workspace_path_abs,
                output_dir="results/",
                arm=arm,
                repeat=repeat,
            )
            collector = runner.run_both(repeat=repeat)
        else:
            # 单臂
            runner = BenchmarkRunner(
                tasks=tasks,
                workspace_path=workspace_path_abs,
                output_dir="results/",
                arm=arm,
                repeat=repeat,
            )
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
        cat_label = "数据分析" if cat == "data_analysis" else "代码生成" if cat == "code_generation" else "对抗测试" if cat == "adversarial" else cat
        print(f"  {cat_label}: {stats['count']} 结果, "
              f"成功率 {stats['success_rate']}, "
              f"完成率 {stats['completion_rate']}")

    # 打印 arm 对比
    arm_bd = metrics.get("arm_breakdown", {})
    if len(arm_bd) > 1:
        print("\n📊 Arm 对比:")
        print(f"  {'':<20} {'routing_on':>14} {'routing_off':>14}")
        print(f"  {'─' * 20} {'─' * 14} {'─' * 14}")
        print(f"  {'成功率':<20} {_pct(arm_bd.get('routing_on', {}).get('success_rate', 0)):>14} "
              f"{_pct(arm_bd.get('routing_off', {}).get('success_rate', 0)):>14}")
        print(f"  {'结果一致率':<20} {_pct(arm_bd.get('routing_on', {}).get('consistency_rate', 0)):>14} "
              f"{_pct(arm_bd.get('routing_off', {}).get('consistency_rate', 0)):>14}")
        print(f"  {'Token 总量':<20} {arm_bd.get('routing_on', {}).get('token_total', 0):>14} "
              f"{arm_bd.get('routing_off', {}).get('token_total', 0):>14}")
        print(f"  {'平均耗时':<20} {str(arm_bd.get('routing_on', {}).get('avg_elapsed_seconds', 0)) + 's':>14} "
              f"{str(arm_bd.get('routing_off', {}).get('avg_elapsed_seconds', 0)) + 's':>14}")


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
                run_index=record.get("run_index", 1),
                arm=record.get("arm", "routing_on"),
                token_usage=record.get("token_usage"),
                numeric_value=record.get("numeric_value"),
            )
            collector.record(result)

    metrics = collector.compute()
    print(f"✅ 已加载 {metrics['total']} 条记录")
    print(f"   完成率: {metrics['completion_rate']}")
    print(f"   成功率: {metrics['success_rate']}")
    if len(metrics.get("arm_breakdown", {})) > 1:
        print(f"   Arm 数: {len(metrics['arm_breakdown'])}")

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


def _pct(rate: float) -> str:
    """小数 → 百分数字符串。"""
    return f"{round(rate * 100)}%"


if __name__ == "__main__":
    main()

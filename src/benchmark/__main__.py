"""Benchmark CLI 入口。

用法:
    python -m benchmark run              # 运行全部 10 个任务
    python -m benchmark run --resume     # 断点续跑（跳过 JSONL 中已成功的任务，Day 5 扩展）

环境变量:
    DEEPSEEK_API_KEY   DeepSeek API 密钥（必须）
    WORKSPACE_PATH     工作区根目录（默认 ./workspace）
"""

import os
import sys
from pathlib import Path


def main() -> None:
    """Benchmark CLI 主入口。"""
    # ── 加载 .env ──
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("[警告] python-dotenv 未安装，跳过 .env 加载。")

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

    # ── 解析命令 ──
    if len(sys.argv) < 2:
        print("用法: python -m benchmark <command>")
        print("  run       运行全部 10 个 benchmark 任务")
        print("  resume    断点续跑（Day 5 扩展）")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command not in ("run", "resume"):
        print(f"未知命令: {command}")
        print("用法: python -m benchmark run")
        sys.exit(1)

    # ── 工作区路径 ──
    workspace_path = os.environ.get("WORKSPACE_PATH", "workspace")
    ws = Path(workspace_path).resolve()

    # 确保子目录存在
    (ws / "data").mkdir(parents=True, exist_ok=True)
    (ws / "reports").mkdir(parents=True, exist_ok=True)
    (ws / "src").mkdir(parents=True, exist_ok=True)

    workspace_path_abs = str(ws)

    # ── 加载任务 ──
    from src.benchmark.tasks import get_default_tasks
    from src.benchmark.runner import BenchmarkRunner

    if command == "resume":
        print("⚠️ --resume 功能将在 Day 5 实现")
        print("  当前回退为 run（从头执行）\n")

    tasks = get_default_tasks()
    print(f"📋 已加载 {len(tasks)} 个 benchmark 任务")
    print(f"📍 工作区: {workspace_path_abs}")
    print()

    # ── 执行 ──
    runner = BenchmarkRunner(
        tasks=tasks,
        workspace_path=workspace_path_abs,
        output_dir="results/",
    )
    try:
        collector = runner.run_all()
    except KeyboardInterrupt:
        print("\n\n⚠️ Benchmark 被中断（Ctrl+C）")
        sys.exit(1)

    # ── 最终指标 ──
    metrics = collector.compute()
    print("\n📊 分类统计:")
    for cat, stats in metrics.get("category_breakdown", {}).items():
        print(f"  {cat}: {stats['count']} 任务, "
              f"成功率 {stats['success_rate']}, "
              f"完成率 {stats['completion_rate']}")


if __name__ == "__main__":
    main()

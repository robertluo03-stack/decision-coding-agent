"""DecisionCoder — 面向经营决策与运筹优化场景的垂直 Coding Agent。

CLI 入口：交互式接收自然语言需求，执行 Plan → Code → Execute → Debug → Report 闭环。

用法:
    python main.py                   # 交互模式（默认工作区 ./workspace）
    python main.py --rich            # 启用 Rich 终端 UI（进度条 + 状态表 + 日志面板）
    python main.py --skip-debug      # 跳过 Debugger 节点（无人值守模式）

环境变量:
    WORKSPACE_PATH     工作区根目录（默认 ./workspace）
    DEEPSEEK_API_KEY   DeepSeek API 密钥（必须）
    USE_RICH           设置为 "true" 启用 Rich 终端 UI（等价于 --rich 参数）
"""

import os
import sys
from pathlib import Path


def _setup_environment() -> str:
    """加载环境变量并检查必要条件。

    1. 加载 .env 文件（python-dotenv）
    2. 检查 DEEPSEEK_API_KEY
    3. 解析 WORKSPACE_PATH
    4. 确保 workspace/data/ 和 workspace/reports/ 目录存在

    Returns:
        工作区绝对路径
    """
    # ---- 加载 .env ----
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        print("[警告] python-dotenv 未安装，跳过 .env 加载。请手动设置环境变量。")

    # ---- 检查 API Key ----
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("=" * 60)
        print("❌ 错误：DEEPSEEK_API_KEY 未设置")
        print("=" * 60)
        print()
        print("请通过以下方式之一设置：")
        print("  1. 创建 .env 文件并写入: DEEPSEEK_API_KEY=sk-xxxxx")
        print("  2. 设置环境变量: export DEEPSEEK_API_KEY=sk-xxxxx")
        print()
        print("获取 API Key: https://platform.deepseek.com/api_keys")
        sys.exit(1)

    # ---- 工作区路径 ----
    workspace_path = os.environ.get("WORKSPACE_PATH", "./workspace")
    ws = Path(workspace_path).resolve()

    # 确保目录存在
    (ws / "data").mkdir(parents=True, exist_ok=True)
    (ws / "reports").mkdir(parents=True, exist_ok=True)
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "tests").mkdir(parents=True, exist_ok=True)

    return str(ws)


def _print_banner(workspace_path: str) -> None:
    """打印欢迎语和工作区信息。"""
    banner = f"""
╔══════════════════════════════════════════════════════════╗
║            DecisionCoder v0.1.0                         ║
║     面向经营决策与运筹优化的垂直 Coding Agent             ║
╚══════════════════════════════════════════════════════════╝

📍 工作区: {workspace_path}
📂 数据目录: {workspace_path}/data/
📊 报告目录: {workspace_path}/reports/
🤖 LLM 后端: DeepSeek (deepseek-chat)

输入自然语言需求开始，输入 "exit" 或 "quit" 退出。
输入 "help" 查看使用示例。
"""
    print(banner)


def _print_help() -> None:
    """打印使用帮助和示例。"""
    help_text = """
════════════════════════════════════════════════════
 使用示例
════════════════════════════════════════════════════

  数据分析:
    读取 data/sales.csv，统计每个 sku 的总销量，画出柱状图

  库存优化:
    计算年需求1000件、订货成本50元、持有成本2元的 EOQ

  代码执行:
    打印 hello world 并计算 1+2+3

════════════════════════════════════════════════════
 提示
════════════════════════════════════════════════════

  - 数据文件请放在 workspace/data/ 目录下
  - 生成的代码使用相对路径读取（如 data/sales.csv）
  - 执行遇错时会进入调试模式，可人工干预
  - 生成报告在 workspace/reports/ 下
"""
    print(help_text)


def _print_status(label: str, detail: str = "") -> None:
    """统一的状态打印格式。"""
    if detail:
        print(f"  [{label}] → {detail}")
    else:
        print(f"  [{label}]")


def _print_plain_summary(result: dict, workspace_path: str) -> None:
    """纯文本模式打印执行摘要。"""
    print()
    print("-" * 60)
    print("📊 执行摘要")
    print("-" * 60)

    plan = result.get("plan", [])
    if plan:
        print(f"  执行计划: {len(plan)} 个步骤")
        for i, step in enumerate(plan, 1):
            print(f"    {i}. {step}")

    exec_result = result.get("execution_result")
    if exec_result:
        print(f"\n  执行结果:\n    {exec_result.strip()[:300]}")

    error = result.get("error")
    if error:
        print(f"\n  ⚠️ 错误: {error[:200]}")

    retry = result.get("retry_count", 0)
    if retry > 0:
        print(f"\n  重试次数: {retry} / 2")

    feedback = result.get("human_feedback")
    if feedback:
        print(f"  人在回路: {feedback[:100]}")

    report = result.get("final_report", "")
    if report:
        print(f"\n  ✅ 报告已生成（{len(report)} 字符）")
        report_files = sorted(
            Path(workspace_path).glob("reports/report_*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if report_files:
            print(f"  📄 报告文件: {report_files[0]}")


def _print_rich_summary(
    result: dict, workspace_path: str, ui_manager: object | None
) -> None:
    """Rich 模式下打印执行摘要（通过 UI log + 终端 print）。"""
    plan = result.get("plan", [])
    if plan:
        print(f"\n📋 执行计划: {len(plan)} 个步骤")
        for i, step in enumerate(plan, 1):
            print(f"  {i}. {step}")

    exec_result = result.get("execution_result")
    if exec_result:
        print(f"\n📊 执行结果:\n  {exec_result.strip()[:300]}")

    error = result.get("error")
    if error:
        print(f"\n⚠️ 错误: {error[:200]}")

    retry = result.get("retry_count", 0)
    if retry > 0:
        print(f"🔄 重试次数: {retry} / 2")

    report = result.get("final_report", "")
    if report:
        print(f"\n✅ 报告已生成（{len(report)} 字符）")
        report_files = sorted(
            Path(workspace_path).glob("reports/report_*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if report_files:
            print(f"📄 报告文件: {report_files[0]}")


def _print_rich_mode_status(is_tty: bool) -> None:
    """打印 Rich 模式状态。"""
    if is_tty:
        print("🎨 Rich 终端 UI 已启动（进度条 + 状态表 + 日志面板）")
    else:
        print("⚠️ 非 TTY 环境，Rich UI 降级为纯文本模式")


def main() -> None:
    """DecisionCoder CLI 主入口。"""
    # ---- 检查是否启用 Rich UI ----
    use_rich = "--rich" in sys.argv or os.environ.get("USE_RICH", "").lower() == "true"

    # ---- 初始化 ----
    workspace_path = _setup_environment()
    _print_banner(workspace_path)

    # ---- 延迟导入 graph（环境变量就绪后再加载） ----
    from src.agent.graph import build_graph
    from src.agent.state import AgentState

    # ---- Rich UI 初始化（Live 延迟到 graph 执行前启动，避免遮挡 banner 和 input prompt） ----
    ui_manager = None
    if use_rich:
        from src.agent.ui.manager import UIManager
        ui_manager = UIManager()
        _print_rich_mode_status(ui_manager._is_tty)

    try:
        graph = build_graph(use_ui=use_rich, ui_manager=ui_manager)
    except Exception as exc:
        if ui_manager is not None:
            ui_manager.stop()
        print(f"❌ Graph 编译失败: {exc}")
        sys.exit(1)

    if not use_rich:
        print("✅ Graph 编译成功，就绪。\n")

    # ---- 主循环 ----
    while True:
        try:
            user_input = input("🔍 请输入任务 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 再见！")
            break

        # 退出命令
        if user_input.lower() in ("exit", "quit", "q"):
            print("👋 再见！")
            break

        # 帮助命令
        if user_input.lower() in ("help", "h", "?"):
            _print_help()
            continue

        # 空输入
        if not user_input:
            continue

        # ---- 执行任务 ----
        if not use_rich:
            print()
            print("-" * 60)
            print(f"📝 任务: {user_input}")
            print("-" * 60)
            print()

        # 构造初始状态
        initial_state: AgentState = {
            "user_query": user_input,
            "workspace_path": workspace_path,
            "plan": [],
            "generated_code": "",
            "file_path": None,
            "execution_result": None,
            "error": None,
            "retry_count": 0,
            "human_feedback": None,
            "final_report": None,
        }

        try:
            # 调用 Graph
            import uuid

            # 启动 Rich Live（在 graph 执行前，确保 UI 覆盖执行过程）
            if use_rich and ui_manager is not None:
                ui_manager.start()
                print(f"\n🚀 开始执行: {user_input[:80]}{'...' if len(user_input) > 80 else ''}\n")

            config = {"configurable": {"thread_id": str(uuid.uuid4())[:8]}}
            result = graph.invoke(initial_state, config)

            if use_rich:
                _print_rich_summary(result, workspace_path, ui_manager)
            else:
                _print_plain_summary(result, workspace_path)

        except KeyboardInterrupt:
            print("\n\n⚠️ 任务被中断（Ctrl+C）")
            continue

        except Exception as exc:
            print(f"\n  ❌ 执行异常: {type(exc).__name__}: {exc}")
            print("  💡 提示: 请检查需求是否明确，或尝试更简单的任务。")
            continue

        finally:
            # 无论成功还是异常，关闭 Rich Live 回到主屏幕
            if use_rich and ui_manager is not None:
                ui_manager.stop()

        if not use_rich:
            print()

    # ---- 清理 Rich UI ----
    if ui_manager is not None:
        ui_manager.stop()


if __name__ == "__main__":
    main()

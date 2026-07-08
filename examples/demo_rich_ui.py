"""Rich 终端 UI Demo — 纯本地模拟，不调用 LLM。

模拟 5 个节点依次执行 + Debugger 调试面板触发。
运行约 10 秒后自动结束。

用法:
    python examples/demo_rich_ui.py       # TTY 模式（Rich Live UI）
    python examples/demo_rich_ui.py -t    # 强制 TTY 模式
"""

from __future__ import annotations

import os
import sys
import time

# 确保能找到 src 包（从 examples/ 找项目根目录）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def main() -> None:
    """Rich UI Demo 主入口。"""
    force_terminal = "-t" in sys.argv or "--tty" in sys.argv

    from src.agent.ui.manager import UIManager

    ui = UIManager(force_terminal=force_terminal if force_terminal else None)
    ui.start()

    is_tty = ui._is_tty
    if is_tty:
        print("🎨 Rich 终端 UI Demo 启动（10 秒后自动结束）")
        print()
    else:
        print("⚠️ 非 TTY 模式 — UI 数据更新正常但终端无 Rich 渲染")
        print("💡 提示: 在真实终端中运行以查看完整效果，或加 -t 强制 TTY")
        print()

    nodes = ["Planner", "Coder", "Executor", "Debugger", "Reporter"]

    # ── Phase 1: 模拟 5 个节点依次执行 ──
    for i, node in enumerate(nodes):
        # 运行中
        ui.update_node(node, "运行中", 0.0, retry=0)
        ui.log(f"[{node}] 开始处理...", level="info")
        ui._drain_queue()

        if is_tty:
            time.sleep(0.5)  # 模拟节点处理时间
        else:
            time.sleep(0.05)

        if node == "Executor":
            # Executor 模拟成功
            ui.update_node(node, "完成", 0.52, retry=0)
            ui.log(f"[{node}] 代码执行成功，stdout 60 字符", level="info")

            # ── Phase 2: 模拟 Debugger ──
            ui.update_node("Debugger", "运行中", 0.0, retry=0)
            ui.log("[Debugger] 触发了！execution_result 含部分错误...", level="warning")
            ui._drain_queue()
            if is_tty:
                time.sleep(0.5)
            else:
                time.sleep(0.05)

            # 进入 debug 模式
            ui.enter_debug_mode(
                error="KeyError: 'qty' — 列名不存在，可能为 'quantity' 或 'sales_volume'",
                diagnosis=(
                    "### 错误分析\n\n"
                    "代码第 12 行尝试访问列 `'qty'`，但 DataFrame 中不存在该列。\n\n"
                    "**可能原因**：\n"
                    "- CSV 文件中列名为 `quantity`（英文全称）\n"
                    "- 或列名为 `sales_volume`（示例数据实际列名）\n\n"
                    "**建议修复**：替换 `df['qty']` 为 `df['sales_volume']`"
                ),
            )
            ui._drain_queue()

            if is_tty:
                time.sleep(2.0)  # 模拟用户查看诊断的时间
            else:
                time.sleep(0.1)

            ui.log("[Debugger] 用户选择 1 — 接受 AI 修复建议", level="info")
            ui.exit_debug_mode()
            ui._drain_queue()

            if is_tty:
                time.sleep(0.3)
            else:
                time.sleep(0.03)

            # Coder 重新修复
            ui.update_node("Coder", "运行中", 0.0, retry=1)
            ui.log("[Coder] 重新生成修复代码...", level="info")
            ui._drain_queue()
            if is_tty:
                time.sleep(0.5)
            else:
                time.sleep(0.05)

            ui.update_node("Debugger", "完成", 2.83, retry=0)
            ui.log("[Executor] 修复后重新执行成功 ✅", level="info")
        else:
            ui.update_node(node, "完成", 0.5, retry=0)
            ui.log(f"[{node}] 完成（耗时 0.5s）", level="info")

    # ── Phase 3: Reporter 收尾 ──
    ui.update_node("Reporter", "完成", 0.3, retry=0)
    ui.log("[Reporter] 报告已生成 → reports/report_20260708.md", level="info")
    ui._drain_queue()

    if is_tty:
        time.sleep(1.0)

    # ── 停止 UI ──
    ui.stop()

    # 打印结果摘要
    print()
    print("═" * 50)
    print("  Rich UI Demo 完成 ✅")
    print("═" * 50)
    print()
    print("  功能展示：")
    print("    ✅ ProgressPanel — 5 节点进度条")
    print("    ✅ StatusTable  — 🟡→🔵→🟢 状态流转")
    print("    ✅ LogPanel     — 日志自动截断")
    print("    ✅ DebugPanel   — 错误摘要 + 4 选项")
    print()
    print("  UI 层文件:")
    print("    src/agent/ui/panels.py  — ProgressPanel / StatusTable / LogPanel / DebugPanel")
    print("    src/agent/ui/manager.py — UIManager（queue.Queue 线程安全）")
    print("    src/agent/ui/tracer.py  — NodeTracer（函数包装器）")
    print()


if __name__ == "__main__":
    main()

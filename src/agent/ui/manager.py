"""UIManager — Rich 终端 UI 管理器，线程安全。

核心设计：
- 使用 queue.Queue 缓冲所有来自工作线程的状态更新 + 日志追加
- 后台线程每 0.1s 消费队列并刷新 Live 显示
- Live 更新始终在主线程（rich 约束），降级时自动 skip

降级策略：非 TTY 环境（CI / 管道 / IDE 终端）自动降级为纯 print()，
Rich 的 force_terminal 参数控制。
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Any

from rich.console import Console, Group as RichGroup
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel

from src.agent.ui.panels import DebugPanel, LogPanel, ProgressPanel, StatusTable


class UIManager:
    """Rich 终端 UI 管理器。

    线程安全设计：
    - update_node() / log() 可从任意线程调用，事件入队
    - 后台线程消费队列并刷新 Live
    - Live 更新在主线程的精确定时器中执行

    降级策略：
    - force_terminal=False → 不启动 Live（纯 print 模式）
    - force_terminal=None → 自动检测 sys.stdout.isatty()
    """

    def __init__(self, force_terminal: bool | None = None) -> None:
        """初始化 UI 管理器。

        Args:
            force_terminal:
                True  → 强制 TTY 模式（即使 stdout 不是终端）。
                False → 强制非 TTY 模式（降级为 print）。
                None  → 自动检测 sys.stdout.isatty()。
        """
        self._force_terminal = force_terminal
        self._is_tty: bool = (
            force_terminal
            if force_terminal is not None
            else sys.stdout.isatty()
        )
        self._console = Console(force_terminal=bool(self._force_terminal))
        self._progress_panel = ProgressPanel()
        self._status_table = StatusTable()
        self._log_panel = LogPanel()
        self._debug_panel = DebugPanel()
        self._debug_mode: bool = False
        self._queue: queue.Queue[tuple] = queue.Queue()
        self._live: Live | None = None
        self._running: bool = False
        self._refresh_thread: threading.Thread | None = None

    # ── 公开接口 ──────────────────────────────────────────

    def start(self) -> None:
        """启动 Live 显示。

        非 TTY 模式时直接返回（不启动 Live）。
        """
        if not self._is_tty:
            self._running = False
            return
        self._running = True
        renderable = self._build_renderable()
        self._live = Live(
            renderable,
            console=self._console,
            refresh_per_second=10,
            screen=True,
        )
        self._live.start()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop, daemon=True
        )
        self._refresh_thread.start()

    def stop(self) -> None:
        """关闭 Live 显示。

        停止刷新线程并关闭 Live。非 TTY 模式时为 no-op。
        """
        self._running = False
        if self._refresh_thread is not None:
            self._refresh_thread.join(timeout=0.5)
            self._refresh_thread = None
        if self._live is not None:
            self._live.stop()
            self._live = None

    def update_node(
        self, node: str, status: str, elapsed: float, retry: int = 0
    ) -> None:
        """更新节点状态（线程安全）。

        Args:
            node: 节点名称（Planner / Coder / Executor / Debugger / Reporter）。
            status: 状态（"等待" | "运行中" | "完成" | "错误"）。
            elapsed: 耗时（秒）。
            retry: 重试次数。
        """
        self._queue.put(("update", node, status, elapsed, retry))

    def log(self, message: str, level: str = "info") -> None:
        """追加日志（线程安全）。

        Args:
            message: 日志文本。
            level: 级别（info | warning | error）。
        """
        self._queue.put(("log", message, level))

    def enter_debug_mode(self, error: str, diagnosis: str) -> None:
        """进入调试模式（线程安全）。

        暂停进度条动画，右侧切换为 DebugPanel 展示错误摘要 + 4 个选项。

        Args:
            error: 错误消息摘要。
            diagnosis: AI / 规则诊断结果。
        """
        self._queue.put(("debug_enter", error, diagnosis))

    def exit_debug_mode(self) -> None:
        """退出调试模式（线程安全）。

        恢复进度条动画，右侧切回日志面板。
        """
        self._queue.put(("debug_exit",))

    # ── 测试辅助 ──────────────────────────────────────────

    def get_node_status(self, node: str) -> dict[str, Any] | None:
        """获取节点当前状态（供测试使用）。

        Args:
            node: 节点名称。

        Returns:
            状态字典副本，或 None（节点不存在）。
        """
        info = self._status_table.nodes.get(node)
        if info is None:
            return None
        return dict(info)

    def get_logs(self) -> list[tuple[str, str]]:
        """获取当前日志列表（供测试使用）。

        Returns:
            [(message, level), ...] 的副本。
        """
        return list(self._log_panel.logs)

    @property
    def debug_mode(self) -> bool:
        """是否处于调试模式（供测试使用）。"""
        return self._debug_mode

    # ── 内部：队列消费 ─────────────────────────────────────

    def _drain_queue(self) -> None:
        """消费队列中所有待处理事件（供测试手动触发）。"""
        while not self._queue.empty():
            try:
                event = self._queue.get_nowait()
                self._handle_event(event)
                self._queue.task_done()
            except queue.Empty:
                break

    def _refresh_loop(self) -> None:
        """后台刷新循环，每 0.1s 消费队列并刷新 UI。"""
        while self._running:
            self._drain_queue()
            if self._live is not None:
                try:
                    self._live.update(self._build_renderable())
                except Exception:
                    pass  # Live 已关闭时忽略异常
            time.sleep(0.1)

    def _handle_event(self, event: tuple) -> None:
        """处理单个队列事件。

        Args:
            event: ("update", node, status, elapsed, retry)
                或 ("log", message, level)
        """
        event_type = event[0]
        if event_type == "update":
            _, node, status, elapsed, retry = event
            self._progress_panel.update(
                node, completed=(status in ("完成", "错误"))
            )
            self._status_table.update(node, status, elapsed, retry)
        elif event_type == "log":
            _, message, level = event
            self._log_panel.add(message, level)
        elif event_type == "debug_enter":
            _, error, diagnosis = event
            self._debug_mode = True
            self._debug_panel.activate(error, diagnosis)
        elif event_type == "debug_exit":
            self._debug_mode = False
            self._debug_panel.deactivate()

    def _build_renderable(self) -> Layout:
        """构建左右分栏布局。

        左（ratio=2）：ProgressPanel + StatusTable 垂直排列。
        右（ratio=1）：DebugPanel（debug 模式）或 LogPanel（正常模式）。

        Returns:
            Rich Layout 渲染对象。
        """
        left_top = Panel(
            self._progress_panel.get_renderable(),
            title="执行进度",
            border_style="blue",
        )
        left_bottom = self._status_table.get_renderable()
        left = RichGroup(left_top, left_bottom)

        if self._debug_mode:
            right_content = self._debug_panel.get_renderable()
            right_title = "🐛 调试模式"
            right_style = "red"
        else:
            right_content = self._log_panel.get_renderable()
            right_title = "日志"
            right_style = "green"

        right = Panel(right_content, title=right_title, border_style=right_style)

        layout = Layout()
        layout.split_row(
            Layout(left, name="left", ratio=2),
            Layout(right, name="right", ratio=1),
        )
        return layout

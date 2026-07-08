"""Rich 终端 UI 面板组件。

ProgressPanel  — Rich Progress 进度条，5 个节点各一个 TaskID
StatusTable   — Rich Table，列：节点名 | 状态 | 耗时 | 重试次数
LogPanel      — Rich Group + Text，最多 50 条日志，自动截断
DebugPanel    — Rich Panel + Markdown，展示错误摘要 + 4 个调试选项
"""

from __future__ import annotations

from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel as RichPanel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text


class ProgressPanel:
    """5 节点进度条面板。

    使用 rich.progress.Progress 为每个节点创建独立的进度条。
    完成 → 100%，未开始/运行中 → 0%（运行状态由 StatusTable 的 emoji 区分）。
    """

    NODES: list[str] = ["Planner", "Coder", "Executor", "Debugger", "Reporter"]

    def __init__(self) -> None:
        """初始化 5 条进度条，每条 total=100."""
        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            expand=True,
        )
        self.task_ids: dict[str, int] = {}
        for node in self.NODES:
            tid = self.progress.add_task(node, total=100)
            self.task_ids[node] = tid

    def update(self, node: str, completed: bool = False) -> None:
        """更新节点进度。

        Args:
            node: 节点名称（必须在 NODES 列表中）。
            completed: True → 进度条 100%；False → 重置为 0%。
        """
        if node not in self.task_ids:
            return
        tid = self.task_ids[node]
        self.progress.update(tid, completed=100 if completed else 0)

    def get_renderable(self) -> Progress:
        """返回 Rich Progress 渲染对象。"""
        return self.progress


class StatusTable:
    """节点状态表格。

    Columns: 节点名 | 状态（🟡/🟢/🔴 emoji） | 耗时 | 重试次数。
    每次 get_renderable() 重建 Table，保证数据一致。
    """

    STATUS_ICONS: dict[str, str] = {
        "等待": "🟡 等待",
        "运行中": "🔵 运行中",
        "完成": "🟢 完成",
        "错误": "🔴 错误",
    }

    def __init__(self) -> None:
        """初始化 5 个节点的默认状态（等待，0 耗时，0 重试）。"""
        self.nodes: dict[str, dict] = {}
        for node in ProgressPanel.NODES:
            self.nodes[node] = {"status": "等待", "elapsed": 0.0, "retry": 0}

    def update(self, node: str, status: str, elapsed: float, retry: int = 0) -> None:
        """更新节点状态。

        Args:
            node: 节点名称。
            status: 状态字符串（"等待" | "运行中" | "完成" | "错误"）。
            elapsed: 耗时（秒）。
            retry: 重试次数。
        """
        if node not in self.nodes:
            return
        self.nodes[node] = {"status": status, "elapsed": elapsed, "retry": retry}

    def get_renderable(self) -> Table:
        """构建当前状态表格（每次调用重建）。"""
        table = Table(title="节点状态", expand=True)
        table.add_column("节点名", style="cyan", width=12)
        table.add_column("状态", style="yellow", width=12)
        table.add_column("耗时", style="green", width=10)
        table.add_column("重试次数", style="magenta", width=10)

        for node, info in self.nodes.items():
            icon = self.STATUS_ICONS.get(info["status"], f"⚪ {info['status']}")
            elapsed_str = f"{info['elapsed']:.2f}s" if info["elapsed"] > 0 else "-"
            table.add_row(node, icon, elapsed_str, str(info["retry"]))

        return table


class LogPanel:
    """日志面板，最多保留 50 条，自动截断。

    使用 rich.console.Group + rich.text.Text 渲染。
    """

    MAX_LOGS: int = 50

    def __init__(self) -> None:
        """初始化空日志列表。"""
        self.logs: list[tuple[str, str]] = []  # (message, level)

    def add(self, message: str, level: str = "info") -> None:
        """追加日志条目，超出上限时保留最后 50 条。

        Args:
            message: 日志文本。
            level: 级别（info | warning | error）。
        """
        self.logs.append((message, level))
        if len(self.logs) > self.MAX_LOGS:
            self.logs = self.logs[-self.MAX_LOGS:]

    def get_renderable(self) -> Group:
        """构建日志渲染对象。

        Returns:
            Rich Group 包含所有日志行，空时显示占位文本。
        """
        LEVEL_STYLES: dict[str, str] = {
            "info": "white",
            "warning": "yellow",
            "error": "red bold",
        }
        texts: list[Text] = []
        for msg, level in self.logs:
            style = LEVEL_STYLES.get(level, "white")
            texts.append(Text(msg, style=style))
        if not texts:
            texts.append(Text("（暂无日志）", style="dim"))
        return Group(*texts)


class DebugPanel:
    """调试模式面板，展示错误摘要 + 4 个选项。

    使用 rich.panel.Panel + rich.markdown.Markdown 渲染。
    在 UIManager 进入 debug 模式时替换右侧日志面板。
    """

    OPTIONS_TEXT: str = (
        "**请选择操作：**\n\n"
        "1. 🤖 AI 修复建议 — 接受 AI 生成的修复代码\n"
        "2. ✏️ 自定义修复指令 — 输入手动修复指示\n"
        "3. ⏭️ 跳过此错误 — 保持原代码继续\n"
        "4. 🛑 中止执行 — 生成失败报告后退出"
    )

    def __init__(self) -> None:
        """初始化空 debug 面板。"""
        self._error: str = ""
        self._diagnosis: str = ""
        self._active: bool = False

    def activate(self, error: str, diagnosis: str) -> None:
        """进入 debug 模式，设置错误信息。

        Args:
            error: 错误消息摘要。
            diagnosis: AI 诊断 / 规则诊断结果。
        """
        self._error = error
        self._diagnosis = diagnosis
        self._active = True

    def deactivate(self) -> None:
        """退出 debug 模式。"""
        self._active = False
        self._error = ""
        self._diagnosis = ""

    @property
    def active(self) -> bool:
        """是否处于 debug 模式。"""
        return self._active

    def get_renderable(self) -> Group:
        """构建 debug 面板渲染对象。

        Returns:
            Rich Group 包含错误信息 + 诊断 + 选项，未激活时返回占位。
        """
        if not self._active:
            return Group(
                Text("（等待调试触发）", style="dim")
            )
        md_content = (
            f"### ❌ 执行异常\n\n"
            f"```\n{self._error[:500]}\n```\n\n"
            f"### 🔍 诊断分析\n\n"
            f"{self._diagnosis[:800]}\n\n"
            f"---\n\n"
            f"{self.OPTIONS_TEXT}"
        )
        md = Markdown(md_content)
        return Group(md)

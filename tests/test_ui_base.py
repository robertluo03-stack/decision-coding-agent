"""测试 Rich 终端 UI 基础框架。

覆盖：
- panels.py 导入 + 组件创建
- UIManager 生命周期（start/stop）
- update_node 状态更新正确性
- TTY 降级（force_terminal=False）

测试策略：不依赖实际终端，使用 force_terminal 参数隔离测试。
"""

from __future__ import annotations

import time
import pytest

from src.agent.ui import LogPanel, ProgressPanel, StatusTable, UIManager
from src.agent.ui.panels import ProgressPanel as PP


class TestPanelsImport:
    """面板类导入 + 基础创建测试。"""

    def test_progress_panel_import(self) -> None:
        """ProgressPanel 可导入并创建。"""
        p = ProgressPanel()
        assert p is not None
        assert len(p.task_ids) == 5
        for node in PP.NODES:
            assert node in p.task_ids

    def test_status_table_import(self) -> None:
        """StatusTable 可导入并创建，默认状态为"等待"。"""
        s = StatusTable()
        assert s is not None
        for node in PP.NODES:
            info = s.nodes[node]
            assert info["status"] == "等待"
            assert info["elapsed"] == 0.0
            assert info["retry"] == 0

    def test_log_panel_import(self) -> None:
        """LogPanel 可导入并创建，初始为空。"""
        l = LogPanel()
        assert l is not None
        assert len(l.logs) == 0

    def test_progress_panel_update(self) -> None:
        """进度条更新不抛异常。"""
        p = ProgressPanel()
        p.update("Planner", completed=True)
        p.update("Coder", completed=False)
        # 未知节点不报错
        p.update("Unknown", completed=True)

    def test_status_table_update(self) -> None:
        """状态表更新后字段正确。"""
        s = StatusTable()
        s.update("Planner", "完成", 1.5, retry=0)
        info = s.nodes["Planner"]
        assert info["status"] == "完成"
        assert info["elapsed"] == 1.5
        assert info["retry"] == 0

        s.update("Coder", "错误", 0.8, retry=1)
        info = s.nodes["Coder"]
        assert info["status"] == "错误"
        assert info["retry"] == 1

    def test_log_panel_add_and_truncation(self) -> None:
        """日志添加 + 超 50 条截断。"""
        l = LogPanel()
        for i in range(55):
            l.add(f"Log {i}", level="info")
        assert len(l.logs) == 50
        assert l.logs[0][0] == "Log 5"  # 前 5 条被截断
        assert l.logs[-1][0] == "Log 54"
        # 验证不同日志级别
        l.add("warn msg", "warning")
        l.add("err msg", "error")
        assert l.logs[-2][0] == "warn msg"
        assert l.logs[-1][0] == "err msg"


class TestUIManager:
    """UIManager 生命周期 + 状态更新测试。"""

    def test_manager_lifecycle_no_tty(self) -> None:
        """非 TTY 模式 start/stop 不抛异常（无 Live）。"""
        mgr = UIManager(force_terminal=False)
        assert mgr._is_tty is False
        mgr.start()  # no-op
        mgr.stop()  # no-op

    def test_manager_lifecycle_force_tty(self) -> None:
        """TTY 模式 start/stop 不抛异常（快速关闭）。"""
        mgr = UIManager(force_terminal=True)
        assert mgr._is_tty is True
        mgr.start()
        # 给 Live 一点时间启动
        time.sleep(0.15)
        mgr.stop()

    def test_update_node_state(self) -> None:
        """update_node 后状态正确（用 _drain_queue 手动消费）。"""
        mgr = UIManager(force_terminal=False)
        mgr.update_node("Planner", "完成", 1.23, retry=0)
        mgr.update_node("Coder", "运行中", 2.50, retry=1)
        mgr._drain_queue()

        info = mgr.get_node_status("Planner")
        assert info is not None
        assert info["status"] == "完成"
        assert info["elapsed"] == 1.23
        assert info["retry"] == 0

        info = mgr.get_node_status("Coder")
        assert info is not None
        assert info["status"] == "运行中"
        assert info["elapsed"] == 2.50
        assert info["retry"] == 1

    def test_log_through_manager(self) -> None:
        """log() 后日志正确追加（_drain_queue 手动消费）。"""
        mgr = UIManager(force_terminal=False)
        mgr.log("任务开始", level="info")
        mgr.log("警告：数据缺失", level="warning")
        mgr.log("执行失败", level="error")
        mgr._drain_queue()

        logs = mgr.get_logs()
        assert len(logs) == 3
        assert logs[0] == ("任务开始", "info")
        assert logs[1] == ("警告：数据缺失", "warning")
        assert logs[2] == ("执行失败", "error")

    def test_update_node_unknown_node(self) -> None:
        """未知节点 update_node 不报错。"""
        mgr = UIManager(force_terminal=False)
        mgr.update_node("UnknownNode", "完成", 0.5, retry=0)
        mgr._drain_queue()
        # 不抛异常即可，未知节点不存储
        assert mgr.get_node_status("UnknownNode") is None

    def test_stop_then_start_again(self) -> None:
        """stop 后再 start 不报错。"""
        mgr = UIManager(force_terminal=False)
        mgr.start()
        mgr.stop()
        mgr.start()
        mgr.stop()

    def test_get_node_status_default_values(self) -> None:
        """未更新时获取节点状态，返回默认值。"""
        mgr = UIManager(force_terminal=False)
        for node in PP.NODES:
            info = mgr.get_node_status(node)
            assert info is not None
            assert info["status"] == "等待"
            assert info["elapsed"] == 0.0
            assert info["retry"] == 0

    def test_multiple_updates_last_wins(self) -> None:
        """同一节点多次 update，最后一次生效。"""
        mgr = UIManager(force_terminal=False)
        mgr.update_node("Coder", "运行中", 1.0, retry=0)
        mgr.update_node("Coder", "完成", 3.0, retry=1)
        mgr._drain_queue()

        info = mgr.get_node_status("Coder")
        assert info is not None
        assert info["status"] == "完成"
        assert info["elapsed"] == 3.0
        assert info["retry"] == 1

    def test_log_truncation_regression(self) -> None:
        """验证 log() 通过 queue → _drain_queue 后 LogPanel 截断正常。"""
        mgr = UIManager(force_terminal=False)
        for i in range(60):
            mgr.log(f"Log {i}")
        mgr._drain_queue()

        logs = mgr.get_logs()
        assert len(logs) == 50
        assert logs[0][0] == "Log 10"
        assert logs[-1][0] == "Log 59"

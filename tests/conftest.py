"""Pytest 公共 fixtures — 环境隔离与 E2E 稳定性保障。

为所有测试提供统一的环境隔离，防止全局 .env 中的 USE_DOCKER / USE_COMPOSE /
USE_MCP 等设置影响 E2E 测试的执行路径选择。

Fixture 清单:
    - force_subprocess_env: autouse，强制 Executor 走 subprocess 路径
    - mock_debugger_input: E2E 测试中 mock _safe_input 默认 side_effect=["1","4"]
"""

import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def force_subprocess_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 Executor 使用 subprocess 路径，隔离全局 .env 干扰。

    问题背景（2026-07-21 踩坑）:
        全局 .env 中若存在 USE_DOCKER=true / USE_COMPOSE=true / USE_MCP=true，
        Executor 会选择非 subprocess 路径。在 Docker 容器内 import src 失败，
        触发 Debugger 的 input() → pytest stdin 捕获 → OSError。

    此 fixture 通过 monkeypatch 固定以下环境变量为 false/空值，
    确保所有测试统一走 subprocess 本地执行路径:
        - USE_DOCKER=false
        - USE_COMPOSE=false
        - USE_MCP=false
        - SANDBOX_URL=""
    """
    monkeypatch.setenv("USE_DOCKER", "false")
    monkeypatch.setenv("USE_COMPOSE", "false")
    monkeypatch.setenv("USE_MCP", "false")
    monkeypatch.setenv("SANDBOX_URL", "")


@pytest.fixture
def mock_debugger_input():
    """Mock _safe_input 防止 pytest stdin 捕获冲突。

    E2E 测试中若代码执行出错，Debugger 节点会调用 _safe_input()
    读取用户选择。在 pytest 下 input() 可能因 stdin 捕获而抛 OSError。

    默认策略 ["1", "4"]：第一次返回 "1"（接受 AI 修复），给调试回路
    一次自愈机会；第二次返回 "4"（中止），防止死循环。
    测试可按需覆盖 side_effect。

    使用方式:
        def test_xxx(mock_debugger_input):
            mock_debugger_input.side_effect = ["1"]  # 始终接受 AI 修复
            result = _invoke(query)

        def test_yyy(mock_debugger_input):
            mock_debugger_input.side_effect = ["4"]  # 直接中止（负路径）
            result = _invoke(query)
    """
    with patch("src.agent.nodes.debugger._safe_input", side_effect=["1", "4"]) as mock:
        yield mock

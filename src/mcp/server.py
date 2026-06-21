"""MCP Server — DecisionCoder 工具层入口。

通过 MCP 协议暴露 File I/O、Python 执行、Shell 等工具。
Week 1 版本用 Python 函数直接调用，Week 3+ 接入完整 MCP SDK。
"""

from loguru import logger


def create_mcp_server():
    """创建并返回 MCP Server 实例。

    TODO: Week 3 接入 mcp.server.stdio
    """
    logger.info("MCP Server initialized (stub — Week 3 integration)")
    return _StubMCPServer()


class _StubMCPServer:
    """MCP Server 占位实现。"""
    def __init__(self):
        self.tools = {
            "file_read": {"description": "读取文件内容"},
            "file_write": {"description": "写入文件"},
            "python_exec": {"description": "在沙箱中执行 Python 代码"},
            "shell_exec": {"description": "执行受限 Shell 命令"},
        }

    def list_tools(self) -> list[str]:
        return list(self.tools.keys())

    def run(self):
        logger.info("MCP Server running (stub)")

"""MCP Server — DecisionCoder 工具层入口。

通过 MCP 协议暴露 File I/O、Python 执行等工具。
Week 2 版本：接入 mcp SDK，使用 FastMCP 注册工具并支持 stdio transport。
"""

from loguru import logger

from mcp.server import FastMCP

from src.mcp.tools.file_tools import (
    file_exists,
    list_dir,
    read_csv,
    read_file,
    write_file,
)
from src.mcp.tools.python_tools import execute_python

# ---------------------------------------------------------------------------
# MCP Server 实例
# ---------------------------------------------------------------------------

server = FastMCP(
    name="decision-coder",
    instructions=(
        "DecisionCoder 是一个面向经营决策与运筹优化的垂直 Coding Agent。"
        "提供文件读写、Python 沙箱执行等工具。"
    ),
)


# ---------------------------------------------------------------------------
# Tool 注册
# ---------------------------------------------------------------------------
# FastMCP @server.tool() 装饰器自动从函数签名推断 inputSchema（JSON Schema），
# 从 return type 推断 outputSchema，无需手动编写 schema 定义。


@server.tool(name="file_read", description="读取文件内容，支持 CSV / JSON / TXT / MD / LOG 等格式")
def tool_file_read(filepath: str, fmt: str | None = None) -> str:
    """读取文件内容，根据后缀自动推断格式。

    无后缀且未指定 fmt 时拒绝读取，避免误读二进制文件。
    所有路径操作限定在工作区范围内，禁止 .. 穿越。

    Args:
        filepath: 文件路径（相对 workspace 或绝对路径）
        fmt: 强制指定格式（"csv" | "json" | "txt"），为空则根据后缀自动推断

    Returns:
        文件内容字符串（CSV/JSON 会格式化为缩进后的文本）
    """
    return read_file(filepath, fmt)


@server.tool(name="file_write", description="写入文件内容，自动创建父目录，支持覆盖保护")
def tool_file_write(filepath: str, content: str, overwrite: bool = True) -> str:
    """写入文件，自动创建父目录。

    所有路径操作限定在工作区范围内，禁止 .. 穿越。

    Args:
        filepath: 文件路径（相对 workspace 或绝对路径）
        content: 要写入的文本内容
        overwrite: 是否允许覆盖已有文件（默认 true）

    Returns:
        确认消息
    """
    return write_file(filepath, content, overwrite=overwrite)


@server.tool(name="file_read_csv", description="读取 CSV 文件，返回结构化的 JSON 字符串")
def tool_file_read_csv(filepath: str) -> str:
    """读取 CSV 文件，返回 JSON 字符串。

    列名从 CSV header 读取，每行映射为一个 JSON 对象。
    所有路径操作限定在工作区范围内。

    Args:
        filepath: CSV 文件路径

    Returns:
        JSON 字符串，格式: [{"col1": "val1", ...}, ...]
    """
    return read_csv(filepath)


@server.tool(name="file_list_dir", description="列出目录内容，返回文件/子目录清单")
def tool_file_list_dir(dirpath: str = ".") -> str:
    """列出目录内容。

    所有路径操作限定在工作区范围内。

    Args:
        dirpath: 目录路径（相对 workspace，默认 "." 即工作区根目录）

    Returns:
        JSON 字符串，包含 dir 路径和 entries 列表
    """
    return list_dir(dirpath)


@server.tool(name="file_exists", description="检查文件或目录是否存在")
def tool_file_exists(filepath: str) -> str:
    """检查文件或目录是否存在。

    所有路径操作限定在工作区范围内，禁止 .. 穿越。

    Args:
        filepath: 文件路径（相对 workspace 或绝对路径）

    Returns:
        JSON 字符串，格式: {"exists": true|false, "filepath": "<绝对路径>"}
    """
    return file_exists(filepath)


@server.tool(name="python_exec", description="在沙箱中安全执行 Python 代码，30 秒超时，保留临时文件用于调试")
def tool_python_exec(code: str, timeout: int = 30, workspace_path: str | None = None) -> dict:
    """在沙箱中执行 Python 代码。

    安全检查精确匹配，只拦截 os.system / subprocess / eval / exec / __import__ 等
    危险调用；合法文件操作（如 open('data.csv')）不再被误杀。
    临时文件保留在 workspace/src/_dc_exec_<uuid>.py 便于调试回溯。

    Args:
        code: Python 源代码
        timeout: 超时秒数（默认 30）
        workspace_path: 工作区根目录（默认从环境变量 WORKSPACE_PATH 读取）

    Returns:
        {"stdout": str, "stderr": str, "success": bool, "file_path": str}
    """
    return execute_python(code, timeout=timeout, workspace_path=workspace_path)


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("DecisionCoder MCP Server 启动 (stdio transport)")
    # run() 是同步函数，内部通过 anyio.run() 启动异步事件循环
    # transport="stdio" 使 Server 通过标准输入/输出与 MCP Client 通信
    server.run(transport="stdio")

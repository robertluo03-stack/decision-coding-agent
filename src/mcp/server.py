"""MCP Server — DecisionCoder 工具层入口。

通过 MCP 协议暴露 File I/O、Python 执行等工具。
Week 2 版本：接入 mcp SDK，使用 FastMCP 注册工具并支持 stdio transport。
"""

from loguru import logger

from mcp.server import FastMCP

from src.mcp.tools.file_tools import read_csv, read_file, write_file
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

    Args:
        filepath: 文件路径（绝对路径或相对路径）
        fmt: 强制指定格式（"csv" | "json" | "txt"），为空则根据文件后缀自动推断

    Returns:
        文件内容字符串（CSV/JSON 会格式化为缩进后的文本）
    """
    return read_file(filepath, fmt)


@server.tool(name="file_write", description="写入文件内容，自动创建父目录")
def tool_file_write(filepath: str, content: str) -> str:
    """写入文件，自动创建父目录。

    Args:
        filepath: 文件路径
        content: 要写入的文本内容

    Returns:
        确认消息
    """
    write_file(filepath, content)
    return f"OK: 已写入 {filepath}"


@server.tool(name="file_read_csv", description="读取 CSV 文件，返回结构化的行列表")
def tool_file_read_csv(filepath: str) -> list[dict[str, str]]:
    """读取 CSV 文件，返回字典列表。

    Args:
        filepath: CSV 文件路径

    Returns:
        字典列表，每行一个 dict（key 为列名，value 为字符串）
    """
    return read_csv(filepath)


@server.tool(name="python_exec", description="在沙箱中安全执行 Python 代码，30 秒超时")
def tool_python_exec(code: str, timeout: int = 30) -> dict:
    """在沙箱中执行 Python 代码。

    安全检查会拦截 os.system / subprocess / eval / exec / __import__ 等危险调用。

    Args:
        code: Python 源代码
        timeout: 超时秒数（默认 30）

    Returns:
        {"stdout": str, "stderr": str, "success": bool}
    """
    return execute_python(code, timeout)


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("DecisionCoder MCP Server 启动 (stdio transport)")
    # run() 是同步函数，内部通过 anyio.run() 启动异步事件循环
    # transport="stdio" 使 Server 通过标准输入/输出与 MCP Client 通信
    server.run(transport="stdio")

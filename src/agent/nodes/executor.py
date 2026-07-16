"""Executor 节点：在沙箱中安全执行生成的 Python 代码。

功能：
  1. 危险代码预检（os.system / subprocess / eval / exec / __import__）
  2. 语法错误预检（SyntaxError compile check）
  3. subprocess 隔离执行，30 秒超时
  4. 捕获 stdout / stderr

Week 2：支持通过 MCP Client 调用 python_exec Tool（USE_MCP=true）。
Week 7：支持通过 Docker Compose Sandbox HTTP 执行（SANDBOX_URL / USE_COMPOSE）。
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from loguru import logger

from src.agent.state import AgentState
from src.agent.sandbox.security_checker import check_code_safety

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

EXECUTION_TIMEOUT = 30  # 秒

# 已迁移到 src/agent/sandbox/security_checker.py — AST 语法级检查。
# 保留 _has_dangerous_code() 作为薄兼容层，内部调用 check_code_safety()。


def _has_dangerous_code(code: str) -> bool:
    """检查代码是否包含危险模式。

    委托给统一的 AST 安全检查器。

    Args:
        code: 待执行的 Python 代码

    Returns:
        如果包含危险代码则返回 True
    """
    is_safe, _ = check_code_safety(code)
    return not is_safe


# ---------------------------------------------------------------------------
# 语法预检
# ---------------------------------------------------------------------------


def _check_syntax(code: str) -> str | None:
    """在 subprocess 执行前用 compile() 预检语法。

    Args:
        code: 待检查的 Python 代码

    Returns:
        如果语法正确返回 None，否则返回错误描述字符串
    """
    try:
        compile(code, "<executor>", "exec")
        return None
    except SyntaxError as exc:
        # 提供准确的语法错误信息（行号 + 消息）
        return f"SyntaxError at line {exc.lineno}: {exc.msg}"
    except Exception as exc:
        return f"Unexpected compile error: {exc}"


# ---------------------------------------------------------------------------
# 临时文件写入
# ---------------------------------------------------------------------------


def _write_temp_file(code: str, workspace: Path) -> Path:
    """将代码写入 workspace/src/ 下的临时 .py 文件。

    文件保留在 workspace 下以便调试（Executor 执行后保留，
    后续迭代中由 Debugger 或清理脚本处理）。

    Args:
        code: Python 代码内容
        workspace: 工作区根目录 Path

    Returns:
        写入的临时文件 Path
    """
    src_dir = workspace / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # 使用 PID + 简单计数器避免冲突
    tmp_path = src_dir / f"_dc_exec_{os.getpid()}.py"
    tmp_path.write_text(code, encoding="utf-8")
    return tmp_path


def _build_error(result: subprocess.CompletedProcess) -> str | None:
    """根据 returncode 和输出构建 error 字段。

    规则（优先级从高到低）：
      1. returncode == 0             → None（无错误）
      2. returncode != 0, stderr 非空 → stderr（保留尾部换行）
      3. returncode != 0, stdout 非空 → stdout 最后 500 字符
      4. 其它                       → "Execution failed (returncode=N)"

    这样即使生成的代码内部用 try/except + exit(1) 吞掉了异常，
    也能正确触发 route_after_executor → Debugger。

    Args:
        result: subprocess.CompletedProcess

    Returns:
        错误描述字符串，或 None
    """
    if result.returncode == 0:
        return None

    stderr = (result.stderr or "").strip()
    if stderr:
        return stderr

    stdout = (result.stdout or "").strip()
    if stdout:
        return stdout[-500:]

    return f"Execution failed (returncode={result.returncode})"


# ---------------------------------------------------------------------------
# MCP Client 执行路径（Week 2）
# ---------------------------------------------------------------------------


def _should_use_mcp() -> bool:
    """检查是否应启用 MCP 执行路径。

    环境变量 USE_MCP=true 时启用，默认 false 保持向后兼容。
    """
    return os.environ.get("USE_MCP", "").strip().lower() in ("true", "1", "yes")


async def _execute_via_mcp(
    code: str,
    workspace: Path,
) -> dict:
    """通过 MCP Client（stdio transport）调用 python_exec Tool 执行代码。

    工作流程：
      1. 启动 src.mcp.server 子进程（stdio transport）
      2. 通过 ClientSession 建立 MCP 连接
      3. 调用 python_exec Tool
      4. 将 MCP 返回结果映射回 Executor AgentState 格式

    Args:
        code: Python 源代码
        workspace: 工作区根目录

    Returns:
        {"execution_result": str|None, "error": str|None, "file_path": str|None}
    """
    import anyio
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp import ClientSession

    # MCP Server 作为子进程启动
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp.server"],
        env={
            **os.environ,
            "WORKSPACE_PATH": str(workspace),
        },
        cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
    )

    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                result = await session.call_tool(
                    "python_exec",
                    {
                        "code": code,
                        "timeout": EXECUTION_TIMEOUT,
                        "workspace_path": str(workspace),
                    },
                )

        # 解析 MCP result（content[0].text 是 JSON 字符串）
        if result.content and hasattr(result.content[0], "text"):
            try:
                data = json.loads(result.content[0].text)
            except json.JSONDecodeError:
                data = {
                    "stdout": "",
                    "stderr": f"Failed to parse MCP response: {result.content[0].text[:200]}",
                    "success": False,
                    "file_path": None,
                }
        else:
            data = {"stdout": "", "stderr": "Empty MCP response", "success": False, "file_path": None}

        # 映射到 Executor AgentState 格式
        if data.get("success"):
            stdout = data.get("stdout", "")
            error = None  # type: str | None
        else:
            stdout = data.get("stdout", "")
            error = data.get("stderr") or "Execution failed (MCP tool returned error)"

        return {
            "execution_result": stdout if stdout else "(no output)",
            "error": error,
            "file_path": data.get("file_path"),
        }

    except ImportError as exc:
        # mcp 或 anyio 未安装 — 由调用方回退
        raise RuntimeError(f"MCP SDK 不可用: {exc}") from exc
    except Exception as exc:
        logger.error("[Executor] MCP 执行失败 | error={}", exc)
        raise


# ---------------------------------------------------------------------------
# Docker Compose Sandbox 执行路径（Week 7）
# ---------------------------------------------------------------------------


def _should_use_compose() -> bool:
    """检查是否应启用 Docker Compose Sandbox 执行路径。

    优先级最高：SANDBOX_URL > USE_COMPOSE=true > USE_MCP > USE_DOCKER > subprocess。

    Returns:
        True 如果 SANDBOX_URL 环境变量存在，或 USE_COMPOSE=true
    """
    # 检查 SANDBOX_URL（docker-compose 自动注入）
    sandbox_url = os.environ.get("SANDBOX_URL", "").strip()
    if sandbox_url:
        return True
    # 检查 USE_COMPOSE 标志
    if os.environ.get("USE_COMPOSE", "").strip().lower() in ("true", "1", "yes"):
        return True
    return False


def _execute_via_compose(
    code: str,
    workspace: Path,
) -> dict:
    """通过 Docker Compose Sandbox HTTP 服务执行代码。

    工作流程：
      1. 从 SANDBOX_URL 环境变量读取 sandbox 地址
      2. 创建 SandboxClient 实例
      3. 调用 execute() 远程执行代码
      4. 将 SandboxClient 返回格式映射为 executor AgentState 格式

    Args:
        code: Python 源代码
        workspace: 工作区根目录（compose 模式下映射到 sandbox 内 /app/workspace）

    Returns:
        {"execution_result": str|None, "error": str|None, "file_path": str|None}
    """
    from src.agent.sandbox.sandbox_client import SandboxClient, SandboxUnavailableError

    sandbox_url = os.environ.get("SANDBOX_URL", "http://sandbox:5000").strip()
    logger.info("[Executor] Compose 路径 | sandbox_url={} | code_len={}", sandbox_url, len(code))

    client = SandboxClient(base_url=sandbox_url)
    try:
        result = client.execute(code, timeout=EXECUTION_TIMEOUT)
        logger.info(
            "[Executor] Compose 路径退出 | has_error={}",
            result["error"] is not None,
        )
        return result
    except SandboxUnavailableError as exc:
        logger.error("[Executor] Compose sandbox 不可用 | error={}", exc)
        return {
            "execution_result": None,
            "error": f"Sandbox unavailable: {exc}",
            "file_path": None,
        }
    finally:
        client.close()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def executor_node(state: AgentState) -> dict:
    """在沙箱中执行 generated_code。

    执行流程（按优先级）：
        1. 空代码检查
        2. 危险代码检查
        3. 语法预检（compile）
        4a. [SANDBOX_URL / USE_COMPOSE] 通过 SandboxClient HTTP 远程执行（最高优先级）
        4b. [USE_MCP=true] 通过 MCP Client 调用 python_exec Tool
        4c. [默认] 写入临时文件 → subprocess.run 执行（向后兼容）

    输入:
        state["generated_code"]   — str，Python 代码
        state["workspace_path"]   — str，工作区绝对路径

    输出:
        {
            "execution_result":  str | None,   # stdout 内容
            "error":             str | None,   # stderr 或错误信息
            "file_path":         str | None,   # 临时文件路径
        }

    Args:
        state: 当前 AgentState

    Returns:
        包含 execution_result / error / file_path 的 partial state
    """
    code: str = state.get("generated_code", "")
    workspace_path: str = state.get("workspace_path", ".")
    workspace = Path(workspace_path)

    # ---- 入口日志 ----
    logger.info(
        "[Executor] 进入节点 | code_len={} | hash={} | workspace={}",
        len(code),
        hashlib.md5(code.encode()).hexdigest()[:8] if code else "N/A",
        workspace_path,
    )

    # ---- 1. 空代码检查 ----
    if not code or not code.strip():
        logger.warning("[Executor] 代码为空，跳过执行")
        logger.info("[Executor] 退出节点（空代码） | error={!r}", "No code to execute")
        return {
            "execution_result": None,
            "error": "No code to execute — generated_code is empty",
            "file_path": None,
        }

    # ---- 2. 危险代码检查（统一 AST 安全检查） ----
    if _has_dangerous_code(code):
        logger.warning("[Executor] 检测到危险代码，已拦截")
        logger.info("[Executor] 退出节点（危险代码） | error={!r}", "Dangerous code detected")
        return {
            "execution_result": None,
            "error": "Security: Dangerous code detected",
            "file_path": None,
        }

    # ---- 3. 语法预检 ----
    syntax_err = _check_syntax(code)
    if syntax_err is not None:
        logger.warning("[Executor] 语法预检失败 | error={!r}", syntax_err)
        logger.info("[Executor] 退出节点（语法错误） | error={!r}", syntax_err)
        return {
            "execution_result": None,
            "error": syntax_err,
            "file_path": None,
        }

    # ---- 4a. Docker Compose Sandbox 路径（最高优先级） ----
    if _should_use_compose():
        logger.info("[Executor] 使用 Compose Sandbox 路径执行代码 | code_len={}", len(code))
        try:
            result = _execute_via_compose(code, workspace)
            logger.info(
                "[Executor] Compose 路径退出 | has_error={}",
                result["error"] is not None,
            )
            return result
        except Exception as exc:
            logger.warning(
                "[Executor] Compose 路径失败（{}），回退到 subprocess 路径",
                exc,
            )

    # ---- 4b. MCP 路径（USE_MCP=true） ----
    if _should_use_mcp():
        logger.info("[Executor] 使用 MCP 路径执行代码 | code_len={}", len(code))
        try:
            import anyio
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None:
                # 已有事件循环（pytest-asyncio 场景）→ 用 run_until_complete
                import concurrent.futures
                future = asyncio.ensure_future(
                    _execute_via_mcp(code, workspace)
                )
                # 在已有循环中直接 await
                result = asyncio.get_event_loop().run_until_complete(
                    asyncio.ensure_future(_execute_via_mcp(code, workspace))
                )
            else:
                result = anyio.run(lambda: _execute_via_mcp(code, workspace))

            logger.info(
                "[Executor] MCP 路径退出 | has_error={}",
                result["error"] is not None,
            )
            return result

        except ImportError:
            # mcp / anyio 未安装 → 回退到 subprocess
            logger.warning(
                "[Executor] MCP SDK 不可用（mcp/anyio 未安装），回退到 subprocess 路径"
            )
        except Exception as exc:
            # MCP 启动失败 / 连接断开 → 回退到 subprocess
            logger.warning(
                "[Executor] MCP 路径失败（{}），回退到 subprocess 路径",
                exc,
            )

    # ---- 4c. subprocess 路径（默认 / fallback） ----
    logger.info("[Executor] 使用 subprocess 路径执行代码")

    tmp_path = _write_temp_file(code, workspace)

    # 将项目根目录注入 PYTHONPATH，确保生成的代码能 import src.domain.*
    project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
    env = {**os.environ, "PYTHONPATH": project_root}

    try:
        result = subprocess.run(
            [sys.executable, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=EXECUTION_TIMEOUT,
            cwd=str(workspace),
            stdin=subprocess.DEVNULL,  # 防止子进程继承 stdio transport pipe（Windows 兼容）
            env=env,
        )

        # 根据 returncode 和 stdout/stderr 决定 error 字段
        error = _build_error(result)

        # ---- 出口日志 ----
        logger.info(
            "[Executor] 退出节点 | file_path={} | returncode={} | stdout_len={} | has_error={}",
            str(tmp_path),
            result.returncode,
            len(result.stdout or ""),
            error is not None,
        )
        if error:
            logger.warning("[Executor] 执行有错误 | error={!r}", error[:100])

        return {
            "file_path": str(tmp_path),
            "execution_result": result.stdout if result.stdout else "(no output)",
            "error": error,
        }

    except subprocess.TimeoutExpired:
        logger.error("[Executor] 执行超时（30s）")
        logger.info("[Executor] 退出节点（超时） | file_path={}", str(tmp_path))
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": "Execution timeout (30s)",
        }
    except FileNotFoundError:
        logger.error("[Executor] Python 解释器未找到")
        logger.info("[Executor] 退出节点（解释器未找到） | file_path={}", str(tmp_path))
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": "Python interpreter not found",
        }
    except Exception as exc:
        logger.error("[Executor] 执行异常 | type={} | message={}", type(exc).__name__, exc)
        logger.info("[Executor] 退出节点（异常） | file_path={}", str(tmp_path))
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": f"Execution error: {exc}",
        }


# 别名，兼容 graph.py / Task 7 的 run(state) 约定
run = executor_node

"""Python 代码执行工具 — 基于 MCP 协议。

提供沙箱化的 Python 代码执行能力。
Week 2 版本：精确安全匹配 + 临时文件保留 + workspace_path 参数。
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

from loguru import logger

from src.agent.sandbox.security_checker import check_code_safety as _check_safety_ast

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 执行超时（秒）
DEFAULT_TIMEOUT = 30

# 语法预检使用 compile() 的模式名
COMPILE_MODE = "exec"


# ---------------------------------------------------------------------------
# 工作区路径解析
# ---------------------------------------------------------------------------


def _get_workspace() -> Path:
    """获取工作区根目录（绝对路径）。

    从环境变量 WORKSPACE_PATH 读取，默认 "./workspace" 并 resolve 为绝对路径。
    """
    raw = os.environ.get("WORKSPACE_PATH", "./workspace")
    return Path(raw).resolve()


# ---------------------------------------------------------------------------
# 安全检查（委托给统一的 AST 检查器）
# ---------------------------------------------------------------------------


def _check_code_safety(code: str) -> Optional[str]:
    """检查代码安全（委托给统一的 AST 检查器）。

    使用 src.agent.sandbox.security_checker 进行语法级 AST 分析，
    精确识别 os.system / subprocess / eval / exec / __import__ 等危险调用，
    同时允许 open('data.csv') 等合法文件操作。

    Args:
        code: Python 源代码

    Returns:
        如果安全则返回 None，否则返回拦截原因描述
    """
    is_safe, reason = _check_safety_ast(code)
    if not is_safe:
        return f"SECURITY BLOCK: {reason}"
    return None


# ---------------------------------------------------------------------------
# 语法预检
# ---------------------------------------------------------------------------


def _check_syntax(code: str) -> Optional[str]:
    """在 subprocess 执行前用 compile() 预检语法。

    Args:
        code: Python 源代码

    Returns:
        如果语法正确返回 None，否则返回错误描述字符串
    """
    try:
        compile(code, "<python_tool>", COMPILE_MODE)
        return None
    except SyntaxError as exc:
        return f"SyntaxError at line {exc.lineno}: {exc.msg}"
    except Exception as exc:
        return f"Unexpected compile error: {exc}"


# ---------------------------------------------------------------------------
# 临时文件写入（与 Executor 对齐）
# ---------------------------------------------------------------------------


def _write_exec_file(code: str, workspace: Path) -> Path:
    """将代码写入 workspace/src/_dc_exec_<uuid>.py。

    与 executor.py 的 _write_temp_file 策略对齐：
      - 写入 workspace/src/ 目录
      - 使用 uuid4 短 id 命名（避免 PID 冲突）
      - 文件保留不删除，便于 Debugger 回溯调试

    Args:
        code: Python 代码内容
        workspace: 工作区根目录

    Returns:
        写入的临时文件 Path
    """
    src_dir = workspace / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # 使用 uuid4 的短 id（8 字符）确保文件名唯一且可读
    short_id = uuid.uuid4().hex[:8]
    exec_path = src_dir / f"_dc_exec_{short_id}.py"
    exec_path.write_text(code, encoding="utf-8")
    return exec_path


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def execute_python(
    code: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    workspace_path: str | None = None,
) -> dict:
    """在沙箱中安全执行 Python 代码。

    与 executor_node 保持接口兼容：
      - 相同的安全检查（BLOCKED_PATTERNS 与 _DANGEROUS_PATTERNS 已统一）
      - 相同的语法预检（compile）
      - 相同的 subprocess.run 执行模式
      - 临时文件保留在 workspace/src/ 下

    Args:
        code: Python 源代码
        timeout: 超时秒数（默认 30）
        workspace_path: 工作区根目录（默认从环境变量 WORKSPACE_PATH 读取）

    Returns:
        {
            "stdout": str,        # 标准输出
            "stderr": str,        # 标准错误
            "success": bool,      # 是否成功执行
            "file_path": str,     # 临时文件路径（便于调试）
        }
    """
    # 解析工作区路径
    ws = Path(workspace_path).resolve() if workspace_path else _get_workspace()

    # ---- 1. 空代码检查 ----
    if not code or not code.strip():
        logger.warning("[PythonTool] 代码为空，跳过执行")
        return {
            "stdout": "",
            "stderr": "Code is empty",
            "success": False,
            "file_path": None,
        }

    # ---- 2. 安全检查 ----
    security_warning = _check_code_safety(code)
    if security_warning:
        logger.warning("[PythonTool] 安全检查拦截 | reason={}", security_warning)
        return {
            "stdout": "",
            "stderr": f"SECURITY BLOCK: {security_warning}",
            "success": False,
            "file_path": None,
        }

    # ---- 3. 语法预检 ----
    syntax_err = _check_syntax(code)
    if syntax_err is not None:
        logger.warning("[PythonTool] 语法预检失败 | error={!r}", syntax_err)
        return {
            "stdout": "",
            "stderr": syntax_err,
            "success": False,
            "file_path": None,
        }

    # ---- 4. 写入临时文件（保留在 workspace/src/，不删除） ----
    exec_path = _write_exec_file(code, ws)
    logger.info("[PythonTool] 代码写入临时文件 | path={}", exec_path)

    # ---- 5. subprocess 执行 ----
    try:
        result = subprocess.run(
            [sys.executable, str(exec_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ws),
        )

        if result.returncode == 0:
            logger.info(
                "[PythonTool] 执行成功 | path={} | stdout_len={}",
                exec_path,
                len(result.stdout or ""),
            )
        else:
            logger.warning(
                "[PythonTool] 执行失败 | path={} | returncode={} | stderr={!r}",
                exec_path,
                result.returncode,
                (result.stderr or "")[:200],
            )

        return {
            "stdout": result.stdout or "(no output)",
            "stderr": result.stderr or "",
            "success": result.returncode == 0,
            "file_path": str(exec_path),
        }

    except subprocess.TimeoutExpired:
        logger.error("[PythonTool] 执行超时（{}s）| path={}", timeout, exec_path)
        return {
            "stdout": "",
            "stderr": f"Execution timed out after {timeout} seconds",
            "success": False,
            "file_path": str(exec_path),
        }

    except FileNotFoundError:
        logger.error("[PythonTool] Python 解释器未找到")
        return {
            "stdout": "",
            "stderr": "Python interpreter not found",
            "success": False,
            "file_path": str(exec_path),
        }

    except Exception as exc:
        logger.error("[PythonTool] 执行异常 | type={} | message={}", type(exc).__name__, exc)
        return {
            "stdout": "",
            "stderr": f"Execution error: {exc}",
            "success": False,
            "file_path": str(exec_path),
        }

"""Executor 节点：在沙箱中安全执行生成的 Python 代码。

功能：
  1. 危险代码预检（os.system / subprocess / eval / exec / __import__）
  2. 语法错误预检（SyntaxError compile check）
  3. subprocess 隔离执行，30 秒超时
  4. 捕获 stdout / stderr

Week 2 计划升级为 Docker 沙箱。
"""

import os
import subprocess
import textwrap
from pathlib import Path

from src.agent.state import AgentState

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

EXECUTION_TIMEOUT = 30  # 秒

_DANGEROUS_PATTERNS: list[str] = [
    "os.system",
    "subprocess",
    "eval(",
    "exec(",
    "__import__",
]

# ---------------------------------------------------------------------------
# 安全检查
# ---------------------------------------------------------------------------


def _has_dangerous_code(code: str) -> bool:
    """检查代码是否包含危险模式。

    Args:
        code: 待执行的 Python 代码

    Returns:
        如果包含危险代码则返回 True
    """
    return any(pattern in code for pattern in _DANGEROUS_PATTERNS)


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


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def executor_node(state: AgentState) -> dict:
    """在沙箱中执行 generated_code。

    执行流程：
        1. 空代码检查
        2. 危险代码检查
        3. 语法预检（compile）
        4. 写入临时文件
        5. subprocess.run 执行（30s 超时，cwd=workspace_path）

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

    # ---- 1. 空代码检查 ----
    if not code or not code.strip():
        return {
            "execution_result": None,
            "error": "No code to execute — generated_code is empty",
            "file_path": None,
        }

    # ---- 2. 危险代码检查 ----
    if _has_dangerous_code(code):
        return {
            "execution_result": None,
            "error": "Security: Dangerous code detected",
            "file_path": None,
        }

    # ---- 3. 语法预检 ----
    syntax_err = _check_syntax(code)
    if syntax_err is not None:
        return {
            "execution_result": None,
            "error": syntax_err,
            "file_path": None,
        }

    # ---- 4. 写入临时文件 ----
    tmp_path = _write_temp_file(code, workspace)

    # ---- 5. subprocess 执行 ----
    try:
        result = subprocess.run(
            ["python", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=EXECUTION_TIMEOUT,
            cwd=str(workspace),
        )

        return {
            "file_path": str(tmp_path),
            "execution_result": result.stdout if result.stdout else "(no output)",
            "error": result.stderr if result.stderr else None,
        }

    except subprocess.TimeoutExpired:
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": "Execution timeout (30s)",
        }
    except FileNotFoundError:
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": "Python interpreter not found",
        }
    except Exception as exc:
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": f"Execution error: {exc}",
        }


# 别名，兼容 graph.py / Task 7 的 run(state) 约定
run = executor_node

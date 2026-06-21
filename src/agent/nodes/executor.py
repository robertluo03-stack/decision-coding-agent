"""Executor 节点：在沙箱中执行生成的 Python 代码。"""

import os
import subprocess
import tempfile
import textwrap
from pathlib import Path

from loguru import logger

from src.agent.state import AgentState

EXECUTION_TIMEOUT = 30  # 秒


def executor_node(state: AgentState) -> dict:
    """将 generated_code 写入临时文件并执行。

    捕获 stdout/stderr，30 秒超时。Week 2 将替换为 Docker 沙箱。

    Args:
        state: 当前 AgentState

    Returns:
        包含 file_path, execution_result, error 的 partial state
    """
    code = state["generated_code"]
    workspace = Path(state["workspace_path"])

    if not code.strip():
        return {
            "execution_result": None,
            "error": "No code to execute — generated_code is empty",
            "file_path": None,
        }

    # 写入临时文件
    tmp_path = workspace / "src" / f"_dc_temp_{os.getpid()}.py"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(code, encoding="utf-8")

    logger.info(f"Executing: {tmp_path}")

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
        logger.warning(f"Execution timed out after {EXECUTION_TIMEOUT}s")
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": f"Execution timed out after {EXECUTION_TIMEOUT} seconds",
        }
    except FileNotFoundError:
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": "Python interpreter not found",
        }
    except Exception as e:
        logger.error(f"Execution error: {e}")
        return {
            "file_path": str(tmp_path),
            "execution_result": None,
            "error": str(e),
        }

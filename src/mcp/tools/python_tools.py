"""Python 代码执行工具 — 基于 MCP 协议。

提供沙箱化的 Python 代码执行能力。
Week 1: subprocess 临时文件执行
Week 2: Docker 沙箱替换
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from loguru import logger

# 执行超时（秒）
DEFAULT_TIMEOUT = 30

# 禁止的模块/关键字（Week 2 强化）
BLOCKED_KEYWORDS = [
    "os.system", "subprocess", "shutil.rmtree",
    "__import__", "eval(", "exec(",
    "open(",  # 过于宽泛，暂时保留，周2细化
]


def execute_python(code: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """在沙箱中执行 Python 代码。

    Args:
        code: Python 源代码
        timeout: 超时秒数

    Returns:
        {"stdout": str, "stderr": str, "success": bool}
    """
    # 安全检查
    security_warning = _check_code_safety(code)
    if security_warning:
        return {
            "stdout": "",
            "stderr": f"SECURITY BLOCK: {security_warning}",
            "success": False,
        }

    # 写入临时文件并执行
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["python", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Execution timed out after {timeout} seconds",
            "success": False,
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _check_code_safety(code: str) -> Optional[str]:
    """简单的代码安全检查（Week 1 版本）。

    Week 2: 用 ast 模块做更细粒度的安全检查。
    Week 3: Docker 沙箱隔离后降低强度。
    """
    for keyword in BLOCKED_KEYWORDS:
        if keyword in code:
            return f"Blocked keyword detected: {keyword}"
    return None

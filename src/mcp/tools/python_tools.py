"""Python 代码执行工具 — 基于 MCP 协议。

提供沙箱化的 Python 代码执行能力。
Week 2 版本：精确安全匹配 + 临时文件保留 + workspace_path 参数 + Docker 沙箱支持。

执行路径（由环境变量 USE_DOCKER 控制）:
  - USE_DOCKER=false  → subprocess 直接执行（Week 1 默认方式）
  - USE_DOCKER=true   → DockerRunner 容器沙箱执行（Docker 不可用时自动回退）
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
# Docker 执行开关
# ---------------------------------------------------------------------------


def _should_use_docker() -> bool:
    """检查是否应启用 Docker 沙箱执行。

    环境变量 USE_DOCKER=true 且 Docker 守护进程可访问时启用。
    """
    # 检查当前进程是否处于 docker 容器内 — 容器内执行 docker run 通常是
    # 不被允许的（DinD 需特权模式），此时跳过 Docker 路径避免无意义的尝试。
    if _running_in_docker():
        logger.info("[PythonTool] 当前在容器内运行，跳过 Docker 路径")
        return False
    return os.environ.get("USE_DOCKER", "").strip().lower() in ("true", "1", "yes")


def _running_in_docker() -> bool:
    """检测当前进程是否运行在 Docker 容器内。

    检查 /.dockerenv 文件存在性（Docker 创建此文件标识容器环境）。
    """
    try:
        return Path("/.dockerenv").exists()
    except OSError:
        return False


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
# Docker 执行路径
# ---------------------------------------------------------------------------


def _execute_via_docker(
    code: str,
    workspace: Path,
    timeout: int,
) -> dict:
    """通过 DockerRunner 容器沙箱执行 Python 代码。

    工作流程：
      1. 创建 DockerRunner 实例
      2. 调用 run() 在隔离容器中执行
      3. 将 DockerRunner 返回格式映射为 execute_python 统一格式

    Args:
        code: Python 源代码
        workspace: 工作区根目录
        timeout: 执行超时秒数

    Returns:
        {"stdout": str, "stderr": str, "success": bool, "file_path": str}
    """
    from src.agent.sandbox.docker_runner import DockerRunner

    runner = DockerRunner(workspace_path=str(workspace))
    result = runner.run(code, timeout=timeout)

    # 映射 DockerRunner.run() 返回 → execute_python 统一格式
    # DockerRunner 约定: returncode=0 成功，-1 基础设施错误
    # execute_python 约定: success=True/False, stdout 空时填充 "(no output)"
    success = result["returncode"] == 0
    stdout = result["stdout"] or "(no output)"
    stderr = result.get("stderr") or ""

    logger.info(
        "[PythonTool] Docker 执行完成 | success={} | stdout_len={} | stderr_len={}",
        success,
        len(stdout),
        len(stderr),
    )

    return {
        "stdout": stdout,
        "stderr": stderr,
        "success": success,
        "file_path": result.get("file_path", str(workspace / "src")),
    }


def _execute_via_docker_with_fallback(
    code: str,
    workspace: Path,
    timeout: int,
) -> dict:
    """尝试 Docker 执行，不可用时回退到 subprocess。

    回退触发条件（任一满足即回退）:
      - Docker 未安装（FileNotFoundError / returncode=-1 + "未安装"）
      - Docker daemon 未运行
      - DockerRunner 初始化失败

    Args:
        code: Python 源代码
        workspace: 工作区根目录
        timeout: 执行超时秒数

    Returns:
        {"stdout": str, "stderr": str, "success": bool, "file_path": str}
    """
    try:
        result = _execute_via_docker(code, workspace, timeout)

        # Docker 不可用 → 返回的 stderr 会包含 "Docker 未安装" 等提示
        if result["stderr"] and (
            "未安装" in result["stderr"]
            or "Docker daemon" in result["stderr"]
            or "docker 命令不可用" in result["stderr"]
        ):
            logger.warning(
                "[PythonTool] Docker 不可用，回退到 subprocess | reason={}",
                result["stderr"][:150],
            )
            return _execute_via_subprocess(code, workspace, timeout)

        return result

    except ImportError as exc:
        # DockerRunner 模块导入失败（极端情况）
        logger.warning("[PythonTool] DockerRunner 导入失败（{}），回退到 subprocess", exc)
        return _execute_via_subprocess(code, workspace, timeout)
    except Exception as exc:
        # Docker 执行本身异常（如镜像不存在、挂载失败等）
        logger.warning("[PythonTool] Docker 执行异常，回退到 subprocess | error={}", exc)
        return _execute_via_subprocess(code, workspace, timeout)


# ---------------------------------------------------------------------------
# subprocess 执行路径（Week 1 默认，Docker 回退）
# ---------------------------------------------------------------------------


def _execute_via_subprocess(
    code: str,
    workspace: Path,
    timeout: int,
) -> dict:
    """通过 subprocess 在本地执行 Python 代码（Week 1 方式）。

    写入临时文件 → subprocess.run → 返回结构化结果。

    Args:
        code: Python 源代码
        workspace: 工作区根目录
        timeout: 执行超时秒数

    Returns:
        {"stdout": str, "stderr": str, "success": bool, "file_path": str}
    """
    # 写入临时文件（保留在 workspace/src/，不删除）
    exec_path = _write_exec_file(code, workspace)
    logger.info("[PythonTool] 代码写入临时文件 | path={}", exec_path)

    try:
        result = subprocess.run(
            [sys.executable, str(exec_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace),
            stdin=subprocess.DEVNULL,
        )

        if result.returncode == 0:
            logger.info(
                "[PythonTool] subprocess 执行成功 | path={} | stdout_len={}",
                exec_path,
                len(result.stdout or ""),
            )
        else:
            logger.warning(
                "[PythonTool] subprocess 执行失败 | path={} | returncode={} | stderr={!r}",
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
        logger.error("[PythonTool] subprocess 执行超时（{}s）| path={}", timeout, exec_path)
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
        logger.error("[PythonTool] subprocess 执行异常 | type={} | message={}",
                     type(exc).__name__, exc)
        return {
            "stdout": "",
            "stderr": f"Execution error: {exc}",
            "success": False,
            "file_path": str(exec_path),
        }


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
      - 相同的安全检查（AST 语法级分析）
      - 相同的语法预检（compile）
      - USE_DOCKER=true 时 Docker 容器沙箱执行（自动回退）
      - USE_DOCKER=false 时 subprocess 直接执行（Week 1 默认）
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

    # ---- 4. 执行（Docker 或 subprocess） ----
    if _should_use_docker():
        logger.info("[PythonTool] 使用 Docker 沙箱执行 | code_len={}", len(code))
        return _execute_via_docker_with_fallback(code, ws, timeout)

    logger.info("[PythonTool] 使用 subprocess 执行 | code_len={}", len(code))
    return _execute_via_subprocess(code, ws, timeout)

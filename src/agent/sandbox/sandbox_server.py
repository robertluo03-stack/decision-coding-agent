"""Sandbox HTTP 执行服务器 — 在隔离容器中运行，提供 POST /execute 端点。

此模块运行在 Docker 沙箱容器内部，不依赖 Agent 层库（langchain/deepseek/rich/loguru）。
仅依赖 Flask + 标准库 + 复用 security_checker.py 的 AST 安全检查。

端点：
  POST /execute  —  接收 {"code": "...", "timeout": 30}
                   返回 {"stdout": "...", "stderr": "...", "returncode": N}
"""

import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from flask import Flask, jsonify, request

from security_checker import check_code_safety

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 60  # 客户端不可请求超过此值
LISTEN_PORT = 5000

app = Flask(__name__)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _check_syntax(code: str) -> str | None:
    """在 subprocess 执行前用 compile() 预检语法。

    Args:
        code: 待检查的 Python 代码

    Returns:
        如果语法正确返回 None，否则返回错误描述字符串
    """
    try:
        compile(code, "<sandbox>", "exec")
        return None
    except SyntaxError as exc:
        return f"SyntaxError at line {exc.lineno}: {exc.msg}"
    except Exception as exc:
        return f"Unexpected compile error: {exc}"


def _execute_code(code: str, timeout: int) -> dict:
    """在子进程中执行 Python 代码并返回结构化结果。

    执行流程：
      1. 写入临时文件
      2. subprocess.run 执行，带超时控制
      3. 返回 stdout / stderr / returncode

    Args:
        code: Python 源代码
        timeout: 执行超时秒数

    Returns:
        {"stdout": str, "stderr": str, "returncode": int}
    """
    # 写入临时文件
    tmp_path = Path(tempfile.gettempdir()) / "_sandbox_exec.py"
    tmp_path.write_text(code, encoding="utf-8")

    try:
        result = subprocess.run(
            [sys.executable, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(tempfile.gettempdir())),
            stdin=subprocess.DEVNULL,
        )

        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Execution timed out after {timeout} seconds",
            "returncode": -1,
        }
    except Exception as exc:
        return {
            "stdout": "",
            "stderr": f"Execution error: {exc}",
            "returncode": -1,
        }


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------


@app.route("/health", methods=["GET"])
def health():
    """健康检查端点 — 用于 docker-compose depends_on 的 healthcheck。"""
    return jsonify({"status": "ok"})


@app.route("/execute", methods=["POST"])
def execute():
    """执行 Python 代码的 HTTP 端点。

    请求体 JSON:
        {"code": "...", "timeout": 30}

    响应体 JSON:
        {"stdout": "...", "stderr": "...", "returncode": N}

    安全流程:
        1. 参数验证
        2. AST 安全检查（复用 security_checker.py）
        3. 语法预检（compile）
        4. subprocess 隔离执行
    """
    # ---- 1. 解析请求 ----
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({
            "stdout": "",
            "stderr": "Invalid JSON in request body",
            "returncode": -1,
        }), 400

    if not data or "code" not in data:
        return jsonify({
            "stdout": "",
            "stderr": "Missing required field: 'code'",
            "returncode": -1,
        }), 400

    code: str = data["code"]
    timeout: int = min(int(data.get("timeout", DEFAULT_TIMEOUT)), MAX_TIMEOUT)

    # ---- 2. 空代码检查 ----
    if not code or not code.strip():
        return jsonify({
            "stdout": "",
            "stderr": "Code is empty",
            "returncode": -1,
        }), 400

    # ---- 3. AST 安全检查（复用统一安全检查器） ----
    is_safe, reason = check_code_safety(code)
    if not is_safe:
        return jsonify({
            "stdout": "",
            "stderr": f"SECURITY BLOCK: {reason}",
            "returncode": -1,
        }), 403

    # ---- 4. 语法预检 ----
    syntax_err = _check_syntax(code)
    if syntax_err is not None:
        return jsonify({
            "stdout": "",
            "stderr": syntax_err,
            "returncode": -1,
        }), 400

    # ---- 5. 执行 ----
    try:
        result = _execute_code(code, timeout)
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({
            "stdout": "",
            "stderr": f"Server error: {exc}",
            "returncode": -1,
        }), 500


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[SandboxServer] 启动在 0.0.0.0:{LISTEN_PORT}")
    # Flask 开发服务器 — 仅用于容器内部通信，不暴露到宿主机
    app.run(host="0.0.0.0", port=LISTEN_PORT, debug=False)

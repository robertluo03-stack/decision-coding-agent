"""Sandbox HTTP 客户端 — 通过 HTTP 调用远程沙箱执行 Python 代码。

用于 docker-compose 编排模式：主 Agent 通过 HTTP 向 sandbox 容器发送代码，
sandbox 在隔离环境中执行并返回结果。

与 executor.py 的接口兼容性：
  - execute() 返回 dict 含 {"execution_result", "error", "file_path"}
  - 内部将 HTTP JSON 响应映射为 executor 期望的 AgentState 格式
"""

from __future__ import annotations

import os
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# 异常定义
# ---------------------------------------------------------------------------


class SandboxUnavailableError(Exception):
    """Sandbox HTTP 服务不可用时抛出。

    可能原因：
      - sandbox 容器未启动或已崩溃
      - 网络连接失败
      - sandbox 返回非 200 状态码
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# SandboxClient
# ---------------------------------------------------------------------------


class SandboxClient:
    """与远程 sandbox HTTP 服务通信的客户端。

    使用方式:
        client = SandboxClient(base_url="http://sandbox:5000")
        result = client.execute("print('hello')")
        # result = {"execution_result": "hello\\n", "error": None, "file_path": None}

    Attributes:
        base_url: sandbox HTTP 服务地址
        timeout: HTTP 请求超时秒数（默认 timeout_seconds + 5 缓冲）
    """

    def __init__(self, base_url: str = "http://localhost:5000") -> None:
        """初始化 SandboxClient。

        Args:
            base_url: sandbox HTTP 服务地址。
                      默认 "http://localhost:5000"（本地开发）。
                      docker-compose 下应设为 "http://sandbox:5000"。
        """
        self.base_url: str = base_url.rstrip("/")
        self._session: requests.Session = requests.Session()

    # ------------------------------------------------------------------
    # HTTP 请求
    # ------------------------------------------------------------------

    def _post_execute(self, code: str, timeout: int) -> dict:
        """向 sandbox 发送 POST /execute 请求。

        Args:
            code: Python 源代码
            timeout: 代码执行超时秒数

        Returns:
            sandbox HTTP 响应 JSON（{"stdout", "stderr", "returncode"}）

        Raises:
            SandboxUnavailableError: 连接失败或非 200 响应
        """
        # HTTP 层超时 = 代码执行超时 + 网络缓冲（5s）
        http_timeout = timeout + 5

        try:
            response = self._session.post(
                f"{self.base_url}/execute",
                json={"code": code, "timeout": timeout},
                timeout=http_timeout,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code != 200:
                # 尝试提取 sandbox 返回的错误信息
                try:
                    body = response.json()
                    detail = body.get("stderr", response.text)
                except Exception:
                    detail = response.text[:500]
                raise SandboxUnavailableError(
                    f"Sandbox returned HTTP {response.status_code}: {detail}",
                    status_code=response.status_code,
                )

            return response.json()

        except requests.ConnectionError as exc:
            raise SandboxUnavailableError(
                f"无法连接到 sandbox ({self.base_url}): {exc}"
            ) from exc
        except requests.Timeout as exc:
            raise SandboxUnavailableError(
                f"Sandbox 请求超时（{http_timeout}s）: {exc}"
            ) from exc
        except requests.RequestException as exc:
            raise SandboxUnavailableError(
                f"Sandbox HTTP 请求失败: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # 公开 API — 与 executor 接口兼容
    # ------------------------------------------------------------------

    def execute(self, code: str, timeout: int = 30) -> dict:
        """向 sandbox 发送代码并返回 executor 兼容的结果。

        返回格式与 executor_node() 兼容：
            {
                "execution_result": str | None,   # stdout 内容
                "error":             str | None,   # stderr 或错误信息
                "file_path":         str | None,   # sandbox 路径下无本地文件
            }

        Args:
            code: 待执行的 Python 源代码
            timeout: 执行超时秒数（默认 30）

        Returns:
            与 executor_node() 兼容的 dict

        Raises:
            SandboxUnavailableError: sandbox 不可用
        """
        result = self._post_execute(code, timeout)

        returncode: int = result.get("returncode", -1)
        stdout: str = result.get("stdout", "")
        stderr: str = result.get("stderr", "")

        # 映射到 executor AgentState 格式
        if returncode == 0:
            execution_result = stdout if stdout else "(no output)"
            error = None  # type: str | None
        else:
            execution_result = stdout if stdout else None
            error = stderr if stderr else f"Execution failed (returncode={returncode})"

        return {
            "execution_result": execution_result,
            "error": error,
            "file_path": None,  # sandbox 内部文件路径对宿主机不可见
        }

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """检查 sandbox 服务是否健康运行。

        Returns:
            True 如果 sandbox /health 端点返回 200
        """
        try:
            response = self._session.get(
                f"{self.base_url}/health",
                timeout=5,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭 HTTP 会话。"""
        self._session.close()

    def __enter__(self) -> "SandboxClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


# ---------------------------------------------------------------------------
# 便捷函数：从环境变量构建客户端
# ---------------------------------------------------------------------------


def create_client_from_env() -> SandboxClient:
    """从环境变量 SANDBOX_URL 创建 SandboxClient。

    如果 SANDBOX_URL 未设置，使用默认值 "http://localhost:5000"。

    Returns:
        配置好的 SandboxClient 实例
    """
    base_url = os.environ.get("SANDBOX_URL", "http://localhost:5000")
    return SandboxClient(base_url=base_url)

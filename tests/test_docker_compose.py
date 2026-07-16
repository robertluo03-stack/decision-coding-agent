"""Docker Compose 编排测试套件。

覆盖场景：
  1. SandboxClient mock — 验证 HTTP 调用逻辑
  2. SandboxClient fallback — sandbox 返回 500 时验证异常类型
  3. Executor compose 路径 — mock SandboxClient 验证新分支被触发
  4. Executor compose 优先级 — SANDBOX_URL 优先于 USE_MCP
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0
_failures: list[str] = []


def _check(condition: bool, name: str, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✅ {name}")
    else:
        _failed += 1
        _failures.append(f"{name}: {detail}")
        print(f"  ❌ {name}  —  {detail}")


# ===================================================================
# 测试 1 — SandboxClient mock: 正常执行
# ===================================================================


def test_sandbox_client_mock() -> None:
    """mock requests.post 验证 SandboxClient 调用逻辑。"""
    print("\n[1] SandboxClient mock — 正常执行")

    from src.agent.sandbox.sandbox_client import SandboxClient

    with mock.patch("src.agent.sandbox.sandbox_client.requests.Session.post") as mock_post:
        # 模拟 sandbox 成功返回
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "stdout": "hello\n",
            "stderr": "",
            "returncode": 0,
        }

        client = SandboxClient(base_url="http://sandbox:5000")
        result = client.execute("print('hello')", timeout=30)
        client.close()

        # 验证返回格式与 executor 兼容
        _check(result["error"] is None,
               f"正常执行 error=None (实际: {result['error']!r})")
        _check("hello" in (result["execution_result"] or ""),
               f"execution_result 包含 'hello' (实际: {result['execution_result']!r})")
        _check(result["file_path"] is None,
               "file_path=None（sandbox 内部路径不可见）")

        # 验证 HTTP 调用参数
        call_args = mock_post.call_args
        _check(call_args is not None, "requests.post 被调用")
        _check("http://sandbox:5000/execute" in str(call_args),
               f"请求 URL 正确 (实际: {call_args})")

        # 验证 JSON payload
        if call_args and len(call_args[1]) >= 0:
            json_data = call_args[1].get("json", {})
            _check(json_data.get("code") == "print('hello')",
                   f"请求 code 正确 (实际: {json_data.get('code')!r})")
            _check(json_data.get("timeout") == 30,
                   f"请求 timeout 正确 (实际: {json_data.get('timeout')})")


# ===================================================================
# 测试 2 — SandboxClient mock: stderr 场景
# ===================================================================


def test_sandbox_client_mock_stderr() -> None:
    """mock requests.post 验证 stderr 返回场景。"""
    print("\n[2] SandboxClient mock — stderr 场景")

    from src.agent.sandbox.sandbox_client import SandboxClient

    with mock.patch("src.agent.sandbox.sandbox_client.requests.Session.post") as mock_post:
        # 模拟代码执行错误（returncode=1, stderr 有内容）
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "stdout": "",
            "stderr": "NameError: name 'x' is not defined\n",
            "returncode": 1,
        }

        client = SandboxClient(base_url="http://localhost:5000")
        result = client.execute("print(x)", timeout=10)
        client.close()

        _check(result["error"] is not None,
               f"执行错误 error 非空 (实际: {result['error']!r})")
        _check("NameError" in (result["error"] or ""),
               f"error 包含 NameError (实际: {result['error']!r})")
        _check(result["execution_result"] is None or result["execution_result"] == "",
               f"错误场景 execution_result 为空或 None (实际: {result['execution_result']!r})")


# ===================================================================
# 测试 3 — SandboxClient fallback: sandbox 返回 500
# ===================================================================


def test_sandbox_client_fallback() -> None:
    """sandbox 返回 500 时验证异常类型为 SandboxUnavailableError。"""
    print("\n[3] SandboxClient fallback — HTTP 500")

    from src.agent.sandbox.sandbox_client import SandboxClient, SandboxUnavailableError

    with mock.patch("src.agent.sandbox.sandbox_client.requests.Session.post") as mock_post:
        mock_post.return_value.status_code = 500
        mock_post.return_value.json.return_value = {
            "stdout": "",
            "stderr": "Internal server error",
            "returncode": -1,
        }
        mock_post.return_value.text = "Internal server error"

        client = SandboxClient(base_url="http://sandbox:5000")
        raised = False
        try:
            client.execute("print('test')")
        except SandboxUnavailableError as exc:
            raised = True
            _check(exc.status_code == 500,
                   f"status_code=500 (实际: {exc.status_code})")
            _check("500" in str(exc),
                   f"异常消息包含 HTTP 状态码 (实际: {str(exc)})")
        except Exception as exc:
            _check(False, f"应抛出 SandboxUnavailableError，实际抛出 {type(exc).__name__}",
                   detail=f"未预期的异常类型: {type(exc).__name__}: {exc}")
        finally:
            client.close()

        _check(raised, "sandbox 500 → SandboxUnavailableError 被抛出")


# ===================================================================
# 测试 4 — SandboxClient fallback: 连接失败
# ===================================================================


def test_sandbox_client_connection_error() -> None:
    """sandbox 连接失败时验证异常类型为 SandboxUnavailableError。"""
    print("\n[4] SandboxClient fallback — 连接失败")

    from src.agent.sandbox.sandbox_client import SandboxClient, SandboxUnavailableError
    import requests

    with mock.patch("src.agent.sandbox.sandbox_client.requests.Session.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError("Connection refused")

        client = SandboxClient(base_url="http://sandbox:9999")
        raised = False
        try:
            client.execute("print('test')")
        except SandboxUnavailableError as exc:
            raised = True
            _check("无法连接到 sandbox" in str(exc),
                   f"异常消息提示连接失败 (实际: {str(exc)})")
        except Exception as exc:
            _check(False, f"应抛出 SandboxUnavailableError，实际抛出 {type(exc).__name__}",
                   detail=f"未预期的异常类型: {type(exc).__name__}: {exc}")
        finally:
            client.close()

        _check(raised, "连接失败 → SandboxUnavailableError 被抛出")


# ===================================================================
# 测试 5 — SandboxClient 健康检查
# ===================================================================


def test_sandbox_client_health_check() -> None:
    """验证 health_check() 方法正确性。"""
    print("\n[5] SandboxClient 健康检查")

    from src.agent.sandbox.sandbox_client import SandboxClient

    # 健康
    with mock.patch("src.agent.sandbox.sandbox_client.requests.Session.get") as mock_get:
        mock_get.return_value.status_code = 200
        client = SandboxClient()
        _check(client.health_check() is True, "health_check 返回 True（200）")
        client.close()

    # 不健康
    with mock.patch("src.agent.sandbox.sandbox_client.requests.Session.get") as mock_get:
        mock_get.return_value.status_code = 500
        client = SandboxClient()
        _check(client.health_check() is False, "health_check 返回 False（500）")
        client.close()

    # 连接失败
    import requests
    with mock.patch("src.agent.sandbox.sandbox_client.requests.Session.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("refused")
        client = SandboxClient()
        _check(client.health_check() is False, "health_check 返回 False（连接失败）")
        client.close()


# ===================================================================
# 测试 6 — Executor compose 路径：mock SandboxClient
# ===================================================================


def test_executor_compose_path() -> None:
    """mock SandboxClient 验证 executor 的 compose 新分支被触发。"""
    print("\n[6] Executor compose 路径 — mock SandboxClient")

    from src.agent.nodes.executor import run  # executor_node 别名

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_compose")
    Path(ws).mkdir(parents=True, exist_ok=True)

    mock_client = mock.MagicMock()
    mock_client.execute.return_value = {
        "execution_result": "hello from sandbox\n",
        "error": None,
        "file_path": None,
    }
    mock_client.close = mock.MagicMock()

    # 需要 mock 两处：_should_use_compose 返回 True + 懒加载的 SandboxClient
    # 注意：SandboxClient 在 _execute_via_compose() 内部懒加载，
    # 因此 mock 路径必须是其定义模块 src.agent.sandbox.sandbox_client
    with mock.patch(
        "src.agent.nodes.executor._should_use_compose", return_value=True
    ), mock.patch(
        "src.agent.sandbox.sandbox_client.SandboxClient", return_value=mock_client
    ):
        result = run({
            "generated_code": "print('hello from sandbox')",
            "workspace_path": ws,
        })

    _check(result["error"] is None,
           f"compose 路径 error=None (实际: {result['error']!r})")
    _check("hello from sandbox" in (result["execution_result"] or ""),
           f"execution_result 包含预期输出 (实际: {result['execution_result']!r})")
    _check(result["file_path"] is None,
           "file_path=None（sandbox 路径不可见）")

    # 验证 SandboxClient 被正确调用
    mock_client.execute.assert_called_once()
    mock_client.close.assert_called_once()


# ===================================================================
# 测试 7 — Executor compose 优先级验证
# ===================================================================


def test_executor_compose_priority() -> None:
    """SANDBOX_URL 存在时优先于 USE_MCP 触发 compose 路径。"""
    print("\n[7] Executor compose 优先级 — SANDBOX_URL 优先于 USE_MCP")

    from src.agent.nodes.executor import _should_use_compose, _should_use_mcp

    # 场景1：仅 SANDBOX_URL 存在 → compose 优先
    with mock.patch.dict(os.environ, {"SANDBOX_URL": "http://sandbox:5000"}, clear=True):
        _check(_should_use_compose() is True,
               "SANDBOX_URL 存在 → compose=True")
        _check(_should_use_mcp() is False,
               "无 USE_MCP → mcp=False")

    # 场景2：SANDBOX_URL 和 USE_MCP 同时存在 → compose 优先
    with mock.patch.dict(os.environ, {
        "SANDBOX_URL": "http://sandbox:5000",
        "USE_MCP": "true",
    }, clear=True):
        _check(_should_use_compose() is True,
               "SANDBOX_URL + USE_MCP → compose=True（优先级更高）")

    # 场景3：仅 USE_COMPOSE 存在 → compose 优先
    with mock.patch.dict(os.environ, {"USE_COMPOSE": "true"}, clear=True):
        _check(_should_use_compose() is True,
               "USE_COMPOSE=true → compose=True")

    # 场景4：仅 USE_MCP 存在 → compose=False
    with mock.patch.dict(os.environ, {"USE_MCP": "true"}, clear=True):
        _check(_should_use_compose() is False,
               "仅 USE_MCP → compose=False")

    # 场景5：什么都不存在 → compose=False
    with mock.patch.dict(os.environ, {}, clear=True):
        _check(_should_use_compose() is False,
               "无任何标志 → compose=False")


# ===================================================================
# 测试 8 — Executor compose 路径失败回退
# ===================================================================


def test_executor_compose_fallback() -> None:
    """compose 路径失败时 executor 回退到 subprocess 路径。"""
    print("\n[8] Executor compose 路径失败 → subprocess 回退")

    from src.agent.nodes.executor import run
    from src.agent.sandbox.sandbox_client import SandboxUnavailableError

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_compose_fb")
    Path(ws).mkdir(parents=True, exist_ok=True)
    (Path(ws) / "src").mkdir(parents=True, exist_ok=True)

    mock_client = mock.MagicMock()
    mock_client.execute.side_effect = SandboxUnavailableError("sandbox is down")
    mock_client.close = mock.MagicMock()

    with mock.patch(
        "src.agent.nodes.executor._should_use_compose", return_value=True
    ), mock.patch(
        "src.agent.sandbox.sandbox_client.SandboxClient", return_value=mock_client
    ):
        result = run({
            "generated_code": "print('fallback test')",
            "workspace_path": ws,
        })

    # 回退到了 subprocess 路径 → subprocess 成功执行
    _check(result["error"] is None,
           f"compose 失败后 subprocess 回退成功 → error=None (实际: {result['error']!r})")
    _check("fallback test" in (result["execution_result"] or ""),
           f"subprocess 正确执行代码 (实际: {result['execution_result']!r})")

    mock_client.execute.assert_called_once()
    mock_client.close.assert_called_once()


# ===================================================================
# 测试 9 — SandboxClient 上下文管理器
# ===================================================================


def test_sandbox_client_context_manager() -> None:
    """验证 SandboxClient 作为上下文管理器工作正常。"""
    print("\n[9] SandboxClient 上下文管理器")

    from src.agent.sandbox.sandbox_client import SandboxClient

    client = SandboxClient(base_url="http://test:5000")
    with client:
        _check(True, "进入上下文管理器")
    # 离开上下文后 _session 已关闭
    _check(client._session is not None, "session 对象仍存在（但已关闭）")


# ===================================================================
# 测试 10 — create_client_from_env 便捷函数
# ===================================================================


def test_create_client_from_env() -> None:
    """验证 create_client_from_env 从环境变量创建客户端。"""
    print("\n[10] create_client_from_env 便捷函数")

    from src.agent.sandbox.sandbox_client import create_client_from_env

    # 使用自定义 SANDBOX_URL
    with mock.patch.dict(os.environ, {"SANDBOX_URL": "http://custom:9999"}, clear=True):
        client = create_client_from_env()
        _check(client.base_url == "http://custom:9999",
               f"自定义 SANDBOX_URL 生效 (实际: {client.base_url})")
        client.close()

    # 未设置 SANDBOX_URL → 默认值
    with mock.patch.dict(os.environ, {}, clear=True):
        client = create_client_from_env()
        _check(client.base_url == "http://localhost:5000",
               f"默认 base_url (实际: {client.base_url})")
        client.close()


# ===================================================================
# 测试 11 — 现有路径不受影响
# ===================================================================


def test_existing_paths_intact() -> None:
    """验证 compose 路径不破坏现有 subprocess 路径。"""
    print("\n[11] 现有路径不受影响")

    from src.agent.nodes.executor import run

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_intact")
    Path(ws).mkdir(parents=True, exist_ok=True)
    (Path(ws) / "src").mkdir(parents=True, exist_ok=True)

    # 不设置任何环境变量 → subprocess 路径
    with mock.patch.dict(os.environ, {}, clear=True):
        result = run({
            "generated_code": "print('subprocess works')",
            "workspace_path": ws,
        })

    _check(result["error"] is None,
           f"subprocess 路径正常 (error=None, 实际: {result['error']!r})")
    _check("subprocess works" in (result["execution_result"] or ""),
           f"subprocess 输出正确 (实际: {result['execution_result']!r})")

    fp = result.get("file_path")
    _check(fp is not None, f"file_path 有值: {fp}")
    if fp:
        _check(Path(fp).exists(), f"临时文件存在: {fp}")


# ===================================================================
# 主入口
# ===================================================================


def main() -> int:
    global _passed, _failed, _failures
    _passed = 0
    _failed = 0
    _failures = []

    print("=" * 60)
    print("Docker Compose 编排测试套件")
    print(f"Python: {sys.version}")
    print("=" * 60)

    test_sandbox_client_mock()
    test_sandbox_client_mock_stderr()
    test_sandbox_client_fallback()
    test_sandbox_client_connection_error()
    test_sandbox_client_health_check()
    test_executor_compose_path()
    test_executor_compose_priority()
    test_executor_compose_fallback()
    test_sandbox_client_context_manager()
    test_create_client_from_env()
    test_existing_paths_intact()

    print("\n" + "=" * 60)
    total = _passed + _failed
    print(f"测试结果: {_passed}/{total} 通过", end="")
    if _failed:
        print(f", {_failed} 失败")
        print("\n失败明细:")
        for f in _failures:
            print(f"  × {f}")
    else:
        print(" — 全部通过 ✅")
    print("=" * 60)

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

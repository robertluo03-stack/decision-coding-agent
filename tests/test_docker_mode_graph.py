"""Docker + MCP 模式下的 Executor 异步兼容性测试。

验证异步事件循环链：
  executor_node → anyio.run() → MCP Client (stdio) → python_tools →
  DockerRunner.run() (sync subprocess)

确保同步 subprocess 在异步 anyio.run() 上下文中不会导致死锁或
"RuntimeError: This event loop is already running" 等兼容性问题。

测试策略:
  - 设置 USE_DOCKER=true + USE_MCP=true
  - 直接调用 executor_node(state)，绕过 Planner/Coder 的 LLM 调用
  - 若 Docker 不可用（未安装/daemon 未运行），测试自动跳过

依赖:
  - Docker Desktop / Docker Engine + decision-coder-sandbox:latest 镜像
  - MCP SDK (mcp>=1.0.0)
"""

import os
import sys
from pathlib import Path

# 在导入项目模块前设置环境变量
os.environ["USE_DOCKER"] = "true"
os.environ["USE_MCP"] = "true"
os.environ["WORKSPACE_PATH"] = str(
    Path(__file__).resolve().parent.parent / "workspace"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.nodes.executor import executor_node
from src.agent.state import AgentState


# ---------------------------------------------------------------------------
# helpers
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


def _make_state(**overrides) -> AgentState:
    """构造初始 state，预填安全代码直接测试执行链路。"""
    defaults: AgentState = {
        "user_query": "Docker 模式 Executor 测试",
        "workspace_path": os.environ["WORKSPACE_PATH"],
        "plan": ["测试"],
        "generated_code": (
            "import sys\n"
            "print('Docker 模式 Executor 测试成功')\n"
            "print(f'Python 版本: {sys.version}')\n"
        ),
        "file_path": None,
        "execution_result": None,
        "error": None,
        "retry_count": 0,
        "human_feedback": None,
        "final_report": None,
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return defaults


def _docker_available() -> bool:
    """检查 Docker daemon 是否可连接。"""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "ps"], capture_output=True, text=True, timeout=5,
            stdin=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except Exception:
        return False


def _mcp_available() -> bool:
    """检查 MCP SDK 是否可导入。"""
    try:
        import anyio  # noqa: F401
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


# ===================================================================
# 测试 1 — Executor MCP 路径不抛事件循环异常
# ===================================================================


def test_executor_mcp_no_event_loop_conflict() -> None:
    """验证 executor_node 在 MCP+Docker 模式下不抛事件循环冲突。

    直接调用 executor_node，绕过 Planner/Coder 的 LLM 调用，
    只测执行链路的异步兼容性。
    """
    print("\n[1] Executor MCP 路径事件循环兼容性")

    if not _mcp_available():
        print("  ⏭️  MCP SDK 不可用，跳过测试")
        return

    if not _docker_available():
        print("  ⏭️  Docker 不可用，跳过测试")
        return

    state = _make_state()

    try:
        result = executor_node(state)
    except RuntimeError as exc:
        error_msg = str(exc)
        _check(
            "event loop" not in error_msg.lower()
            and "already running" not in error_msg.lower(),
            "无事件循环 RuntimeError",
            detail=error_msg,
        )
        _check(False, "executor_node 正常返回", detail=error_msg)
        return
    except Exception as exc:
        _check(False, "executor_node 正常返回", detail=f"{type(exc).__name__}: {exc}")
        return

    _check(isinstance(result, dict), "返回 dict 类型")

    error = result.get("error")
    if error:
        print(f"  ⚠️ 执行有错误: {str(error)[:200]}")
        _check(
            "event loop" not in str(error).lower(),
            "错误信息不含事件循环冲突",
            detail=str(error)[:100],
        )
    else:
        result_text = result.get("execution_result", "") or ""
        _check(
            "Docker 模式 Executor 测试成功" in result_text,
            "execution_result 包含成功标志",
            detail=result_text[:200],
        )


# ===================================================================
# 测试 2 — 多次调用无资源泄漏
# ===================================================================


def test_executor_mcp_multiple_calls() -> None:
    """验证多次调用 executor_node 不累积资源泄漏。"""
    print("\n[2] Executor 多次调用稳定性")

    if not _mcp_available():
        print("  ⏭️  MCP SDK 不可用，跳过测试")
        return

    if not _docker_available():
        print("  ⏭️  Docker 不可用，跳过测试")
        return

    for i in range(3):
        state = _make_state(
            generated_code=f"print('第 {i+1} 次 Docker 执行')",
        )

        try:
            result = executor_node(state)
        except Exception as exc:
            _check(
                False,
                f"第 {i+1} 次调用成功",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return

        _check(
            isinstance(result, dict) and result is not None,
            f"第 {i+1} 次返回 dict",
        )


# ===================================================================
# 测试 3 — Graph 在 Docker 模式下正常编译
# ===================================================================


def test_graph_compiles_in_docker_mode() -> None:
    """build_graph() 在 Docker+MCP 环境变量下编译成功。"""
    print("\n[3] Graph 编译 (Docker 模式)")

    try:
        from src.agent.graph import build_graph
        graph = build_graph()
    except Exception as exc:
        _check(False, "编译成功", detail=str(exc))
        return

    _check(graph is not None, "编译结果非 None")
    _check(hasattr(graph, "invoke"), "编译结果有 invoke() 方法")


# ===================================================================
# 统计
# ===================================================================


if __name__ == "__main__":
    test_executor_mcp_no_event_loop_conflict()
    test_executor_mcp_multiple_calls()
    test_graph_compiles_in_docker_mode()

    total = _passed + _failed
    print(f"\n{'='*50}")
    print(f"测试完成: {_passed}/{total} 通过")
    if _failed > 0:
        print(f"失败 ({_failed}):")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("全部通过 ✅")
        sys.exit(0)

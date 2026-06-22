"""Executor 节点测试套件。

覆盖场景（按 WEEK1_PROMPTS.md 任务 4 验收标准）：
  1. 正常代码执行 — print("hello") → execution_result="hello\n", error=None
  2. 超时机制 — while True: pass → error="Execution timeout (30s)"
  3. 危险代码拦截 — 5 种危险模式均被拦截
  4. SyntaxError 捕获 — 编译错误提前发现
  5. 路径正确 — cwd=workspace_path，代码能读取 data/xxx
  6. 临时文件管理 — file_path 有效，文件存在于 workspace/src/

所有测试数据在脚本内自动生成，不依赖外部文件。
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

# 将项目根目录加入 sys.path（tests/ 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.nodes.executor import run  # executor_node 的别名
from src.agent.nodes.executor import _has_dangerous_code
from src.agent.nodes.executor import _check_syntax
from src.agent.nodes.executor import _build_error


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_state(
    generated_code: str = "",
    workspace_path: str | None = None,
) -> dict:
    """构造最小 AgentState 字典（仅 executor 关心的字段）。"""
    if workspace_path is None:
        workspace_path = str(Path(tempfile.gettempdir()) / "dc_exec_test_ws")
    return {
        "generated_code": generated_code,
        "workspace_path": workspace_path,
    }


def _ensure_workspace(ws: str) -> None:
    """确保工作区及子目录存在。"""
    p = Path(ws)
    p.mkdir(parents=True, exist_ok=True)
    (p / "data").mkdir(parents=True, exist_ok=True)
    (p / "src").mkdir(parents=True, exist_ok=True)


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
# 测试 1 — 正常代码执行
# ===================================================================

def test_normal_execution() -> None:
    print("\n[1] 正常代码执行")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_normal")
    _ensure_workspace(ws)

    result = run(_make_state(
        generated_code="print('hello')",
        workspace_path=ws,
    ))

    _check(result["error"] is None,
           f"error=None (实际: {result['error']!r})")

    _check(result["execution_result"] is not None,
           "execution_result 非空")

    _check("hello" in (result["execution_result"] or ""),
           f"execution_result 包含 'hello' (实际: {result['execution_result']!r})")

    # file_path 应该指向 workspace/src/_dc_exec_*.py
    fp = result.get("file_path")
    _check(fp is not None, f"file_path 有值: {fp}")
    _check(
        Path(fp).exists(),
        f"临时文件存在: {fp}",
    )


# ===================================================================
# 测试 2 — 多行代码执行（包含 import）
# ===================================================================

def test_multiline_execution() -> None:
    print("\n[2] 多行代码执行（含 import + 计算）")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_multi")
    _ensure_workspace(ws)

    code = textwrap.dedent("""\
        import math

        def calc_eoq(d, s, h):
            return math.sqrt(2 * d * s / h)

        result = calc_eoq(1000, 50, 2)
        print(f"EOQ = {result:.2f}")
    """)

    result = run(_make_state(generated_code=code, workspace_path=ws))

    _check(result["error"] is None,
           f"error=None (实际: {result['error']!r})")

    _check("223.61" in (result["execution_result"] or "") or "223.6" in (result["execution_result"] or ""),
           f"EOQ 结果正确 (实际: {result['execution_result']!r})")


# ===================================================================
# 测试 3 — stdout 有换行
# ===================================================================

def test_stdout_newline() -> None:
    print("\n[3] stdout 换行处理")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_nl")
    _ensure_workspace(ws)

    result = run(_make_state(
        generated_code="print('line1')\nprint('line2')",
        workspace_path=ws,
    ))

    _check(result["error"] is None, f"error=None (实际: {result['error']!r})")
    output = result["execution_result"] or ""
    _check("line1" in output and "line2" in output,
           f"包含两行输出 (实际: {output!r})")


# ===================================================================
# 测试 4 — 空代码 / 仅空白
# ===================================================================

def test_empty_code() -> None:
    print("\n[4] 空代码 / 仅空白")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_empty")
    _ensure_workspace(ws)

    # 空字符串
    r1 = run(_make_state(generated_code="", workspace_path=ws))
    _check(r1["execution_result"] is None, "空代码: execution_result=None")
    _check("No code to execute" in (r1["error"] or ""),
           f"空代码: 提示缺少代码 (实际: {r1['error']!r})")
    _check(r1["file_path"] is None, "空代码: file_path=None")

    # 仅空白
    r2 = run(_make_state(generated_code="   \n  \t  ", workspace_path=ws))
    _check(r2["execution_result"] is None, "仅空白: execution_result=None")
    _check("No code to execute" in (r2["error"] or ""),
           f"仅空白: 提示缺少代码 (实际: {r2['error']!r})")


# ===================================================================
# 测试 5 — 危险代码拦截 (5 种模式)
# ===================================================================

def test_dangerous_code_blocked() -> None:
    print("\n[5] 危险代码拦截")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_danger")
    _ensure_workspace(ws)

    test_cases = [
        ("os.system",   "import os\nos.system('dir')"),
        ("subprocess",  "import subprocess\nsubprocess.run(['ls'])"),
        ("eval(",       "eval('1+1')"),
        ("exec(",       "exec('x=1')"),
        ("__import__",  "m = __import__('os')"),
    ]

    for label, code in test_cases:
        result = run(_make_state(generated_code=code, workspace_path=ws))
        err = result.get("error") or ""
        is_blocked = "Security: Dangerous code detected" in err
        _check(
            is_blocked,
            f"拦截 {label}: error='{err}'",
            detail=f"未拦截 {label}"
        )
        _check(result["execution_result"] is None,
               f"{label}: execution_result=None")
        _check(result["file_path"] is None,
               f"{label}: file_path=None (未写入文件)")


# ===================================================================
# 测试 6 — SyntaxError 预检
# ===================================================================

def test_syntax_error_caught() -> None:
    print("\n[6] SyntaxError 预检")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_syntax")
    _ensure_workspace(ws)

    # 括号不匹配
    r1 = run(_make_state(generated_code='print("hello"', workspace_path=ws))
    _check(r1["execution_result"] is None,
           "execution_result=None（未执行）")
    _check(
        "SyntaxError" in (r1["error"] or ""),
        f"捕获 SyntaxError (实际: {r1['error']!r})",
    )
    _check(r1["file_path"] is None, "file_path=None（不写毒文件）")

    # 缩进错误
    r2 = run(_make_state(
        generated_code="if True:\nprint('bad indent')",
        workspace_path=ws,
    ))
    _check("SyntaxError" in (r2["error"] or "") or "IndentationError" in (r2["error"] or ""),
           f"捕获缩进错误 (实际: {r2['error']!r})")


# ===================================================================
# 测试 7 — 超时机制
# ===================================================================

def test_timeout() -> None:
    print("\n[7] 超时机制 (30s)")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_timeout")
    _ensure_workspace(ws)

    code = "while True: pass"

    start = time.time()
    result = run(_make_state(generated_code=code, workspace_path=ws))
    elapsed = time.time() - start

    _check(
        "Execution timeout (30s)" in (result["error"] or ""),
        f"超时错误信息正确 (实际: {result['error']!r})",
    )
    _check(result["execution_result"] is None,
           "execution_result=None")

    fp = result.get("file_path")
    _check(fp is not None, f"file_path 有值（已写入文件）: {fp}")

    # 超时后文件仍然存在（方便调试）
    if fp:
        _check(Path(fp).exists(),
               f"超时文件保留在 workspace 便于调试: {fp}")

    # 用时应在 30s 附近（±2s 容忍）
    _check(
        28 <= elapsed <= 33,
        f"超时时间 ~30s (实际 {elapsed:.1f}s)",
    )


# ===================================================================
# 测试 8 — 路径正确（cwd=workspace_path）
# ===================================================================

def test_workspace_cwd() -> None:
    print("\n[8] 路径正确 (cwd=workspace_path)")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_cwd")
    _ensure_workspace(ws)

    # 在工作区下创建测试数据文件
    (Path(ws) / "data" / "test.csv").write_text("col1,col2\n1,2\n3,4\n", encoding="utf-8")

    code = textwrap.dedent("""\
        import os
        print("CWD:", os.getcwd())

        # 尝试读取相对路径的数据文件
        try:
            with open("data/test.csv", "r") as f:
                content = f.read()
                print("FILE_OK:", repr(content.strip()))
        except FileNotFoundError as e:
            print("FILE_NOT_FOUND:", e)
    """)

    result = run(_make_state(generated_code=code, workspace_path=ws))
    output = result["execution_result"] or ""

    _check(result["error"] is None,
           f"error=None (实际: {result['error']!r})")

    _check("FILE_OK" in output,
           f"相对路径读取成功: {output[:200]!r}")


# ===================================================================
# 测试 9 — 临时文件管理
# ===================================================================

def test_temp_file_management() -> None:
    print("\n[9] 临时文件管理")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_tmpfile")
    _ensure_workspace(ws)

    result = run(_make_state(
        generated_code="print('temp file test')",
        workspace_path=ws,
    ))

    fp = result.get("file_path")
    _check(fp is not None, "file_path 有值")

    fp_path = Path(fp)
    _check(fp_path.exists(), f"文件存在: {fp}")

    # 文件应该在 workspace/src/ 下
    _check("src" in fp_path.parts or fp_path.parent.name == "src",
           f"文件在 workspace/src/ 目录下: {fp}")

    # 检查文件内容就是 generated_code
    if fp_path.exists():
        content = fp_path.read_text(encoding="utf-8")
        _check("temp file test" in content,
               "临时文件内容正确")


# ===================================================================
# 测试 10 — stderr 捕获
# ===================================================================

def test_stderr_captured() -> None:
    print("\n[10] stderr 捕获")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_stderr")
    _ensure_workspace(ws)

    code = textwrap.dedent("""\
        import sys
        print("stdout message", file=sys.stdout)
        print("stderr message", file=sys.stderr)
    """)

    result = run(_make_state(generated_code=code, workspace_path=ws))

    _check("stdout message" in (result["execution_result"] or ""),
           "stdout 正确捕获")
    # 写入 stderr 但 returncode=0 → _build_error 返回 None（非错误）
    _check(result["error"] is None,
           f"rc=0 时 stderr 不视为 error (实际: {result['error']!r})")


# ===================================================================
# 测试 11 — 辅助函数单元测试
# ===================================================================

def test_helper_functions() -> None:
    print("\n[11] 辅助函数 _has_dangerous_code / _check_syntax")

    # ---- _has_dangerous_code ----
    _check(_has_dangerous_code("import os\nos.system('ls')"), "检测 os.system")
    _check(_has_dangerous_code("subprocess.run(['ls'])"), "检测 subprocess")
    _check(_has_dangerous_code("eval('1+1')"), "检测 eval(")
    _check(_has_dangerous_code("exec('x=1')"), "检测 exec(")
    _check(_has_dangerous_code("__import__('os')"), "检测 __import__")
    _check(not _has_dangerous_code("import math\nprint('safe')"), "安全代码不误报")
    _check(not _has_dangerous_code("import os.path\nprint(os.path.join('a','b'))"),
           "合法 os.path 不误报（不含 os.system）")

    # ---- _check_syntax ----
    _check(_check_syntax("print('ok')") is None, "合法语法 → None")
    err = _check_syntax("print('bad'")
    _check(err is not None and "SyntaxError" in err,
           f"括号不匹配 → SyntaxError (实际: {err!r})")

    err2 = _check_syntax("if True:\nprint('indent')")
    _check(err2 is not None,
           f"缩进错误 → 非 None (实际: {err2!r})")


# ===================================================================
# 测试 12 — 边界：无返回值代码（仅 import）
# ===================================================================

def test_edge_no_output() -> None:
    print("\n[12] 边界：无 print 代码")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_noout")
    _ensure_workspace(ws)

    result = run(_make_state(
        generated_code="x = 1 + 1\n# no print",
        workspace_path=ws,
    ))

    _check(result["error"] is None,
           f"无输出代码 error=None (实际: {result['error']!r})")
    _check("(no output)" == (result["execution_result"] or ""),
           f"无输出时 execution_result='(no output)' (实际: {result['execution_result']!r})")


# ===================================================================
# 测试 13 — returncode != 0 但 stderr 为空 → 仍报告 error
# ===================================================================

def test_nonzero_exit_no_stderr() -> None:
    """代码内部 try/except + exit(1)，stderr 可能为空，验证 error 仍被设置。"""
    print("\n[13] returncode != 0, stderr 为空 → 仍然 error")

    ws = str(Path(tempfile.gettempdir()) / "dc_exec_test_exit1")
    _ensure_workspace(ws)

    # 模拟：代码内部 try/except 了异常，print 了错误信息，然后 exit(1)
    code = textwrap.dedent("""\
        import sys

        try:
            1 / 0
        except ZeroDivisionError:
            print("程序出错: division by zero")
            sys.exit(1)
    """)

    result = run(_make_state(generated_code=code, workspace_path=ws))

    _check(result["error"] is not None,
           f"error 非空 (实际: {result['error']!r})")
    _check("程序出错" in (result["error"] or ""),
           f"error 包含 stdout 最后内容 (实际: {result['error'][:200]!r})")
    _check(
        result["execution_result"] is None or "程序出错" in (result["execution_result"] or ""),
        "execution_result 包含部分输出"
    )


# ===================================================================
# 测试 14 — _build_error 辅助函数
# ===================================================================

def test_build_error_helper() -> None:
    """_build_error() 单元测试：四种场景全覆盖。"""
    print("\n[14] _build_error 辅助函数")

    import subprocess as sp

    # 场景1: returncode=0 → None
    r1 = sp.CompletedProcess(["py"], 0, stdout="ok", stderr="")
    _check(_build_error(r1) is None, "returncode=0 → error=None")

    # 场景2: returncode != 0, stderr 非空 → 返回 stderr
    r2 = sp.CompletedProcess(["py"], 1, stdout="", stderr="NameError: x not defined\n")
    err2 = _build_error(r2)
    _check(err2 == "NameError: x not defined", f"rc=1 + stderr → stderr (实际: {err2!r})")

    # 场景3: returncode != 0, stderr 空, stdout 非空 → 返回 stdout 最后 500 字符
    r3 = sp.CompletedProcess(["py"], 1, stdout="程序出错: 除零错误", stderr="")
    err3 = _build_error(r3)
    _check(err3 == "程序出错: 除零错误",
           f"rc=1 + stdout → stdout (实际: {err3!r})")

    # 场景4: returncode != 0, 都为空 → 返回通用信息
    r4 = sp.CompletedProcess(["py"], 2, stdout="", stderr="")
    err4 = _build_error(r4)
    _check("Execution failed" in err4 and "2" in err4,
           f"rc=2 + 全空 → 通用错误 (实际: {err4!r})")

    # 场景5: long stdout → 截断最后 500 字符
    r5 = sp.CompletedProcess(["py"], 1, stdout="x" * 1000, stderr="")
    err5 = _build_error(r5)
    _check(len(err5) <= 500, f"长 stdout 截断 → {len(err5)} 字符 (≤500)")

    # 场景6: returncode=0, stderr 有内容但不表示错误 → None
    r6 = sp.CompletedProcess(["py"], 0, stdout="ok\n", stderr="warning: deprecated\n")
    _check(_build_error(r6) is None, "rc=0 + stderr → error=None (returncode 优先)")


# ===================================================================
# 主入口
# ===================================================================

def main() -> int:
    global _passed, _failed, _failures
    _passed = 0
    _failed = 0
    _failures = []

    print("=" * 60)
    print("Executor 节点测试套件")
    print(f"Python: {sys.version}")
    print("=" * 60)

    test_normal_execution()
    test_multiline_execution()
    test_stdout_newline()
    test_empty_code()
    test_dangerous_code_blocked()
    test_syntax_error_caught()
    test_timeout()
    test_workspace_cwd()
    test_temp_file_management()
    test_stderr_captured()
    test_helper_functions()
    test_edge_no_output()
    test_nonzero_exit_no_stderr()
    test_build_error_helper()

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

"""安全检测器 test_security.py —— AST 级别危险代码检查与安全执行验证。

覆盖场景（按 Week2 开发提示词 2.5 验收标准）：
  1. os.system("echo pwned") — 系统命令注入，应被拦截
  2. subprocess.call(...)     — 子进程逃逸，应被拦截
  3. eval("1+1")              — 动态代码执行，应被拦截
  4. exec("print(1)")         — 动态代码执行，应被拦截
  5. __import__('os').system  — 变形写法，应被 AST 识别并拦截
  6. open('data.csv')         — 合法文件读取，不应误杀
  7. 正常数学计算              — 安全代码应能正常执行

所有测试独立运行，不依赖外部网络。
"""

import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.sandbox.security_checker import check_code_safety


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _run_code_in_subprocess(code: str) -> subprocess.CompletedProcess:
    """在 subprocess 中安全执行 Python 代码。

    将 code 写入临时文件，用当前 Python 解释器执行，30 秒超时。

    Args:
        code: 待执行的 Python 源代码

    Returns:
        subprocess.CompletedProcess 对象
    """
    tmp_path = Path(tempfile.gettempdir()) / f"_dc_sec_test_{Path(__file__).stem}.py"
    tmp_path.write_text(code, encoding="utf-8")

    try:
        return subprocess.run(
            [sys.executable, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
        )
    finally:
        # 清理临时文件
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _assert_blocked(code: str, expected_keyword: str) -> None:
    """辅助断言：给定代码应被安全检查拦截。

    Args:
        code: 待检查的 Python 代码
        expected_keyword: 拦截原因中应包含的关键词
    """
    is_safe, reason = check_code_safety(code)
    assert not is_safe, (
        f"预期被拦截但通过了安全检查。\n"
        f"代码: {code}\n"
        f"原因: {reason}"
    )
    assert reason is not None
    assert expected_keyword in reason, (
        f"拦截原因应包含 '{expected_keyword}'，实际原因: {reason}"
    )


def _assert_safe(code: str) -> None:
    """辅助断言：给定代码应通过安全检查。

    Args:
        code: 待检查的 Python 代码
    """
    is_safe, reason = check_code_safety(code)
    assert is_safe, (
        f"预期安全但被拦截。\n"
        f"代码: {code}\n"
        f"原因: {reason}"
    )
    assert reason is None


# ===================================================================
# 测试 1：拦截 os.system("echo pwned")
# ===================================================================


def test_dangerous_os_system() -> None:
    """验证 os.system("echo pwned") 被 AST 安全检查拦截。

    os.system 会调用系统 Shell，存在命令注入风险，
    安全检查器必须拦截此模式。
    """
    code = 'import os\nos.system("echo pwned")'
    _assert_blocked(code, "os.system")


# ===================================================================
# 测试 2：拦截 subprocess.call(...)
# ===================================================================


def test_dangerous_subprocess() -> None:
    """验证 subprocess.call(...) 被 AST 安全检查拦截。

    subprocess 模块可启动任意系统进程，存在沙箱逃逸风险，
    安全检查器必须拦截所有 subprocess.* 调用。
    """
    code = 'import subprocess\nsubprocess.call(["echo", "pwned"])'
    _assert_blocked(code, "subprocess")


# ===================================================================
# 测试 3：拦截 eval("1+1")
# ===================================================================


def test_dangerous_eval() -> None:
    """验证 eval("1+1") 被 AST 安全检查拦截。

    eval 可执行任意 Python 表达式，存在代码注入风险，
    安全检查器必须拦截此模式。
    """
    code = 'eval("1+1")'
    _assert_blocked(code, "eval")


# ===================================================================
# 测试 4：拦截 exec("print(1)")
# ===================================================================


def test_dangerous_exec() -> None:
    """验证 exec("print(1)") 被 AST 安全检查拦截。

    exec 可执行任意 Python 语句，存在代码注入风险，
    安全检查器必须拦截此模式。
    """
    code = 'exec("print(1)")'
    _assert_blocked(code, "exec")


# ===================================================================
# 测试 5：拦截变形写法 __import__('os').system('echo pwned')
# ===================================================================


def test_dangerous_import() -> None:
    """验证变形写法 __import__('os').system('echo pwned') 被 AST 识别并拦截。

    攻击者可能使用 __import__ 动态导入模块来绕过简单的字符串匹配检查。
    AST 级别分析能识别这种变形写法中的 __import__ 调用，
    而不是仅依赖关键词匹配。
    """
    code = "__import__('os').system('echo pwned')"
    # AST 解析后 visit_Call 会先检测最内层 __import__ 调用并拦截
    _assert_blocked(code, "__import__")


# ===================================================================
# 测试 6：合法 open('data.csv') 不被误杀
# ===================================================================


def test_safe_file_open() -> None:
    """验证 open('data.csv') 合法文件写入不被安全检查误杀。

    历史版本曾因为简单的字符串匹配误阻断所有 open() 调用，
    升级到 AST 级别分析后，应能区分合法文件操作和危险操作（如 open('/dev/null')）。
    本测试同时验证安全代码能够成功执行。
    """
    code = textwrap.dedent("""\
        import tempfile
        from pathlib import Path

        # 在临时目录创建测试文件并写入
        tmp = Path(tempfile.gettempdir()) / "_dc_sec_test_fopen.csv"
        with open(str(tmp), "w") as f:
            f.write("col1,col2\\n1,2\\n")
        print("WRITE_OK")
        tmp.unlink()
    """)

    # 第一步：安全检查应放行
    _assert_safe(code)

    # 第二步：代码能正常执行
    result = _run_code_in_subprocess(code)
    assert result.returncode == 0, (
        f"安全代码执行失败（rc={result.returncode}）。\n"
        f"stderr: {result.stderr}\n"
        f"stdout: {result.stdout}"
    )
    assert "WRITE_OK" in result.stdout, (
        f"代码未按预期输出 WRITE_OK。stdout: {result.stdout}"
    )


# ===================================================================
# 测试 7：正常数学计算代码能安全执行
# ===================================================================


def test_safe_code() -> None:
    """验证正常数学计算代码通过安全检查并能成功执行。

    包含 import、函数定义、数学计算、print 输出的典型场景，
    不应触发任何安全检查拦截。
    """
    code = textwrap.dedent("""\
        import math

        def calc_eoq(demand, setup_cost, holding_cost):
            return math.sqrt(2 * demand * setup_cost / holding_cost)

        result = calc_eoq(1000, 50, 2)
        print(f"EOQ = {result:.2f}")
    """)

    # 第一步：安全检查应放行
    _assert_safe(code)

    # 第二步：代码能正常执行
    result = _run_code_in_subprocess(code)
    assert result.returncode == 0, (
        f"安全代码执行失败（rc={result.returncode}）。\n"
        f"stderr: {result.stderr}\n"
        f"stdout: {result.stdout}"
    )
    # EOQ = sqrt(2*1000*50/2) = sqrt(50000) ≈ 223.61
    assert "223.61" in result.stdout or "223.6" in result.stdout, (
        f"EOQ 结果应为 223.61，实际输出: {result.stdout}"
    )


# ===================================================================
# 主入口：支持 pytest 和直接运行
# ===================================================================

if __name__ == "__main__":
    # 直接运行 python tests/test_security.py 时用 pytest 执行自身
    print("=" * 60)
    print("安全检测器测试套件 (test_security.py)")
    print(f"Python: {sys.version}")
    print("=" * 60)
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))

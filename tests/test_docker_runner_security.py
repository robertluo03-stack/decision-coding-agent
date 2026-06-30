"""测试 DockerRunner 的第二道安全防线（AST 级别危险代码检查）。

覆盖场景：
  1. 正常代码通过安全检查
  2. os.system("ls") 被拦截
  3. eval("1+1") 被拦截
  4. __import__('os').system('rm -rf /') 变形写法被拦截
  5. open('data.csv') 合法操作通过
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.sandbox.security_checker import check_code_safety


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


def test_safe_code() -> None:
    """正常代码应该通过安全检查。"""
    is_safe, reason = check_code_safety("print('hello world')")
    assert is_safe, f"正常代码未通过: {reason}"
    assert reason is None


def test_safe_file_open() -> None:
    """合法 open() 操作应该通过安全检查（不再误杀）。"""
    is_safe, reason = check_code_safety("f = open('data.csv', 'r')")
    assert is_safe, f"合法文件读取未通过: {reason}"
    assert reason is None


def test_danger_os_system() -> None:
    """os.system() 应被拦截。"""
    is_safe, reason = check_code_safety("import os; os.system('ls')")
    assert not is_safe, "os.system 未被拦截"
    assert "os.system" in reason


def test_danger_eval() -> None:
    """eval() 应被拦截。"""
    is_safe, reason = check_code_safety("eval('1+1')")
    assert not is_safe, "eval 未被拦截"
    assert "eval" in reason


def test_danger_exec() -> None:
    """exec() 应被拦截。"""
    is_safe, reason = check_code_safety("exec('x=1')")
    assert not is_safe, "exec 未被拦截"
    assert "exec" in reason


def test_danger_subprocess() -> None:
    """subprocess.run() 应被拦截。"""
    is_safe, reason = check_code_safety("import subprocess; subprocess.run(['ls'])")
    assert not is_safe, "subprocess.run 未被拦截"
    assert "subprocess" in reason


def test_danger_import_builtin() -> None:
    """__import__('os') 应被拦截。"""
    is_safe, reason = check_code_safety("m = __import__('os'); m.system('whoami')")
    assert not is_safe, "__import__ 未被拦截"
    assert "__import__" in reason


def test_danger_obfuscated_chain() -> None:
    """变形写法 __import__('os').system('rm -rf /') 应被 AST 识别并拦截。"""
    code = "__import__('os').system('rm -rf /')"
    is_safe, reason = check_code_safety(code)
    assert not is_safe, f"变形写法 {code!r} 未被拦截"
    # AST 将 __import__('os').system(...) 解析为：
    #   Call(func=Attribute(value=Call(func=Name("__import__")), attr="system"))
    # visit_Call 先看到外层 Call，func_str 为 "__import__.os.system"，
    # _check_attribute_chain 检测到 subprocess.* 模式...
    # 实际上 visit_Call 通过 generic_visit 会递归进入内层 __import__ call，
    # 所以 __import__ 本身会被拦截；同时外层的 .system 链也会被检测。
    assert "__import__" in reason or "system" in reason.lower(), \
        f"拦截原因应包含 __import__ 或 system: {reason}"


def test_danger_compile() -> None:
    """compile() 应被拦截。"""
    is_safe, reason = check_code_safety("compile('x=1', '<string>', 'exec')")
    assert not is_safe, "compile 未被拦截"
    assert "compile" in reason


# ---------------------------------------------------------------------------
# DockerRunner 第二道防线集成测试（不调用 Docker）
# ---------------------------------------------------------------------------


def test_docker_runner_blocked() -> None:
    """验证 DockerRunner.run() 在落地执行前拦截危险代码。

    此测试不依赖 Docker 环境，仅验证安全桥接逻辑。
    """
    from src.agent.sandbox.docker_runner import DockerRunner

    runner = DockerRunner(workspace_path=str(Path(__file__).resolve().parent))

    # 危险代码应在写入文件前被拦截（returncode=-1, stderr 包含 Security 标识）
    result = runner.run("import os; os.system('rm -rf /')")
    assert result["returncode"] == -1, \
        f"危险代码应被拦截（returncode=-1），实际: {result}"
    assert "Security" in result["stderr"], \
        f"错误信息应包含 'Security' 标识: {result['stderr']}"


def test_docker_runner_obfuscated_blocked() -> None:
    """验证 DockerRunner.run() 拦截变形写法。"""
    from src.agent.sandbox.docker_runner import DockerRunner

    runner = DockerRunner(workspace_path=str(Path(__file__).resolve().parent))

    result = runner.run("__import__('os').system('rm -rf /')")
    assert result["returncode"] == -1, \
        f"变形写法应被拦截（returncode=-1），实际: {result}"
    assert "Security" in result["stderr"], \
        f"错误信息应包含 'Security' 标识: {result['stderr']}"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        ("安全代码", test_safe_code),
        ("合法文件读取", test_safe_file_open),
        ("拦截 os.system", test_danger_os_system),
        ("拦截 eval", test_danger_eval),
        ("拦截 exec", test_danger_exec),
        ("拦截 subprocess", test_danger_subprocess),
        ("拦截 __import__", test_danger_import_builtin),
        ("拦截变形写法", test_danger_obfuscated_chain),
        ("拦截 compile", test_danger_compile),
        ("DockerRunner 拦截危险代码", test_docker_runner_blocked),
        ("DockerRunner 拦截变形写法", test_docker_runner_obfuscated_blocked),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        try:
            func()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {name}: {exc}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"结果: {passed} 通过, {failed} 失败 (共 {len(tests)} 项)")
    print(f"{'='*50}")

    if failed > 0:
        sys.exit(1)

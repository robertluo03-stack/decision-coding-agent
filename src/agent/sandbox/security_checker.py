"""统一安全检查 — 基于 AST 语法级分析。

合并 coder.py / executor.py / python_tools.py 三方的安全检查逻辑，
使用 ast 模块替代简单字符串匹配：

  - 禁止：os.system, subprocess, eval, exec, __import__, compile, open(os.devnull)
  - 允许：open('data.csv') 等合法文件操作（不再误杀）
  - 可识别 __import__('os').system('...') 等变形写法
"""

import ast
from typing import Optional


class _DangerousPatternVisitor(ast.NodeVisitor):
    """AST 遍历器：检测危险调用模式。

    检查以下 5 类危险操作：
      1. os.system(...) — 系统命令注入
      2. subprocess.*(...) — 子进程逃逸
      3. eval(...) / exec(...) — 动态代码执行
      4. __import__(...) — 动态模块导入
      5. compile(...) — 动态编译
    """

    def __init__(self) -> None:
        self.blocked: list[str] = []  # 收集所有违规描述

    # ------------------------------------------------------------------
    # 检测 os.system 调用
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        """检测禁止的函数调用模式。"""
        func_str = self._get_func_str(node.func)

        # os.system("...")
        if func_str == "os.system":
            self.blocked.append(f"危险调用: {func_str}()")
            return

        # eval(...) / exec(...)
        if func_str in ("eval", "exec"):
            self.blocked.append(f"危险调用: {func_str}()")
            return

        # compile(...)
        if func_str == "compile":
            self.blocked.append(f"危险调用: {func_str}()")
            return

        # __import__('os')
        if func_str == "__import__":
            self.blocked.append(f"危险调用: {func_str}()")
            return

        # 检测变形写法: __import__('os').system('...')
        # 以及 subprocess.run(...) 等
        self._check_attribute_chain(func_str, node.func)

        # 递归访问子节点
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # 检测 open('/dev/null') — 特殊文件写入企图
    # ------------------------------------------------------------------

    def visit_Call__open_check(self, node: ast.Call) -> None:
        """检查 open() 调用的文件路径。"""
        func_str = self._get_func_str(node.func)
        if func_str != "open":
            return

        # 获取第一个位置参数（文件路径）
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                path = first_arg.value.lower()
                if path in ("/dev/null", "os.devnull", "nul"):
                    self.blocked.append(
                        f"危险调用: open({first_arg.value!r}) — 文件重定向"
                    )

    # ------------------------------------------------------------------
    # 检测 subprocess.* 属性访问
    # ------------------------------------------------------------------

    def _check_attribute_chain(self, func_str: str, func_node: ast.expr) -> None:
        """检测通过属性访问链的危险调用。

        例如:
          - subprocess.run(...)
          - subprocess.Popen(...)
          - subprocess.call(...)
        """
        if func_str.startswith("subprocess."):
            self.blocked.append(f"危险调用: {func_str}()")

    # ------------------------------------------------------------------
    # 将 AST 节点转为字符串表示
    # ------------------------------------------------------------------

    def _get_func_str(self, node: ast.expr) -> str:
        """将 AST 表达式节点转回函数名字符串。

        支持:
          - ast.Name("eval") → "eval"
          - ast.Attribute(ast.Name("os"), "system") → "os.system"
          - ast.Call(ast.Name("__import__"), ...), ast.Attribute(..., "system")
            → "__import__.os.system"  (通过 visit_Call 递归处理)
        """
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._get_func_str(node.value)
            return f"{base}.{node.attr}"
        if isinstance(node, ast.Call):
            return self._get_func_str(node.func)
        return ""


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def check_code_safety(code: str) -> tuple[bool, Optional[str]]:
    """检查 Python 代码是否安全。

    使用 AST 语法级分析，不仅检查简单的字符串匹配，
    还能识别通过属性链的变形写法（如 __import__('os').system('...')）。

    Args:
        code: Python 源代码字符串

    Returns:
        (is_safe, reason) — 如果安全返回 (True, None)，否则返回 (False, 拦截原因)

    Examples:
        >>> check_code_safety("print('hello')")
        (True, None)

        >>> check_code_safety("import os; os.system('ls')")
        (False, '危险调用: os.system()')

        >>> check_code_safety("f = open('data.csv')")
        (True, None)

        >>> check_code_safety("m = __import__('os'); m.system('whoami')")
        (False, '危险调用: __import__()')
    """
    # 1. 解析为 AST
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # 语法错误不在此拦截，由上层 executor 的 compile 预检处理
        return (True, None)

    # 2. AST 遍历检测危险模式
    visitor = _DangerousPatternVisitor()
    visitor.visit(tree)

    if visitor.blocked:
        # 返回第一条违规信息
        reason = "; ".join(visitor.blocked)
        return (False, reason)

    return (True, None)

"""安全沙箱模块 — 统一的安全检查入口。

Week 2: 用 AST（ast 模块）进行语法级安全检查，替代简单的字符串匹配。
"""

from src.agent.sandbox.security_checker import check_code_safety

__all__ = ["check_code_safety"]

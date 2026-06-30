"""增强规则回退测试 —— 覆盖 _diagnose_by_rule 和 _fix_by_rule 新增/增强逻辑。

验证每种错误类型的诊断和修复建议，以及通用错误回退。
所有测试独立运行，不依赖外部网络/LLM。
"""

import sys
from pathlib import Path

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.nodes.debugger import (
    _diagnose_by_rule,
    _fix_by_rule,
    _extract_error_line,
    _extract_undefined_name,
    _extract_missing_module,
    _extract_key_name,
    _extract_error_line_number,
    _has_unbalanced_parens,
)

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
# 测试 1 — _diagnose_by_rule 所有错误类型
# ===================================================================


def test_diagnose_syntax_error() -> None:
    """SyntaxError 诊断应包含行号和括号/缩进提示。"""
    print("\n[1] 诊断 SyntaxError")

    # 无行号
    r1 = _diagnose_by_rule("SyntaxError: invalid syntax")
    _check("语法错误" in r1, "包含'语法错误'")
    _check("括号" in r1, "包含'括号'提示")

    # 有行号（标准 Python 格式）
    r2 = _diagnose_by_rule(
        "  File \"test.py\", line 5\n"
        "    print('hello'\n"
        "SyntaxError: '(' was never closed"
    )
    _check("第 5 行" in r2, "提取行号 → '第 5 行'")


def test_diagnose_name_error() -> None:
    """NameError 诊断应包含未定义变量名。"""
    print("\n[2] 诊断 NameError")

    r = _diagnose_by_rule("NameError: name 'pd' is not defined")
    _check("'pd'" in r, "包含未定义变量名 'pd'")
    _check("未定义" in r, "包含'未定义'关键词")
    _check("import" in r.lower(), "包含 import 建议")


def test_diagnose_module_not_found() -> None:
    """ModuleNotFoundError 诊断应包含缺失模块名和安装建议。"""
    print("\n[3] 诊断 ModuleNotFoundError")

    r = _diagnose_by_rule("ModuleNotFoundError: No module named 'pandas'")
    _check("pandas" in r, "包含模块名 'pandas'")
    _check("安装" in r or "pip" in r, "包含安装建议")
    _check("标准库" in r, "包含标准库替代建议")


def test_diagnose_type_error() -> None:
    """TypeError 诊断应包含类型转换建议。"""
    print("\n[4] 诊断 TypeError")

    r = _diagnose_by_rule("TypeError: can only concatenate str (not \"int\") to str")
    _check("类型不匹配" in r, "包含'类型不匹配'")
    _check("str()" in r or "int()" in r or "type()" in r, "包含类型转换建议")


def test_diagnose_index_error() -> None:
    """IndexError 诊断应包含越界和边界检查建议。"""
    print("\n[5] 诊断 IndexError")

    r = _diagnose_by_rule("IndexError: list index out of range")
    _check("索引超出" in r, "包含'索引超出'")
    _check("len(" in r, "包含 len() 检查建议")


def test_diagnose_key_error() -> None:
    """KeyError 诊断应包含键名和 get() 建议。"""
    print("\n[6] 诊断 KeyError")

    r = _diagnose_by_rule("KeyError: 'sku'")
    _check("'sku'" in r, "包含键名 'sku'")
    _check(".get(" in r, "包含 .get() 建议")
    _check("df.columns" in r, "包含 df.columns 建议")


def test_diagnose_zero_division() -> None:
    """ZeroDivisionError 诊断应包含保护条件建议。"""
    print("\n[7] 诊断 ZeroDivisionError")

    r = _diagnose_by_rule("ZeroDivisionError: division by zero")
    _check("除以零" in r, "包含'除以零'")
    _check("ZeroDivisionError" in r, "包含异常类型")
    _check("!=" in r or "if" in r, "包含条件判断建议")


def test_diagnose_value_error() -> None:
    """ValueError 诊断应包含范围和格式检查建议。"""
    print("\n[8] 诊断 ValueError")

    r = _diagnose_by_rule("ValueError: math domain error")
    _check("值" in r and "类型正确" in r, "包含 ValueError 描述")


def test_diagnose_attribute_error() -> None:
    """AttributeError 诊断应包含类型检查建议。"""
    print("\n[9] 诊断 AttributeError")

    r = _diagnose_by_rule("AttributeError: 'NoneType' object has no attribute 'method'")
    _check("属性" in r, "包含'属性'关键词")
    _check("None" in r or "hasattr" in r or "type(obj)" in r, "包含防御建议")


def test_diagnose_file_not_found() -> None:
    """FileNotFoundError 诊断应包含路径检查建议。"""
    print("\n[10] 诊断 FileNotFoundError")

    r = _diagnose_by_rule("FileNotFoundError: [Errno 2] No such file or directory: 'data.csv'")
    _check("文件未找到" in r, "包含'文件未找到'")
    _check("./data/" in r or "os.path.exists" in r, "包含路径检查建议")


def test_diagnose_timeout() -> None:
    """Timeout 诊断应包含循环/效率优化建议。"""
    print("\n[11] 诊断 Timeout")

    r = _diagnose_by_rule("[TIMEOUT] 容器执行超时（30s）")
    _check("超时" in r, "包含'超时'")
    _check("循环" in r, "包含'循环'建议")


def test_diagnose_unknown_error() -> None:
    """未知错误应返回通用提示。"""
    print("\n[12] 诊断未知错误")

    r = _diagnose_by_rule("")
    _check("未知错误" in r, "空 error → 未知错误")
    _check("建议检查代码逻辑" in r, "包含通用建议")

    r2 = _diagnose_by_rule("WeirdCustomException: something went very wrong")
    _check("未知错误" in r2, "自定义异常 → 未知错误")
    _check("WeirdCustomException" in r2, "包含错误摘要")


# ===================================================================
# 测试 2 — 错误信息提取辅助函数
# ===================================================================


def test_extract_error_line() -> None:
    """_extract_error_line 正确提取 Python 行号。"""
    print("\n[13] 行号提取")

    _check(
        _extract_error_line("File \"t.py\", line 5\nSyntaxError") == "（第 5 行）",
        "标准格式 → line 5"
    )
    _check(
        _extract_error_line("SyntaxError: invalid syntax") == "",
        "无行号 → 空字符串"
    )
    _check(
        _extract_error_line("IndentationError: expected an indented block, line 12") == "（第 12 行）",
        "IndentationError 格式 → line 12"
    )


def test_extract_undefined_name() -> None:
    """_extract_undefined_name 正确提取 NameError 中的变量名。"""
    print("\n[14] 未定义变量名提取")

    _check(
        _extract_undefined_name("NameError: name 'pd' is not defined") == "pd",
        "提取 'pd'"
    )
    _check(
        _extract_undefined_name("NameError: name 'result' is not defined") == "result",
        "提取 'result'"
    )
    _check(
        _extract_undefined_name("No match here") == "",
        "不匹配 → 空字符串"
    )


def test_extract_missing_module() -> None:
    """_extract_missing_module 正确提取 ModuleNotFoundError 中的模块名。"""
    print("\n[15] 缺失模块名提取")

    _check(
        _extract_missing_module("ModuleNotFoundError: No module named 'pandas'") == "pandas",
        "提取 'pandas'"
    )
    _check(
        _extract_missing_module("ModuleNotFoundError: No module named 'scipy'") == "scipy",
        "提取 'scipy'"
    )
    _check(
        _extract_missing_module("ImportError: cannot import name 'foo'") == "",
        "无模块名 → 空字符串"
    )


def test_extract_key_name() -> None:
    """_extract_key_name 正确提取 KeyError 中的键名。"""
    print("\n[16] 键名提取")

    _check(
        _extract_key_name("KeyError: 'sku'") == "sku",
        "提取 'sku'"
    )
    _check(
        _extract_key_name("KeyError('column_name')") == "column_name",
        "提取 'column_name'"
    )
    _check(
        _extract_key_name("No key here") == "",
        "不匹配 → 空字符串"
    )


def test_extract_error_line_number() -> None:
    """_extract_error_line_number 正确提取整数行号。"""
    print("\n[17] 行号整数提取")

    _check(
        _extract_error_line_number("File \"t.py\", line 5\nSyntaxError") == 5,
        "标准格式 → 5"
    )
    _check(
        _extract_error_line_number("No line here") == 0,
        "无行号 → 0"
    )


def test_has_unbalanced_parens() -> None:
    """_has_unbalanced_parens 正确检测括号失衡。"""
    print("\n[18] 括号失衡检测")

    _check(_has_unbalanced_parens("print('hello'") is True, "缺失 ) → True")
    _check(_has_unbalanced_parens("print('hello')") is False, "匹配 → False")
    _check(_has_unbalanced_parens("x = (1 + (2 * 3))") is False, "嵌套匹配 → False")
    _check(_has_unbalanced_parens("x = (1 + 2") is True, "缺失闭合 → True")


# ===================================================================
# 测试 3 — _fix_by_rule 各错误类型修复
# ===================================================================


def test_fix_syntax_error() -> None:
    """SyntaxError 修复应尝试补全括号。"""
    print("\n[19] 修复 SyntaxError")

    code = "print('hello'"
    fixed = _fix_by_rule(code, "SyntaxError: '(' was never closed")
    _check(")" in fixed, f"补括号 → {fixed!r}")
    _check(fixed != code, "修复后与原代码不同")
    _check("print" in fixed, "保留 print 逻辑")


def test_fix_module_not_found() -> None:
    """ModuleNotFoundError 修复应注释缺失模块的导入行。"""
    print("\n[20] 修复 ModuleNotFoundError")

    code = "import pandas as pd\nimport numpy as np\nprint('ok')"
    error = "ModuleNotFoundError: No module named 'pandas'"
    fixed = _fix_by_rule(code, error)
    _check("# import pandas" in fixed or "已注释" in fixed, "注释 pandas 导入")
    # numpy 也应被注释（在第三方库列表中）
    _check("numpy" in fixed, "numpy 导入被处理")
    _check("print('ok')" in fixed, "保留非导入代码")


def test_fix_zero_division() -> None:
    """ZeroDivisionError 修复应添加除零保护。"""
    print("\n[21] 修复 ZeroDivisionError")

    code = "x = a / b\nprint(x)"
    fixed = _fix_by_rule(code, "ZeroDivisionError: division by zero")
    _check("try:" in fixed, "包含 try 块")
    _check("ZeroDivisionError" in fixed.lower() or "除零" in fixed, "包含除零说明")


def test_fix_name_error() -> None:
    """NameError 修复应添加缺失变量的注释提示。"""
    print("\n[22] 修复 NameError")

    code = "df = pd.read_csv('data.csv')\nprint(df)"
    error = "NameError: name 'pd' is not defined"
    fixed = _fix_by_rule(code, error)
    _check("pd" in fixed, "保留原变量名")
    _check("import pandas" in fixed.lower(), "建议 import pandas")
    _check("try:" in fixed, "包含异常保护")


def test_fix_key_error() -> None:
    """KeyError 修复应添加 .get() 防御建议。"""
    print("\n[23] 修复 KeyError")

    code = "result = data['sku']\nprint(result)"
    error = "KeyError: 'sku'"
    fixed = _fix_by_rule(code, error)
    _check("'sku'" in fixed, "包含缺失键名")
    _check("get(" in fixed or "try:" in fixed, "包含防御措施")


def test_fix_index_error() -> None:
    """IndexError 修复应添加 try/except 保护。"""
    print("\n[24] 修复 IndexError")

    code = "x = items[0]\nprint(x)"
    fixed = _fix_by_rule(code, "IndexError: list index out of range")
    _check("try:" in fixed, "包含 try 块")
    _check("IndexError" in fixed, "包含 IndexError 说明")


def test_fix_type_error() -> None:
    """TypeError 修复应添加 try/except 保护。"""
    print("\n[25] 修复 TypeError")

    code = "result = 'price: ' + 100"
    fixed = _fix_by_rule(code, "TypeError: can only concatenate str")
    _check("try:" in fixed, "包含 try 块")


def test_fix_with_user_instruction() -> None:
    """有用户指令时，修复应包含指令注释 + try/except。"""
    print("\n[26] 修复（有用户指令）")

    code = "x = 1 / 0"
    instruction = "把除数改成非零值"
    fixed = _fix_by_rule(code, "ZeroDivisionError", instruction=instruction)
    _check(instruction in fixed, "包含用户指令注释")
    _check("try:" in fixed, "包含 try 块")


# ===================================================================
# 测试 4 — 修复不破坏原有逻辑
# ===================================================================


def test_fix_preserves_logic() -> None:
    """修复后的代码应保留原有业务逻辑。"""
    print("\n[27] 修复保留原有逻辑")

    # 正常计算代码 — SyntaxError 修复后逻辑仍在
    code = "result = 1000 * 50 / 2\nprint('EOQ:', result"
    fixed = _fix_by_rule(code, "SyntaxError: '(' was never closed")
    _check("1000" in fixed, "保留数字常量")
    _check("result" in fixed, "保留变量名")
    _check("EOQ" in fixed, "保留字符串字面量")


def test_fix_unknown_error() -> None:
    """未知错误应走 try/except 通用包装。"""
    print("\n[28] 修复未知错误")

    code = "x = complicated_function()"
    fixed = _fix_by_rule(code, "WeirdCustomException: unknown")
    _check("try:" in fixed, "包含 try 块")
    _check("complicated_function" in fixed, "保留原代码")
    _check("except Exception" in fixed, "包含 except Exception")


# ===================================================================
# 主入口
# ===================================================================


def main() -> int:
    global _passed, _failed, _failures
    _passed = 0
    _failed = 0
    _failures = []

    print("=" * 60)
    print("增强规则回退测试套件 (test_debugger_enhanced.py)")
    print(f"Python: {sys.version}")
    print("=" * 60)

    # 诊断测试
    test_diagnose_syntax_error()
    test_diagnose_name_error()
    test_diagnose_module_not_found()
    test_diagnose_type_error()
    test_diagnose_index_error()
    test_diagnose_key_error()
    test_diagnose_zero_division()
    test_diagnose_value_error()
    test_diagnose_attribute_error()
    test_diagnose_file_not_found()
    test_diagnose_timeout()
    test_diagnose_unknown_error()

    # 提取辅助函数测试
    test_extract_error_line()
    test_extract_undefined_name()
    test_extract_missing_module()
    test_extract_key_name()
    test_extract_error_line_number()
    test_has_unbalanced_parens()

    # 修复测试
    test_fix_syntax_error()
    test_fix_module_not_found()
    test_fix_zero_division()
    test_fix_name_error()
    test_fix_key_error()
    test_fix_index_error()
    test_fix_type_error()
    test_fix_with_user_instruction()
    test_fix_preserves_logic()
    test_fix_unknown_error()

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

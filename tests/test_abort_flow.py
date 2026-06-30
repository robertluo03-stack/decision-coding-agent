"""retry_count 上限 + 失败报告集成测试。

验证 Debugger → Reporter ABORT 流程：
  1. retry_count >= 2 时 Debugger 不调用 LLM，直接返回 ABORT + error 字段
  2. human_feedback == "ABORT" 时 Reporter 生成失败报告（fail_<timestamp>.md）
  3. 失败报告包含：失败原因、重试次数、最后错误信息

所有测试不依赖外部网络/LLM/Docker。
"""

import sys
import tempfile
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.nodes.debugger import debugger_node
from src.agent.nodes.reporter import reporter_node, _write_report
from src.agent.state import AgentState


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> AgentState:
    """构造完整 AgentState 字典。"""
    defaults: AgentState = {
        "user_query": "读取 test.csv，统计每个 sku 的总销量",
        "workspace_path": str(Path(tempfile.gettempdir()) / "dc_abort_test_ws"),
        "plan": ["读取文件", "分组统计", "输出摘要"],
        "generated_code": "import pandas as pd\ndf = pd.read_csv('data/test.csv')\nprint(df.groupby('sku')['qty'].sum())",
        "file_path": "/tmp/test.py",
        "execution_result": None,
        "error": "KeyError: 'sku'",
        "retry_count": 2,
        "human_feedback": None,
        "final_report": None,
    }
    defaults.update(overrides)  # type: ignore[typeddict-item]
    return defaults


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
# 测试 1 — retry_count >= 2 直接 ABORT，不调用 LLM
# ===================================================================

def test_debugger_retry_limit_no_llm() -> None:
    """retry_count >= 2 时：1) 不调用 LLM 2) 返回 ABORT 3) 返回 error。"""
    print("\n[1] Debugger retry_count=2 → 直接 ABORT（不调用 LLM）")

    state = _make_state(retry_count=2, error="KeyError: 'sku'")

    # 调用 debugger_node 应该不触发 LLM（不会尝试 import ChatDeepSeek）
    result = debugger_node(state)

    # 验证返回 hf=ABORT
    _check(
        result.get("human_feedback") == "ABORT",
        f"human_feedback == 'ABORT' (实际: {result.get('human_feedback')!r})"
    )
    # 验证 retry_count 不变
    _check(
        result.get("retry_count") == 2,
        f"retry_count 保持 2 (实际: {result.get('retry_count')})"
    )
    # 验证 error 字段被设置
    error = result.get("error", "")
    _check(
        "已达到最大重试次数" in error,
        f"error 包含中文失败原因 (实际: {error!r})"
    )
    _check(
        "强制终止" in error,
        f"error 包含强制终止 (实际: {error!r})"
    )


# ===================================================================
# 测试 2 — retry_count >= 2 + 不同错误类型
# ===================================================================

def test_debugger_retry_limit_various_errors() -> None:
    """不同错误类型在 retry_count >= 2 时都应直接 ABORT。"""
    print("\n[2] Debugger retry_count >= 2 — 各种错误类型都直接 ABORT")

    for retry in [2, 3, 5]:
        for error in [
            "NameError: name 'pd' is not defined",
            "ModuleNotFoundError: No module named 'pandas'",
            "ZeroDivisionError: division by zero",
        ]:
            state = _make_state(retry_count=retry, error=error)
            result = debugger_node(state)
            _check(
                result.get("human_feedback") == "ABORT",
                f"retry={retry} {error[:25]}... → ABORT"
            )
            _check(
                "已达到最大重试次数" in (result.get("error") or ""),
                f"retry={retry}: error 字段已设置"
            )


# ===================================================================
# 测试 3 — Debugger 返回 error 字段被 Reporter 使用
# ===================================================================

def test_reporter_abort_report_uses_error() -> None:
    """Reporter 在 ABORT 状态下生成失败报告，包含 error 和 retry_count。"""
    print("\n[3] Reporter ABORT → 失败报告包含 error 和 retry_count")

    from src.agent.nodes.reporter import _build_report

    state = _make_state(
        retry_count=2,
        error="已达到最大重试次数（2），强制终止",
        human_feedback="ABORT",
        execution_result=None,
    )

    report = _build_report(state, is_aborted=True, has_error=True)

    # 失败报告标题
    _check("任务中止报告" in report, "标题包含'任务中止报告'")
    _check("🛑" in report, "状态图标 🛑")
    _check("用户中止" in report, "状态文本'用户中止'")

    # 包含失败原因
    _check(
        "已达到最大重试次数" in report,
        "失败报告包含错误详情"
    )
    _check(
        "强制终止" in report,
        "失败报告包含强制终止"
    )

    # 包含重试次数
    _check("2 / 2" in report, "失败报告包含重试次数 2/2")

    # 包含调试记录（终止原因）
    _check(
        "已达最大重试次数" in report or "强制终止" in report,
        "调试记录包含终止原因"
    )


# ===================================================================
# 测试 4 — 失败报告写入 fail_<timestamp>.md
# ===================================================================

def test_reporter_fail_filename() -> None:
    """ABORT 状态下 _write_report 写入 fail_<timestamp>.md。"""
    print("\n[4] Reporter ABORT → 写入 fail_<timestamp>.md")

    ws = Path(tempfile.gettempdir()) / "dc_abort_test_failfn"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "reports").mkdir(parents=True, exist_ok=True)

    # ABORT 状态
    state_abort = _make_state(
        workspace_path=str(ws),
        human_feedback="ABORT",
    )
    report = "# 测试失败报告"
    filepath = _write_report(state_abort, report)

    _check(
        filepath.name.startswith("fail_"),
        f"ABORT → 文件名以 fail_ 开头 (实际: {filepath.name})"
    )
    _check(
        filepath.suffix == ".md",
        f"扩展名 .md (实际: {filepath.suffix})"
    )
    _check(
        filepath.exists(),
        f"文件存在: {filepath}"
    )
    content = filepath.read_text(encoding="utf-8")
    _check(
        "测试失败报告" in content,
        "文件内容正确"
    )

    # 非 ABORT 状态
    state_normal = _make_state(
        workspace_path=str(ws),
        human_feedback="AI_FIX:...",
    )
    filepath2 = _write_report(state_normal, "# 测试成功报告")
    _check(
        filepath2.name.startswith("report_"),
        f"非 ABORT → 文件名以 report_ 开头 (实际: {filepath2.name})"
    )

    # 清理
    try:
        filepath.unlink()
        filepath2.unlink()
        (ws / "reports").rmdir()
        ws.rmdir()
    except Exception:
        pass


# ===================================================================
# 测试 5 — 失败报告格式与成功报告一致（Markdown 结构）
# ===================================================================

def test_reporter_abort_markdown_structure() -> None:
    """失败报告保持 Markdown 结构完整性（标题、代码块、分隔线、附录）。"""
    print("\n[5] 失败报告 Markdown 结构完整性")

    from src.agent.nodes.reporter import _build_report

    state = _make_state(
        retry_count=2,
        error="已达到最大重试次数（2），强制终止",
        human_feedback="ABORT",
        plan=["步骤1", "步骤2"],
        generated_code="print('test')",
    )

    report = _build_report(state, is_aborted=True, has_error=True)

    # 结构检查
    _check(report.startswith("#"), "以一级标题开头")
    _check("## 1. 任务描述" in report, "包含任务描述章节")
    _check("## 2. 执行计划" in report, "包含执行计划章节")
    _check("## 3. 生成代码" in report, "包含生成代码章节")
    _check("```python" in report, "包含 Python 代码块")
    _check("## 5. 错误信息与调试记录" in report, "包含错误信息与调试记录章节")
    _check("## 附录" in report, "包含附录章节")
    _check("---" in report, "包含分隔线")

    # 代码块配对检查
    backtick_count = report.count("```")
    _check(
        backtick_count % 2 == 0,
        f"代码块正确配对 (共 {backtick_count} 个 ```)"
    )


# ===================================================================
# 测试 6 — 端到端：Debugger(ABORT) → Reporter(失败报告)
# ===================================================================

def test_end_to_end_abort_flow() -> None:
    """完整流程：Debugger retry_count=2 → ABORT → Reporter 生成失败报告。"""
    print("\n[6] 端到端：Debugger(ABORT) → Reporter(失败报告)")

    state = _make_state(
        retry_count=2,
        error="KeyError: 'sku'",
        human_feedback=None,
    )

    # Step 1: Debugger 返回 ABORT + error
    db_result = debugger_node(state)
    _check(db_result["human_feedback"] == "ABORT", "Debugger 返回 ABORT")
    _check("error" in db_result, "Debugger 返回 error 字段")

    # 模拟 LangGraph 合并（partial state merge）
    state_merged = dict(state)
    state_merged.update(db_result)

    # Step 2: Reporter 使用合并后的状态
    rp_result = reporter_node(state_merged)

    report = rp_result.get("final_report", "")
    _check(len(report) > 0, "Reporter 生成了报告")
    _check("任务中止报告" in report, "报告标题为失败报告")
    _check(
        "已达到最大重试次数" in report or "强制终止" in report,
        "报告包含 Debugger 设置的终止原因"
    )
    _check("重试次数" in report,
           "报告中包含调试记录")
    # 注意：Debugger 返回的 error 字段会覆盖 Executor 的错误（LangGraph partial merge），
    # 所以 Reporter 看到的 error 是 "已达到最大重试次数..." 而不是原始 KeyError。
    # 这是正确行为——终止原因就是最终的 error 状态。


# ===================================================================
# 主入口
# ===================================================================


def main() -> int:
    global _passed, _failed, _failures
    _passed = 0
    _failed = 0
    _failures = []

    print("=" * 60)
    print("retry_count 上限 + 失败报告集成测试")
    print(f"Python: {sys.version}")
    print("=" * 60)

    test_debugger_retry_limit_no_llm()
    test_debugger_retry_limit_various_errors()
    test_reporter_abort_report_uses_error()
    test_reporter_fail_filename()
    test_reporter_abort_markdown_structure()
    test_end_to_end_abort_flow()

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

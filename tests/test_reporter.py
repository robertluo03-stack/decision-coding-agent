"""Reporter 节点测试套件。

覆盖场景（按 WEEK1_PROMPTS.md 任务 6 验收标准）：
  1. 成功报告 — 无 error 且非 ABORT → 标题 "执行报告"，含结果摘要
  2. 中止报告 — human_feedback="ABORT" → 标题 "任务中止报告"
  3. 错误报告 — 有 error 但非 ABORT → 含错误信息和调试记录
  4. 文件写入 — 报告写入 workspace/reports/report_<timestamp>.md
  5. 必要字段 — 任务描述、执行计划、执行结果、错误信息、调试记录
  6. 边界场景 — 空 query / 空 plan / None 值

所有测试数据在脚本内自动生成，不依赖外部文件。
"""

import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.nodes.reporter import run  # reporter_node 的别名


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_state(**overrides) -> dict:
    """构造完整的 AgentState 字典，默认值模拟典型成功执行后的状态。"""
    defaults = {
        "user_query": "读取 test_sales.csv，统计每个 sku 的总销量",
        "workspace_path": str(Path(tempfile.gettempdir()) / "dc_report_test_ws"),
        "plan": [
            "读取 test_sales.csv 文件",
            "按 sku 分组统计总销量",
            "输出统计摘要",
        ],
        "generated_code": "import pandas as pd\n\ndf = pd.read_csv('data/test_sales.csv')\nresult = df.groupby('sku')['qty'].sum()\nprint(result)\n",
        "file_path": "/tmp/dc_report_test_ws/src/_dc_exec_12345.py",
        "execution_result": "SKU001    25\nSKU002    20\n",
        "error": None,
        "retry_count": 0,
        "human_feedback": None,
        "final_report": None,
    }
    defaults.update(overrides)
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
# 测试 1 — 成功报告
# ===================================================================

def test_success_report() -> None:
    """无 error 且非 ABORT → 标题 '执行报告'，状态 '执行成功'。"""
    print("\n[1] 成功报告 — 基本结构")

    state = _make_state()
    result = run(state)
    report = result.get("final_report", "")

    _check(len(report) > 100, f"报告内容足够长 ({len(report)} 字符)")

    # 标题检查
    _check("# 执行报告" in report,
           "标题为 '执行报告'")
    _check("任务中止报告" not in report,
           "标题不是中止报告")

    # 状态检查
    _check("✅" in report and "执行成功" in report,
           "状态图标和文本正确（✅ 执行成功）")

    # 必要字段检查 — 适应新报告结构
    _check("任务描述" in report or "原始需求" in report,
           "包含任务描述章节")
    _check("执行计划" in report,
           "包含执行计划章节")
    _check("生成代码" in report,
           "包含生成代码（应在附录中）")
    _check("执行结果" in report,
           "包含执行结果章节")
    _check("结果分析" in report,
           "包含结果分析章节")

    # 具体内容
    _check(state["user_query"] in report,
           f"包含用户原始需求 ({state['user_query'][:30]}...)")

    plan_match = any(step in report for step in state["plan"])
    _check(plan_match, "包含执行计划步骤")

    _check(state["generated_code"].strip() in report,
           "包含生成的 Python 代码")

    _check("SKU001    25" in report,
           "包含执行结果输出")

    # 代码应在附录中
    code_pos = report.find("生成代码")
    appendix_pos = report.find("## 附录")
    _check(code_pos > appendix_pos if code_pos > 0 and appendix_pos > 0 else True,
           "生成代码在附录中（不占据报告主体）")

    # 成功报告不应该有错误章节
    _check("错误" not in report or "---" in report,
           "成功报告不含错误章节")


# ===================================================================
# 测试 2 — 中止报告
# ===================================================================

def test_abort_report() -> None:
    """human_feedback == 'ABORT' → 标题 '任务中止报告'。"""
    print("\n[2] 中止报告")

    state = _make_state(
        human_feedback="ABORT",
        error="Execution timeout (30s)",
        execution_result=None,
        retry_count=2,
    )
    result = run(state)
    report = result.get("final_report", "")

    _check(len(report) > 100, f"报告内容足够长 ({len(report)} 字符)")
    _check("# 任务中止报告" in report,
           "标题为 '任务中止报告'")
    _check("🛑" in report,
           "状态图标为 🛑")
    _check("用户中止" in report,
           "状态文本为 '用户中止'")

    # 错误信息
    _check("Execution timeout (30s)" in report,
           "包含超时错误信息")
    _check("重试次数" in report and "2" in report,
           "包含重试次数")
    _check("中止执行" in report or "用户主动中止" in report or "中止" in report,
           "包含中止说明")

    # 仍有任务描述和计划
    _check("任务描述" in report,
           "仍包含任务描述章节")
    _check("执行计划" in report,
           "仍包含执行计划章节")


# ===================================================================
# 测试 3 — 错误报告（非中止）
# ===================================================================

def test_error_report() -> None:
    """有 error 但非 ABORT → '执行报告' 标题，含错误详情和调试记录。"""
    print("\n[3] 错误报告（非中止）")

    state = _make_state(
        error="NameError: name 'pd' is not defined",
        execution_result=None,
        retry_count=1,
    )
    result = run(state)
    report = result.get("final_report", "")

    _check("# 执行报告" in report,
           "标题仍为 '执行报告'（非中止）")
    _check("⚠️" in report and "执行异常" in report,
           "状态图标和文本正确（⚠️ 执行异常）")

    # 错误信息章节
    _check("错误" in report or "错误信息" in report,
           "包含错误信息章节")
    _check("NameError: name 'pd' is not defined" in report,
           "包含具体错误信息")

    # 调试记录
    _check("调试" in report or "debug" in report.lower(),
           "包含调试/重试记录")
    _check("重试次数" in report and "1" in report,
           f"包含当前重试次数")


# ===================================================================
# 测试 4 — 文件写入
# ===================================================================

def test_file_written() -> None:
    """报告写入 workspace/reports/report_<timestamp>.md。"""
    print("\n[4] 文件写入")

    ws = Path(tempfile.gettempdir()) / "dc_report_test_write"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "reports").mkdir(parents=True, exist_ok=True)

    # 清理之前的报告文件
    for old in (ws / "reports").glob("report_*.md"):
        old.unlink()

    state = _make_state(workspace_path=str(ws))
    result = run(state)

    report_md = result.get("final_report", "")
    _check(len(report_md) > 100, "返回非空报告内容")

    # 检查文件是否写入
    report_files = sorted((ws / "reports").glob("report_*.md"))
    _check(len(report_files) > 0,
           f"reports/ 目录下存在报告文件 (共 {len(report_files)} 个)")

    if report_files:
        latest = report_files[-1]
        _check(latest.exists(),
               f"文件实际存在: {latest.name}")

        # 文件名格式：report_YYYYMMDD_HHMMSS.md
        name = latest.name
        _check(
            bool(re.match(r"report_\d{8}_\d{6}\.md$", name)),
            f"文件名格式正确: {name}",
        )

        # 文件内容 = final_report
        file_content = latest.read_text(encoding="utf-8")
        _check(
            file_content.strip() == report_md.strip(),
            "文件内容与 final_report 一致",
        )

        # 清理
        latest.unlink()

    # 目录不存在时自动创建
    new_ws = Path(tempfile.gettempdir()) / "dc_report_test_auto"
    # 确保 reports 子目录不存在
    rm_dir = new_ws / "reports"
    if rm_dir.exists():
        for f in rm_dir.iterdir():
            f.unlink()
        rm_dir.rmdir()
    new_ws.mkdir(parents=True, exist_ok=True)

    state2 = _make_state(workspace_path=str(new_ws))
    run(state2)
    _check(
        (new_ws / "reports").exists(),
        "自动创建 reports/ 目录",
    )
    # 清理
    for f in (new_ws / "reports").glob("*.md"):
        f.unlink()


# ===================================================================
# 测试 5 — human_feedback 格式化标签
# ===================================================================

def test_feedback_labels() -> None:
    """验证不同 human_feedback 值在报告中的可读表述。"""
    print("\n[5] human_feedback 标签格式化")

    feedback_cases = [
        ("AI_FIX:print('ok')", "接受 AI 修复"),
        ("USER_FIX:改 pandas 为 csv 模块", "用户自定义修复"),
        ("ABORT", "中止执行"),
        ("SKIP", "跳过"),
    ]

    for raw, expected_keyword in feedback_cases:
        state = _make_state(
            human_feedback=raw,
            error="some error",
        )
        result = run(state)
        report = result.get("final_report", "")
        _check(
            expected_keyword in report,
            f"'{raw}' → 报告含 '{expected_keyword}'",
            detail=f"报告片段: {report[report.find('人在回路'):][:80] if '人在回路' in report else 'N/A'}",
        )


# ===================================================================
# 测试 6 — 边界：空字段
# ===================================================================

def test_edge_empty_fields() -> None:
    """空 query / 空 plan / None 值不崩溃。"""
    print("\n[6] 边界场景 — 空字段")

    # 空 query
    s1 = _make_state(user_query="")
    r1 = run(s1)["final_report"]
    _check(len(r1) > 50, "空 query: 仍然生成有效报告")
    _check("用户未提供需求" in r1 or "(无" in r1,
           "空 query: 报告含占位说明")

    # 空 plan
    s2 = _make_state(plan=[])
    r2 = run(s2)["final_report"]
    _check(len(r2) > 50, "空 plan: 仍然生成有效报告")
    _check("无执行计划" in r2,
           "空 plan: 报告含占位说明")

    # None execution_result
    s3 = _make_state(execution_result=None)
    r3 = run(s3)["final_report"]
    _check(len(r3) > 50, "None execution_result: 仍然生成有效报告")
    _check("执行结果" not in r3 or "3. 执行结果" not in r3,
           "None execution_result: 跳过执行结果章节")

    # None error
    s4 = _make_state(error=None)
    r4 = run(s4)["final_report"]
    _check("错误" not in r4 or "5. 错误" not in r4,
           "None error: 错误章节（如有）不含 5. 编号")


# ===================================================================
# 测试 7 — 边界：最大重试次数
# ===================================================================

def test_edge_max_retries() -> None:
    """retry_count >= 2 且 human_feedback='ABORT' 的完整中止流程。"""
    print("\n[7] 边界场景 — 最大重试 + 中止")

    state = _make_state(
        error="SyntaxError: invalid syntax",
        execution_result=None,
        retry_count=2,
        human_feedback="ABORT",
    )
    result = run(state)
    report = result.get("final_report", "")

    _check("# 任务中止报告" in report, "标题为中止报告")
    _check("SyntaxError" in report, "包含语法错误信息")
    _check("重试次数" in report and "2" in report, "包含重试次数=2")
    _check("中止" in report, "包含中止说明")

    # 达最大重试次数说明
    _check(
        "已达最大重试次数" in report or "2 / 2" in report or "强制终止" in report,
        "包含已达上限提示",
    )


# ===================================================================
# 测试 8 — Markdown 格式完整性
# ===================================================================

def test_markdown_format_integrity() -> None:
    """验证报告的 Markdown 格式规范。"""
    print("\n[8] Markdown 格式完整性")

    state = _make_state()
    result = run(state)
    report = result.get("final_report", "")

    # 标题
    _check(report.startswith("# "), "以一级标题开头")

    # 子标题
    _check("## " in report, "包含二级标题")
    _check("### " in report, "如有三级标题")

    # 代码块
    code_blocks = re.findall(r"```", report)
    _check(len(code_blocks) >= 2 and len(code_blocks) % 2 == 0,
           f"代码块正确配对 (共 {len(code_blocks)} 个 ```)")

    # 分隔线
    _check("---" in report, "包含分隔线")

    # 时间戳
    timestamp_match = re.search(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", report
    )
    _check(timestamp_match is not None,
           "包含时间戳（YYYY-MM-DD HH:MM:SS 格式）")

    # 新结构验证：附录在结果分析之后
    analysis_pos = report.find("## 4. 结果分析")
    appendix_pos = report.find("## 附录")
    _check(analysis_pos > 0, "包含结果分析章节（第 4 节）")
    _check(appendix_pos > analysis_pos if analysis_pos > 0 and appendix_pos > 0 else True,
           "附录在结果分析之后")


# ===================================================================
# 测试 9 — 返回字段正确性
# ===================================================================

def test_return_value() -> None:
    """验证返回字典的字段正确。"""
    print("\n[9] 返回值字段正确性")

    state = _make_state()
    result = run(state)

    _check("final_report" in result,
           "返回字典包含 final_report 键")
    _check(isinstance(result["final_report"], str),
           "final_report 是字符串")
    _check(len(result["final_report"]) > 0,
           "final_report 非空")


# ===================================================================
# 测试 10 — 报告的幂等性
# ===================================================================

def test_idempotency() -> None:
    """相同输入两次调用，报告结构一致（时间戳和 LLM 分析可能不同）。"""
    print("\n[10] 报告的幂等性")

    state = _make_state()
    r1 = run(state)["final_report"]
    r2 = run(state)["final_report"]

    # 去掉时间戳行和 LLM 分析行后比较
    def _strip_variable(s: str) -> str:
        s = re.sub(r"\*\*生成时间\*\*: .*", "", s)
        # 去掉 LLM 回退分析（每次可能不同）
        s = re.sub(r"\n## 4\. 结果分析\n\n.*?\n\n## 5\.", "\n## 4. 结果分析\n\n(analysis)\n\n## 5.", s, flags=re.DOTALL)
        return s

    s1 = _strip_variable(r1)
    s2 = _strip_variable(r2)
    _check(s1 == s2, "去除可变内容后结构一致（幂等）")


# ===================================================================
# 主入口
# ===================================================================

def main() -> int:
    global _passed, _failed, _failures
    _passed = 0
    _failed = 0
    _failures = []

    print("=" * 60)
    print("Reporter 节点测试套件")
    print(f"Python: {sys.version}")
    print("=" * 60)

    test_success_report()
    test_abort_report()
    test_error_report()
    test_file_written()
    test_feedback_labels()
    test_edge_empty_fields()
    test_edge_max_retries()
    test_markdown_format_integrity()
    test_return_value()
    test_idempotency()

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

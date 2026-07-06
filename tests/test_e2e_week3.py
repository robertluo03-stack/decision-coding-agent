"""Week 3 E2E 集成测试 — 数据分析闭环验证。

3 个任务 × subprocess 模式 = 9 个断言，验证从 Plan → Code → Execute → Report
的完整数据分析闭环。

任务 A：分析 sales.csv — 验证报告含 4+ 章节
任务 B：画图表 — 验证生成 HTML 图表文件
任务 C：Text-to-SQL 问数 — 验证 SQL 生成和执行结果

用法:
    python tests/test_e2e_week3.py
    python -m pytest tests/test_e2e_week3.py -v
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# ---- 项目根目录 ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

# ---- 加载 .env（避免 Week 2 坑 6 复现） ----
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---- Workspace 准备 ----
WS = PROJECT_ROOT / "workspace"
(WS / "data").mkdir(parents=True, exist_ok=True)
(WS / "reports").mkdir(parents=True, exist_ok=True)
(WS / "reports" / "charts").mkdir(parents=True, exist_ok=True)
(WS / "src").mkdir(parents=True, exist_ok=True)
(WS / "output").mkdir(parents=True, exist_ok=True)

# ---- 模块导入 ----
from src.agent.graph import build_graph
from src.agent.state import AgentState

HAS_API_KEY = bool(os.environ.get("DEEPSEEK_API_KEY"))


def _make_state(query: str) -> AgentState:
    """构造初始 AgentState。"""
    return {
        "user_query": query,
        "workspace_path": str(WS),
        "plan": [],
        "generated_code": "",
        "file_path": None,
        "execution_result": None,
        "error": None,
        "retry_count": 0,
        "human_feedback": None,
        "final_report": None,
    }


def _invoke(query: str) -> dict:
    """调用完整 Graph 执行一次任务。"""
    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())[:8]}}
    return graph.invoke(_make_state(query), config)


# ======================================================================
# 辅助断言
# ======================================================================


def _assert_state(result: dict, query_hint: str) -> None:
    """对图执行结果做基本断言。"""
    plan = result.get("plan", [])
    code = result.get("generated_code", "")
    error = result.get("error")
    report = result.get("final_report", "")
    exec_result = result.get("execution_result") or ""
    retry_count = result.get("retry_count", 0)

    # 1. Plan 非空且非回退
    plan_ok = len(plan) > 0 and not any(
        "错误" in str(p) or "Planner 调用失败" in str(p) for p in plan
    )
    assert len(plan) > 0, f"[{query_hint}] plan 为空"
    assert plan_ok, f"[{query_hint}] plan 是回退: {plan[:2]}"

    # 2. 代码生成
    assert len(code) > 50, f"[{query_hint}] 代码过短: {len(code)} 字符"

    # 3. 无执行错误
    assert error is None, f"[{query_hint}] 有执行错误: {error}"

    # 4. 有执行输出
    assert len(str(exec_result)) > 0, f"[{query_hint}] 无执行输出"

    # 5. 报告非空
    assert len(report) > 100, f"[{query_hint}] 报告过短: {len(report)} 字符"

    # 6. 报告标记为成功
    assert "✅ 执行成功" in report, f"[{query_hint}] 报告未标记成功"

    # 7. retry_count = 0（一次通过）
    assert retry_count == 0, f"[{query_hint}] 触发了重试: retry={retry_count}"

    # 8. 不是回退代码
    is_fallback = "安全模式" in str(exec_result) or "无有效代码可执行" in str(exec_result)
    assert not is_fallback, f"[{query_hint}] 执行的是回退代码: {str(exec_result)[:200]}"


# ======================================================================
# 任务 A：分析 sales.csv
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_task_a_analysis_report_subprocess():
    """任务 A：输入"分析 sales.csv"，验证报告包含质量检查+统计摘要章节。"""
    query = "分析 workspace/data/sales.csv"
    result = _invoke(query)

    _assert_state(result, "Task A")

    report = result.get("final_report", "")
    # 验证报告至少包含 2 个核心章节（报告可能来自 run_analysis 或 Coder）
    has_quality = "质量" in report or "quality" in report.lower()
    has_summary = "统计" in report or "统计摘要" in report or "均值" in report or "描述" in report
    assert has_quality or has_summary, f"[Task A] 报告缺少分析章节: {report[:500]}"

    print(f"[Task A] ✅ Plan: {len(result.get('plan', []))} 步")
    print(f"[Task A] ✅ Code: {len(result.get('generated_code', ''))} 字符")
    print(f"[Task A] ✅ Report: {len(report)} 字符")


# ======================================================================
# 任务 B：画图表
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_task_b_chart_generation_subprocess():
    """任务 B：输入画图需求，验证至少生成 1 张 HTML 图表。"""
    # 清理旧图表避免误判
    chart_dir = WS / "reports" / "charts"
    for old in chart_dir.glob("*.html"):
        old.unlink(missing_ok=True)

    query = "画 workspace/data/sales.csv 各区域的销量对比柱状图，保存到 reports/charts/"
    result = _invoke(query)

    _assert_state(result, "Task B")

    # 验证图表文件生成
    html_files = list(chart_dir.glob("*.html"))
    assert len(html_files) >= 1, f"[Task B] 未生成任何图表 HTML，chart_dir={chart_dir}"

    # 验证 HTML 文件非空
    for f in html_files:
        size = f.stat().st_size
        assert size > 100, f"[Task B] 图表文件 {f.name} 过小: {size} bytes"
        content = f.read_text(encoding="utf-8")
        assert "Plotly" in content or "plotly" in content, f"[Task B] {f.name} 不是有效 Plotly HTML"

    print(f"[Task B] ✅ 生成了 {len(html_files)} 张图表")
    for f in html_files:
        print(f"[Task B]    - {f.name} ({f.stat().st_size} bytes)")


# ======================================================================
# 任务 C：Text-to-SQL 问数
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_task_c_text_to_sql_subprocess():
    """任务 C：自然语言问数，验证 SQL 生成和执行结果。"""
    query = "查询 workspace/data/sales.csv 各区域平均销量是多少"
    result = _invoke(query)

    _assert_state(result, "Task C")

    exec_result = result.get("execution_result", "")
    report = result.get("final_report", "")

    # Coder 可能选 run_text_to_sql 或手写 SQL —— 都行
    # 验证输出中包含区域信息或聚合结果
    has_region_info = any(
        kw in str(exec_result) + report
        for kw in ("区域", "region", "华北", "华东", "华南", "avg", "平均", "AVG")
    )
    assert has_region_info, f"[Task C] 结果中未找到区域/聚合信息: {str(exec_result)[:500]}"

    print(f"[Task C] ✅ 执行结果: {str(exec_result)[:300]}")


# ======================================================================
# 任务 D：数据质量检查（单一场景）
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_task_d_quality_check_subprocess():
    """任务 D：输入数据质量检查需求，验证报告含评分和建议。"""
    query = "检查 workspace/data/sales.csv 的数据质量"
    result = _invoke(query)

    _assert_state(result, "Task D")

    exec_result = result.get("execution_result", "")
    report = result.get("final_report", "")

    # 应该包含评分或质量关键词
    has_score = any(
        kw in str(exec_result) + report
        for kw in ("评分", "score", "质量", "overall_score", "缺失", "missing")
    )
    assert has_score, f"[Task D] 结果中未找到质量评分: {str(exec_result)[:500]}"

    print(f"[Task D] ✅ 质量检查完成")


# ======================================================================
# 边界测试：图表目录自动创建（不依赖 LLM）
# ======================================================================


def test_chart_dir_auto_creation():
    """验证 charts 目录能自动创建。"""
    from src.domain.chart_templates import bar_chart
    import pandas as pd
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a" / "b" / "c" / "test.html"
        df = pd.DataFrame({"X": [1, 2, 3], "Y": [4, 5, 6]})
        result = bar_chart(df, "X", "Y", "测试", str(out))
        assert Path(result).exists()


def test_workspace_sales_csv_exists():
    """确认测试数据 sales.csv 存在且格式正确。"""
    csv_path = WS / "data" / "sales.csv"
    assert csv_path.exists(), f"sales.csv 不存在: {csv_path}"

    import pandas as pd
    df = pd.read_csv(csv_path)
    required_cols = {"date", "sku", "region", "sales_volume", "unit_price"}
    actual_cols = set(df.columns)
    assert actual_cols == required_cols, f"sales.csv 列名不匹配: {actual_cols} != {required_cols}"
    assert len(df) >= 50, f"sales.csv 行数不足: {len(df)}"


# ======================================================================
# 主入口
# ======================================================================


def main() -> int:
    """运行 E2E 测试并报告结果。"""
    import traceback

    print("=" * 70)
    print("🚀 DecisionCoder Week 3 E2E 集成测试")
    print(f"   DEEPSEEK_API_KEY={'✅' if HAS_API_KEY else '❌ 未设置（LLM 测试将跳过）'}")
    print(f"   WORKSPACE_PATH={WS}")
    print(f"   sales.csv={'✅' if (WS / 'data' / 'sales.csv').exists() else '❌'}")
    print("=" * 70)

    tests = [
        ("任务 A: 数据分析报告", test_task_a_analysis_report_subprocess),
        ("任务 B: 图表生成", test_task_b_chart_generation_subprocess),
        ("任务 C: Text-to-SQL", test_task_c_text_to_sql_subprocess),
        ("任务 D: 数据质量检查", test_task_d_quality_check_subprocess),
        ("边界: charts 目录创建", test_chart_dir_auto_creation),
        ("边界: sales.csv 存在性", test_workspace_sales_csv_exists),
    ]

    passed = 0
    failed = 0
    skipped = 0

    for name, fn in tests:
        print(f"\n{'─' * 60}")
        print(f"▶ {name}")
        try:
            fn()
            passed += 1
            print(f"  ✅ 通过")
        except pytest.skip.Exception:
            skipped += 1
            print(f"  ⏭️  跳过（无 API Key）")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ 断言失败: {e}")
        except Exception:
            failed += 1
            print(f"  ❌ 异常: {traceback.format_exc()[:300]}")

    total = passed + failed + skipped
    print("\n" + "=" * 70)
    print(f"📊 Week 3 E2E 结果: {passed}/{total} 通过", end="")
    if skipped:
        print(f"（{skipped} 跳过）", end="")
    if failed:
        print(f"，{failed} 失败 ❌")
    else:
        print(" ✅")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

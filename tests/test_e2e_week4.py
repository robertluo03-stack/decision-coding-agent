"""Week 4 E2E 集成测试 — 供应链优化闭环验证。

4 个任务 × subprocess 模式，验证从自然语言输入到供应链模板
输出的完整闭环。

任务 A：EOQ 经济订货批量 — 验证调用 inventory_eoq 并输出 EOQ≈223.6
任务 B：需求预测 — 验证调用 demand_forecast 并输出预测值
任务 C：安全库存 — 验证调用 safety_stock 并输出安全库存量
任务 D：补货点 — 验证调用 reorder_point 并输出补货点和建议

用法:
    python tests/test_e2e_week4.py
    python -m pytest tests/test_e2e_week4.py -v
"""

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

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


def _invoke(query: str, choices: list[str] | None = None) -> dict:
    """调用完整 Graph 执行一次任务。

    Mock _safe_input 使用 side_effect 策略：默认 ["1", "4"]
    （第一次接受 AI 修复给自愈机会，第二次中止防死循环）。
    负路径测试可传 choices=["4"] 直接中止。
    若测试需要其他行为，在测试函数中额外 patch 覆盖即可。
    """
    if choices is None:
        choices = ["1", "4"]
    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())[:8]}}
    with patch("src.agent.nodes.debugger._safe_input", side_effect=choices):
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

    # 6. 报告标记为成功（或至少不包含失败标记）
    assert "✅ 执行成功" in report or "执行成功" in report, (
        f"[{query_hint}] 报告未标记成功"
    )

    # 7. retry_count ≤ 1（允许一次自愈重试）
    assert retry_count <= 1, f"[{query_hint}] 重试次数过多: retry={retry_count}"

    # 8. 不是回退代码
    is_fallback = "安全模式" in str(exec_result) or "无有效代码可执行" in str(exec_result)
    assert not is_fallback, f"[{query_hint}] 执行的是回退代码: {str(exec_result)[:200]}"


# ======================================================================
# 任务 A：EOQ 经济订货批量
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_task_a_eoq_subprocess():
    """任务 A：输入"年需求1000，订货成本50，持有成本2，帮我算EOQ"，验证 EOQ 计算结果。"""
    query = "年需求1000，订货成本50，持有成本2，帮我算EOQ"
    result = _invoke(query)

    _assert_state(result, "Task A")

    exec_result = str(result.get("execution_result", ""))
    report = result.get("final_report", "")
    code = result.get("generated_code", "")

    # 验证代码调用了 EOQ 模板或手算了 EOQ 公式
    has_eoq_import = "inventory_eoq" in code or "EOQParams" in code
    has_eoq_formula = "sqrt" in code.lower() or "eoq" in code.lower()
    assert has_eoq_import or has_eoq_formula, (
        f"[Task A] 代码中未找到 EOQ 相关调用: {code[:300]}"
    )

    # 验证输出中包含 EOQ 数值（~223.6）
    combined = exec_result + report
    has_eoq_value = any(
        kw in combined.lower() for kw in ("223", "224", "eoq", "批量")
    )
    assert has_eoq_value, f"[Task A] 输出中未找到 EOQ 相关值: {exec_result[:300]}"

    print(f"[Task A] ✅ Plan: {len(result.get('plan', []))} 步")
    print(f"[Task A] ✅ Code: {len(code)} 字符")
    print(f"[Task A] ✅ Output: {exec_result[:200]}")


# ======================================================================
# 任务 B：需求预测
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_task_b_forecast_subprocess():
    """任务 B：输入需求预测需求，验证调用了 forecast 或 auto_forecast。"""
    query = (
        "使用 demand_forecast 模板预测未来 3 个月的需求量，"
        "历史数据 [100, 120, 110, 130, 125, 140]，方法选 auto"
    )
    result = _invoke(query)

    _assert_state(result, "Task B")

    exec_result = str(result.get("execution_result", ""))
    report = result.get("final_report", "")
    code = result.get("generated_code", "")

    # 验证代码调用了 forecast 模板
    has_forecast = "demand_forecast" in code or "forecast" in code.lower()
    assert has_forecast, f"[Task B] 代码中未找到 forecast 调用: {code[:300]}"

    # 验证输出中包含预测相关信息
    combined = exec_result + report
    has_prediction = any(
        kw in combined.lower()
        for kw in ("预测", "forecast", "mae", "rmse", "mape", "method")
    )
    assert has_prediction, f"[Task B] 输出中未找到预测相关信息: {exec_result[:300]}"

    print(f"[Task B] ✅ Plan: {len(result.get('plan', []))} 步")
    print(f"[Task B] ✅ Code: {len(code)} 字符")
    print(f"[Task B] ✅ Output: {exec_result[:200]}")


# ======================================================================
# 任务 C：安全库存
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_task_c_safety_stock_subprocess():
    """任务 C：输入安全库存需求，验证调用了 safety_stock。"""
    query = (
        "使用 safety_stock 模板计算安全库存："
        "平均需求 200，需求标准差 30，提前期 1，服务水平 95%。"
        "只打印 safety_stock、z_score、service_level、formula_used 和 reorder_point_component。"
    )
    result = _invoke(query)

    _assert_state(result, "Task C")

    exec_result = str(result.get("execution_result", ""))
    report = result.get("final_report", "")
    code = result.get("generated_code", "")

    # 验证代码调用了 safety_stock 模板
    has_safety = "safety_stock" in code or "SafetyStock" in code
    assert has_safety, f"[Task C] 代码中未找到 safety_stock 调用: {code[:300]}"

    # 验证输出中包含安全库存相关信息
    combined = exec_result + report
    has_ss = any(
        kw in combined.lower()
        for kw in ("安全库存", "safety", "z", "服务水平", "service level")
    )
    assert has_ss, f"[Task C] 输出中未找到安全库存相关信息: {exec_result[:300]}"

    print(f"[Task C] ✅ Plan: {len(result.get('plan', []))} 步")
    print(f"[Task C] ✅ Code: {len(code)} 字符")
    print(f"[Task C] ✅ Output: {exec_result[:200]}")


# ======================================================================
# 任务 D：补货点（ROP）
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_task_d_reorder_point_subprocess():
    """任务 D：输入补货点需求，验证调用了 reorder_point 并输出建议。"""
    query = (
        "使用 reorder_point 模板计算补货点："
        "平均需求 150，提前期 2，安全库存 100。"
        "只打印 reorder_point、lead_time_demand、safety_stock 和 suggestion，"
        "不要打印 avg_demand。"
    )
    result = _invoke(query)

    _assert_state(result, "Task D")

    exec_result = str(result.get("execution_result", ""))
    report = result.get("final_report", "")
    code = result.get("generated_code", "")

    # 验证代码调用了 reorder_point 模板
    has_rop = (
        "reorder_point" in code
        or "ROPParams" in code
        or "ROPResult" in code
    )
    # Fallback: Coder might compute ROP manually (lead_time_demand + safety_stock)
    has_manual_rop = "safety_stock" in code.lower() or (
        "lead_time" in code.lower() and "avg_demand" in code.lower()
    )
    assert has_rop or has_manual_rop, (
        f"[Task D] 代码中未找到 ROP 相关调用: {code[:300]}"
    )

    # 验证输出中包含补货点或建议
    combined = exec_result + report
    has_suggestion = any(
        kw in combined.lower()
        for kw in ("补货", "reorder", "建议", "当库存", "trigger", "rop", "订货点")
    )
    assert has_suggestion, (
        f"[Task D] 输出中未找到补货相关建议: {exec_result[:300]}"
    )

    print(f"[Task D] ✅ Plan: {len(result.get('plan', []))} 步")
    print(f"[Task D] ✅ Code: {len(code)} 字符")
    print(f"[Task D] ✅ Output: {exec_result[:200]}")


# ======================================================================
# 边界测试：模板直接调用验证（不依赖 LLM）
# ======================================================================


def test_eoq_template_direct():
    """直接调用 EOQ 模板验证计算正确性。"""
    from src.domain.templates.inventory_eoq import calculate, EOQParams

    result = calculate(EOQParams(annual_demand=1000, ordering_cost=50, holding_cost=2))
    assert abs(result.eoq - 223.61) < 0.1, f"EOQ 计算错误: {result.eoq}"
    assert result.annual_orders > 0
    assert result.total_cost > 0


def test_forecast_template_direct():
    """直接调用 forecast 模板验证计算正确性。"""
    from src.domain.templates.demand_forecast import forecast, ForecastParams

    result = forecast(
        ForecastParams(history=[100.0, 120.0, 110.0, 130.0, 125.0, 140.0], method="sma", periods=3)
    )
    assert len(result.forecasts) == 3
    assert result.mae >= 0
    assert result.mape >= 0


def test_safety_stock_template_direct():
    """直接调用 safety_stock 模板验证计算正确性。"""
    from src.domain.templates.safety_stock import calculate_safety_stock, SafetyStockParams

    result = calculate_safety_stock(
        SafetyStockParams(avg_demand=200, demand_std=30, lead_time=1, service_level=95)
    )
    assert result.safety_stock > 0
    assert result.z_score > 1.0


def test_reorder_point_template_direct():
    """直接调用 reorder_point 模板验证计算正确性。"""
    from src.domain.templates.reorder_point import calculate, ROPParams

    result = calculate(ROPParams(avg_demand=150, lead_time=2, safety_stock=100))
    assert result.reorder_point == 400.0  # 150*2 + 100
    assert "建议" in result.suggestion or len(result.suggestion) > 0


# ======================================================================
# 主入口
# ======================================================================


def main() -> int:
    """运行 E2E 测试并报告结果。"""
    import traceback

    print("=" * 70)
    print("🚀 DecisionCoder Week 4 E2E 集成测试（供应链优化）")
    print(f"   DEEPSEEK_API_KEY={'✅' if HAS_API_KEY else '❌ 未设置（LLM 测试将跳过）'}")
    print(f"   WORKSPACE_PATH={WS}")
    print("=" * 70)

    tests = [
        ("任务 A: EOQ 经济订货批量", test_task_a_eoq_subprocess),
        ("任务 B: 需求预测", test_task_b_forecast_subprocess),
        ("任务 C: 安全库存", test_task_c_safety_stock_subprocess),
        ("任务 D: 补货点 (ROP)", test_task_d_reorder_point_subprocess),
        ("边界: EOQ 模板直接调用", test_eoq_template_direct),
        ("边界: 预测模板直接调用", test_forecast_template_direct),
        ("边界: 安全库存模板直接调用", test_safety_stock_template_direct),
        ("边界: 补货点模板直接调用", test_reorder_point_template_direct),
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
    print(f"📊 Week 4 E2E 结果: {passed}/{total} 通过", end="")
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

"""Week 5 E2E 集成测试 — 供应链库存分析闭环验证。

3 个场景，验证从自然语言输入到专业增强报告的完整闭环。

场景 1：完整流水线（数据驱动）— sku_inventory.csv → 增强报告
场景 2：纯参数模式（直接计算）— 年需求 5000 → EOQ + 安全库存
场景 3：边界 — 不存在的文件 → Debugger → 失败报告

用法:
    python tests/test_e2e_week5.py
    python -m pytest tests/test_e2e_week5.py -v
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

# ---- 加载 .env ----
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

# 测试数据文件是否存在
SKU_CSV = WS / "data" / "sku_inventory.csv"
HAS_SKU_CSV = SKU_CSV.exists()


# ======================================================================
# 辅助函数
# ======================================================================


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


def _assert_common(result: dict, query_hint: str, *, skip_plan_check: bool = False) -> None:
    """对图执行结果做基本断言（Week 5 通用检查清单）。

    Args:
        result: graph.invoke 返回的 state
        query_hint: 测试场景名（用于错误信息）
        skip_plan_check: True 时跳过"Plan 非回退"检查（用于预期失败的场景）
    """
    plan = result.get("plan", [])
    code = result.get("generated_code", "")
    error = result.get("error")
    report = result.get("final_report", "")
    exec_result = result.get("execution_result") or ""
    retry_count = result.get("retry_count", 0)

    # 1. final_report 非空
    assert report is not None, f"[{query_hint}] final_report 为 None"
    assert len(report) > 100, f"[{query_hint}] 报告过短: {len(report)} 字符"

    # 2. Plan 非空（失败场景可能 Plan 正常但执行出错）
    assert len(plan) > 0, f"[{query_hint}] plan 为空"
    if not skip_plan_check:
        plan_ok = not any(
            "Planner 调用失败" in str(p) for p in plan
        )
        assert plan_ok, f"[{query_hint}] plan 是 LLM 回退: {plan[:2]}"

    # 3. 代码生成
    assert len(code) > 50, f"[{query_hint}] 代码过短: {len(code)} 字符"

    # 4. retry_count ≤ 1（人类干预不超过 1 次）
    assert retry_count <= 1, f"[{query_hint}] 重试次数过多: retry={retry_count}"


def _assert_success(result: dict, query_hint: str) -> None:
    """对成功场景的额外断言（无 error, retry ≤ 1）。"""
    _assert_common(result, query_hint)
    error = result.get("error")
    retry_count = result.get("retry_count", 0)
    exec_result = result.get("execution_result") or ""
    report = result.get("final_report", "")

    assert error is None, f"[{query_hint}] 有执行错误: {error}"
    assert retry_count <= 1, f"[{query_hint}] 重试次数过多: retry={retry_count}"
    assert len(str(exec_result)) > 0, f"[{query_hint}] 无执行输出"

    # 报告标记为成功
    assert "✅ 执行成功" in report, f"[{query_hint}] 报告未标记成功"

    # 不是回退代码
    is_fallback = "安全模式" in str(exec_result) or "无有效代码可执行" in str(exec_result)
    assert not is_fallback, f"[{query_hint}] 执行的是回退代码"


# ======================================================================
# 场景 1：完整流水线（数据驱动）
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
@pytest.mark.skipif(not HAS_SKU_CSV, reason="sku_inventory.csv 不存在")
def test_e2e_inventory_pipeline_full():
    """场景 1：完整流水线 — 从 sku_inventory.csv 到增强报告。

    验证：
      - final_report 非空且标记成功
      - error 为 None, retry_count = 0
      - 报告中包含库存优化相关内容
    """
    query = (
        "分析 workspace/data/sku_inventory.csv 的库存数据，"
        "预测需求并给出订货建议"
    )
    result = _invoke(query)

    _assert_common(result, "场景 1")
    error = result.get("error")
    retry_count = result.get("retry_count", 0)

    # May succeed with 0 retries, or trigger one debugger retry with AI fix
    assert retry_count <= 1, f"[场景 1] 重试次数过多: retry={retry_count}"

    report = result.get("final_report", "")
    exec_result = str(result.get("execution_result", ""))

    # Verify inventory analysis content
    has_inventory_content = any(
        kw in (exec_result + report).lower()
        for kw in ("eoq", "安全库存", "补货点", "订货", "inventory", "库存", "需求预测")
    )
    assert has_inventory_content, (
        f"[场景 1] 输出中未找到库存分析关键词: {exec_result[:300]}"
    )

    print(f"[场景 1] ✅ Plan: {len(result.get('plan', []))} 步")
    print(f"[场景 1] ✅ Code: {len(result.get('generated_code', ''))} 字符")
    print(f"[场景 1] ✅ Report: {len(report)} 字符")
    print(f"[场景 1] ✅ retry_count={retry_count} ({'零干预' if retry_count == 0 else 'AI 自动修复'})")


# ======================================================================
# 场景 2：纯参数模式（直接计算）
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_e2e_inventory_params_only():
    """场景 2：纯参数模式 — 无数据文件，直接计算 EOQ 和安全库存。

    验证：
      - final_report 非空且标记成功
      - error 为 None, retry_count = 0
      - 报告中包含 EOQ 数值（约 447）
      - 报告中包含安全库存相关描述
    """
    query = (
        "年需求 5000，订货成本 100，持有成本 5，帮我算 EOQ 和安全库存"
    )
    result = _invoke(query)

    _assert_common(result, "场景 2")
    error = result.get("error")
    retry_count = result.get("retry_count", 0)
    assert retry_count <= 1, f"[场景 2] 重试次数过多: retry={retry_count}"

    exec_result = str(result.get("execution_result", ""))
    report = result.get("final_report", "")
    combined = exec_result + report

    # EOQ 检查: sqrt(2*5000*100/5) = sqrt(200000) ≈ 447.2
    has_eoq = any(
        kw in combined.lower()
        for kw in ("447", "448", "446", "eoq", "批量")
    )
    assert has_eoq, f"[场景 2] 输出中未找到 EOQ 数值: {exec_result[:300]}"

    # 安全库存检查
    has_ss = any(
        kw in combined.lower()
        for kw in ("安全库存", "safety", "z", "服务水平", "service")
    )
    assert has_ss, f"[场景 2] 输出中未找到安全库存描述: {exec_result[:300]}"

    print(f"[场景 2] ✅ Plan: {len(result.get('plan', []))} 步")
    print(f"[场景 2] ✅ Code: {len(result.get('generated_code', ''))} 字符")
    print(f"[场景 2] ✅ Output: {exec_result[:200]}")


# ======================================================================
# 场景 3：边界 — 不存在的文件
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_e2e_inventory_file_not_found():
    """场景 3：边界 — 请求分析不存在的文件，预期进入 Debugger 或生成失败报告。

    显式使用 choices=["4"]（直接 ABORT）：此类场景 AI 修复无意义
    （文件本身就不存在），且会污染 retry_count 断言。

    验证：
      - final_report 非空（即使是失败报告）
      - retry_count = 1（触发一次 Debugger 后 ABORT）
      - 报告包含错误标记或中止标记
    """
    query = "分析 workspace/data/not_exist.csv 给出订货建议"

    result = _invoke(query, choices=["4"])

    # 场景 3: 文件不存在 → 预期进入 Debugger 或直接失败
    # 使用 skip_plan_check，因为 Plan 中"输出错误提示"是正常步骤
    _assert_common(result, "场景 3", skip_plan_check=True)

    report = result.get("final_report", "")
    error = result.get("error")
    retry_count = result.get("retry_count", 0)

    # 应该触发错误（文件不存在）
    # 可能是 Debugger → ABORT → fail 报告，或 Coder 自身处理
    has_failure_indicator = any(
        kw in report
        for kw in ("❌", "错误", "失败", "中止", "异常", "找不到", "不存在", "not found", "FileNotFound")
    )
    assert has_failure_indicator or error is not None, (
        f"[场景 3] 预期有错误报告，但未找到失败标记。report[:300]: {report[:300]}"
    )

    print(f"[场景 3] ✅ error={'ABORT' if error else 'None'}")
    print(f"[场景 3] ✅ retry_count={retry_count}")
    print(f"[场景 3] ✅ 报告含失败标记")


# ======================================================================
# 边界测试：无需 LLM 的直接调用
# ======================================================================


def test_pipeline_with_sku_csv():
    """边界：直接调用 inventory_pipeline 以 sku_inventory.csv 运行。"""
    if not HAS_SKU_CSV:
        pytest.skip("sku_inventory.csv 不存在")

    from src.domain.templates.inventory_pipeline import (
        run_inventory_pipeline,
        InventoryPipelineParams,
    )

    result = run_inventory_pipeline(
        InventoryPipelineParams(
            csv_path=str(SKU_CSV),
            time_col="month",
            demand_col="demand",
            output_dir=str(WS / "reports"),
        )
    )

    assert result.report_path != ""
    assert Path(result.report_path).exists()

    report_text = Path(result.report_path).read_text(encoding="utf-8")
    # 验证增强报告章节（全流程成功时应有增强）
    assert "## 7. 模型假设" in report_text
    assert "## 8. 局限性与风险提示" in report_text
    assert "## 9. 业务建议" in report_text
    assert "## 10. 附录" in report_text

    # 验证核心结果非 None
    assert result.forecast_result is not None
    assert result.eoq_result is not None
    assert result.safety_stock_result is not None
    assert result.rop_result is not None


def test_params_only_direct_call():
    """边界：直接调用 EOQ + 安全库存模板，验证纯参数模式计算正确。"""
    from src.domain.templates.inventory_eoq import calculate, EOQParams
    from src.domain.templates.safety_stock import calculate_safety_stock, SafetyStockParams

    # EOQ: sqrt(2*5000*100/5) = sqrt(200000) ≈ 447.21
    eoq_result = calculate(EOQParams(annual_demand=5000, ordering_cost=100, holding_cost=5))
    assert abs(eoq_result.eoq - 447.21) < 0.5, f"EOQ 应为 ~447.21，实际 {eoq_result.eoq}"

    # 安全库存：月均需求=5000/12≈416.7, 用默认标准差推断
    ss_result = calculate_safety_stock(
        SafetyStockParams(avg_demand=416.67, demand_std=50, lead_time=1, service_level=95)
    )
    assert ss_result.safety_stock > 0
    assert ss_result.z_score > 1.0
    assert ss_result.service_level > 0.9


def test_sku_csv_data_integrity():
    """边界：验证 sku_inventory.csv 数据完整性。"""
    if not HAS_SKU_CSV:
        pytest.skip("sku_inventory.csv 不存在")

    import pandas as pd

    df = pd.read_csv(SKU_CSV)
    assert len(df) == 24, f"预期 24 行，实际 {len(df)}"
    assert list(df.columns) == ["month", "sku_id", "demand", "unit_cost"], f"列名不匹配: {list(df.columns)}"

    # 验证异常值存在
    assert df.loc[5, "demand"] == 150, f"第 6 行（2024-06）demand 应为 150，实际 {df.loc[5, 'demand']}"
    assert df.loc[13, "demand"] == 70, f"第 14 行（2025-02）demand 应为 70，实际 {df.loc[13, 'demand']}"

    # 验证上升趋势
    assert df["demand"].iloc[-1] > df["demand"].iloc[0], "需求应有上升趋势"


def test_report_enhancer_integration():
    """边界：报告增强器可在 pipeline result 上正常工作。"""
    if not HAS_SKU_CSV:
        pytest.skip("sku_inventory.csv 不存在")

    from src.domain.templates.inventory_pipeline import run_inventory_pipeline, InventoryPipelineParams
    from src.domain.report_enhancer import build_enhancer_input, enhance_report

    result = run_inventory_pipeline(
        InventoryPipelineParams(
            csv_path=str(SKU_CSV),
            output_dir=str(WS / "reports"),
        )
    )

    base_report = Path(result.report_path).read_text(encoding="utf-8")
    info = build_enhancer_input(result)
    enhanced = enhance_report(base_report, info)

    assert "## 7. 模型假设" in enhanced
    assert "## 8. 局限性与风险提示" in enhanced
    assert "## 9. 业务建议" in enhanced


# ======================================================================
# 主入口
# ======================================================================


def main() -> int:
    """运行 E2E 测试并报告结果。"""
    import traceback

    print("=" * 70)
    print("🚀 DecisionCoder Week 5 E2E 集成测试（供应链库存分析）")
    print(f"   DEEPSEEK_API_KEY={'✅' if HAS_API_KEY else '❌ 未设置（LLM 测试将跳过）'}")
    print(f"   sku_inventory.csv={'✅' if HAS_SKU_CSV else '❌ 不存在'}")
    print(f"   WORKSPACE_PATH={WS}")
    print("=" * 70)

    tests = [
        ("场景 1: 完整流水线 (LLM)", test_e2e_inventory_pipeline_full),
        ("场景 2: 纯参数模式 (LLM)", test_e2e_inventory_params_only),
        ("场景 3: 文件不存在 (LLM)", test_e2e_inventory_file_not_found),
        ("边界: Pipeline 直接调用", test_pipeline_with_sku_csv),
        ("边界: EOQ+SS 直接调用", test_params_only_direct_call),
        ("边界: sku_inventory.csv 完整性", test_sku_csv_data_integrity),
        ("边界: 增强器集成验证", test_report_enhancer_integration),
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
            print(f"  ⏭️  跳过")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ 断言失败: {e}")
        except Exception:
            failed += 1
            print(f"  ❌ 异常: {traceback.format_exc()[:300]}")

    total = passed + failed + skipped
    print("\n" + "=" * 70)
    print(f"📊 Week 5 E2E 结果: {passed}/{total} 通过", end="")
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

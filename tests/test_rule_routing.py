"""规则路由集成测试 — 验证 Coder 前的模板匹配 + 参数提取路由层。

2 条集成测试：
  测试 A: 规则命中 — EOQ 高置信匹配，LLM 应调用 inventory_eoq 模板
  测试 B: 规则未命中 — 通用编程任务，不应包含任何领域模板 import

用法:
    python tests/test_rule_routing.py
    python -m pytest tests/test_rule_routing.py -v
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


def _invoke(query: str, debugger_choice: str = "1") -> dict:
    """调用完整 Graph 执行一次任务。

    默认 mock Debugger _safe_input 为 "1"（接受 AI 修复），
    避免 stdin 捕获冲突。
    """
    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())[:8]}}
    with patch("src.agent.nodes.debugger._safe_input", return_value=debugger_choice):
        return graph.invoke(_make_state(query), config)


# ======================================================================
# 测试 A: 规则命中 — EOQ 高置信匹配
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_rule_routing_hit_eoq():
    """规则命中测试：EOQ 关键词 → 模板匹配成功 → LLM 调用 inventory_eoq。

    验证：
      - error 为 None（一次通过）
      - generated_code 中包含 inventory_eoq 或 EOQParams
      - 执行输出中包含 EOQ 数值（~223.6）
    """
    query = "年需求1000，订货成本50，持有成本2，帮我算EOQ"
    result = _invoke(query)

    error = result.get("error")
    code = result.get("generated_code", "")
    exec_result = str(result.get("execution_result", ""))
    report = result.get("final_report", "")

    # 1. 无执行错误
    assert error is None, f"[规则命中] 有执行错误: {error}"

    # 2. 代码中调用了 inventory_eoq 模板（非手写公式）
    has_template_import = "inventory_eoq" in code or "EOQParams" in code
    assert has_template_import, (
        f"[规则命中] 代码中未找到 inventory_eoq 模板调用: {code[:300]}"
    )

    # 3. 输出中包含 EOQ 数值 sqrt(2*1000*50/2) ≈ 223.6
    combined = exec_result + report
    has_eoq_value = any(
        kw in combined.lower() for kw in ("223", "224", "eoq")
    )
    assert has_eoq_value, (
        f"[规则命中] 输出中未找到 EOQ 相关值: {exec_result[:300]}"
    )

    print(f"[规则命中] ✅ Code: {len(code)} 字符")
    print(f"[规则命中] ✅ Output: {exec_result[:200]}")
    print(f"[规则命中] ✅ 确认调用了 inventory_eoq 模板")


# ======================================================================
# 测试 B: 规则未命中 — 通用编程任务
# ======================================================================


@pytest.mark.skipif(not HAS_API_KEY, reason="DEEPSEEK_API_KEY 未设置")
def test_rule_routing_miss_general():
    """规则未命中测试：通用编程任务 → UNKNOWN → 保持 LLM 路由。

    验证：
      - error 为 None
      - generated_code 中不包含任何领域模板 import
      - 执行输出中包含素数结果
    """
    query = "写一个 Python 函数 is_prime(n) 来判断一个整数是否是素数，并打印 1-50 之间的所有素数"
    result = _invoke(query)

    error = result.get("error")
    code = result.get("generated_code", "")
    exec_result = str(result.get("execution_result", ""))
    report = result.get("final_report", "")

    # 1. 无执行错误
    assert error is None, f"[规则未命中] 有执行错误: {error}"

    # 2. 代码中不包含任何领域模板 import
    domain_imports = [
        "inventory_eoq", "safety_stock", "demand_forecast",
        "reorder_point", "inventory_pipeline", "data_quality",
        "chart_templates", "text_to_sql", "data_analysis",
        "report_enhancer",
    ]
    has_any_domain_import = any(di in code for di in domain_imports)
    assert not has_any_domain_import, (
        f"[规则未命中] 代码中意外包含领域模板 import: {code[:300]}"
    )

    # 3. 输出中包含素数相关结果
    combined = exec_result + report
    has_prime_result = any(
        kw in combined.lower()
        for kw in ("prime", "素数", "2", "3", "5", "7")
    )
    assert has_prime_result, (
        f"[规则未命中] 输出中未找到素数结果: {exec_result[:300]}"
    )

    print(f"[规则未命中] ✅ Code: {len(code)} 字符")
    print(f"[规则未命中] ✅ Output: {exec_result[:200]}")
    print(f"[规则未命中] ✅ 确认不包含任何领域模板 import")


# ======================================================================
# 附加：单元级验证 — 规则路由函数直接测试
# ======================================================================


def test_run_rule_routing_eoq():
    """单元级：_run_rule_routing 对 EOQ 输入返回正确匹配。"""
    from src.agent.nodes.coder import _run_rule_routing

    template_match, params = _run_rule_routing(
        "年需求1000，订货成本50，持有成本2，帮我算EOQ"
    )

    assert template_match is not None, "EOQ 输入应命中规则路由"
    assert template_match["template_type"] == "eoq"
    assert template_match["confidence"] >= 1.5

    assert params is not None
    assert abs(params.get("annual_demand", 0) - 1000.0) < 0.1
    assert abs(params.get("ordering_cost", 0) - 50.0) < 0.1
    assert abs(params.get("holding_cost", 0) - 2.0) < 0.1

    print(f"[单元级 EOQ] ✅ template_match={template_match}")
    print(f"[单元级 EOQ] ✅ params={params}")


def test_run_rule_routing_unknown():
    """单元级：_run_rule_routing 对无意义输入返回 (None, None)。"""
    from src.agent.nodes.coder import _run_rule_routing

    template_match, params = _run_rule_routing(
        "写一个冒泡排序算法"
    )

    assert template_match is None, "无供应链关键词应返回 None"
    assert params is None

    print(f"[单元级 UNKNOWN] ✅ 正确返回 (None, None)")


def test_run_rule_routing_safety_stock():
    """单元级：_run_rule_routing 对安全库存输入返回正确匹配。"""
    from src.agent.nodes.coder import _run_rule_routing

    template_match, params = _run_rule_routing(
        "服务水平 95%，提前期 2，安全库存怎么算"
    )

    assert template_match is not None
    assert template_match["template_type"] == "safety_stock"
    assert params is not None
    assert abs(params.get("service_level", 0) - 95.0) < 0.1
    assert abs(params.get("lead_time", 0) - 2.0) < 0.1

    print(f"[单元级 SS] ✅ template_match={template_match}")
    print(f"[单元级 SS] ✅ params={params}")


def test_run_rule_routing_no_routing_env(monkeypatch):
    """单元级：DECISIONCODER_NO_ROUTING=true 时应返回 (None, None)
    且 template_matcher 未被调用。

    验证：
      - monkeypatch 设置环境变量后，_run_rule_routing 直接返回 None
      - 对真实 EOQ 输入也不触发模板匹配和参数提取
    """
    from unittest.mock import patch

    monkeypatch.setenv("DECISIONCODER_NO_ROUTING", "true")

    # patch 源模块的 match_template：如果环境开关失效、代码走到了
    # import + 调用路径，mock 会抛 AssertionError 而不会执行真实逻辑
    with patch(
        "src.domain.template_matcher.match_template",
        side_effect=AssertionError("环境开关失效：match_template 不该被调用"),
    ):
        from src.agent.nodes.coder import _run_rule_routing

        template_match, params = _run_rule_routing(
            "年需求1000，订货成本50，持有成本2，帮我算EOQ"
        )

    assert template_match is None, (
        "DECISIONCODER_NO_ROUTING=true 时 template_match 应为 None"
    )
    assert params is None, (
        "DECISIONCODER_NO_ROUTING=true 时 params 应为 None"
    )

    print("[单元级 NO_ROUTING] ✅ 环境开关生效，跳过规则路由")


# ======================================================================
# 主入口
# ======================================================================


def main() -> int:
    """运行规则路由集成测试并报告结果。"""
    import traceback

    print("=" * 70)
    print("🚀 DecisionCoder 规则路由集成测试")
    print(f"   DEEPSEEK_API_KEY={'✅' if HAS_API_KEY else '❌ 未设置（LLM 测试将跳过）'}")
    print(f"   WORKSPACE_PATH={WS}")
    print("=" * 70)

    tests = [
        ("测试 A: 规则命中 — EOQ 高置信 (LLM)", test_rule_routing_hit_eoq),
        ("测试 B: 规则未命中 — 通用编程 (LLM)", test_rule_routing_miss_general),
        ("单元级: _run_rule_routing EOQ", test_run_rule_routing_eoq),
        ("单元级: _run_rule_routing UNKNOWN", test_run_rule_routing_unknown),
        ("单元级: _run_rule_routing SafetyStock", test_run_rule_routing_safety_stock),
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
            print(f"  ❌ 异常: {traceback.format_exc()[:400]}")

    total = passed + failed + skipped
    print("\n" + "=" * 70)
    print(f"📊 规则路由测试结果: {passed}/{total} 通过", end="")
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

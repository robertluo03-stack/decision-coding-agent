"""E2E 回归测试脚本 — Docker 模式 + subprocess 模式

运行 3 个任务，确认 Docker 和 subprocess 两种模式均成功执行。
用法:
    .venv/Scripts/python workspace/tests/test_e2e_docker.py
"""

import os
import sys
import uuid
from pathlib import Path

# 设置项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
os.chdir(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

# ---- 加载 .env（模拟 main.py 的 _setup_environment 行为） ----
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[setup] .env 已加载")
except ImportError:
    print("[setup] python-dotenv 未安装，跳过 .env 加载")

# 确保 workspace 目录存在
ws = PROJECT_ROOT / "workspace"
(ws / "data").mkdir(parents=True, exist_ok=True)
(ws / "reports").mkdir(parents=True, exist_ok=True)
(ws / "src").mkdir(parents=True, exist_ok=True)
(ws / "output").mkdir(parents=True, exist_ok=True)
os.environ["WORKSPACE_PATH"] = str(ws)

from src.agent.graph import build_graph
from src.agent.state import AgentState

_passed = 0
_failed = 0
_all_results = []


def _check(condition: bool, name: str, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✅ {name}")
    else:
        _failed += 1
        print(f"  ❌ {name}  —  {detail}")


def run_full_graph_task(task_name: str, user_query: str, use_mcp: bool = False) -> dict:
    """通过完整 LangGraph 管道运行单个任务。"""
    print()
    print("=" * 70)
    print(f"📝 {task_name}")
    print(f"   需求: {user_query}")
    print(f"   路径: {'MCP' if use_mcp else 'subprocess'}")
    print("=" * 70)

    graph = build_graph()

    initial_state: AgentState = {
        "user_query": user_query,
        "workspace_path": str(ws),
        "plan": [],
        "generated_code": "",
        "file_path": None,
        "execution_result": None,
        "error": None,
        "retry_count": 0,
        "human_feedback": None,
        "final_report": None,
    }

    config = {"configurable": {"thread_id": str(uuid.uuid4())[:8]}}
    result = graph.invoke(initial_state, config)
    return result


def evaluate_task(task_name: str, result: dict, mode: str) -> dict:
    """评估单个任务的执行结果。"""
    print()
    print(f"--- 评估: {task_name} [{mode}] ---")

    plan = result.get("plan", [])
    code = result.get("generated_code", "")
    exec_result = result.get("execution_result", "")
    error = result.get("error")
    report = result.get("final_report", "")
    retry_count = result.get("retry_count", 0)

    # 检查 Plan 是否来自 LLM 而非回退
    plan_ok = len(plan) > 0 and not any(
        "错误" in str(p) or "Planner 调用失败" in str(p) for p in plan
    )

    _check(len(plan) > 0, f"{task_name}: Plan 非空", f"plan={plan[:2]}")
    _check(plan_ok, f"{task_name}: Plan 来自 LLM（非回退）", f"plan[0]={plan[0] if plan else 'N/A'}")

    _check(len(code) > 50, f"{task_name}: Code 非空", f"code_len={len(code)}")
    _check(error is None, f"{task_name}: 无执行错误", f"error={error}")

    _check(
        exec_result is not None and len(str(exec_result)) > 0,
        f"{task_name}: 有执行结果",
        f"result[:100]={str(exec_result)[:100]}",
    )

    _check(
        report is not None and len(report) > 100,
        f"{task_name}: 报告非空",
        f"report_len={len(report) if report else 0}",
    )

    _check(retry_count == 0, f"{task_name}: retry_count=0", f"retry_count={retry_count}")

    # 检查报告是否包含成功标记
    if report:
        _check(
            "✅ 执行成功" in report,
            f"{task_name}: 报告标记为成功",
            f"report[:200]={report[:200]}",
        )

    # 关键：执行结果不应来自回退代码
    is_fallback = "安全模式" in str(exec_result) or "无有效代码可执行" in str(exec_result)
    _check(
        not is_fallback,
        f"{task_name}: 执行的是业务代码（非回退）",
        f"result[:100]={str(exec_result)[:100]}",
    )

    info = {
        "task": task_name,
        "mode": mode,
        "plan_steps": len(plan),
        "plan_from_llm": plan_ok,
        "code_len": len(code),
        "exec_result": str(exec_result)[:200] if exec_result else "None",
        "error": str(error)[:100] if error else "None",
        "retry_count": retry_count,
        "report_len": len(report) if report else 0,
        "is_fallback": is_fallback,
        "success": error is None and not is_fallback and plan_ok,
    }
    _all_results.append(info)

    print(f"\n  执行结果预览: {str(exec_result)[:250]}")
    if error:
        print(f"  错误: {str(error)[:250]}")

    return info


def main():
    global _passed, _failed

    print("=" * 70)
    print("🚀 DecisionCoder E2E 回归测试")
    print(f"   DEEPSEEK_API_KEY={'✅' if os.environ.get('DEEPSEEK_API_KEY') else '❌'}")
    print(f"   WORKSPACE_PATH={os.environ.get('WORKSPACE_PATH')}")
    print("=" * 70)

    # ---- Phase 1: subprocess 模式 (默认) ----
    os.environ.pop("USE_MCP", None)
    os.environ.pop("USE_DOCKER", None)
    print("\n" + "█" * 70)
    print("█  Phase 1: subprocess 模式（默认执行路径）")
    print("█" * 70)

    tasks = [
        ("任务1：1-100 求和", "计算 1 到 100 的和并打印结果"),
        ("任务2：pandas DataFrame", "用 pandas 创建一个包含3列的 DataFrame（列名为 A, B, C），包含5行随机整数数据（范围1-100），计算每列的平均值并打印"),
        ("任务3：scipy 优化", "用 scipy.optimize.minimize 求函数 f(x) = (x-3)**2 + 5 的最小值，打印最优解"),
    ]

    for task_name, query in tasks:
        try:
            result = run_full_graph_task(task_name, query, use_mcp=False)
            evaluate_task(task_name, result, "subprocess")
        except Exception as exc:
            import traceback
            print(f"  ❌ {task_name}: 执行异常 — {type(exc).__name__}: {exc}")
            traceback.print_exc()
            _failed += 1
            _all_results.append({
                "task": task_name, "mode": "subprocess",
                "plan_steps": 0, "plan_from_llm": False, "code_len": 0,
                "exec_result": "EXCEPTION", "error": str(exc)[:200],
                "retry_count": 0, "report_len": 0,
                "is_fallback": True, "success": False,
            })

    # ---- Phase 1b: USE_MCP=true 模式 (MCP Client → python_tools → subprocess) ----
    os.environ["USE_MCP"] = "true"
    os.environ.pop("USE_DOCKER", None)
    print("\n" + "█" * 70)
    print("█  Phase 1b: MCP 模式（USE_MCP=true, USE_DOCKER=false）")
    print("█" * 70)

    for task_name, query in tasks:
        try:
            result = run_full_graph_task(task_name, query, use_mcp=True)
            evaluate_task(task_name, result, "MCP/subprocess")
        except Exception as exc:
            import traceback
            print(f"  ❌ {task_name}: 执行异常 — {type(exc).__name__}: {exc}")
            traceback.print_exc()
            _failed += 1
            _all_results.append({
                "task": task_name, "mode": "MCP/subprocess",
                "plan_steps": 0, "plan_from_llm": False, "code_len": 0,
                "exec_result": "EXCEPTION", "error": str(exc)[:200],
                "retry_count": 0, "report_len": 0,
                "is_fallback": True, "success": False,
            })

    # ---- Phase 2: Docker 模式（直接测试 DockerRunner + execute_python） ----
    os.environ["USE_DOCKER"] = "true"
    print("\n" + "█" * 70)
    print("█  Phase 2: Docker 沙箱模式（直接 python_tools.execute_python）")
    print("█" * 70)

    docker_tests = [
        ("Docker: 1-100 求和", "total = sum(range(1, 101))\nprint(f'1到100的和: {total}')"),
        ("Docker: pandas DataFrame", (
            "import pandas as pd\n"
            "import numpy as np\n"
            "np.random.seed(42)\n"
            "df = pd.DataFrame({\n"
            "    'A': np.random.randint(1, 101, 5),\n"
            "    'B': np.random.randint(1, 101, 5),\n"
            "    'C': np.random.randint(1, 101, 5)\n"
            "})\n"
            "print('DataFrame:')\n"
            "print(df)\n"
            "print(f'\\n列A平均值: {df[\"A\"].mean():.2f}')\n"
            "print(f'列B平均值: {df[\"B\"].mean():.2f}')\n"
            "print(f'列C平均值: {df[\"C\"].mean():.2f}')"
        )),
        ("Docker: scipy 优化", (
            "from scipy.optimize import minimize\n"
            "f = lambda x: (x[0] - 3)**2 + 5\n"
            "result = minimize(f, x0=[0], method='BFGS')\n"
            "print(f'最优解 x = {result.x[0]:.6f}')\n"
            "print(f'最小值 f(x) = {result.fun:.6f}')\n"
            "print(f'优化成功: {result.success}')"
        )),
    ]

    from src.mcp.tools.python_tools import execute_python

    for task_name, code in docker_tests:
        print()
        print(f"--- {task_name} ---")
        try:
            result = execute_python(code, workspace_path=str(ws))
            success = result.get("success", False)
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")

            _check(success, f"{task_name}: 执行成功", f"stderr={stderr[:100]}")
            _check(len(stdout) > 10, f"{task_name}: 有输出", f"stdout[:100]={stdout[:100]}")
            _check(not stderr or stderr == "", f"{task_name}: 无 stderr", f"stderr={stderr[:100]}")

            print(f"  stdout: {stdout[:200]}")

            _all_results.append({
                "task": task_name, "mode": "Docker",
                "plan_steps": 0, "plan_from_llm": True, "code_len": len(code),
                "exec_result": stdout[:200], "error": stderr[:100] if stderr else "None",
                "retry_count": 0, "report_len": 0,
                "is_fallback": False, "success": success and not stderr,
            })
        except Exception as exc:
            import traceback
            print(f"  ❌ {task_name}: 执行异常 — {type(exc).__name__}: {exc}")
            traceback.print_exc()
            _failed += 1
            _all_results.append({
                "task": task_name, "mode": "Docker",
                "plan_steps": 0, "plan_from_llm": True, "code_len": len(code),
                "exec_result": "EXCEPTION", "error": str(exc)[:200],
                "retry_count": 0, "report_len": 0,
                "is_fallback": True, "success": False,
            })

    # ---- 汇总 ----
    print()
    print("=" * 70)
    print("📊 测试汇总")
    print("=" * 70)
    total = _passed + _failed
    print(f"  通过: {_passed}/{total}")
    print(f"  失败: {_failed}/{total}")
    print()

    for r in _all_results:
        status = "✅" if r["success"] else "❌"
        print(f"  {status} {r['task']} [{r['mode']}]")
        print(f"      代码: {r['code_len']} 字符 | 重试: {r['retry_count']} | 回退: {r['is_fallback']}")
        print(f"      错误: {r['error']}")
        print(f"      结果: {r['exec_result'][:120]}")
        print()

    # 检查报告文件
    print("--- 生成的报告文件 ---")
    reports_dir = ws / "reports"
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
            print(f"  📄 {f.name}  ({f.stat().st_mtime})")
    else:
        print("  (无)")

    # 检查临时文件
    print()
    print("--- 临时执行文件 ---")
    src_dir = ws / "src"
    if src_dir.exists():
        for f in sorted(src_dir.glob("_dc_exec_*.py"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
            print(f"  📄 {f.name}")

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

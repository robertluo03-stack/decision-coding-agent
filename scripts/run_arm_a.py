#!/usr/bin/env python3
"""Arm A: Claude Code 裸用（无 DecisionCoder 框架），与 B/C 臂公平对照。

B/C 臂（routing_on / routing_off）：在 DecisionCoder repo 内运行 LangGraph 闭环，
可访问 src/ 域模板库、规则路由、Debuggcer 重试等全量能力。
A 臂（claude_code）：在仓库外隔离空目录运行裸 `claude -p`，仅能访问 3 个数据 CSV
文件，无任何框架增强——测量"裸 LLM 工具使用"基线。

公平性控制：
- 任务集、query、判定关键词：与 B/C 臂完全一致（17 任务 × 3 重复 = 51 次）
- 隔离工作目录：仓库外空目录，仅放 sales.csv / inventory.csv / sku_inventory.csv
- 判定扫描域差异：A 臂扫 claude 返回的 result 最终文本，B/C 臂扫 stdout + 报告
  （方法注释见 judge_result 函数）

用法：
  python scripts/run_arm_a.py --smoke    # 冒烟：仅 CG-01 × 1，验证字段与端点
  python scripts/run_arm_a.py --full     # 全量：17 任务 × 3 = 51 次（需先提交本脚本）
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ISOLATED_WORKSPACE = Path("C:/Users/18500/Desktop/Study/agent/arm_a_workspace")
DATA_FILES = ["sales.csv", "inventory.csv", "sku_inventory.csv"]
DATA_SOURCE_DIR = PROJECT_ROOT / "workspace" / "data"
ARTIFACTS_ROOT = PROJECT_ROOT / "results" / "artifacts"


# ═══════════════════════════════════════════════════════════════════════════
# Keyword matching — 复用 src/benchmark/validators.py 的 _keyword_found 算法
# ═══════════════════════════════════════════════════════════════════════════
# A 臂扫描域：claude 返回 JSON 中 "result" 字段的最终答复文本。
# B/C 臂扫描域：execution_result（stdout 全文）+ final_report（Markdown 报告全文）。
# 差异在于 A 臂不扫描中间执行输出（Python stdout 日志、图表路径等），
# 只扫描 claude 对话的最终回复。关键词匹配算法本身保持一致。


def _is_numeric_keyword(keyword: str) -> bool:
    """Check if keyword is a pure numeric value (int or float)."""
    try:
        float(keyword)
        return True
    except ValueError:
        return False


def _keyword_found(output_text: str, keyword: str) -> bool:
    """Check if keyword appears in output.

    Case-insensitive substring match with float-tolerant prefix matching:
    "223" matches "223.61" and vice versa (from src/benchmark/validators.py).

    Args:
        output_text: Text to scan (A arm: claude result; B/C: stdout + report).
        keyword: Expected keyword.

    Returns:
        True if keyword is found.
    """
    text_lower = output_text.lower()
    kw_lower = keyword.lower()

    # Direct substring match
    if kw_lower in text_lower:
        return True

    # Float-tolerant: keyword is numeric, check prefix of any number in output
    if _is_numeric_keyword(kw_lower):
        for num in re.findall(r'\d+\.?\d*', text_lower):
            if num.startswith(kw_lower) or kw_lower.startswith(num):
                return True

    return False


# ═══════════════════════════════════════════════════════════════════════════
# Task definitions — query 逐字取自 src/benchmark/tasks.py
# ═══════════════════════════════════════════════════════════════════════════

def get_all_tasks() -> list[dict]:
    """Return all 17 tasks: BA-01~05, CG-01~05, ADV-01~07.

    Queries, keywords, and data_files are verbatim from
    src/benchmark/tasks.py (get_default_tasks + get_adversarial_tasks).
    Timeouts: 60s for BA/CG, 30s for ADV.
    """
    tasks: list[dict] = []

    # ── BA-01~05: 数据分析 ──
    tasks.extend([
        {
            "id": "BA-01", "category": "data_analysis", "timeout": 60,
            "query": "读取 sales.csv，统计 sales_volume 列的均值、中位数和标准差",
            "expected_keywords": ["sales", "均值", "标准差", "销量"],
            "template_keywords": [],
            "data_files": ["sales.csv"],
            "needs_manual_review": False,
        },
        {
            "id": "BA-02", "category": "data_analysis", "timeout": 60,
            "query": "检查 sales.csv 的数据质量，报告缺失值、异常值和综合评分",
            "expected_keywords": ["缺失值", "异常值", "评分", "数据质量"],
            "template_keywords": [],
            "data_files": ["sales.csv"],
            "needs_manual_review": False,
        },
        {
            "id": "BA-03", "category": "data_analysis", "timeout": 60,
            "query": "对 sales.csv 各区域销量画出柱状图，保存为 HTML 文件",
            "expected_keywords": ["bar", "html", "sales"],
            "template_keywords": ["bar_chart"],
            "data_files": ["sales.csv"],
            "needs_manual_review": False,
        },
        {
            "id": "BA-04", "category": "data_analysis", "timeout": 60,
            "query": "使用 run_text_to_sql 查询 sales.csv，统计每个区域（region）的平均销量",
            "expected_keywords": ["SELECT", "AVG", "region", "区域"],
            "template_keywords": [],
            "data_files": ["sales.csv"],
            "needs_manual_review": False,
        },
        {
            "id": "BA-05", "category": "data_analysis", "timeout": 60,
            "query": "一键分析 inventory.csv 并生成完整报告",
            "expected_keywords": ["inventory", "sku", "warehouse"],
            "template_keywords": [],
            "data_files": ["inventory.csv"],
            "needs_manual_review": False,
        },
    ])

    # ── CG-01~05: 代码生成 ──
    tasks.extend([
        {
            "id": "CG-01", "category": "code_generation", "timeout": 60,
            "query": "计算 EOQ：年需求 1000，订货成本 50，持有成本 2，打印结果",
            "expected_keywords": ["EOQ", "223"],
            "template_keywords": ["inventory_eoq"],
            "data_files": None,
            "needs_manual_review": False,
        },
        {
            "id": "CG-02", "category": "code_generation", "timeout": 60,
            "query": "使用 demand_forecast 模板预测未来 3 期需求：history=[100, 120, 110, 130, 125, 140]",
            "expected_keywords": ["预测", "MAPE"],
            "template_keywords": ["forecasts"],
            "data_files": None,
            "needs_manual_review": False,
        },
        {
            "id": "CG-03", "category": "code_generation", "timeout": 60,
            "query": "使用 safety_stock 模板计算安全库存：avg_demand=100, demand_std=20, lead_time=2, service_level=95%",
            "expected_keywords": ["安全库存", "Z", "1.64"],
            "template_keywords": [],
            "data_files": None,
            "needs_manual_review": False,
        },
        {
            "id": "CG-04", "category": "code_generation", "timeout": 60,
            "query": "使用 reorder_point 模板计算补货点：avg_demand=100, lead_time=2, safety_stock=50",
            "expected_keywords": ["补货点", "ROP", "250"],
            "template_keywords": ["reorder_point"],
            "data_files": None,
            "needs_manual_review": False,
        },
        {
            "id": "CG-05", "category": "code_generation", "timeout": 60,
            "query": "使用 inventory_pipeline 模板分析 sku_inventory.csv，订购成本 100，持有成本率 20%，单位成本 50，服务水平 95%，提前期 1",
            "expected_keywords": ["EOQ", "安全库存"],
            "template_keywords": ["pipeline"],
            "data_files": ["sku_inventory.csv"],
            "needs_manual_review": False,
        },
    ])

    # ── ADV-01~07: 对抗任务 ──
    adv_tasks = [
        ("ADV-01", "年需求1000，订货成本50，持有成本2，帮我算EOQ",
         ["EOQ", "223"], ["inventory_eoq"], False),
        ("ADV-02", "每年要卖1000件，每次下单花50，存一年一件2块，最优订货量多少",
         ["EOQ", "223"], ["inventory_eoq"], False),
        ("ADV-03", "D=1000, S=50, H=2, 算一下经济订货批量",
         ["EOQ", "223"], ["inventory_eoq"], False),
        ("ADV-04", "帮我做个库存优化：年需求量一千，订货成本五十，单位持有成本二",
         ["EOQ", "223"], ["inventory_eoq"], False),
        ("ADV-05", "EOQ计算：annual_demand=1000, ordering_cost=50, holding_cost=2",
         ["EOQ", "223"], ["inventory_eoq"], False),
        ("ADV-06", "写一个函数判断字符串是否为回文并测试",
         ["回文", "palindrome"], [], True),
        ("ADV-07", "产品原价100元，打8折后参加满300减50，买3件最终多少钱，写代码计算",
         ["190"], [], True),
    ]
    for tid, query, exp_kw, tpl_kw, manual in adv_tasks:
        tasks.append({
            "id": tid, "category": "adversarial", "timeout": 30,
            "query": query,
            "expected_keywords": exp_kw,
            "template_keywords": tpl_kw,
            "data_files": None,
            "needs_manual_review": manual,
        })

    return tasks


# ═══════════════════════════════════════════════════════════════════════════
# Environment checks
# ═══════════════════════════════════════════════════════════════════════════

def _find_claude() -> str:
    """Resolve the claude CLI executable path.

    On Windows, npm installs claude.cmd; the shim 'claude' is a bash script that
    isn't found by CreateProcess without shell=True. We try .cmd first, then
    fall back to 'claude' for non-Windows or WSL contexts.
    """
    candidates = ["claude.cmd", "claude"]
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    return "claude"  # let the next call fail with a clear message


def check_claude_cli() -> str:
    """Check claude CLI is in PATH, return version string. Exit if not found.

    Requirement (spec §4c): 脚本开头先执行 claude --version 并把输出版本号写入
    manifest；若 CLI 不在 PATH 中，停下来报告，不要静默失败。
    """
    cli_path = _find_claude()
    try:
        result = subprocess.run(
            [cli_path, "--version"], capture_output=True, text=True, timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()
        if result.returncode != 0 or not version:
            print("ERROR: claude --version returned non-zero or empty output.")
            print(f"  stdout: {result.stdout!r}")
            print(f"  stderr: {result.stderr!r}")
            sys.exit(1)
        print(f"[OK] claude --version: {version}")
        print(f"     path: {cli_path}")
        return version
    except FileNotFoundError:
        print("ERROR: claude CLI not found in PATH.")
        print("  Tried: claude.cmd, claude")
        print("  npm global dir might not be in Python's PATH.")
        print("  Try running from Git Bash or add npm/global to Windows PATH.")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("ERROR: claude --version timed out (10s).")
        sys.exit(1)


def _scan_for_claude_md(path: Path) -> list[Path]:
    """Walk up from path to root, list any CLAUDE.md files found."""
    found = []
    current = path.resolve()
    while current != current.parent:
        candidate = current / "CLAUDE.md"
        if candidate.exists():
            found.append(candidate)
        current = current.parent
    return found


def check_no_claude_md_in_chain(path: Path) -> None:
    """Requirement (spec §4a): 确认隔离目录及其全部父级目录中不存在任何 CLAUDE.md.

    Any found files are reported but do not abort — human decides.
    """
    found = _scan_for_claude_md(path)
    if found:
        print(f"WARNING: Found {len(found)} CLAUDE.md file(s) in the isolation path chain:")
        for f in found:
            print(f"  - {f}")
        print("  These may leak project context to Claude Code. Human should review.")
    else:
        print("[OK] No CLAUDE.md found in isolation directory or any parent.")


def check_user_claude_md() -> dict | None:
    """Requirement (spec §4b): 检查用户级记忆文件 ~/.claude/CLAUDE.md.

    Reports existence, size, and whether content references decision-coder,
    supply-chain templates, or benchmark experiment tasks.
    Does NOT print sensitive content — only summary booleans.
    Human decides whether to temporarily move/rename the file.
    """
    user_md = Path.home() / ".claude" / "CLAUDE.md"
    if not user_md.exists():
        print("[OK] No user-level CLAUDE.md (~/.claude/CLAUDE.md) found.")
        return None

    content = user_md.read_text(encoding="utf-8")
    has_dc = "decision-coder" in content.lower() or "decisioncoder" in content.lower()
    has_sc = any(
        kw in content.lower()
        for kw in ["供应链", "supply chain", "inventory_eoq", "demand_forecast",
                    "safety_stock", "reorder_point", "inventory_pipeline",
                    "经济订货", "安全库存", "补货点"]
    )
    has_exp = any(
        kw in content.lower()
        for kw in ["benchmark", "arm_a", "arm_b", "arm_c", "routing_on", "routing_off",
                    "BA-01", "CG-01", "ADV-01"]
    )

    print(f"\n[INFO] User-level CLAUDE.md exists: {user_md}")
    print(f"       Size: {len(content)} bytes")
    print(f"       References decision-coder project: {has_dc}")
    print(f"       References supply-chain / inventory templates: {has_sc}")
    print(f"       References benchmark / experiment tasks: {has_exp}")
    print(f"       (Full content not printed — human decides whether to temporarily move it)")

    return {
        "path": str(user_md),
        "size_bytes": len(content),
        "has_decision_coder_ref": has_dc,
        "has_supply_chain_ref": has_sc,
        "has_benchmark_ref": has_exp,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Workspace setup
# ═══════════════════════════════════════════════════════════════════════════

def setup_isolated_workspace() -> Path:
    """Create isolated workspace with only the 3 data CSV files.

    Requirement (spec §3): 仓库外空目录，仅复制 sales.csv / inventory.csv /
    sku_inventory.csv；以该目录为 cwd 调用 claude。
    禁止在 decision-coder 仓库内运行 A 臂。
    """
    ws = ISOLATED_WORKSPACE

    # Clean slate
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)

    for fname in DATA_FILES:
        src = DATA_SOURCE_DIR / fname
        if not src.exists():
            print(f"ERROR: Source data file not found: {src}")
            sys.exit(1)
        shutil.copy2(src, ws / fname)

    print(f"\n[OK] Isolated workspace: {ws}")
    for f in sorted(ws.iterdir()):
        print(f"       {f.name} ({f.stat().st_size} bytes)")

    # Spec §4a: scan for CLAUDE.md in the chain
    print("\n[CHECK] Scanning isolation path chain for CLAUDE.md...")
    check_no_claude_md_in_chain(ws)

    return ws


# ═══════════════════════════════════════════════════════════════════════════
# Claude runner
# ═══════════════════════════════════════════════════════════════════════════

def run_claude(query: str, cwd: Path, timeout: int) -> dict:
    """Call claude -p "<query>" --output-format json --dangerously-skip-permissions.

    Requirement (spec §5): 每运行施加任务超时，超时杀进程并记失败。
    捕获返回 JSON 的全部字段（result、is_error、total_cost_usd、usage、
    duration_ms 等，以实际字段为准）。

    Args:
        query: Exact task query string.
        cwd: Working directory (isolated workspace).
        timeout: Per-task timeout in seconds.

    Returns:
        Dict with all JSON fields from claude output, plus metadata keys
        prefixed with _ (exit_code, timed_out, stderr, elapsed_seconds,
        parse_error).
    """
    cli_path = _find_claude()

    # On Windows, claude.cmd needs shell=True and git-bash on PATH
    is_win_cmd = cli_path.endswith(".cmd")

    # Escape double-quotes in query for shell
    escaped_query = query.replace('"', '\\"')
    if is_win_cmd:
        cmd_line = f'"{cli_path}" -p "{escaped_query}" --output-format json --dangerously-skip-permissions'
    else:
        cmd_line = f'"{cli_path}" -p "{escaped_query}" --output-format json --dangerously-skip-permissions'

    # Build env: ensure GIT_BASH_PATH is set for claude.cmd on Windows
    env = os.environ.copy()
    if is_win_cmd and "CLAUDE_CODE_GIT_BASH_PATH" not in env:
        # Try common git-bash locations; claude.cmd needs Windows backslash paths
        git_bash_candidates = [
            r"E:\Git\bin\bash.exe",
            r"C:\Program Files\Git\bin\bash.exe",
        ]
        for candidate in git_bash_candidates:
            if os.path.exists(candidate):
                env["CLAUDE_CODE_GIT_BASH_PATH"] = candidate
                break

    start = time.time()
    proc = None
    stdout = ""
    stderr = ""

    try:
        proc = subprocess.Popen(
            cmd_line,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True,
            env=env,
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            stdout, stderr = "", "[kill timed out]"
        exit_code = -1
    except Exception as exc:
        elapsed = time.time() - start
        return {
            "result": f"[SUBPROCESS_EXCEPTION: {exc}]",
            "is_error": True,
            "total_cost_usd": None,
            "usage": None,
            "duration_ms": None,
            "_exit_code": -1,
            "_timed_out": False,
            "_stderr": str(exc),
            "_elapsed_seconds": elapsed,
            "_parse_error": str(exc),
        }

    elapsed = time.time() - start

    # Parse JSON output from claude
    try:
        parsed = json.loads(stdout.strip())
    except json.JSONDecodeError as exc:
        parsed = {
            "result": stdout[:10000] if stdout else "[EMPTY_STDOUT]",
            "is_error": True,
            "total_cost_usd": None,
            "usage": None,
            "duration_ms": None,
        }
        parsed["_parse_error"] = str(exc)

    # Attach metadata (underscore prefix to avoid colliding with claude fields)
    parsed["_exit_code"] = exit_code
    parsed["_timed_out"] = timed_out
    parsed["_stderr"] = stderr[:2000] if stderr else ""
    parsed["_elapsed_seconds"] = elapsed
    if "_parse_error" not in parsed:
        parsed["_parse_error"] = None

    return parsed


# ═══════════════════════════════════════════════════════════════════════════
# Judgment
# ═══════════════════════════════════════════════════════════════════════════
# A 臂扫描域：claude 返回 JSON 中 "result" 字段的最终答复文本（对话回复）。
# B/C 臂扫描域（validators.py）：execution_result（完整 stdout）+ final_report
# （Markdown 报告全文）的合并文本。
#
# 差异影响：
# - B/C 臂能扫到 Python 脚本 stdout 中的中间输出（如 print 的数值、表头），
#   A 臂只能看到 claude 整理后的最终回复——可能丢失部分关键词。
# - 关键词匹配算法（_keyword_found）完全一致：不区分大小写 substring +
#   浮点数前缀宽松匹配。


def judge_result(task: dict, claude_output: dict) -> dict:
    """Evaluate task success via expected_keywords AND logic on claude result text.

    Failure veto (spec §6): is_error=true 或 非零退出 或 超时 → success=False。
    与 B/C 臂的"失败否决"对齐（B/C 中 ABORT 导致 success=False）。

    Args:
        task: Task dict with expected_keywords, template_keywords.
        claude_output: Parsed JSON output from claude (including _ metadata).

    Returns:
        Judgment dict: success, completed, aborted, output_keywords_found,
        template_keywords_found, hard_fail.
    """
    result_text = claude_output.get("result", "") or ""
    is_error = claude_output.get("is_error", True)
    exit_code = claude_output.get("_exit_code", -1)
    timed_out = claude_output.get("_timed_out", False)

    # Failure veto — same logic as B/C arm's validate_task_result
    hard_fail = bool(is_error) or (exit_code != 0) or bool(timed_out)

    # expected_keywords (结果词): AND 判定 — 全部命中 ⇒ success
    output_keywords_found: list[str] = []
    for kw in task["expected_keywords"]:
        if _keyword_found(result_text, kw):
            output_keywords_found.append(kw)

    # template_keywords (机制词): 不计入 success，单独统计
    template_keywords_found: list[str] = []
    for kw in task.get("template_keywords", []):
        if _keyword_found(result_text, kw):
            template_keywords_found.append(kw)

    all_expected_found = len(output_keywords_found) == len(task["expected_keywords"])

    # success = all expected keywords found AND no hard failure
    success = all_expected_found and not hard_fail
    completed = not timed_out

    return {
        "success": success,
        "completed": completed,
        "aborted": False,  # A 臂无 ABORT 概念
        "output_keywords_found": output_keywords_found,
        "template_keywords_found": template_keywords_found,
        "hard_fail": hard_fail,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Archival
# ═══════════════════════════════════════════════════════════════════════════

def archive_run(
    batch_dir: Path,
    task_id: str,
    run_index: int,
    claude_output: dict,
) -> Path:
    """Save raw JSON output and extracted result text to archive.

    Requirement (spec §7): 保存原始 JSON 输出与提取的最终文本。

    Directory: <batch>/<task_id>/run<N>/
    Files: claude_output.json, result_text.txt
    """
    archive_path = batch_dir / task_id / f"run{run_index}"
    archive_path.mkdir(parents=True, exist_ok=True)

    # Full raw output (all captured fields including _ metadata)
    (archive_path / "claude_output.json").write_text(
        json.dumps(claude_output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # Extracted result text (the scan domain for keyword matching)
    result_text = claude_output.get("result", "")
    if isinstance(result_text, str):
        (archive_path / "result_text.txt").write_text(result_text, encoding="utf-8")

    return archive_path


def build_jsonl_record(
    task: dict,
    run_index: int,
    claude_output: dict,
    judgment: dict,
    archive_path: Path,
    git_commit: str,
) -> dict:
    """Build a JSONL record aligned with B/C arm field structure.

    Requirement (spec §7): 字段与既有批次对齐。
    B/C fields: task_id, arm, run_index, success, completed, aborted,
    retry_count, elapsed_seconds, token_usage, expected_keywords,
    output_keywords_found, archive_path, needs_manual_review, git_commit.

    token_usage 原样保存 claude 返回的 usage 全量字段（input_tokens、
    output_tokens、cache_read_input_tokens、cache_creation_input_tokens 等，
    以实际返回为准）。
    total_cost_usd 原样写入 cost 字段，cost_note 标明其为 Claude Code
    按 Anthropic 价目估算，非 DeepSeek 实价，仅存档，不用于成本对比。
    """
    usage = claude_output.get("usage")
    cost = claude_output.get("total_cost_usd")

    record: dict = {
        "task_id": task["id"],
        "arm": "claude_code",
        "run_index": run_index,
        "success": judgment["success"],
        "completed": judgment["completed"],
        "aborted": judgment["aborted"],
        "retry_count": 0,  # A 臂无重试机制
        "elapsed_seconds": claude_output.get("_elapsed_seconds", 0),
        "error": claude_output.get("_parse_error"),
        "output_keywords_found": judgment["output_keywords_found"],
        "template_keywords_found": judgment["template_keywords_found"],
        "expected_keywords": task["expected_keywords"],
        "archive_path": str(archive_path.resolve()),
        "needs_manual_review": task.get("needs_manual_review", False),
        "git_commit": git_commit,
        # usage 完整入库，保留 claude 返回的全部字段
        "token_usage": usage if isinstance(usage, dict) else {},
    }

    # total_cost_usd 原样保留，但标明非 DeepSeek 实价
    if cost is not None:
        record["cost"] = cost
    record["cost_note"] = (
        "Claude Code 按 Anthropic 价目估算，非 DeepSeek 实价，仅存档，不用于成本对比"
    )

    return record


def write_jsonl_line(jsonl_path: Path, record: dict) -> None:
    """Append one line to JSONL, flush immediately for crash safety."""
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_manifest(
    batch_dir: Path,
    batch_id: str,
    git_commit: str,
    git_dirty: bool,
    claude_version: str,
    tasks: list[dict],
) -> None:
    """Write manifest.json for the batch.

    Requirement (spec §7): git_commit、git_dirty、claude --version 输出、
    模型端点描述 "DeepSeek v4 pro"（不记录任何密钥）、任务清单、日期。
    """
    manifest = {
        "batch_id": batch_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "claude_version": claude_version,
        "model": "主链路 claude-sonnet-4-6 → deepseek-v4-pro；辅助 claude-haiku-4-5 → deepseek-v4-flash；经 ccswitch 本地代理（http://127.0.0.1:15721），映射配置见 ~/.claude/settings.json",
        "tasks": [
            {
                "id": t["id"],
                "category": t["category"],
                "query": t["query"],
                "timeout": t["timeout"],
            }
            for t in tasks
        ],
        "arm_config": {
            "arm": "claude_code",
            "repeat": 3,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = batch_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[OK] Manifest: {manifest_path}")


# ═══════════════════════════════════════════════════════════════════════════
# Git helpers
# ═══════════════════════════════════════════════════════════════════════════

def get_git_info() -> tuple[str, bool]:
    """Get short commit hash and dirty flag from repo root."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown", True

    try:
        dirty = subprocess.run(
            ["git", "diff-index", "--quiet", "HEAD", "--"],
            capture_output=True, cwd=str(PROJECT_ROOT),
        ).returncode != 0
    except Exception:
        dirty = True

    return commit, dirty


# ═══════════════════════════════════════════════════════════════════════════
# Smoke test
# ═══════════════════════════════════════════════════════════════════════════

def run_smoke(workspace: Path) -> None:
    """CG-01 × 1 smoke test — verify endpoint, fields, keywords, cost/token.

    Requirement (spec: 冒烟): 仅 CG-01 × 1 次，打印捕获到的 JSON 字段清单与
    判定结果，确认 cost/token 字段真实存在后交付。不要直接跑全量。

    Also reports: actual cwd, isolation dir contents, return JSON field list,
    cost/token non-empty status.
    """
    task = {
        "id": "CG-01",
        "query": "计算 EOQ：年需求 1000，订货成本 50，持有成本 2，打印结果",
        "expected_keywords": ["EOQ", "223"],
        "template_keywords": ["inventory_eoq"],
        "timeout": 60,
        "needs_manual_review": False,
    }

    print("\n" + "=" * 70)
    print("SMOKE TEST: CG-01 × 1")
    print("=" * 70)
    print(f"\n  Workspace (cwd): {workspace}")
    print(f"  Workspace contents:")
    for f in sorted(workspace.iterdir()):
        print(f"    {f.name} ({f.stat().st_size} bytes)")
    print(f"\n  Query: {task['query']}")
    print(f"  Timeout: {task['timeout']}s")
    print(f"\n--- Running claude -p ... ---")

    output = run_claude(task["query"], workspace, task["timeout"])

    # ── Metadata ──
    print(f"\n--- Subprocess metadata ---")
    print(f"  Exit code: {output.get('_exit_code')}")
    print(f"  Timed out: {output.get('_timed_out')}")
    print(f"  Elapsed:   {output.get('_elapsed_seconds', 0):.2f}s")
    stderr = output.get("_stderr", "")
    if stderr:
        print(f"  Stderr:    {stderr[:300]}")

    # ── Full JSON field inventory ──
    public_fields = {k: v for k, v in output.items() if not k.startswith("_")}
    meta_fields = {k: v for k, v in output.items() if k.startswith("_")}

    print(f"\n--- JSON fields from claude --output-format json ({len(public_fields)} public) ---")
    for key in sorted(public_fields):
        val = public_fields[key]
        displayed = _format_field_value(val)
        print(f"  {key}: {displayed}")

    print(f"\n--- Metadata fields ({len(meta_fields)} underscore-prefixed) ---")
    for key in sorted(meta_fields):
        val = meta_fields[key]
        displayed = _format_field_value(val)
        print(f"  {key}: {displayed}")

    # ── Cost / token check ──
    is_error = output.get("is_error", True)
    usage = output.get("usage")
    cost = output.get("total_cost_usd")
    duration_ms = output.get("duration_ms")

    print(f"\n--- Cost / Token check ---")
    print(f"  is_error:       {is_error}")
    print(f"  usage:          {_format_field_value(usage)}")
    print(f"  total_cost_usd: {cost}")
    print(f"  duration_ms:    {duration_ms}")
    print(f"  usage non-empty:     {bool(usage)}")
    print(f"  cost non-null:       {cost is not None}")
    print(f"  duration_ms non-null:{duration_ms is not None}")

    # ── Keyword judgment ──
    judgment = judge_result(task, output)
    result_text = output.get("result", "") or ""

    print(f"\n--- Keyword judgment ---")
    print(f"  Result text length: {len(result_text)} chars")
    print(f"  Result text (first 600 chars):\n{result_text[:600]}")
    print(f"  Expected keywords:  {task['expected_keywords']}")
    print(f"  Found:              {judgment['output_keywords_found']}")
    print(f"  Template keywords:  {task['template_keywords']}")
    print(f"  Template found:     {judgment['template_keywords_found']}")
    print(f"  Hard fail:          {judgment['hard_fail']}")
    print(f"  SUCCESS:            {judgment['success']}")

    # ── Verdict ──
    print(f"\n--- Verdict ---")
    if judgment["success"]:
        print("[PASS] Smoke test passed — keywords found, no errors.")
    else:
        missing = set(task["expected_keywords"]) - set(judgment["output_keywords_found"])
        print(f"[FAIL] success=False — missing keywords: {missing}")
        if judgment["hard_fail"]:
            print(f"       Hard fail: is_error={is_error}, exit={output.get('_exit_code')}, timeout={output.get('_timed_out')}")
    print("=" * 70)


def _format_field_value(val, max_len: int = 300) -> str:
    """Format a field value for display — truncate long strings, format dicts."""
    if val is None:
        return "null"
    if isinstance(val, dict):
        inner = ", ".join(f"{k}={_format_field_value(v, 80)}" for k, v in val.items())
        return "{" + inner + "}"
    if isinstance(val, list):
        items = ", ".join(_format_field_value(v, 60) for v in val[:5])
        if len(val) > 5:
            items += f", ... (+{len(val) - 5})"
        return "[" + items + "]"
    if isinstance(val, str) and len(val) > max_len:
        return repr(val[:max_len] + "...")
    return repr(val)


# ═══════════════════════════════════════════════════════════════════════════
# Full batch
# ═══════════════════════════════════════════════════════════════════════════

def run_full_batch(workspace: Path) -> None:
    """Run all 17 tasks × 3 repetitions = 51 runs, with archival and JSONL.

    Requirement (spec §8): 跑批前先提交本脚本，保证 manifest 落在干净哈希上。
    """
    tasks = get_all_tasks()
    total_runs = len(tasks) * 3

    # Pre-flight checks
    claude_version = check_claude_cli()
    git_commit, git_dirty = get_git_info()

    print(f"Git commit: {git_commit}  dirty: {git_dirty}")

    if git_dirty:
        print("\nERROR: Repository is dirty.")
        print("  Per spec §8, commit this script before running the full batch:")
        print("    git add scripts/run_arm_a.py")
        print('    git commit -m "add arm A runner script"')
        print("  Then re-run: python scripts/run_arm_a.py --full")
        sys.exit(1)

    check_user_claude_md()

    # Batch directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_id = f"arm_a_{ts}_{git_commit}"
    batch_dir = ARTIFACTS_ROOT / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = batch_dir / f"benchmark_{batch_id}.jsonl"
    # Create empty JSONL (will append line by line)
    jsonl_path.write_text("", encoding="utf-8")

    print(f"\n{'=' * 70}")
    print(f"FULL BATCH: {total_runs} runs ({len(tasks)} tasks × 3 reps)")
    print(f"Batch dir:  {batch_dir}")
    print(f"JSONL:       {jsonl_path}")
    print(f"{'=' * 70}\n")

    run_num = 0

    for task in tasks:
        for rep in range(1, 4):
            run_num += 1
            label = f"[{run_num}/{total_runs}] {task['id']} run {rep}"
            print(f"{label} ...", end=" ", flush=True)

            output = run_claude(task["query"], workspace, task["timeout"])
            judgment = judge_result(task, output)
            archive_path = archive_run(batch_dir, task["id"], rep, output)

            record = build_jsonl_record(
                task, rep, output, judgment, archive_path, git_commit,
            )
            # Include task category for downstream grouping
            record["category"] = task["category"]
            write_jsonl_line(jsonl_path, record)

            kw_str = f"{len(judgment['output_keywords_found'])}/{len(task['expected_keywords'])}"
            elapsed = output.get("_elapsed_seconds", 0)
            status = "PASS" if judgment["success"] else "FAIL"
            fail_reason = ""
            if not judgment["success"]:
                if judgment["hard_fail"]:
                    fail_reason = f" [hard_fail: err={output.get('is_error')} exit={output.get('_exit_code')} to={output.get('_timed_out')}]"
                else:
                    missing = set(task["expected_keywords"]) - set(judgment["output_keywords_found"])
                    fail_reason = f" [missing: {missing}]"
            print(f"{status}  kw={kw_str}  {elapsed:.1f}s{fail_reason}")

    # Write manifest
    write_manifest(batch_dir, batch_id, git_commit, git_dirty, claude_version, tasks)

    # Quick summary from JSONL
    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    success_count = sum(1 for r in records if r.get("success"))
    completed_count = sum(1 for r in records if r.get("completed"))
    total_cost = sum(
        (r.get("token_usage") or {}).get("total_tokens", 0)
        if isinstance(r.get("token_usage"), dict) else 0
        for r in records
    )

    print(f"\n{'=' * 70}")
    print(f"BATCH COMPLETE")
    print(f"  Total:    {len(records)}")
    print(f"  Success:  {success_count}/{len(records)} ({100*success_count/len(records):.0f}%)")
    print(f"  Completed:{completed_count}/{len(records)} ({100*completed_count/len(records):.0f}%)")
    print(f"  Tokens:   {total_cost}")
    print(f"{'=' * 70}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Entry point. --smoke for CG-01×1, --full for 51-run batch."""
    if "--smoke" not in sys.argv and "--full" not in sys.argv:
        print("Usage:")
        print("  python scripts/run_arm_a.py --smoke   # CG-01 × 1 (verify endpoint)")
        print("  python scripts/run_arm_a.py --full    # 17 tasks × 3 = 51 runs")
        print("\nRun --smoke first to verify cost/token fields exist.")
        sys.exit(0)

    smoke = "--smoke" in sys.argv

    print("=" * 70)
    print("Arm A Runner — Claude Code (bare)")
    print("=" * 70)

    # Spec §4c: check claude CLI first
    _claude_version = check_claude_cli()

    # Spec §4b: check user-level CLAUDE.md
    check_user_claude_md()

    # Spec §3-4a: setup isolated workspace
    workspace = setup_isolated_workspace()
    print()

    if smoke:
        # Spec: 冒烟 — 仅 CG-01 × 1，验证字段与端点
        run_smoke(workspace)
    else:
        # Spec §8: 全量前必须提交本脚本
        run_full_batch(workspace)


if __name__ == "__main__":
    main()

"""Benchmark 执行引擎。

BenchmarkRunner — 遍历任务集，逐个执行 graph.run()，收集结果写入 JSONL。
支持 use_ui=True 时通过 Rich 终端 UI 实时展示进度。

新增（对照实验）：
- arm 参数（routing_on / routing_off）
- repeat 参数（重复运行次数，默认 1）
- token 用量追踪（token_tracker）
- 数值结果提取（numeric_extractor）
- run_both() 双臂对照执行

新增（证据保留 + 失败否决）：
- batch_id: <时间戳>_<git短哈希>，会话级别
- git_commit / git_dirty 记录在 JSONL 和 manifest.json 中
- archive_artifacts: 清理前复制报告和图表到 results/artifacts/
- 失败否决: ABORT/fail_*.md → success=False
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.benchmark.metrics import MetricsCollector
from src.benchmark.validators import validate_task_result
from src.benchmark.token_tracker import start_token_tracking, stop_token_tracking, get_token_totals
from src.benchmark.numeric_extractor import extract_numeric_value


class BenchmarkTimeoutError(Exception):
    """任务执行超时异常。"""

    pass


class BenchmarkRunner:
    """Benchmark 执行引擎。

    用法:
        tasks = get_default_tasks()
        runner = BenchmarkRunner(tasks, workspace_path="workspace/")
        collector = runner.run_all()

        # 双臂对照
        collector = runner.run_both(repeat=3)

        # 带 Rich UI
        collector = runner.run_all(use_ui=True)
    """

    def __init__(
        self,
        tasks: list[BenchmarkTask],
        workspace_path: str = "workspace/",
        output_dir: str = "results/",
        arm: str = "routing_on",
        repeat: int = 1,
    ) -> None:
        """初始化执行引擎。

        Args:
            tasks: 待执行的 benchmark 任务列表。
            workspace_path: 工作区根路径。
            output_dir: JSONL 输出目录（相对于项目根）。
            arm: 实验臂（"routing_on" | "routing_off"）。
            repeat: 每个任务的重复执行次数（默认 1）。
        """
        self.tasks = tasks
        self.workspace_path = str(Path(workspace_path).resolve())
        self.output_dir = str(Path(output_dir).resolve())
        self.arm = arm
        self.repeat = max(repeat, 1)

        # 确保输出目录存在
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        # ── 批次标识：时间戳 + git 短哈希 ──
        self._git_commit = self._get_git_commit()
        self._git_dirty = self._check_git_dirty()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        git_short = self._git_commit[:7] if self._git_commit else "nogit"
        self.batch_id: str = f"{timestamp}_{git_short}"

        # ── 脏工作区警告 ──
        if self._git_dirty:
            print(
                "⚠️ [Benchmark] 工作区存在未提交修改（git status --porcelain 非空），"
                "正式实验前建议先提交！"
            )

        # ── 归档目录：results/artifacts/<batch_id>/ ──
        self._artifact_base = (
            Path(self.output_dir) / "artifacts" / self.batch_id
        )
        # Manifest 累计（在 run_all 结束时写入）
        self._manifest: dict[str, Any] = {
            "batch_id": self.batch_id,
            "git_commit": self._git_commit,
            "git_dirty": self._git_dirty,
            "cli_args": {},
            "tasks": [],
            "arm_config": {},
            "generated_at": datetime.now().isoformat(),
        }

        # JSONL 输出路径（每次 run_all() 生成新文件）
        self._jsonl_path = Path(self.output_dir) / f"benchmark_{self.batch_id}.jsonl"
        self._lock = threading.Lock()

    # ── Git 信息获取 ────────────────────────────────────────

    @staticmethod
    def _get_git_commit() -> str:
        """获取当前 HEAD 的完整 commit hash。

        调用 `git rev-parse HEAD`，失败返回空字符串。

        Returns:
            40 位 SHA-1 哈希字符串，或空字符串。
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass
        return ""

    @staticmethod
    def _check_git_dirty() -> bool:
        """检查工作区是否有未提交的修改。

        Returns:
            True 表示有未暂存或未跟踪文件（git status --porcelain 非空）。
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return len(result.stdout.strip()) > 0
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass
        return False

    # ── 公开接口 ──────────────────────────────────────────

    def run_single(self, task: BenchmarkTask) -> tuple[dict, float]:
        """执行单个任务。

        Args:
            task: 任务定义。

        Returns:
            (final_state, elapsed_seconds) — 即使超时/异常也会返回 state。
        """
        from src.agent.graph import run as graph_run

        t_start = time.time()

        # ── 超时控制 ──
        result_state: dict = {}
        error_occurred: Exception | None = None
        done = threading.Event()

        def _execute() -> None:
            nonlocal result_state, error_occurred
            try:
                result_state = graph_run(
                    user_query=task.query,
                    workspace_path=self.workspace_path,
                )
            except Exception as exc:
                error_occurred = exc
                result_state = {
                    "user_query": task.query,
                    "workspace_path": self.workspace_path,
                    "plan": [],
                    "generated_code": "",
                    "file_path": None,
                    "execution_result": None,
                    "error": str(exc),
                    "retry_count": 0,
                    "human_feedback": None,
                    "final_report": None,
                }
            finally:
                done.set()

        exec_thread = threading.Thread(target=_execute, daemon=True)
        exec_thread.start()

        timed_out = not done.wait(timeout=task.timeout)

        if timed_out:
            # 超时：线程仍在运行（daemon 会随主线程退出），但不再等待
            result_state = {
                "user_query": task.query,
                "workspace_path": self.workspace_path,
                "plan": [],
                "generated_code": "",
                "file_path": None,
                "execution_result": None,
                "error": f"BenchmarkTimeoutError: 任务超时（{task.timeout}s）",
                "retry_count": 0,
                "human_feedback": None,
                "final_report": None,
            }
            elapsed = time.time() - t_start
            return result_state, elapsed

        elapsed = time.time() - t_start

        if error_occurred is not None:
            # 确保 error 字段被设置
            if not result_state.get("error"):
                result_state["error"] = str(error_occurred)

        return result_state, elapsed

    def run_all(self, use_ui: bool = False) -> MetricsCollector:
        """执行全部任务，逐任务收集结果。

        每个任务执行后立即：
        1. 验证结果（validate_task_result）
        2. 写入 JSONL（断点续跑友好）
        3. 打印进度（或通过 Rich UI 展示）

        自动设置 DECISIONCODER_HITL_AUTO="1,4"，确保无人值守时
        Debugger 的 _safe_input 不阻塞等待人工输入。
        每个任务开始前重置 HITL 自动应答计数器。
        首次写入 JSONL 时清除旧文件；追加写入时不删除（如 --both 双臂复用）。
        运行结束后恢复 DECISIONCODER_NO_ROUTING 环境变量。

        Args:
            use_ui: 是否启用 Rich 终端 UI（默认 False）。

        Returns:
            MetricsCollector（包含全部 BenchmarkResult）。
        """
        n = len(self.tasks)
        total_runs = n * self.repeat
        collector = MetricsCollector()

        # ── Arm 环境切换 ──
        _prev_no_routing = os.environ.get("DECISIONCODER_NO_ROUTING")
        self._toggle_env_for_arm(self.arm)

        # ── HITL 自动应答（benchmark 无人值守） ──
        self._setup_hitl_auto()

        # ── Rich UI 初始化 ──
        ui_manager = None
        if use_ui:
            ui_manager = self._init_ui()

        # 仅首次运行（JSONL 为空或不存在）时清空旧文件
        _is_empty = (
            not self._jsonl_path.exists()
            or self._jsonl_path.stat().st_size == 0
        )
        if not _is_empty:
            # 追加模式：保留已有内容
            pass
        else:
            # 首次写入：清空旧文件
            if self._jsonl_path.exists():
                self._jsonl_path.unlink()

        try:
            run_counter = 0

            # ── 构建 manifest 任务清单 ──
            for task in self.tasks:
                self._manifest["tasks"].append({
                    "id": task.id,
                    "category": task.category,
                    "query": task.query,
                    "timeout": task.timeout,
                })
            self._manifest["arm_config"] = {
                "arm": self.arm,
                "repeat": self.repeat,
            }

            for run_i in range(1, self.repeat + 1):
                for task_i, task in enumerate(self.tasks):
                    run_counter += 1

                    if not use_ui:
                        print(f"\n{'─' * 50}")
                        print(f"[{run_counter}/{total_runs}] {task.id} — "
                              f"{task.category} — arm={self.arm} — run {run_i}/{self.repeat}")
                        print(f"{'─' * 50}")

                    # ── 任务前环境清理 ──
                    self._cleanup_workspace()

                    # ── 重置 HITL 自动应答计数器（每个任务独立） ──
                    self._reset_hitl_counter()

                    # ── Token 追踪 ──
                    start_token_tracking()

                    # ── 执行 ──
                    if use_ui and ui_manager is not None:
                        ui_manager.log(
                            f"[{task.id}] arm={self.arm} run={run_i} 开始...",
                            level="info",
                        )
                    else:
                        print(f"  执行中...")

                    state, elapsed = self.run_single(task)

                    # ── 收集 token 用量 ──
                    token_usage = get_token_totals()

                    # ── 停止 Token 追踪 ──
                    stop_token_tracking()

                    # ── 提取数值结果 ──
                    numeric_value = extract_numeric_value(
                        task.id,
                        str(state.get("execution_result", "")),
                    )

                    # ── 验证 ──
                    result = validate_task_result(
                        task, state, round(elapsed, 2), self.workspace_path
                    )
                    # 注入扩展字段
                    result.category = task.category  # type: ignore[attr-defined]
                    result.run_index = run_i
                    result.arm = self.arm
                    result.token_usage = token_usage
                    result.numeric_value = numeric_value
                    result.needs_manual_review = task.needs_manual_review

                    # ── 归档报告与图表（清理前保存） ──
                    archive_path = self._archive_artifacts(task, run_i)
                    result.archive_path = archive_path

                    collector.record(result)

                    # ── 写入 JSONL ──
                    self._append_jsonl(result)

                    # ── 打印结果 ──
                    if use_ui and ui_manager is not None:
                        status_icon = "✅" if result.success else ("❌" if result.completed else "⏱")
                        ui_manager.log(
                            f"{status_icon} [{task.id}] {result.elapsed_seconds:.1f}s | "
                            f"重试 {result.retry_count} | token={token_usage.get('total_tokens', 0)} | "
                            f"结果命中 {result.output_keywords_found} | "
                            f"机制[{','.join(result.template_keywords_found) or '—'}]",
                            level="info" if result.success else "error",
                        )
                    else:
                        verdict = "✅ 通过" if result.success else ("❌ 失败" if result.completed else "⏱ 超时")
                        template_info = f" | 机制[{','.join(result.template_keywords_found) or '—'}]"
                        print(f"  {verdict} | 耗时 {result.elapsed_seconds:.1f}s | "
                              f"重试 {result.retry_count} | "
                              f"token={token_usage.get('total_tokens', 0)} | "
                              f"结果词命中 {result.output_keywords_found}"
                              f"{template_info}")

        finally:
            # ── 恢复 HITL 环境变量 ──
            self._restore_hitl_auto()
            # ── 恢复 DECISIONCODER_NO_ROUTING 环境变量 ──
            if _prev_no_routing is not None:
                os.environ["DECISIONCODER_NO_ROUTING"] = _prev_no_routing
            else:
                os.environ.pop("DECISIONCODER_NO_ROUTING", None)
            if ui_manager is not None:
                ui_manager.stop()

        # ── 最终汇总 ──
        metrics = collector.compute()

        # ── 写入 manifest.json ──
        self._manifest["generated_at"] = datetime.now().isoformat()
        self._manifest["metrics_summary"] = {
            "total": metrics["total"],
            "completion_rate": metrics["completion_rate"],
            "success_rate": metrics["success_rate"],
            "avg_retry_count": metrics["avg_retry_count"],
            "avg_elapsed_seconds": metrics["avg_elapsed_seconds"],
            "token_total": metrics.get("token_total", 0),
        }
        manifest_path = self._artifact_base / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(self._manifest, f, ensure_ascii=False, indent=2)
        if not use_ui:
            print(f"\n{'═' * 50}")
            print(f"Benchmark 完成：arm={self.arm} | {metrics['total']} 个结果")
            print(f"  完成率:  {metrics['completion_rate']}")
            print(f"  成功率:  {metrics['success_rate']}")
            print(f"  平均重试: {metrics['avg_retry_count']}")
            print(f"  平均耗时: {metrics['avg_elapsed_seconds']}s")
            if "token_total" in metrics:
                print(f"  Token 总量: {metrics['token_total']}")
            print(f"  结果文件: {self._jsonl_path}")
            print(f"{'═' * 50}")

        return collector

    def run_both(self, repeat: int = 3) -> MetricsCollector:
        """双臂对照执行：routing_on → routing_off。

        顺序执行两个 arm，合并结果到一个 MetricsCollector。
        两个 arm 共享同一个 batch_id、JSONL 文件和 artifact_base。

        Args:
            repeat: 每个 arm 的重复次数（默认 3）。

        Returns:
            包含双臂全部结果的 MetricsCollector。
        """
        collector = MetricsCollector()

        for arm_name in ("routing_on", "routing_off"):
            print(f"\n{'═' * 60}")
            print(f"🔬 实验臂: {arm_name}")
            print(f"{'═' * 60}")

            # 构造单 arm 的 runner（复用 batch_id / JSONL / artifact_base）
            runner = BenchmarkRunner(
                tasks=self.tasks,
                workspace_path=self.workspace_path,
                output_dir=self.output_dir,
                arm=arm_name,
                repeat=repeat,
            )
            # 覆盖为当前 runner 的批号，确保两臂同批次
            runner.batch_id = self.batch_id
            runner._git_commit = self._git_commit
            runner._git_dirty = self._git_dirty
            runner._artifact_base = self._artifact_base
            runner._manifest = self._manifest
            runner._jsonl_path = self._jsonl_path
            runner._lock = self._lock

            arm_collector = runner.run_all()
            for r in arm_collector.results:
                collector.record(r)

        return collector

    # ── HITL 自动应答 ──

    _hitl_prev_value: str | None = None  # 保存初始值，用于恢复

    def _setup_hitl_auto(self) -> None:
        """设置 HITL 自动应答环境变量（默认 "1,4"）。

        保存当前值以便任务结束后恢复。
        """
        self._hitl_prev_value = os.environ.get("DECISIONCODER_HITL_AUTO")
        os.environ["DECISIONCODER_HITL_AUTO"] = "1,4"

    def _restore_hitl_auto(self) -> None:
        """恢复 HITL 自动应答环境变量到初始值。"""
        if self._hitl_prev_value is None:
            os.environ.pop("DECISIONCODER_HITL_AUTO", None)
        else:
            os.environ["DECISIONCODER_HITL_AUTO"] = self._hitl_prev_value

    @staticmethod
    def _reset_hitl_counter() -> None:
        """重置 HITL 自动应答计数器（每个任务前调用）。"""
        from src.agent.nodes.debugger import _reset_hitl_auto_counter
        _reset_hitl_auto_counter()

    # ── 内部辅助（续） ──

    @property
    def jsonl_path(self) -> str:
        """当前 JSONL 输出路径（供 __main__.py 报告生成使用）。"""
        return str(self._jsonl_path)

    def _toggle_env_for_arm(self, arm: str) -> None:
        """根据 arm 设置/清除环境变量。

        Args:
            arm: "routing_on" 或 "routing_off"。
        """
        if arm == "routing_off":
            os.environ["DECISIONCODER_NO_ROUTING"] = "true"
        else:
            # routing_on: 清除环境变量（恢复纯 LLM 路由对照）
            os.environ.pop("DECISIONCODER_NO_ROUTING", None)

    def _init_ui(self) -> object | None:
        """初始化 Rich 终端 UI。

        Returns:
            UIManager 实例，或 None（降级时）。
        """
        try:
            from src.agent.ui.manager import UIManager
            ui = UIManager()
            ui.start()
            if ui._is_tty:
                print("🎨 Rich 终端 UI 已启动")
            for task in self.tasks:
                ui.update_node(task.id, "等待", 0.0, retry=0)
            return ui
        except Exception:
            return None

    def _cleanup_workspace(self) -> None:
        """任务前清理临时文件（避免上一任务污染）。

        删除：
        - workspace/src/_dc_exec_*.py（执行临时文件）
        - workspace/reports/ 目录（旧报告）
        """
        ws = Path(self.workspace_path)
        # 清理临时执行文件
        src_dir = ws / "src"
        if src_dir.exists():
            for f in src_dir.glob("_dc_exec_*.py"):
                try:
                    f.unlink()
                except OSError:
                    pass
        # 清理旧报告
        reports_dir = ws / "reports"
        if reports_dir.exists():
            try:
                shutil.rmtree(reports_dir)
            except OSError:
                pass

    def _archive_artifacts(
        self, task: BenchmarkTask, run_index: int
    ) -> str | None:
        """清理前将报告与图表归档到 results/artifacts/<batch_id>/<task_id>/<arm>/run<N>/。

        归档内容：
        - workspace/reports/report_*.md
        - workspace/reports/fail_*.md
        - workspace/reports/charts/*.html

        Args:
            task: 当前任务定义。
            run_index: 运行序号。

        Returns:
            归档目录路径，或 None（无文件可归档时）。
        """
        ws = Path(self.workspace_path)
        reports_dir = ws / "reports"
        if not reports_dir.exists():
            return None

        # 收集可归档文件
        report_files = list(reports_dir.glob("report_*.md"))
        fail_files = list(reports_dir.glob("fail_*.md"))
        chart_dir = reports_dir / "charts"
        chart_files = (
            list(chart_dir.glob("*.html")) if chart_dir.exists() else []
        )

        all_files = report_files + fail_files + chart_files
        if not all_files:
            return None

        # 目标路径
        dest_dir = (
            self._artifact_base
            / task.id
            / self.arm
            / f"run{run_index}"
        )
        dest_dir.mkdir(parents=True, exist_ok=True)

        # 复制文件
        for f in all_files:
            dest = dest_dir / f.name
            try:
                shutil.copy2(f, dest)
            except OSError:
                pass

        # 图表文件保持目录结构
        if chart_files:
            chart_dest = dest_dir / "charts"
            chart_dest.mkdir(parents=True, exist_ok=True)
            for f in chart_files:
                try:
                    shutil.copy2(f, chart_dest / f.name)
                except OSError:
                    pass

        return str(dest_dir.resolve())

    def _append_jsonl(self, result: BenchmarkResult) -> None:
        """追加单行 JSON 到 JSONL 文件（线程安全）。

        Args:
            result: BenchmarkResult。
        """
        record: dict[str, Any] = {
            "task_id": result.task_id,
            "success": result.success,
            "completed": result.completed,
            "aborted": result.aborted,
            "retry_count": result.retry_count,
            "elapsed_seconds": result.elapsed_seconds,
            "error": result.error,
            "output_keywords_found": result.output_keywords_found,
            "template_keywords_found": result.template_keywords_found,
            "report_path": result.report_path,
            "archive_path": result.archive_path,
            "run_index": result.run_index,
            "arm": result.arm,
            "git_commit": self._git_commit,
            "needs_manual_review": result.needs_manual_review,
        }
        if result.token_usage is not None:
            record["token_usage"] = result.token_usage
        if result.numeric_value is not None:
            record["numeric_value"] = result.numeric_value

        with self._lock:
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

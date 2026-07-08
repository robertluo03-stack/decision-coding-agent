"""Benchmark 执行引擎。

BenchmarkRunner — 遍历任务集，逐个执行 graph.run()，收集结果写入 JSONL。
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.benchmark.metrics import MetricsCollector
from src.benchmark.validators import validate_task_result


class BenchmarkTimeoutError(Exception):
    """任务执行超时异常。"""

    pass


class BenchmarkRunner:
    """Benchmark 执行引擎。

    用法:
        tasks = get_default_tasks()
        runner = BenchmarkRunner(tasks, workspace_path="workspace/")
        collector = runner.run_all()
        metrics = collector.compute()
    """

    def __init__(
        self,
        tasks: list[BenchmarkTask],
        workspace_path: str = "workspace/",
        output_dir: str = "results/",
    ) -> None:
        """初始化执行引擎。

        Args:
            tasks: 待执行的 benchmark 任务列表。
            workspace_path: 工作区根路径。
            output_dir: JSONL 输出目录（相对于项目根）。
        """
        self.tasks = tasks
        self.workspace_path = str(Path(workspace_path).resolve())
        self.output_dir = str(Path(output_dir).resolve())

        # 确保输出目录存在
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        # JSONL 输出路径（每次 run_all() 生成新文件）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._jsonl_path = Path(self.output_dir) / f"benchmark_{timestamp}.jsonl"
        self._lock = threading.Lock()

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

    def run_all(self) -> MetricsCollector:
        """执行全部任务，逐任务收集结果。

        每个任务执行后立即：
        1. 验证结果（validate_task_result）
        2. 写入 JSONL（断点续跑友好）
        3. 打印进度

        Returns:
            MetricsCollector（包含全部 BenchmarkResult）。
        """
        n = len(self.tasks)
        collector = MetricsCollector()

        # 清除 JSONL 文件（覆盖旧内容）
        if self._jsonl_path.exists():
            self._jsonl_path.unlink()

        for i, task in enumerate(self.tasks):
            print(f"\n{'─' * 50}")
            print(f"[{i + 1}/{n}] {task.id} — {task.category}")
            print(f"{'─' * 50}")

            # ── 任务前环境清理 ──
            self._cleanup_workspace()

            # ── 执行 ──
            print(f"  执行中...")
            state, elapsed = self.run_single(task)

            # ── 验证 ──
            result = validate_task_result(
                task, state, round(elapsed, 2), self.workspace_path
            )
            # 注入 category（供 MetricsCollector 分组）
            result.category = task.category  # type: ignore[attr-defined]
            collector.record(result)

            # ── 写入 JSONL ──
            self._append_jsonl(result)

            # ── 打印结果 ──
            verdict = "✅ 通过" if result.success else ("❌ 失败" if result.completed else "⏱ 超时")
            print(f"  {verdict} | 耗时 {result.elapsed_seconds:.1f}s | "
                  f"重试 {result.retry_count} | "
                  f"关键词命中 {result.output_keywords_found}")

        # ── 最终汇总 ──
        metrics = collector.compute()
        print(f"\n{'═' * 50}")
        print(f"Benchmark 完成：{metrics['total']} 个任务")
        print(f"  完成率:  {metrics['completion_rate']}")
        print(f"  成功率:  {metrics['success_rate']}")
        print(f"  平均重试: {metrics['avg_retry_count']}")
        print(f"  平均耗时: {metrics['avg_elapsed_seconds']}s")
        print(f"  结果文件: {self._jsonl_path}")
        print(f"{'═' * 50}")

        return collector

    # ── 内部辅助 ──────────────────────────────────────────

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
            import shutil
            try:
                shutil.rmtree(reports_dir)
            except OSError:
                pass

    def _append_jsonl(self, result: BenchmarkResult) -> None:
        """追加单行 JSON 到 JSONL 文件（线程安全）。

        Args:
            result: BenchmarkResult。
        """
        record = {
            "task_id": result.task_id,
            "success": result.success,
            "completed": result.completed,
            "retry_count": result.retry_count,
            "elapsed_seconds": result.elapsed_seconds,
            "error": result.error,
            "output_keywords_found": result.output_keywords_found,
            "report_path": result.report_path,
        }
        with self._lock:
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

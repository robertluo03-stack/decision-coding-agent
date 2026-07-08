"""MetricsCollector — Benchmark 指标收集与计算。

收集所有 BenchmarkResult → compute() 计算聚合指标字典。
所有指标保留 2 位小数。
"""

from __future__ import annotations

from src.benchmark.models import BenchmarkResult


class MetricsCollector:
    """Benchmark 指标收集器。

    用法:
        mc = MetricsCollector()
        mc.record(BenchmarkResult(...))
        ...
        metrics = mc.compute()
    """

    def __init__(self) -> None:
        """初始化空结果列表。"""
        self.results: list[BenchmarkResult] = []

    def record(self, result: BenchmarkResult) -> None:
        """追加一个执行结果。

        Args:
            result: 单次 benchmark 执行结果。
        """
        self.results.append(result)

    def compute(self) -> dict:
        """计算聚合指标。

        Returns:
            指标字典包含：
            - total: 总任务数
            - completion_rate: 完成率（completed / total），保留 2 位小数
            - success_rate: 成功率（success / total），保留 2 位小数
            - avg_retry_count: 平均重试次数
            - avg_elapsed_seconds: 平均耗时
            - category_breakdown: {category: {count, success_rate, completion_rate}}
            - task_details: 每个任务的 {task_id, success, completed, retry, elapsed, error}
        """
        total = len(self.results)
        if total == 0:
            return {
                "total": 0,
                "completion_rate": 0.0,
                "success_rate": 0.0,
                "avg_retry_count": 0.0,
                "avg_elapsed_seconds": 0.0,
                "category_breakdown": {},
                "task_details": [],
            }

        completed = sum(1 for r in self.results if r.completed)
        succeeded = sum(1 for r in self.results if r.success)

        retries = [r.retry_count for r in self.results]
        elapsed = [r.elapsed_seconds for r in self.results]

        # ── 按 category 分组统计 ──
        category_breakdown: dict = {}
        categories: dict[str, list[BenchmarkResult]] = {}
        for r in self.results:
            cat = getattr(r, "category", "unknown")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r)

        for cat, cat_results in categories.items():
            cat_total = len(cat_results)
            cat_completed = sum(1 for r in cat_results if r.completed)
            cat_succeeded = sum(1 for r in cat_results if r.success)
            category_breakdown[cat] = {
                "count": cat_total,
                "success_rate": round(cat_succeeded / cat_total, 2) if cat_total > 0 else 0.0,
                "completion_rate": round(cat_completed / cat_total, 2) if cat_total > 0 else 0.0,
                "avg_retry_count": round(
                    sum(r.retry_count for r in cat_results) / cat_total, 2
                ) if cat_total > 0 else 0.0,
                "avg_elapsed_seconds": round(
                    sum(r.elapsed_seconds for r in cat_results) / cat_total, 2
                ) if cat_total > 0 else 0.0,
            }

        # ── 任务详情 ──
        task_details = []
        for r in self.results:
            task_details.append({
                "task_id": r.task_id,
                "success": r.success,
                "completed": r.completed,
                "retry_count": r.retry_count,
                "elapsed_seconds": round(r.elapsed_seconds, 2),
                "error": r.error,
                "output_keywords_found": r.output_keywords_found,
            })

        return {
            "total": total,
            "completion_rate": round(completed / total, 2),
            "success_rate": round(succeeded / total, 2),
            "avg_retry_count": round(sum(retries) / total, 2),
            "avg_elapsed_seconds": round(sum(elapsed) / total, 2),
            "category_breakdown": category_breakdown,
            "task_details": task_details,
        }

"""MetricsCollector — Benchmark 指标收集与计算。

收集所有 BenchmarkResult → compute() 计算聚合指标字典。
所有指标保留 2 位小数。

新增：
- arm_breakdown：按 arm 分组统计，含 template_hit_rate
- consistency_rate：数值结果一致率
- token_total / token_prompt / token_completion：全局 token 汇总
- template_hit_rate：机制词命中率（所有任务 template_keywords 的总命中比例）
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
            - total: 总结果数
            - completed: 已完成数
            - succeeded: 成功数
            - completion_rate: 完成率
            - success_rate: 成功率
            - avg_retry_count: 平均重试次数
            - avg_elapsed_seconds: 平均耗时
            - category_breakdown: {category: {count, success_rate, ...}}
            - task_details: 每个结果的详细信息
            - arm_breakdown: {arm: {count, success_rate, consistency_rate, ...}}（多 arm 时）
            - consistency_rate: 全局数值结果一致率
            - token_total / token_prompt / token_completion: 全局 token 汇总
        """
        total = len(self.results)
        if total == 0:
            return {
                "total": 0,
                "completed": 0,
                "succeeded": 0,
                "completion_rate": 0.0,
                "success_rate": 0.0,
                "avg_retry_count": 0.0,
                "avg_elapsed_seconds": 0.0,
                "category_breakdown": {},
                "task_details": [],
                "arm_breakdown": {},
                "consistency_rate": 0.0,
                "template_hit_rate": 0.0,
                "token_total": 0,
                "token_prompt": 0,
                "token_completion": 0,
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

        # ── 按 arm 分组统计 ──
        arm_breakdown: dict = {}
        arms: dict[str, list[BenchmarkResult]] = {}
        for r in self.results:
            arm = getattr(r, "arm", "routing_on")
            if arm not in arms:
                arms[arm] = []
            arms[arm].append(r)

        for arm, arm_results in arms.items():
            arm_stats = self._compute_arm_stats(arm_results)
            arm_breakdown[arm] = arm_stats

        # ── 全局一致率 ──
        consistency_rate = self._compute_consistency_rate(self.results)

        # ── 全局 template_hit_rate ──
        template_hit_rate = self._compute_template_hit_rate(self.results)

        # ── Token 汇总 ──
        token_total = 0
        token_prompt = 0
        token_completion = 0
        for r in self.results:
            tu = getattr(r, "token_usage", None) or {}
            token_prompt += tu.get("prompt_tokens", 0)
            token_completion += tu.get("completion_tokens", 0)
            token_total += tu.get("total_tokens", 0)

        # ── 任务详情 ──
        task_details = []
        for r in self.results:
            detail: dict = {
                "task_id": r.task_id,
                "success": r.success,
                "completed": r.completed,
                "retry_count": r.retry_count,
                "elapsed_seconds": round(r.elapsed_seconds, 2),
                "error": r.error,
                "output_keywords_found": r.output_keywords_found,
                "template_keywords_found": r.template_keywords_found,
                "run_index": r.run_index,
                "arm": r.arm,
                "needs_manual_review": r.needs_manual_review,
            }
            if r.token_usage is not None:
                detail["token_usage"] = r.token_usage
            if r.numeric_value is not None:
                detail["numeric_value"] = r.numeric_value
            task_details.append(detail)

        return {
            "total": total,
            "completed": completed,
            "succeeded": succeeded,
            "completion_rate": round(completed / total, 2),
            "success_rate": round(succeeded / total, 2),
            "avg_retry_count": round(sum(retries) / total, 2),
            "avg_elapsed_seconds": round(sum(elapsed) / total, 2),
            "category_breakdown": category_breakdown,
            "task_details": task_details,
            "arm_breakdown": arm_breakdown,
            "consistency_rate": consistency_rate,
            "template_hit_rate": template_hit_rate,
            "token_total": token_total,
            "token_prompt": token_prompt,
            "token_completion": token_completion,
        }

    # ── 辅助方法 ──────────────────────────────────────────

    def _compute_arm_stats(self, results: list[BenchmarkResult]) -> dict:
        """计算单个 arm 的统计指标。

        Args:
            results: 同一 arm 的全部结果。

        Returns:
            包含 count / success_rate / completion_rate / avg_retry / avg_elapsed
            / consistency_rate / token_total / token_prompt / token_completion 的字典。
        """
        total = len(results)
        if total == 0:
            return {
                "count": 0,
                "success_rate": 0.0,
                "completion_rate": 0.0,
                "avg_retry_count": 0.0,
                "avg_elapsed_seconds": 0.0,
                "consistency_rate": 0.0,
                "token_total": 0,
                "token_prompt": 0,
                "token_completion": 0,
            }

        completed = sum(1 for r in results if r.completed)
        succeeded = sum(1 for r in results if r.success)
        retries = [r.retry_count for r in results]
        elapsed = [r.elapsed_seconds for r in results]
        consistency = self._compute_consistency_rate(results)
        tpl_hit_rate = self._compute_template_hit_rate(results)

        token_total = 0
        token_prompt = 0
        token_completion = 0
        for r in results:
            tu = getattr(r, "token_usage", None) or {}
            token_total += tu.get("total_tokens", 0)
            token_prompt += tu.get("prompt_tokens", 0)
            token_completion += tu.get("completion_tokens", 0)

        return {
            "count": total,
            "success_rate": round(succeeded / total, 2),
            "completion_rate": round(completed / total, 2),
            "avg_retry_count": round(sum(retries) / total, 2),
            "avg_elapsed_seconds": round(sum(elapsed) / total, 2),
            "consistency_rate": consistency,
            "template_hit_rate": tpl_hit_rate,
            "token_total": token_total,
            "token_prompt": token_prompt,
            "token_completion": token_completion,
        }

    def _compute_consistency_rate(self, results: list[BenchmarkResult]) -> float:
        """计算数值结果一致率。

        按 (task_id, arm) 分组，每组内有效数值偏差在 ±5% 内的比例。

        Args:
            results: 结果列表。

        Returns:
            0.0~1.0 的一致率。
        """
        from collections import defaultdict

        # 按 (task_id, arm) 分组
        groups: dict[tuple[str, str], list[float]] = defaultdict(list)
        for r in results:
            nv = getattr(r, "numeric_value", None)
            if nv is not None:
                key = (r.task_id, r.arm)
                groups[key].append(nv)

        if not groups:
            return 0.0

        total_pairs = 0
        consistent_pairs = 0

        for values in groups.values():
            if len(values) < 2:
                continue
            # 排序取中位数作为参考
            sorted_vals = sorted(values)
            median_idx = len(sorted_vals) // 2
            reference = sorted_vals[median_idx]
            total_pairs += len(values)
            for v in values:
                if reference == 0:
                    if v == 0:
                        consistent_pairs += 1
                else:
                    deviation = abs(v - reference) / abs(reference)
                    if deviation <= 0.05:
                        consistent_pairs += 1

        if total_pairs == 0:
            return 0.0
        return round(consistent_pairs / total_pairs, 2)

    def _compute_template_hit_rate(self, results: list[BenchmarkResult]) -> float:
        """计算机制词命中率（template_hit_rate）。

        每个有机制词任务计 1 分（该结果中命中 ≥1 个机制词即得分），
        除以总结果数。用于量化规则路由命中率。

        Args:
            results: 结果列表。

        Returns:
            0.0~1.0 的命中率。
        """
        if not results:
            return 0.0

        any_hit = sum(
            1 for r in results
            if len(getattr(r, "template_keywords_found", [])) > 0
        )
        return round(any_hit / len(results), 2)

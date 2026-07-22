"""测试对抗任务集。

验证：
- get_adversarial_tasks() 返回 7 个任务
- 所有任务字段正确
- 任务 ID 唯一，前缀为 ADV-
- 验证不修改 get_default_tasks()
"""

from __future__ import annotations

import pytest

from src.benchmark.tasks import get_default_tasks, get_adversarial_tasks
from src.benchmark.models import BenchmarkTask


class TestAdversarialTasks:
    """对抗任务集测试。"""

    def test_returns_7_tasks(self) -> None:
        """返回 7 个对抗任务。"""
        tasks = get_adversarial_tasks()
        assert len(tasks) == 7

    def test_does_not_modify_default(self) -> None:
        """不修改 get_default_tasks() 的结果。"""
        default_before = get_default_tasks()
        adv = get_adversarial_tasks()
        default_after = get_default_tasks()

        assert len(default_before) == 10
        assert len(default_after) == 10
        assert len(adv) == 7
        # 默认任务集中不含 ADV- 前缀
        for t in default_after:
            assert not t.id.startswith("ADV-")

    def test_all_ids_unique(self) -> None:
        """所有任务 ID 唯一。"""
        tasks = get_adversarial_tasks()
        ids = [t.id for t in tasks]
        assert len(ids) == len(set(ids))

    def test_all_ids_have_adv_prefix(self) -> None:
        """所有任务 ID 以 ADV- 开头。"""
        tasks = get_adversarial_tasks()
        for t in tasks:
            assert t.id.startswith("ADV-"), f"{t.id} 不以前缀 ADV- 开头"

    def test_all_categories_are_adversarial(self) -> None:
        """所有 category 为 adversarial。"""
        tasks = get_adversarial_tasks()
        for t in tasks:
            assert t.category == "adversarial", f"{t.id} category={t.category}"

    def test_eoq_variants_have_eoq_keywords(self) -> None:
        """ADV-01~05 预期关键词包含 EOQ 和 223。"""
        tasks = get_adversarial_tasks()
        for t in tasks[:5]:
            assert "EOQ" in t.expected_keywords
            assert "223" in t.expected_keywords
            assert t.timeout == 30

    def test_fallback_tasks_have_correct_keywords(self) -> None:
        """ADV-06 回文，ADV-07 折扣计算。"""
        adv06 = [t for t in get_adversarial_tasks() if t.id == "ADV-06"][0]
        adv07 = [t for t in get_adversarial_tasks() if t.id == "ADV-07"][0]

        assert "回文" in adv06.expected_keywords or "palindrome" in adv06.expected_keywords
        assert "190" in adv07.expected_keywords or "最终" in adv07.expected_keywords

    def test_all_queries_non_empty(self) -> None:
        """所有 query 非空。"""
        for t in get_adversarial_tasks():
            assert t.query.strip(), f"{t.id} query 为空"

    def test_all_keywords_range_2_to_5(self) -> None:
        """所有 expected_keywords 数量在 2-5 之间。"""
        for t in get_adversarial_tasks():
            assert 2 <= len(t.expected_keywords) <= 5, (
                f"{t.id} 关键词数量={len(t.expected_keywords)}"
            )

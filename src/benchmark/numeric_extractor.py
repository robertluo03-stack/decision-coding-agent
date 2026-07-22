"""数值结果提取器。

从任务执行输出（execution_result）中提取核心数值，用于对比同一任务的多次执行结果。

仅对含确定性数值结果的任务进行提取（EOQ、安全库存、补货点、需求预测）。
其他任务返回 None。

用法:
    from src.benchmark.numeric_extractor import extract_numeric_value, compute_consistency

    value = extract_numeric_value("CG-01", "EOQ = 223.61, 年订货次数 = 4.47")
    # → 223.61

    values = [223.61, 224.01, 220.15]
    consistent, mean_val = compute_consistency(values)
    # → (2, 222.59)
"""

from __future__ import annotations

import math
import re


def extract_numeric_value(task_id: str, execution_result: str) -> float | None:
    """从执行输出中提取核心数值。

    根据 task_id 前缀选择不同的提取策略：
    - CG-01 / ADV-01~05 (EOQ 类): 匹配 EOQ/eoq/经济订货批量 周围的数值
    - CG-02 (需求预测): 匹配 forecasts 后的数值
    - CG-03 (安全库存): 匹配 安全库存 周围的数值
    - CG-04 (补货点): 匹配 补货点/reorder_point/ROP 周围的数值
    - 其他: 返回 None

    Args:
        task_id: 任务 ID（如 "CG-01", "ADV-03"）。
        execution_result: executor 返回的 stdout 文本。

    Returns:
        提取到的数值（float），或 None。
    """
    if not execution_result:
        return None

    text = execution_result
    task_upper = task_id.upper()

    # ── EOQ 类（CG-01 / ADV-01~05） ──
    if task_upper.startswith("CG-01") or task_upper.startswith("ADV") and task_upper not in ("ADV-06", "ADV-07"):
        # 优先匹配 "EOQ = 223.61" 模式
        m = re.search(r'(?:e?e?o?q?|经济订货批量|订货批量)\s*[=:＝:：]?\s*(\d+\.?\d*)', text, re.IGNORECASE)
        if m:
            return _to_float(m.group(1))
        # 回退：取第一段包含 "订货" 或 "EOQ" 行中的第一个数值
        for line in text.split("\n"):
            if re.search(r'eoq|经济订货|订货批', line, re.IGNORECASE):
                nums = re.findall(r'\d+\.?\d*', line)
                for n in nums:
                    f = float(n)
                    # EOQ 通常在 100-10000 范围内
                    if 50 < f < 50000:
                        return f
        return None

    # ── 需求预测（CG-02） ──
    if task_upper.startswith("CG-02"):
        # 匹配 forecasts / 预测值 / 预测 后的数值序列，取第一个
        m = re.search(
            r'(?:forecasts|预测值|预测结果|预测)\s*[=:＝:：\[\]]*\s*\[?\s*(\d+\.?\d*)',
            text, re.IGNORECASE,
        )
        if m:
            return _to_float(m.group(1))
        return None

    # ── 安全库存（CG-03） ──
    if task_upper.startswith("CG-03"):
        # 匹配 safety_stock / 安全库存 / safety stock 后的数值
        m = re.search(
            r'(?:safety_?stock|安全库存)\s*[=:＝:：]?\s*(\d+\.?\d*)',
            text, re.IGNORECASE,
        )
        if m:
            return _to_float(m.group(1))
        return None

    # ── 补货点（CG-04） ──
    if task_upper.startswith("CG-04"):
        # 匹配 reorder_point / 补货点 / ROP 后的数值
        m = re.search(
            r'(?:reorder_?point|补货点|ROP)\s*[=:＝:：]?\s*(\d+\.?\d*)',
            text, re.IGNORECASE,
        )
        if m:
            return _to_float(m.group(1))
        return None

    return None


def compute_consistency(values: list[float | None]) -> tuple[int, float | None]:
    """计算多次运行结果的一致率。

    一致判定：同一任务多次运行的结果在 ±5% 范围内。
    排序后取中位数作为参考值，其他值与参考值比较。

    Args:
        values: 多次运行提取到的数值列表（可能含 None）。

    Returns:
        (consistent_count, mean_value)。
        consistent_count: 与参考值（中位数）偏差在 ±5% 内的次数。
        mean_value: 所有有效数值的平均值（无有效值时为 None）。
    """
    valid = [v for v in values if v is not None]
    if not valid:
        return 0, None

    # 取中位数作为参考值（比均值更抗 outlier）
    sorted_vals = sorted(valid)
    median_idx = len(sorted_vals) // 2
    reference = sorted_vals[median_idx]

    consistent = 0
    for v in valid:
        if reference == 0:
            if v == 0:
                consistent += 1
        else:
            deviation = abs(v - reference) / abs(reference)
            if deviation <= 0.05:  # ±5%
                consistent += 1

    mean_val = sum(valid) / len(valid)
    return consistent, round(mean_val, 4)


# ── 内部辅助 ──────────────────────────────────────────────────


def _to_float(s: str) -> float | None:
    """字符串 → float，容错。"""
    try:
        return float(s.strip())
    except (ValueError, TypeError):
        return None

"""Benchmark 任务集与指标收集框架。

提供 BenchmarkTask / BenchmarkResult 数据模型、10 个预定义任务、
以及 MetricsCollector 指标计算器。
"""

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.benchmark.tasks import get_default_tasks
from src.benchmark.metrics import MetricsCollector

__all__ = ["BenchmarkRunner", "BenchmarkTask", "MetricsCollector"]

# BenchmarkRunner 别名（预留扩展点，当前由 graph.run() 驱动）
BenchmarkRunner = object

"""Benchmark 任务集与指标收集框架。

提供 BenchmarkTask / BenchmarkResult 数据模型、10 个预定义任务、
MetricsCollector 指标计算器、以及 BenchmarkRunner 执行引擎。
"""

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.benchmark.tasks import get_default_tasks
from src.benchmark.metrics import MetricsCollector
from src.benchmark.runner import BenchmarkRunner

__all__ = ["BenchmarkRunner", "BenchmarkTask", "MetricsCollector"]

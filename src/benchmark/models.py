"""Benchmark 数据模型。

BenchmarkTask   — 单个 benchmark 任务定义
BenchmarkResult — 单次执行结果
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class BenchmarkTask:
    """Benchmark 任务定义。

    Attributes:
        id: 任务唯一标识（如 "BA-01"）。
        category: 任务类别（data_analysis | code_generation）。
        query: 自然语言需求（传给 Agent）。
        expected_keywords: 预期输出中应包含的关键词（用于自动验证）。
        timeout: 执行超时时间（秒），默认 60。
        data_files: 依赖的数据文件（相对于 workspace/data/），None 表示不依赖文件。
    """

    id: str
    category: Literal["data_analysis", "code_generation"]
    query: str
    expected_keywords: list[str]
    timeout: int = 60
    data_files: list[str] | None = None


@dataclass
class BenchmarkResult:
    """单次 Benchmark 执行结果。

    Attributes:
        task_id: 对应 BenchmarkTask.id。
        success: 是否所有 expected_keywords 都在输出中出现。
        completed: 是否正常完成（无 LLM 调用失败 / timeout）。
        retry_count: Debugger 重试次数。
        elapsed_seconds: 总执行耗时。
        error: 错误信息（None 表示无错误）。
        output_keywords_found: 实际找到的 expected_keywords 子集。
        report_path: 生成的报告文件路径（None 表示无报告）。
    """

    task_id: str
    success: bool = False
    completed: bool = False
    retry_count: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    output_keywords_found: list[str] = field(default_factory=list)
    report_path: str | None = None

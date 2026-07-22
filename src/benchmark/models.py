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
        category: 任务类别（data_analysis | code_generation | adversarial）。
        query: 自然语言需求（传给 Agent）。
        expected_keywords: 预期输出中应包含的结果关键词（全部命中 ⇒ success）。
            — 结果词：任何正确完成任务的系统都应产出（数值、领域术语、数据引用）。
        template_keywords: 预期输出中应包含的模板机制关键词（不计入 success，
            单独统计 template_hit_rate，用于量化规则路由命中率）。
            — 机制词：只有本项目模板/函数才会产出（函数名、模块名、属性名）。
        timeout: 执行超时时间（秒），默认 60。
        data_files: 依赖的数据文件（相对于 workspace/data/），None 表示不依赖文件。
        needs_manual_review: 标记任务需要人工复核（如结果词过少、语言依赖等）。
    """

    id: str
    category: Literal["data_analysis", "code_generation", "adversarial"]
    query: str
    expected_keywords: list[str]
    template_keywords: list[str] = field(default_factory=list)
    timeout: int = 60
    data_files: list[str] | None = None
    needs_manual_review: bool = False


@dataclass
class BenchmarkResult:
    """单次 Benchmark 执行结果。

    Attributes:
        task_id: 对应 BenchmarkTask.id。
        success: 是否所有 expected_keywords（结果词）都在输出中出现。
        completed: 是否正常完成（无 LLM 调用失败 / timeout）。
        retry_count: Debugger 重试次数。
        elapsed_seconds: 总执行耗时。
        error: 错误信息（None 表示无错误）。
        output_keywords_found: 实际找到的 expected_keywords（结果词）子集。
        template_keywords_found: 实际找到的 template_keywords（机制词）子集。
        report_path: 生成的报告文件路径（None 表示无报告）。
        run_index: 重复运行序号（1-based，默认 1）。
        arm: 实验臂名称（"routing_on" | "routing_off"）。
        token_usage: Token 用量 {prompt_tokens, completion_tokens, total_tokens}。
        numeric_value: 从执行结果中提取的核心数值（None 表示无）。
        needs_manual_review: 标记需要人工复核。
    """

    task_id: str
    success: bool = False
    completed: bool = False
    retry_count: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    output_keywords_found: list[str] = field(default_factory=list)
    template_keywords_found: list[str] = field(default_factory=list)
    report_path: str | None = None
    run_index: int = 1
    arm: str = "routing_on"
    token_usage: dict | None = None
    numeric_value: float | None = None
    needs_manual_review: bool = False

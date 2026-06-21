"""Planner 节点：将用户自然语言需求拆解为执行计划步骤列表。"""

import os
import re

from src.agent.state import AgentState


# Prompt template for the planner (embedded from src/agent/prompts/planner.md)
_PLANNER_SYSTEM_PROMPT = """你是一个经营决策分析专家。你的任务是将用户的自然语言需求拆解为清晰的执行计划步骤。

## 背景

用户可能提出以下类型的需求：
- 数据分析（读取文件、清洗、分析、可视化）
- 库存优化（EOQ、安全库存、补货点计算）
- 需求预测（移动平均、指数平滑）
- Python 代码生成和执行

## 输出格式

严格返回步骤列表，每行一个步骤，格式为 "N. 步骤描述"。
步骤应该具体、可执行。不要包含任何解释、前言或后记。

## 示例

用户: 帮我分析 sales.csv 的销售趋势
1. 读取 sales.csv 文件
2. 检查数据质量（缺失值、异常值）
3. 计算月度销售汇总
4. 绘制销售趋势图
5. 生成分析报告

## 约束

- 步骤不超过 5 个
- 每个步骤只做一件事
- 最后一步始终是"生成报告"
"""


def planner_node(state: AgentState) -> dict:
    """解析用户需求，使用 DeepSeek API 生成执行计划。

    Args:
        state: 当前 AgentState，包含 user_query 和 workspace_path

    Returns:
        包含 plan 字段的 partial state，格式: {"plan": ["步骤1", "步骤2", ...]}
    """
    query = state["user_query"]

    # 空输入检查
    if not query or not query.strip():
        return {"plan": ["错误：输入为空"]}

    try:
        plan = _generate_plan_with_llm(query)
    except Exception as exc:
        plan = [f"错误：Planner 调用失败 — {exc}"]

    return {"plan": plan}


def _generate_plan_with_llm(query: str) -> list[str]:
    """使用 DeepSeek API 生成计划。

    Args:
        query: 用户自然语言需求

    Returns:
        执行步骤字符串列表，最多 5 个

    Raises:
        ValueError: 环境变量 DEEPSEEK_API_KEY 未设置时抛出
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("环境变量 DEEPSEEK_API_KEY 未设置")

    from langchain_deepseek import ChatDeepSeek

    llm = ChatDeepSeek(
        model="deepseek-chat",
        api_key=api_key,
        temperature=0.3,
    )

    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": f"用户需求: {query}\n\n请生成执行计划："},
    ]

    response = llm.invoke(messages)
    content = response.content.strip()

    return _parse_plan_response(content)


def _parse_plan_response(content: str) -> list[str]:
    """从 LLM 返回文本中提取步骤列表。

    优先匹配 "N. 描述" 格式的行；若未匹配到编号步骤，
    则回退为逐行非空文本作为步骤；若仍无结果则整体作为单一步骤。

    Args:
        content: LLM 原始响应文本

    Returns:
        解析后的步骤列表，最多 5 个
    """
    lines = content.strip().split("\n")
    steps: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 匹配 "1. xxx", "2. xxx", "N. xxx" 格式
        match = re.match(r"^\d+\.\s*(.+)", line)
        if match:
            steps.append(match.group(1).strip())

    # 回退：如果没有匹配到编号步骤，将长度 > 3 的非空行当作步骤
    if not steps:
        for line in lines:
            line = line.strip()
            if line and len(line) > 3:
                steps.append(line)

    # 最终回退：整个内容作为一个步骤
    if not steps:
        steps = [content]

    # 约束：最多 5 个步骤
    if len(steps) > 5:
        steps = steps[:5]

    return steps


# 别名，兼容 graph.py / Task 7 的 run(state) 约定
run = planner_node

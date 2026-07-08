"""Planner 节点：将用户自然语言需求拆解为执行计划步骤列表。"""

import hashlib
import os
import re

from loguru import logger

from src.agent.state import AgentState
from src.agent.nodes.prompts.loader import load_prompt
from src.agent.nodes.prompts.planner_user import build_planner_user_message


def planner_node(state: AgentState) -> dict:
    """解析用户需求，使用 DeepSeek API 生成执行计划。

    Args:
        state: 当前 AgentState，包含 user_query 和 workspace_path

    Returns:
        包含 plan 字段的 partial state，格式: {"plan": ["步骤1", "步骤2", ...]}
    """
    query = state["user_query"]

    # ---- 入口日志 ----
    logger.info(
        "[Planner] 进入节点 | user_query={!r} | plan={} | retry_count={}",
        query[:50],
        len(state.get("plan", [])),
        state.get("retry_count", 0),
    )

    # 空输入检查
    if not query or not query.strip():
        logger.warning("[Planner] 输入为空，返回错误计划")
        return {"plan": ["错误：输入为空"]}

    try:
        plan = _generate_plan_with_llm(query)
    except Exception as exc:
        logger.error("[Planner] LLM 调用异常 | type={} | message={}", type(exc).__name__, exc)
        plan = [f"错误：Planner 调用失败 — {exc}"]

    # ---- 出口日志 ----
    logger.info(
        "[Planner] 退出节点 | plan_steps={} | steps={!r}",
        len(plan),
        plan,
    )

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
        logger.error("[Planner] DEEPSEEK_API_KEY 未设置")
        raise ValueError("环境变量 DEEPSEEK_API_KEY 未设置")

    from langchain_deepseek import ChatDeepSeek

    llm = ChatDeepSeek(
        model="deepseek-chat",
        api_key=api_key,
        temperature=0.3,
        request_timeout=120,
        max_retries=2,
    )

    messages = [
        {"role": "system", "content": load_prompt("planner.md")},
        {"role": "user", "content": build_planner_user_message(query)},
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

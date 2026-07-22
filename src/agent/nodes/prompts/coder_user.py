"""Coder user message builder.

Supports rule-based template routing: when a high-confidence template match
is detected, the matched template type, confidence, and extracted parameters
are injected into the user message to guide the LLM toward calling the
corresponding domain template function directly.
"""


# ---------------------------------------------------------------------------
# 模板引导信息表
# ---------------------------------------------------------------------------
# Map template_type value to (display_name, import_and_call_guidance)
# The guidance text instructs the LLM to use the exact domain template function.

_TEMPLATE_GUIDANCE: dict[str, tuple[str, str]] = {
    "eoq": (
        "经济订货批量 (EOQ)",
        "必须调用 `src.domain.templates.inventory_eoq` 的 `calculate(EOQParams(...))` 函数，"
        "不要手写 math.sqrt 公式。"
        "模板用法：\n"
        "```python\n"
        "from src.domain.templates.inventory_eoq import calculate, EOQParams\n"
        "result = calculate(EOQParams(annual_demand=D, ordering_cost=S, holding_cost=H))\n"
        "print(f\"经济订货批量（EOQ）= {result.eoq:.2f} 件\")\n"
        "print(f\"年订货次数 = {result.annual_orders:.2f} 次\")\n"
        "print(f\"年总成本 = ¥{result.total_cost:.2f}\")\n"
        "```",
    ),
    "forecast": (
        "需求预测 (Demand Forecast)",
        "必须调用 `src.domain.templates.demand_forecast` 的 `forecast(ForecastParams(...))` 或 "
        "`auto_forecast(history, periods=N)` 函数。",
    ),
    "safety_stock": (
        "安全库存 (Safety Stock)",
        "必须调用 `src.domain.templates.safety_stock` 的 "
        "`calculate_safety_stock(SafetyStockParams(...))` 函数。",
    ),
    "reorder_point": (
        "补货点 (Reorder Point / ROP)",
        "必须调用 `src.domain.templates.reorder_point` 的 "
        "`calculate(ROPParams(...))` 函数。",
    ),
    "data_analysis": (
        "一键数据分析 (Data Analysis)",
        "优先调用 `src.domain.templates.data_analysis` 的 `run_analysis(file_path)` 函数。",
    ),
}


def build_coder_user_message(
    query: str,
    plan: list[str],
    template_match: dict | None = None,
    extracted_params: dict[str, float] | None = None,
) -> str:
    """Build the user message for the Coder LLM call.

    When template_match is provided with a non-UNKNOWN template_type,
    injects rule-based routing guidance into the message to steer the
    LLM toward calling the corresponding domain template function.

    Args:
        query: 用户原始自然语言需求
        plan: 执行计划步骤列表
        template_match: 可选，规则路由匹配结果（含 template_type, confidence）。
            为 None 或 template_type=="unknown" 时行为与原有完全一致。
        extracted_params: 可选，从 query 中提取的 {参数名: 数值} 字典。

    Returns:
        Formatted user message string.
    """
    plan_lines = "\n".join(
        f"{i + 1}. {step}" for i, step in enumerate(plan)
    )

    # ---- 基础消息（与原有完全一致） ----
    base_message = (
        f"用户需求：{query}\n\n"
        f"执行计划：\n{plan_lines}\n\n"
        f"请按照上述计划生成完整的 Python 代码。"
        f"数据文件放在 ./data/ 目录下，使用相对路径读取。"
        f"输出结果请用 print() 打印。"
    )

    # ---- 规则路由信息注入 ----
    if template_match is not None and template_match.get("template_type", "unknown") != "unknown":
        guidance = _build_routing_guidance(template_match, extracted_params)
        if guidance:
            return base_message + "\n\n" + guidance

    return base_message


def _build_routing_guidance(
    template_match: dict,
    extracted_params: dict[str, float] | None,
) -> str:
    """Build the rule-based routing guidance block to inject into the user message.

    Args:
        template_match: dict with keys template_type (str), confidence (float).
        extracted_params: dict of param_name → float value, or None.

    Returns:
        Guidance block string, or empty string if template is unknown.
    """
    template_type = template_match.get("template_type", "unknown")
    confidence = template_match.get("confidence", 0.0)

    entry = _TEMPLATE_GUIDANCE.get(template_type)
    if entry is None:
        return ""

    display_name, call_guidance = entry

    parts: list[str] = []
    parts.append("【规则路由信息 — 以下信息来自规则引擎，请严格遵循】")
    parts.append("")
    parts.append(f"- 识别到的任务类型：{display_name}")
    parts.append(f"- 置信度：{confidence:.1f}")
    parts.append("")

    # Show extracted parameters
    if extracted_params:
        parts.append("已从用户输入中提取的参数（直接使用，无需重新提取）：")
        parts.append("```")
        for name, value in extracted_params.items():
            parts.append(f"  {name} = {value}")
        parts.append("```")
        parts.append("")
    else:
        parts.append("（未提取到参数，请从用户输入中自行解析）")
        parts.append("")

    parts.append("模板调用指引：")
    parts.append(call_guidance)
    parts.append("")

    return "\n".join(parts)

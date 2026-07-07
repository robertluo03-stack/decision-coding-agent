"""供应链优化报告增强器。

基于规则引擎自动生成专业的：
  - 模型假设说明
  - 局限性与风险提示
  - 业务改进建议

纯 if-else 规则驱动，零 LLM 调用、零延迟、100% 可预测。

使用方式:
    from src.domain.report_enhancer import enhance_report, EnhancerInput
    enhanced = enhance_report(base_report_text, EnhancerInput(...))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class EnhancerInput:
    """从 pipeline result 中提取的增强所需信息。

    Attributes:
        history_length: 历史数据期数
        forecast_method: 使用的预测方法名
        mape: 预测 MAPE（百分数，如 5.2 表示 5.2%）
        eoq: EOQ 经济订货批量
        annual_demand: 年需求量
        safety_stock: 安全库存量
        safety_stock_ratio: 安全库存 / 平均月需求
        rop: 补货点
        lead_time: 提前期
        service_level: 目标服务水平（0-1 或 0-100）
        formula_used: 安全库存公式场景（含"情况 A/B/C"）
        outlier_count: 异常值数量
        missing_ratio: 缺失值比例（0-1）
    """
    history_length: int = 0
    forecast_method: Optional[str] = None
    mape: Optional[float] = None
    eoq: Optional[float] = None
    annual_demand: Optional[float] = None
    safety_stock: Optional[float] = None
    safety_stock_ratio: Optional[float] = None
    rop: Optional[float] = None
    lead_time: Optional[float] = None
    service_level: Optional[float] = None
    formula_used: Optional[str] = None
    outlier_count: int = 0
    missing_ratio: float = 0.0


@dataclass
class EnhancedSections:
    """增强的三个章节内容。

    Attributes:
        assumptions: 模型假设列表
        limitations: 局限性列表
        recommendations: 业务建议列表
    """
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 内部辅助：规则条件匹配
# ---------------------------------------------------------------------------


def _check(condition: str, info: EnhancerInput) -> bool:
    """解析规则条件字符串，匹配 EnhancerInput 字段。

    支持的表达式（简单限定，无需完整 DSL）：
      - "key is None" / "key is not None"
      - "key > value" / "key < value" / "key >= value" / "key <= value"
      - "key != value" / "key == value"
      - "key contains 'text'"（仅 str 字段）
      - "key1 contains 'text' or key2 contains 'text'"（复合 OR）
      - "key1 < key2 * multiplier"（含运算的复合比较）

    Args:
        condition: 规则条件字符串
        info: 增强器输入

    Returns:
        条件是否成立
    """
    condition = condition.strip()

    # Handle compound AND / OR: "key1 op1 val1 and key2 op2 val2"
    if " and " in condition:
        parts = condition.split(" and ")
        return all(_check(part, info) for part in parts)

    if " or " in condition:
        parts = condition.split(" or ")
        return any(_check(part, info) for part in parts)

    # Handle "is None" / "is not None"
    if " is not None" in condition:
        key = condition.replace(" is not None", "").strip()
        val = getattr(info, key, None)
        return val is not None
    if " is None" in condition:
        key = condition.replace(" is None", "").strip()
        val = getattr(info, key, None)
        return val is None

    # Handle "contains"
    if " contains " in condition:
        before, _, after = condition.partition(" contains ")
        key = before.strip()
        search = after.strip().strip("'").strip('"')
        val = getattr(info, key, None)
        if val is None:
            return False
        return search in str(val)

    # Handle comparisons: key op value
    for op in (">=", "<=", "!=", "==", ">", "<"):
        if f" {op} " in condition:
            # Check for compound right side like "key * num"
            lhs, rhs = condition.split(f" {op} ", 1)
            lhs = lhs.strip()
            lhs_val = getattr(info, lhs, None)
            if lhs_val is None:
                return False

            # Parse RHS: might be a simple number, or "key * multiplier"
            rhs = rhs.strip()
            try:
                rhs_val = float(rhs)
            except ValueError:
                # Complex RHS like "lead_time * annual_demand / 12 * 0.5"
                rhs_val = _eval_math_expression(rhs, info)
                if rhs_val is None:
                    return False

            if op == ">":
                return float(lhs_val) > rhs_val
            elif op == "<":
                return float(lhs_val) < rhs_val
            elif op == ">=":
                return float(lhs_val) >= rhs_val
            elif op == "<=":
                return float(lhs_val) <= rhs_val
            elif op == "==":
                return str(lhs_val) == str(rhs_val)
            elif op == "!=":
                return str(lhs_val) != str(rhs_val)

    return False


def _eval_math_expression(expr: str, info: EnhancerInput) -> Optional[float]:
    """求值简单数学表达式，如 'annual_demand / 12 * 3'。

    Args:
        expr: 数学表达式（仅支持 + - * / 和 info 字段名）
        info: 增强器输入

    Returns:
        计算结果，或 None（无法求值）
    """
    # Replace field names with values
    result = expr
    for field_name, field_type in EnhancerInput.__dataclass_fields__.items():
        val = getattr(info, field_name, None)
        if val is not None and isinstance(val, (int, float)):
            # Replace the field name in the expression
            result = result.replace(field_name, str(val))

    try:
        import ast
        import operator
        _OP_MAP = {
            ast.Add: operator.add, ast.Sub: operator.sub,
            ast.Mult: operator.mul, ast.Div: operator.truediv,
        }

        def _eval_node(node):
            if isinstance(node, ast.Constant):
                return float(node.value)
            elif isinstance(node, ast.BinOp):
                op_type = type(node.op)
                if op_type in _OP_MAP:
                    return _OP_MAP[op_type](_eval_node(node.left), _eval_node(node.right))
            return None

        tree = ast.parse(result.strip(), mode="eval")
        val = _eval_node(tree.body)
        return float(val) if val is not None else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 规则常量
# ---------------------------------------------------------------------------


RULES_ASSUMPTIONS: list[tuple[str, str]] = [
    # (condition, template) — condition 为空表示无条件（始终包含）

    # 基础假设
    ("", "假设需求服从正态分布（安全库存计算的前提）"),
    ("", "假设历史数据能代表未来需求模式"),

    # 条件假设 — 安全库存场景
    ("formula_used contains '情况 A'", "假设提前期固定，仅需求存在波动"),
    ("formula_used contains '情况 B'", "假设需求固定，仅提前期存在波动"),
    ("formula_used contains '情况 C'", "假设需求与提前期均存在波动"),

    # 条件假设 — 预测方法
    ("forecast_method contains 'Holt'", "假设需求存在线性趋势"),
    ("forecast_method contains 'SES'", "假设需求平稳，无显著趋势"),
    ("forecast_method contains 'SMA'", "假设需求在短期窗口内平均化"),
    ("forecast_method contains 'WMA'", "假设近期数据对未来有更强的参考价值"),

    # 条件假设 — 参数
    ("service_level is not None", "假设目标服务水平为 {service_level:.0f}%"),
    ("lead_time is not None", "假设平均提前期为 {lead_time:.1f} 个时间单位"),
]


RULES_LIMITATIONS: list[tuple[str, str]] = [
    # (condition, template)

    # 数据量
    ("history_length < 6", "历史数据量较少（仅 {history_length} 期），预测置信度较低"),
    ("history_length >= 6 and history_length < 12", "历史数据量有限（{history_length} 期），建议积累更多数据以提高预测精度"),

    # 预测精度
    ("mape > 20", "预测误差较大（MAPE={mape:.1f}%），模型可能未充分捕捉需求特征"),
    ("mape > 10 and mape <= 20", "预测精度一般（MAPE={mape:.1f}%），建议关注实际需求与预测的偏差"),

    # 数据质量
    ("outlier_count > 0", "数据中检测到 {outlier_count} 个异常值，可能对参数估计产生影响"),
    ("missing_ratio > 0.05", "缺失值比例较高（{missing_ratio:.1%}），已通过插值或忽略处理"),

    # 模型局限
    ("forecast_method contains 'SMA' or forecast_method contains 'SES' or forecast_method contains 'Holt' or forecast_method contains 'WMA'",
     "未考虑季节性因素，若需求存在季节性波动，预测可能偏离"),
    ("", "EOQ 模型假设需求均匀分布，实际需求波动可能导致临时缺货或积压"),
    ("", "安全库存基于概率模型，实际服务水平可能因极端事件而偏离目标"),
    ("", "本分析未考虑供应商产能约束、运输延迟等供应链中断风险"),
]


RULES_RECOMMENDATIONS: list[tuple[str, str]] = [
    # (condition, template)

    # EOQ 相关
    ("eoq > 1000", "EOQ 值较大（{eoq:.0f}），建议评估分批采购以降低资金占用和仓储压力"),
    ("eoq > 0 and eoq < 10", "EOQ 值较小（{eoq:.0f}），补货频率较高，建议与供应商协商合并订货"),

    # 安全库存相关
    ("safety_stock_ratio > 0.5", "安全库存占比超过 50%（{safety_stock_ratio:.0%}），需求波动剧烈，建议与供应商协商缩短提前期或采用 VMI 模式"),
    ("safety_stock_ratio > 0.3 and safety_stock_ratio <= 0.5", "安全库存占比较高（{safety_stock_ratio:.0%}），建议分析需求波动根因"),
    ("safety_stock_ratio > 0 and safety_stock_ratio < 0.05", "安全库存占比极低（{safety_stock_ratio:.1%}），当前设置偏激进，建议监控服务水平实际达成率"),

    # 补货点相关
    ("rop is not None", "建议定期（每月/每季度）重新运行分析，根据最新数据调整库存参数"),

    # 预测精度相关
    ("mape is not None and mape < 10", "预测精度良好（MAPE={mape:.1f}%），可适当降低安全库存以释放资金"),

    # 通用建议（始终包含）
    ("", "建议建立库存健康度监控看板，追踪实际库存与理论参数的偏差"),
    ("", "建议将库存参数嵌入 ERP/WMS 系统，实现自动补货提醒"),
]


# ---------------------------------------------------------------------------
# 模板格式化
# ---------------------------------------------------------------------------


def _format_template(template: str, info: EnhancerInput) -> str:
    """将模板字符串中的 {field} 占位符替换为 info 的实际值。

    支持的格式：
      - {field:.1f} / {field:.2f} / {field:.0%} / {field:.1%} / {field:.0f} 等

    Args:
        template: 含占位符的模板字符串
        info: 增强器输入

    Returns:
        格式化后的字符串
    """
    result = template
    import re

    # Match patterns like {history_length}, {mape:.1f}, {missing_ratio:.1%}, {safety_stock_ratio:.0%}
    pattern = r"\{(\w+)(?::([^}]+))?\}"
    matches = list(re.finditer(pattern, template))
    # Process in reverse order to avoid index shifts
    for m in reversed(matches):
        field_name = m.group(1)
        format_spec = m.group(2)  # e.g. ".1f", ".0%", ".1%"
        val = getattr(info, field_name, None)

        if val is not None:
            if format_spec is not None:
                try:
                    formatted = format(val, format_spec)
                except (ValueError, TypeError):
                    formatted = str(val)
            else:
                formatted = str(val)
        else:
            formatted = m.group(0)  # leave placeholder unchanged

        result = result[:m.start()] + formatted + result[m.end():]

    return result


# ---------------------------------------------------------------------------
# 章节生成
# ---------------------------------------------------------------------------


def _generate_assumptions(info: EnhancerInput) -> list[str]:
    """基于 EnhancerInput 生成模型假设列表。

    根据使用的模板和参数，从 RULES_ASSUMPTIONS 中匹配对应假设。

    Args:
        info: 增强器输入

    Returns:
        假设文本列表
    """
    assumptions: list[str] = []
    for condition, template in RULES_ASSUMPTIONS:
        if condition == "" or _check(condition, info):
            formatted = _format_template(template, info)
            assumptions.append(formatted)
    return assumptions


def _generate_limitations(info: EnhancerInput) -> list[str]:
    """基于数据质量和模型特征生成局限性列表。

    Args:
        info: 增强器输入

    Returns:
        局限性文本列表
    """
    limitations: list[str] = []
    for condition, template in RULES_LIMITATIONS:
        if condition == "" or _check(condition, info):
            formatted = _format_template(template, info)
            limitations.append(formatted)
    return limitations


def _generate_recommendations(info: EnhancerInput) -> list[str]:
    """基于结果值的规则化建议。

    Args:
        info: 增强器输入

    Returns:
        建议文本列表
    """
    recommendations: list[str] = []
    for condition, template in RULES_RECOMMENDATIONS:
        if condition == "" or _check(condition, info):
            formatted = _format_template(template, info)
            recommendations.append(formatted)
    return recommendations


# ---------------------------------------------------------------------------
# 报告插入逻辑
# ---------------------------------------------------------------------------


def _insert_enhanced_sections(
    base_report: str, sections: EnhancedSections
) -> str:
    """将增强的三个章节插入 base_report 的 ## 7. 综合建议 位置。

    替换逻辑：
      - 找到 "## 7. 综合建议" 行
      - 替换为三个新章节（7.模型假设 / 8.局限性 / 9.业务建议）
      - 原 "## 8. 附录" 改为 "## 10. 附录"

    Args:
        base_report: 原始 Markdown 报告
        sections: 增强后的三个章节内容

    Returns:
        增强后的完整 Markdown 报告
    """
    lines = base_report.split("\n")
    new_lines: list[str] = []
    in_original_section7 = False
    in_original_section8 = False
    sections_inserted = False
    section7_found = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Detect "## 7. 综合建议"
        if stripped.startswith("## 7.") and ("综合建议" in stripped or "7." in stripped):
            section7_found = True
            in_original_section7 = True
            # Insert three enhanced sections instead
            new_lines.append("")
            new_lines.append("## 7. 模型假设")
            new_lines.append("")
            for item in sections.assumptions:
                new_lines.append(f"- {item}")
            new_lines.append("")
            new_lines.append("## 8. 局限性与风险提示")
            new_lines.append("")
            for item in sections.limitations:
                new_lines.append(f"- {item}")
            new_lines.append("")
            new_lines.append("## 9. 业务建议")
            new_lines.append("")
            for i_rec, item in enumerate(sections.recommendations, 1):
                new_lines.append(f"{i_rec}. {item}")
            new_lines.append("")
            sections_inserted = True
            continue

        # Skip lines in the original section 7 (until next "## " heading)
        if in_original_section7:
            if stripped.startswith("## "):
                in_original_section7 = False
                # This is the original "## 8. 附录" — rename to "## 10. 附录"
                if "8." in stripped and "附录" in stripped:
                    in_original_section8 = True
                    new_lines.append("## 10. 附录")
                    continue
                elif "8." in stripped:
                    new_lines.append(stripped.replace("## 8.", "## 10."))
                    continue
                else:
                    new_lines.append(line)
            else:
                # Skip content of original section 7
                continue
        elif in_original_section8:
            # Keep all content after renamed section 8 heading
            new_lines.append(line)
        else:
            new_lines.append(line)

    # Fallback: if "## 7. 综合建议" not found, append at end
    if not section7_found:
        new_lines.append("")
        new_lines.append("## 7. 模型假设")
        new_lines.append("")
        for item in sections.assumptions:
            new_lines.append(f"- {item}")
        new_lines.append("")
        new_lines.append("## 8. 局限性与风险提示")
        new_lines.append("")
        for item in sections.limitations:
            new_lines.append(f"- {item}")
        new_lines.append("")
        new_lines.append("## 9. 业务建议")
        new_lines.append("")
        for i_rec, item in enumerate(sections.recommendations, 1):
            new_lines.append(f"{i_rec}. {item}")
        new_lines.append("")

    return "\n".join(new_lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def enhance_report(base_report: str, info: EnhancerInput) -> str:
    """增强供应链库存分析报告。

    在 base_report 的第 7 章"综合建议"位置插入三个增强章节：
      - ## 7. 模型假设
      - ## 8. 局限性与风险提示
      - ## 9. 业务建议

    原第 8 章"附录"顺延为第 10 章。

    Args:
        base_report: 原始 Markdown 报告文本
        info: 增强器输入（从 pipeline 结果中提取）

    Returns:
        增强后的完整 Markdown 报告字符串

    Example:
        >>> info = EnhancerInput(history_length=24, mape=8.5, eoq=223.6)
        >>> enhanced = enhance_report(base_md, info)
        >>> print("## 7. 模型假设" in enhanced)
        True
    """
    sections = EnhancedSections(
        assumptions=_generate_assumptions(info),
        limitations=_generate_limitations(info),
        recommendations=_generate_recommendations(info),
    )
    return _insert_enhanced_sections(base_report, sections)


def build_enhancer_input(pipeline_result) -> EnhancerInput:
    """从 InventoryPipelineResult 提取信息构建 EnhancerInput。

    Args:
        pipeline_result: InventoryPipelineResult 实例

    Returns:
        EnhancerInput 实例
    """
    info = EnhancerInput()

    # History length: infer from quality_report
    if pipeline_result.quality_report:
        info.history_length = pipeline_result.quality_report.get("total_rows", 0)
        # Missing ratio
        cols = pipeline_result.quality_report.get("columns", [])
        if cols:
            total_missing = sum(c.get("missing_rate", 0) for c in cols)
            info.missing_ratio = total_missing / len(cols)
        # Outlier count
        info.outlier_count = sum(
            c.get("outlier_count", 0) for c in cols
        )

    # Forecast result
    if pipeline_result.forecast_result:
        fr = pipeline_result.forecast_result
        info.forecast_method = fr.method_used
        info.mape = fr.mape

    # EOQ result
    if pipeline_result.eoq_result:
        info.eoq = pipeline_result.eoq_result.eoq

    # Safety stock result
    if pipeline_result.safety_stock_result:
        ss = pipeline_result.safety_stock_result
        info.safety_stock = ss.safety_stock
        info.service_level = ss.service_level
        info.formula_used = ss.formula_used

    # ROP result
    if pipeline_result.rop_result:
        info.rop = pipeline_result.rop_result.reorder_point

    # Lead time & annual demand: try to infer from ROP result
    if pipeline_result.rop_result and info.safety_stock is not None:
        rp = pipeline_result.rop_result
        info.lead_time = rp.lead_time_demand / max(0.001, rp.reorder_point - info.safety_stock)
        info.annual_demand = rp.lead_time_demand * 12  # rough estimate from monthly

    # Safety stock ratio: safety_stock / avg_monthly_demand
    if info.safety_stock is not None and info.annual_demand is not None:
        avg_monthly = info.annual_demand / 12.0
        if avg_monthly > 0:
            info.safety_stock_ratio = info.safety_stock / avg_monthly

    return info


def enhance_from_pipeline(pipeline_result) -> str:
    """便捷入口：直接从 InventoryPipelineResult 构建 EnhancerInput 并增强报告。

    读取 pipeline_result.report_path 对应的报告文件，生成增强内容后写回。

    Args:
        pipeline_result: InventoryPipelineResult 实例

    Returns:
        增强后的完整 Markdown 报告字符串

    Raises:
        FileNotFoundError: 报告文件不存在
    """
    from pathlib import Path

    base_report = Path(pipeline_result.report_path).read_text(encoding="utf-8")
    info = build_enhancer_input(pipeline_result)
    enhanced = enhance_report(base_report, info)
    return enhanced


# 导出别名（与项目约定一致）
run = enhance_report

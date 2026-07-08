#!/usr/bin/env python3
"""
供应链库存优化 Demo —— 从原始数据到决策建议的端到端闭环。

用法:
    python examples/demo_inventory_optimization.py <csv_path> [output_dir]
    python examples/demo_inventory_optimization.py workspace/data/sku_inventory.csv
    python examples/demo_inventory_optimization.py workspace/data/sku_inventory.csv workspace/reports/

不依赖 LLM，纯 Python + 规则引擎。
"""

import os
import sys

# 确保能找到 src 包（从 examples/ 找项目根目录）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.domain.templates.inventory_pipeline import (  # noqa: E402
    run_inventory_pipeline,
    InventoryPipelineParams,
    quick_analyze,
)


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------


def _print_header(text: str) -> None:
    """打印居中分隔标题。"""
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}")


def _print_section(title: str) -> None:
    """打印小标题。"""
    print(f"\n{title}")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main() -> None:
    """命令行入口：解析参数 → 运行流水线 → 打印摘要。"""
    if len(sys.argv) < 2:
        print("用法: python demo_inventory_optimization.py <csv_path> [output_dir]")
        print("示例: python demo_inventory_optimization.py workspace/data/sku_inventory.csv")
        print("      python demo_inventory_optimization.py workspace/data/sku_inventory.csv workspace/reports/")
        print("")
        print("参数说明:")
        print("  csv_path    — 库存需求 CSV 文件路径（必需）")
        print("  output_dir  — 报告输出目录（可选，默认 workspace/reports/）")
        sys.exit(1)

    csv_path: str = sys.argv[1]
    output_dir: str = sys.argv[2] if len(sys.argv) > 2 else "workspace/reports/"

    # 检查文件存在
    if not os.path.exists(csv_path):
        print(f"\n  错误：文件不存在 → {csv_path}")
        sys.exit(1)

    _print_header("供应链库存优化分析")

    print(f"\n  数据文件 : {csv_path}")
    print(f"  输出目录 : {output_dir}")
    print(f"\n  ▶ 正在运行 8 步分析流水线...")

    # Run pipeline
    try:
        result = run_inventory_pipeline(
            InventoryPipelineParams(csv_path=csv_path, output_dir=output_dir)
        )
    except Exception as e:
        print(f"\n  ✕ 流水线执行异常: {e}")
        sys.exit(1)

    if not result.report_path:
        print("\n  ✕ 分析未能完成（CSV 列名校验失败或数据为空）")
        print("    请确认 CSV 包含 month 和 demand 列，或使用 time_col / demand_col 参数指定。")
        sys.exit(1)

    # ---- 摘要输出 ----
    _print_section("📊 分析结果摘要")

    # 数据质量
    if result.quality_report:
        qr = result.quality_report
        print(f"\n  【数据质量】")
        print(f"    综合评分  : {qr['overall_score']}/100")
        total_outliers = sum(c.get("outlier_count", 0) for c in qr.get("columns", []))
        if total_outliers > 0:
            print(f"    异常值数  : {total_outliers} 个（将在报告中标注）")

    # 需求预测
    if result.forecast_result:
        fr = result.forecast_result
        print(f"\n  【需求预测】")
        print(f"    使用方法  : {fr.method_used}")
        print(f"    预测值    : {', '.join(f'{v:.1f}' for v in fr.forecasts)}")
        print(f"    MAPE      : {fr.mape}%")
        if fr.mape < 10:
            print(f"    ▸ 预测精度良好，可信度较高")

    # EOQ
    if result.eoq_result:
        er = result.eoq_result
        print(f"\n  【EOQ 经济订货批量】")
        print(f"    EOQ       : {er.eoq:.1f} 件")
        print(f"    年订货次数: {er.annual_orders:.1f} 次")
        print(f"    年总成本  : {er.total_cost:.2f}")

    # 安全库存
    if result.safety_stock_result:
        ss = result.safety_stock_result
        print(f"\n  【安全库存】")
        print(f"    安全库存量: {ss.safety_stock:.1f} 件")
        print(f"    Z 值      : {ss.z_score}（服务水平 {ss.service_level:.0%}）")

    # 补货点
    if result.rop_result:
        rp = result.rop_result
        print(f"\n  【补货点决策】")
        print(f"    补货点    : {rp.reorder_point:.1f}")
        print(f"    提前期消耗: {rp.lead_time_demand:.1f}")
        print(f"    ▸ {rp.suggestion}")

    # 图表
    if result.charts:
        print(f"\n  【生成图表】")
        for chart_path in result.charts:
            print(f"    ▸ {chart_path}")

    # 报告
    print(f"\n{'─' * 60}")
    print(f"  📝 完整报告: {result.report_path}")
    print(f"{'─' * 60}\n")


if __name__ == "__main__":
    main()

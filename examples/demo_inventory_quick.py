"""供应链库存优化快速分析 Demo — 纯 Python 执行，不调用 LLM。

直接调用 inventory_pipeline.quick_analyze() 运行 8 步分析流水线，
打印结构化中文摘要到终端，可选择性保存报告。

Requires API Key: ❌ 不需要

用法:
    python examples/demo_inventory_quick.py
    python examples/demo_inventory_quick.py --save-report
    python examples/demo_inventory_quick.py --output-dir examples/output/
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# 确保能找到 src 包（从 examples/ 找项目根目录）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _print_header(text: str) -> None:
    """打印居中分隔标题。"""
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}")


def _print_section(title: str) -> None:
    """打印小标题。"""
    print(f"\n{title}")


def main() -> None:
    """快速分析 Demo 主入口。"""
    parser = argparse.ArgumentParser(description="供应链库存优化快速分析 Demo")
    parser.add_argument("--save-report", action="store_true", help="保存报告到输出目录")
    parser.add_argument("--output-dir", default="examples/output/", help="输出目录（默认 examples/output/）")
    parser.add_argument("--csv", default="workspace/data/sku_inventory.csv", help="CSV 数据文件路径")
    args = parser.parse_args()

    csv_path: str = args.csv
    output_dir: str = args.output_dir
    save_report: bool = args.save_report

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 检查数据文件
    if not os.path.exists(csv_path):
        print(f"\n❌ 错误: 数据文件不存在 → {csv_path}")
        print("请确认文件路径正确，或使用 --csv 指定路径。")
        sys.exit(1)

    _print_header("供应链库存优化分析")
    print(f"\n  数据文件 : {csv_path}")
    print(f"  输出目录 : {output_dir}")
    print(f"  保存报告 : {'是' if save_report else '否'}")
    print(f"\n  ▶ 正在运行 8 步分析流水线...")
    print(f"  （不调用 LLM，纯 Python + 规则引擎）")

    start = time.time()

    try:
        from src.domain.templates.inventory_pipeline import quick_analyze

        result = quick_analyze(csv_path, output_dir=output_dir)
    except Exception as exc:
        print(f"\n❌ 错误: {exc}")
        print("流水线执行异常，请检查 CSV 文件格式。")
        sys.exit(1)

    elapsed = time.time() - start

    if not result.report_path:
        print("\n❌ 分析未能完成（CSV 列名校验失败或数据为空）")
        print("  请确认 CSV 包含 month 和 demand 列。")
        sys.exit(1)

    # ── 中文摘要输出 ──
    _print_section("📊 分析结果摘要")

    # 数据质量
    if result.quality_report:
        qr = result.quality_report
        print(f"\n  【数据质量】")
        print(f"    综合评分  : {qr['overall_score']}/100")
        total_outliers = sum(c.get("outlier_count", 0) for c in qr.get("columns", []))
        if total_outliers > 0:
            print(f"    异常值数  : {total_outliers} 个")

    # 需求预测
    if result.forecast_result:
        fr = result.forecast_result
        print(f"\n  【需求预测】")
        print(f"    使用方法  : {fr.method_used}")
        print(f"    预测值    : {', '.join(f'{v:.1f}' for v in fr.forecasts)}")
        print(f"    MAPE      : {fr.mape}%")
        if fr.mape < 10:
            print(f"    ▸ 预测精度良好，可信度较高")
        else:
            print(f"    ▸ 预测精度一般，建议结合业务判断")

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
    print(f"  ⏱  总耗时: {elapsed:.1f}s")
    print(f"{'─' * 60}")

    # 可选：保存快速摘要到 output_dir
    if save_report:
        summary_path = os.path.join(output_dir, "demo_inventory_quick_report.md")
        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"# 供应链库存优化分析报告\n\n")
                f.write(f"- 数据文件: {csv_path}\n")
                f.write(f"- 总耗时: {elapsed:.1f}s\n")
                f.write(f"- 完整报告: {result.report_path}\n")
            print(f"  📁 摘要已保存: {summary_path}")
        except OSError as exc:
            print(f"  ⚠️ 摘要保存失败: {exc}")

    print(f"\n  Demo 完成 ✅ — 纯 Python 执行，无 LLM 调用。")


if __name__ == "__main__":
    main()

import pandas as pd
from src.domain.data_quality import run_quality_check
from src.domain.chart_templates import bar_chart

df = pd.read_csv("data/sales.csv")

print("=" * 60)
print("数据质量检查报告")
print("=" * 60)

report = run_quality_check(df)

print(f"数据质量评分：{report['overall_score']}/100")
print(f"总行数：{report['total_rows']}，总列数：{report['total_columns']}")
print(f"重复行：{report['duplicate_rows']}（{report['duplicate_rate']:.2%}）")
print()
print("各列质量概况：")
for col in report["columns"]:
    print(f"  [{col['name']}] dtype={col['dtype']}, "
          f"缺失率={col['missing_rate']:.2%} ({col['missing_level']}), "
          f"异常值={col['outlier_count']}, 类型冲突={col['type_conflict']}")
print()
if report["recommendations"]:
    print("修复建议：")
    for i, rec in enumerate(report["recommendations"], 1):
        print(f"  {i}. {rec}")

print()
print("=" * 60)
print("各区域销量柱状图")
print("=" * 60)

print("数据前3行，查看实际列名：")
print(df.head(3))

# 查找区域列，如果找不到则使用第一列
region_candidates = [c for c in df.columns if '区域' in c or 'region' in c.lower() or 'area' in c.lower()]
region_col = region_candidates[0] if region_candidates else df.columns[0]

# 查找销量列，如果找不到则使用第二列
qty_candidates = [c for c in df.columns if '销量' in c or 'qty' in c.lower() or '数量' in c or 'sales' in c.lower()]
qty_col = qty_candidates[0] if qty_candidates else (df.columns[1] if len(df.columns) > 1 else df.columns[0])

region_sales = df.groupby(region_col)[qty_col].sum().reset_index()
region_sales = region_sales.sort_values(qty_col, ascending=False)

print(f"\n按 {region_col} 汇总 {qty_col}：")
print(region_sales.to_string(index=False))

chart_path = bar_chart(
    region_sales,
    x_col=region_col,
    y_col=qty_col,
    title="各区域销量对比",
    output_path="reports/charts/chart_region_sales.html"
)
print(f"\n图表已保存到 {chart_path}")
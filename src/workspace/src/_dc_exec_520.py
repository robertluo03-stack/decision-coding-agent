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

actual_columns = df.columns.tolist()
print(f"实际列名：{actual_columns}")

region_col = None
sales_col = None
for col in actual_columns:
    col_lower = col.lower()
    if region_col is None and ("region" in col_lower or "area" in col_lower or "区域" in col_lower):
        region_col = col
    if sales_col is None and ("sales" in col_lower or "qty" in col_lower or "销量" in col_lower or "数量" in col_lower):
        sales_col = col

if region_col is None:
    region_col = actual_columns[0]
if sales_col is None:
    sales_col = actual_columns[-1]

print(f"使用区域列：{region_col}，销量列：{sales_col}")

region_sales = df.groupby(region_col)[sales_col].sum().reset_index()

chart_path = bar_chart(
    region_sales,
    x_col=region_col,
    y_col=sales_col,
    title="各区域销量对比",
    output_path="reports/charts/chart_region_sales.html"
)
print(f"图表已保存到 {chart_path}")
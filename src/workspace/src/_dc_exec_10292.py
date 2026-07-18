import pandas as pd
from src.domain.data_quality import run_quality_check
from src.domain.chart_templates import bar_chart

df = pd.read_csv("data/sales.csv")

report = run_quality_check(df)

print("=" * 60)
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
print("各区域销量汇总：")
print(df.columns.tolist())

# 查找区域列，如果找不到则使用第一列
region_candidates = [c for c in df.columns if 'region' in c.lower() or '区域' in c]
if region_candidates:
    region_col = region_candidates[0]
else:
    region_col = df.columns[0]
    print(f"警告：未找到区域列，默认使用第一列 '{region_col}'")

# 查找销量列，如果找不到则使用第二列
sales_candidates = [c for c in df.columns if 'sales' in c.lower() or '销量' in c or 'qty' in c.lower()]
if sales_candidates:
    sales_col = sales_candidates[0]
else:
    sales_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    print(f"警告：未找到销量列，默认使用第二列 '{sales_col}'")

region_sales = df.groupby(region_col)[sales_col].sum().reset_index()
print(region_sales)

bar_chart(region_sales, x_col=region_col, y_col=sales_col, title='各区域销量柱状图', output_path='reports/charts/chart_region_sales.html')
print("图表已保存到 reports/charts/chart_region_sales.html")
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

df = pd.read_csv("data/2222.csv")

print("=" * 60)
print("数据概览")
print("=" * 60)
print(f"数据集形状: {df.shape}")
print(f"列名: {list(df.columns)}")
print(f"\n前3行数据:")
print(df.head(3))

print("\n" + "=" * 60)
print("数据质量检查")
print("=" * 60)
print("\n缺失值统计:")
print(df.isnull().sum())
print(f"\n缺失值总数: {df.isnull().sum().sum()}")

print("\n数据类型:")
print(df.dtypes)

print("\n基本统计描述:")
print(df.describe(include='all'))

print("\n" + "=" * 60)
print("销量统计")
print("=" * 60)

actual_columns = list(df.columns)

qty_col = None
for col in actual_columns:
    col_lower = col.lower()
    if col_lower in ['qty', 'quantity', '销量', '数量', 'sales', 'amount']:
        qty_col = col
        break

if qty_col is None:
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        qty_col = numeric_cols[0]
        print(f"未找到明确的销量列，使用数值列: {qty_col}")
    else:
        qty_col = actual_columns[-1]
        print(f"未找到数值列，使用最后一列: {qty_col}")

df[qty_col] = pd.to_numeric(df[qty_col], errors='coerce')

print(f"\n销量列: {qty_col}")
print(f"销量基本统计:")
print(f"  总销量: {df[qty_col].sum():.2f}")
print(f"  平均销量: {df[qty_col].mean():.2f}")
print(f"  最大销量: {df[qty_col].max():.2f}")
print(f"  最小销量: {df[qty_col].min():.2f}")
print(f"  中位数销量: {df[qty_col].median():.2f}")
print(f"  标准差: {df[qty_col].std():.2f}")

date_col = None
for col in actual_columns:
    col_lower = col.lower()
    if col_lower in ['date', 'time', '日期', '时间', 'datetime', 'order_date', 'sale_date']:
        date_col = col
        break

if date_col:
    try:
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        print(f"\n按日期维度统计销量:")
        daily_sales = df.groupby(df[date_col].dt.date)[qty_col].sum().sort_index()
        print(daily_sales)
        print(f"\n按月份维度统计销量:")
        monthly_sales = df.groupby(df[date_col].dt.to_period('M'))[qty_col].sum().sort_index()
        print(monthly_sales)
    except:
        print(f"\n日期列 {date_col} 无法解析为日期格式，跳过时间维度统计")

product_col = None
for col in actual_columns:
    col_lower = col.lower()
    if col_lower in ['sku', 'product', 'item', '产品', '商品', 'name', 'product_name', 'item_name']:
        product_col = col
        break

if product_col:
    print(f"\n按产品维度统计销量:")
    product_sales = df.groupby(product_col)[qty_col].agg(['sum', 'mean', 'count', 'std']).fillna(0)
    product_sales = product_sales.sort_values('sum', ascending=False)
    print(product_sales)
    
    print(f"\n销量前5的产品:")
    print(product_sales.head(5))
    
    print(f"\n销量后5的产品:")
    print(product_sales.tail(5))

print("\n" + "=" * 60)
print("异常值检测")
print("=" * 60)
Q1 = df[qty_col].quantile(0.25)
Q3 = df[qty_col].quantile(0.75)
IQR = Q3 - Q1
lower_bound = Q1 - 1.5 * IQR
upper_bound = Q3 + 1.5 * IQR
outliers = df[(df[qty_col] < lower_bound) | (df[qty_col] > upper_bound)]
print(f"异常值数量: {len(outliers)}")
if len(outliers) > 0:
    print(f"异常值范围: 低于 {lower_bound:.2f} 或高于 {upper_bound:.2f}")
    print(f"异常值占比: {len(outliers)/len(df)*100:.2f}%")

print("\n" + "=" * 60)
print("销量分布")
print("=" * 60)
percentiles = [0, 10, 25, 50, 75, 90, 95, 99, 100]
percentile_values = np.percentile(df[qty_col].dropna(), percentiles)
for p, v in zip(percentiles, percentile_values):
    print(f"  {p}% 分位数: {v:.2f}")

print("\n" + "=" * 60)
print("报告生成完成")
print("=" * 60)
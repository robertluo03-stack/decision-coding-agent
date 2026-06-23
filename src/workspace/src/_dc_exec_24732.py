import pandas as pd
import numpy as np

df = pd.read_csv("data/sales.csv")

print("=" * 60)
print("数据概览")
print("=" * 60)
print(f"数据形状: {df.shape}")
print(f"列名: {list(df.columns)}")
print(f"\n前3行数据:\n{df.head(3)}")

print("\n" + "=" * 60)
print("数据质量检查")
print("=" * 60)
print(f"缺失值统计:\n{df.isnull().sum()}")
print(f"\n各列数据类型:\n{df.dtypes}")

print("\n" + "=" * 60)
print("按SKU分组销量统计")
print("=" * 60)

sku_col = [col for col in df.columns if col.lower() in ['sku', 'skuid', 'product_id', 'item']][0]
qty_col = [col for col in df.columns if col.lower() in ['qty', 'quantity', '销量', '数量', 'sales']][0]

grouped = df.groupby(sku_col)[qty_col].agg(['sum', 'mean', 'std', 'min', 'max', 'count']).reset_index()
grouped.columns = [sku_col, '总销量', '平均销量', '销量标准差', '最小销量', '最大销量', '订单数']
grouped = grouped.sort_values('总销量', ascending=False).reset_index(drop=True)

print(grouped.to_string(index=False))

print("\n" + "=" * 60)
print("销量分布概览")
print("=" * 60)
print(f"总销量: {grouped['总销量'].sum():.0f}")
print(f"SKU数量: {len(grouped)}")
print(f"平均每个SKU销量: {grouped['总销量'].mean():.2f}")
print(f"销量中位数: {grouped['总销量'].median():.2f}")
print(f"销量标准差: {grouped['总销量'].std():.2f}")
print(f"销量前5 SKU:\n{grouped.head(5).to_string(index=False)}")
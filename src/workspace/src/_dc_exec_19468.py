import pandas as pd

df = pd.read_csv("data/sales.csv")
print("实际列名：", df.columns.tolist())
print()

sku_col = [c for c in df.columns if c.lower() in ('sku', 'skucode', 'product_code', 'item_code')][0]
qty_col = [c for c in df.columns if c.lower() in ('qty', 'quantity', '销量', '数量', 'sales')][0]

result = df.groupby(sku_col)[qty_col].sum().reset_index()
result.columns = ['SKU', '总销量']
result = result.sort_values('总销量', ascending=False)

print("=" * 60)
print("各 SKU 总销量统计")
print("=" * 60)
for _, row in result.iterrows():
    print(f"  {row['SKU']}: {row['总销量']}")
print(f"\n共 {len(result)} 个 SKU")
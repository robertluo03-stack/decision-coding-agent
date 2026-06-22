import pandas as pd

try:
    df = pd.read_csv("data/sales.csv")
except FileNotFoundError:
    print("错误：文件 data/sales.csv 未找到，请确认文件路径是否正确。")
    exit(1)
except Exception as e:
    print(f"读取文件时发生错误：{e}")
    exit(1)

sku_sales = df.groupby("SKU")["销量"].sum().reset_index()
sku_sales.columns = ["SKU", "总销量"]

print("=" * 40)
print("每个 SKU 的总销量统计结果")
print("=" * 40)
print(sku_sales.to_string(index=False))
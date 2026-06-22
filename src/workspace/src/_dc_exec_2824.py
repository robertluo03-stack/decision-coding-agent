import sys
import pandas as pd

try:
    df = pd.read_csv("data/sales.csv")
except FileNotFoundError:
    print("错误：未找到 data/sales.csv 文件，请检查文件路径。")
    exit(1)
except Exception as e:
    print(f"读取文件时发生错误：{e}")
    exit(1)

if "sku" not in df.columns or "销量" not in df.columns:
    print("错误：数据文件中缺少 'sku' 或 '销量' 列。")
    exit(1)

sku_sales = df.groupby("sku")["销量"].sum().reset_index()
sku_sales.columns = ["SKU", "总销量"]

print("=" * 40)
print("各 SKU 总销量统计结果")
print("=" * 40)
print(sku_sales.to_string(index=False))
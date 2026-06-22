import pandas as pd

try:
    df = pd.read_csv("data/sales.csv")
    print("数据读取成功")
    print(f"数据形状: {df.shape}")
    print()
except FileNotFoundError:
    print("错误: 文件 data/sales.csv 未找到")
    exit(1)
except Exception as e:
    print(f"读取文件时出错: {e}")
    exit(1)

try:
    sku_sales = df.groupby("SKU")["销量"].sum().reset_index()
    sku_sales = sku_sales.sort_values("销量", ascending=False)
    print("=" * 40)
    print("每个 SKU 的总销量统计")
    print("=" * 40)
    print(sku_sales.to_string(index=False))
except KeyError as e:
    print(f"错误: 数据中缺少必要的列: {e}")
    exit(1)
except Exception as e:
    print(f"统计销量时出错: {e}")
    exit(1)
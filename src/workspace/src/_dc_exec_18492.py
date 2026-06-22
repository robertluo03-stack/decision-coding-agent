import pandas as pd
import numpy as np

try:
    # 1. 读取 data/2222.csv 文件
    df = pd.read_csv("data/2222.csv")
    print("=" * 60)
    print("数据读取成功！")
    print("=" * 60)
    print("数据概览：")
    print(df.head(3))
    print("\n数据形状：", df.shape)
    print("\n列名：", list(df.columns))
    
    # 2. 检查数据质量
    print("\n" + "=" * 60)
    print("数据质量检查")
    print("=" * 60)
    
    # 缺失值检查
    missing = df.isnull().sum()
    missing_cols = missing[missing > 0]
    if len(missing_cols) > 0:
        print("\n存在缺失值的列：")
        for col, count in missing_cols.items():
            print(f"  - {col}: {count} 个缺失值")
    else:
        print("\n没有缺失值")
    
    # 异常值检查（针对数值列）
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        print("\n数值列统计信息：")
        print(df[numeric_cols].describe())
        
        # 检查可能的异常值（使用 IQR 方法）
        for col in numeric_cols:
            Q1 = df[col].quantile(0.25)
            Q3 = df[col].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            outliers = df[(df[col] < lower_bound) | (df[col] > upper_bound)]
            if len(outliers) > 0:
                print(f"\n列 '{col}' 发现 {len(outliers)} 个异常值（超出1.5倍IQR范围）")
    
    # 3. 统计销量
    print("\n" + "=" * 60)
    print("销量统计")
    print("=" * 60)
    
    # 查找可能的销量列
    sales_col = None
    for col in df.columns:
        col_lower = col.lower()
        if col_lower in ['qty', 'quantity', '销量', '数量', 'sales', 'amount', 'count']:
            sales_col = col
            break
    
    if sales_col is None:
        # 如果没有找到明确的销量列，使用第一个数值列
        if len(numeric_cols) > 0:
            sales_col = numeric_cols[0]
            print(f"\n未找到明确的销量列，使用 '{sales_col}' 作为销量列")
        else:
            print("\n未找到数值列，无法进行销量统计")
            sales_col = None
    
    if sales_col is not None:
        sales_data = df[sales_col]
        
        print(f"\n销量列：'{sales_col}'")
        print(f"总销量（求和）：{sales_data.sum():.2f}")
        print(f"平均销量：{sales_data.mean():.2f}")
        print(f"中位数销量：{sales_data.median():.2f}")
        print(f"最小销量：{sales_data.min():.2f}")
        print(f"最大销量：{sales_data.max():.2f}")
        print(f"标准差：{sales_data.std():.2f}")
        
        # 按 SKU 或产品分组统计（如果存在相关列）
        group_col = None
        for col in df.columns:
            col_lower = col.lower()
            if col_lower in ['sku', 'product', '产品', '商品', 'item', 'id']:
                group_col = col
                break
        
        if group_col is not None:
            print(f"\n按 '{group_col}' 分组统计销量：")
            group_stats = df.groupby(group_col)[sales_col].agg(['sum', 'mean', 'count']).sort_values('sum', ascending=False)
            print(group_stats.head(10))
    
    # 4. 生成报告
    print("\n" + "=" * 60)
    print("报告摘要")
    print("=" * 60)
    print(f"数据文件：data/2222.csv")
    print(f"数据行数：{len(df)}")
    print(f"数据列数：{len(df.columns)}")
    
    if sales_col is not None:
        print(f"总销量：{sales_data.sum():.2f}")
        print(f"平均销量：{sales_data.mean():.2f}")
    
    print("\n报告生成完成！")

except FileNotFoundError:
    print("错误：找不到文件 data/2222.csv")
    print("请确保文件存在于 ./data/ 目录下")
except pd.errors.EmptyDataError:
    print("错误：文件 data/2222.csv 为空")
except pd.errors.ParserError:
    print("错误：文件 data/2222.csv 格式不正确，无法解析")
except Exception as e:
    print(f"发生未知错误：{e}")
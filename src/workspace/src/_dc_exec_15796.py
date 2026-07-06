import pandas as pd
from src.domain.templates.data_analysis import run_analysis

report_path = run_analysis("data/sales.csv", output_dir="reports/")
print(f"分析报告已生成: {report_path}")
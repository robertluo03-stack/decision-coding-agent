# Examples

Demo 示例集合，展示 DecisionCoder 的核心功能。所有 Demo 均可在无 LLM / 无 API Key 的环境下独立运行。

## 示例列表

### demo_rich_ui.py

展示 Rich 终端 UI 的完整效果，模拟 5 个节点依次执行 + Debugger 调试面板触发。

```bash
python examples/demo_rich_ui.py           # 自动检测 TTY
python examples/demo_rich_ui.py -t        # 强制 TTY 模式（Rich Live 渲染）
python examples/demo_rich_ui.py --output-dir examples/output/  # 指定输出目录
```

- **API Key**：不需要
- **运行时间**：约 10 秒
- **展示内容**：ProgressPanel（5 节点进度条）+ StatusTable（🟡→🔵→🟢 状态流转）+ LogPanel（50 条日志截断）+ DebugPanel（错误摘要 + 4 选项）

---

### demo_benchmark.py

生成 10 个 mock Benchmark 结果（7 成功 3 失败，含不同 retry_count），调用 ReportGenerator 输出 MD + HTML 两份报告。

```bash
python examples/demo_benchmark.py
python examples/demo_benchmark.py --output-dir examples/output/
```

- **API Key**：不需要
- **输出文件**：`examples/output/demo_benchmark_report.md` + `demo_benchmark_report.html`
- **展示内容**：MetricsCollector 指标汇总（完成率/成功率/平均重试/平均耗时）+ HTML 报告（卡片 + 进度条 + 徽章、内联 CSS）

---

### demo_inventory_quick.py

直接调用 `inventory_pipeline.quick_analyze()` 运行 8 步供应链分析流水线，打印结构化中文摘要到终端。

```bash
python examples/demo_inventory_quick.py
python examples/demo_inventory_quick.py --save-report
python examples/demo_inventory_quick.py --csv workspace/data/sku_inventory.csv
```

- **API Key**：不需要
- **数据文件**：默认使用 `workspace/data/sku_inventory.csv`（24 期月度库存数据，含 2 个异常值 + 上升趋势）
- **展示内容**：数据质量评分、需求预测（Holt 方法 + MAPE）、EOQ 经济订货批量、安全库存、补货点决策建议、2 张 Plotly 图表

---

### demo_text_to_sql.py

绕过 LLM 直接展示 Text-to-SQL 引擎的完整处理流程，使用预生成 SQL 替代 DeepSeek API 调用。

```bash
python examples/demo_text_to_sql.py
python examples/demo_text_to_sql.py --csv workspace/data/sales.csv
```

- **API Key**：不需要
- **运行时间**：< 1 秒
- **展示内容**：Step 1 Schema 提取（CREATE TABLE DDL）、Step 2 SQL 安全检查（安全 + 危险各 1 例）、Step 3 DuckDB 内存执行（Markdown 表格输出）、Step 4 自然语言摘要生成

---

### demo_inventory_optimization.py

从命令行接收 CSV 路径，调用 `inventory_pipeline` 完整流水线，打印结构化中文摘要。

```bash
python examples/demo_inventory_optimization.py workspace/data/sku_inventory.csv
python examples/demo_inventory_optimization.py workspace/data/sku_inventory.csv workspace/reports/
```

- **API Key**：不需要
- **参数**：`csv_path`（必需）、`output_dir`（可选）
- **展示内容**：完整的 8 步流水线中文摘要输出（数据质量 → 预测 → EOQ → SS → ROP → 图表 → 报告）

---

### RECORDING_GUIDE.md

录屏指南文档，包含 4 个演示场景的录制建议、解说词要点和技术设置说明。总时长建议 3 分钟，覆盖 Rich UI、LLM 闭环、Benchmark、供应链分析四大场景。

## Demo 对比速查

| Demo | LLM 依赖 | 数据文件 | 运行时间 | 输出 |
|------|---------|---------|---------|------|
| `demo_rich_ui.py` | 否 | 无 | ~10s | 终端 Rich UI |
| `demo_benchmark.py` | 否 | 无 | <1s | MD + HTML 报告 |
| `demo_inventory_quick.py` | 否 | `sku_inventory.csv` | ~1.5s | 终端中文摘要 + 图表 |
| `demo_text_to_sql.py` | 否 | `sales.csv` | <1s | 终端 Markdown 表格 |
| `demo_inventory_optimization.py` | 否 | `sku_inventory.csv` | ~15s | 终端摘要 + 10 章增强报告 |

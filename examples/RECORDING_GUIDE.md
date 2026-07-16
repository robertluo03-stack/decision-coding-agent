# 录屏指南 — DecisionCoder Demo 演示

> 4 个场景，总时长建议 3 分钟。录音时说明核心亮点，保持语速平稳。

## 录屏前准备

```bash
# 1. 确认环境
.venv\Scripts\activate
pip install -e .

# 2. 确保 demo 脚本可运行
python examples/demo_rich_ui.py -t        # 确认 Rich UI 正常
python examples/demo_benchmark.py         # 确认报告生成
python examples/demo_inventory_quick.py   # 确认分析结果
python examples/demo_text_to_sql.py       # 确认 SQL 查询

# 3. 确认数据文件存在
ls workspace/data/sales.csv
ls workspace/data/sku_inventory.csv
```

**终端设置建议**：
- 字体大小：14pt+（录屏后缩放仍可读）
- 配色：深色背景 + 浅色字体（Windows Terminal / iTerm2 默认暗色主题即可）
- 分辨率：1920×1080
- 窗口：全屏终端，不显示桌面

---

## 场景 1：Rich 终端 UI 展示（30s）

```bash
python examples/demo_rich_ui.py -t
```

**预期效果**：5 个节点依次完成（Planner → Coder → Executor → Debugger → Reporter），Executor 后触发 Debugger 调试面板，展示红色错误诊断 + 4 个选项，AI 修复后重新执行成功。

**解说词要点**：
- "这是项目的 Rich 终端 UI，基于 Python Rich 库自研"
- "5 个节点实时进度条，🟡等待 → 🔵运行中 → 🟢完成 → 🔴错误"
- "Debugger 面板展示 Markdown 错误诊断和 4 个人机交互选项"
- "整个 UI 通过 queue.Queue 实现线程安全，非 TTY 环境自动降级为 print"

**时长**：~30 秒

---

## 场景 2：真实验 LLM 闭环（45s）

```bash
# 需先设置 DEEPSEEK_API_KEY
python main.py --rich
# 输入: "分析 workspace/data/sales.csv 的数据质量，画出各区域销量柱状图"
```

**预期效果**：从自然语言输入到最终报告的全自动闭环。Planner 拆解任务 → Coder 生成代码 → Executor 执行 → Reporter 输出报告。

**解说词要点**：
- "输入一句自然语言，Agent 自动完成拆解、编码、执行、报告全流程"
- "LangGraph 状态机管理整个 Plan-Code-Execute-Report 闭环"
- "Planner 将需求拆解为步骤，Coder 选择合适的领域模板生成代码"
- "Executor 在沙箱中安全执行，30 秒超时保护"

> **替代方案**（无 API Key）：
> ```bash
> python examples/demo_inventory_quick.py
> ```
> 展示完整的供应链分析结果摘要，约 30 秒。

**时长**：~45 秒

---

## 场景 3：Benchmark 评测框架（30s）

```bash
python examples/demo_benchmark.py
# 然后打开生成的 HTML 报告
start examples/output/demo_benchmark_report.html   # Windows
open examples/output/demo_benchmark_report.html    # macOS
```

**预期效果**：终端输出 10 个 mock 任务的统计摘要（完成率/成功率/平均重试/平均耗时），生成 MD + HTML 两份报告。浏览器打开 HTML 展示内联 CSS 卡片、进度条、徽章。

**解说词要点**：
- "Benchmark 框架包含 10 个预定义任务，5 个数据分析 + 5 个代码生成"
- "每个任务自动执行、验证、统计，JSONL 输出支持断点续跑"
- "HTML 报告零外部依赖，进度条、卡片、徽章全部内联 CSS"
- "指标包括完成率、运行成功率、平均重试次数、平均耗时"

**时长**：~30 秒

---

## 场景 4：供应链库存分析（30s）

```bash
python examples/demo_inventory_quick.py
```

**预期效果**：自动读取 `sku_inventory.csv`，运行 8 步分析流水线（数据质量 → 需求预测 → EOQ → 安全库存 → 补货点），打印结构化中文摘要，展示纯 Python 规则引擎能力。

**解说词要点**：
- "供应链库存优化端到端闭环：数据质量 → 预测 → EOQ → 安全库存 → 补货点决策"
- "零 LLM 调用，纯 Python + 规则引擎，毫秒级响应"
- "7 个领域优化模板是项目的核心差异化壁垒"
- "每个步骤都有量化输出和服务水平建议"

**时长**：~30 秒

---

## 录屏流程建议

| 时间 | 场景 | 内容 |
|------|------|------|
| 0:00 - 0:30 | 场景 1 | Rich 终端 UI — 进度条 + 调试面板 |
| 0:30 - 1:15 | 场景 2 | 真实 LLM 闭环 — 输入需求到报告输出 |
| 1:15 - 1:45 | 场景 3 | Benchmark — 10 任务统计 + HTML 报告 |
| 1:45 - 2:15 | 场景 4 | 供应链分析 — 8 步流水线中文摘要 |

> **总时长 2 分 15 秒**，预留 45 秒给开场白和收尾总结 = **3 分钟整**。

## 额外场景（备选）

```bash
# Text-to-SQL 引擎展示
python examples/demo_text_to_sql.py

# 供应链完整 CLI Demo
python examples/demo_inventory_optimization.py workspace/data/sku_inventory.csv
```

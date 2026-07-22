# DecisionCoder Benchmark 评测框架

> 10 任务自动化评测系统 — 架构概览见 [architecture.md](architecture.md)。

## 任务集

10 个预定义任务（5 数据分析 + 5 代码生成），定义在 [tasks.py](../src/benchmark/tasks.py) 的 `get_default_tasks()`。

### 数据分析类（BA-01 ~ BA-05）

| ID | Query | 预期关键词 | Timeout | 数据文件 |
|----|-------|-----------|---------|---------|
| BA-01 | 读取 sales.csv，统计 sales_volume 列的均值、中位数和标准差 | `sales`, `均值`, `标准差`, `销量` | 60s | `sales.csv` |
| BA-02 | 检查 sales.csv 的数据质量，报告缺失值、异常值和综合评分 | `缺失值`, `异常值`, `评分`, `数据质量` | 60s | `sales.csv` |
| BA-03 | 对 sales.csv 各区域销量画出柱状图，保存为 HTML 文件 | `图表`, `bar`, `bar_chart`, `html` | 60s | `sales.csv` |
| BA-04 | 用 run_text_to_sql 查询 sales.csv，统计每个区域（region）的平均销量 | `SELECT`, `AVG`, `region`, `区域` | 60s | `sales.csv` |
| BA-05 | 一键分析 inventory.csv 并生成完整报告 | `分析`, `inventory`, `报告` | 120s | `inventory.csv` |

### 代码生成类（CG-01 ~ CG-05）

| ID | Query | 预期关键词 | Timeout | 数据文件 |
|----|-------|-----------|---------|---------|
| CG-01 | 计算 EOQ：年需求 1000，订货成本 50，持有成本 2 | `EOQ`, `223`, `inventory_eoq` | 30s | — |
| CG-02 | 对历史需求数据做需求预测 | `forecast`, `预测`, `MAE` | 30s | — |
| CG-03 | 计算安全库存：日均需求 100，需求标准差 20，提前期 2 天，服务水平 95% | `安全库存`, `Z`, `1.64` | 30s | — |
| CG-04 | 计算补货点：日均需求 100，提前期 2 天，安全库存 50，EOQ 224 | `补货点`, `ROP`, `库存策略` | 30s | — |
| CG-05 | 运行库存管道流水线分析 | `pipeline`, `库存`, `报告` | 120s | `inventory.csv` |

## 指标计算

评测框架收集 4 个核心指标，定义在 [models.py](../src/benchmark/models.py) 的 `MetricsCollector`。

| 指标 | 公式 | 说明 |
|------|------|------|
| **完成率** | `completed / total` | 任务未超时且返回结果的占比。`completed` = 在 timeout 内完成执行的任务数 |
| **成功率** | `success / completed` | 完成的任务中通过关键词验证的占比。关键词匹配不区分大小写，浮点数宽松匹配（±1%） |
| **平均重试** | `sum(retry_count) / total` | 所有任务 retry_count 的平均值。越低越好，0 表示所有任务一次成功 |
| **平均耗时** | `sum(elapsed) / completed` | 成功完成任务的平均执行时长（秒）。仅统计 completed=true 的任务 |

### 关键词验证算法

```
validate_task_result(result, expected_keywords):
    text = lower(result.output + result.execution_result)
    for keyword in expected_keywords:
        if keyword is a float-like number:
            check if any number in text is within ±1% of keyword
        else:
            check if lower(keyword) is in text
    return all keywords matched
```

## 报告格式

### JSONL 输出结构

每行一条任务结果，`BenchmarkRunner` 逐行追加，支持断点续跑：

```jsonl
{"id":"BA-01","status":"success","elapsed":12.3,"retry_count":0,"output":"...","timestamp":"2026-07-16T10:30:00"}
{"id":"BA-02","status":"success","elapsed":18.7,"retry_count":1,"output":"...","timestamp":"2026-07-16T10:30:19"}
```

### Markdown 报告章节

`ReportGenerator.generate_md()` 生成以下章节：

1. **概览卡片**：完成率/成功率/平均重试/平均耗时 4 个 KPI
2. **分类汇总表**：按数据分析 / 代码生成分组统计
3. **任务明细表**：每个任务的 ID、状态、耗时、重试次数
4. **失败任务分析**：仅当有失败时显示

### HTML 报告样式

`ReportGenerator.generate_html()` 生成内联 CSS 报告（零外部依赖）：

- **进度条**：CSS `width: X%` + `linear-gradient` 背景
- **状态卡片**：成功（绿）/ 失败（红）/ 超时（黄）
- **分类徽章**：`border-radius` 圆角标签
- **响应式**：`max-width: 900px` 居中布局

## 运行命令

```bash
# 运行全部 10 个任务（JSONL 输出到 results/）
python -m benchmark run

# 带 Rich 终端 UI（实时进度）
python -m benchmark run --rich

# 从 JSONL 生成报告
python -m benchmark report results/benchmark_20260716_103000.jsonl
# → 生成 results/benchmark_20260716_103000_report.md
# → 生成 results/benchmark_20260716_103000_report.html

# 查看帮助
python -m benchmark --help
```

## 对照实验（Arm 对比）

支持双臂对照实验，验证规则路由对端到端成功率/一致率/Token 成本的贡献。

```bash
# 单臂 routing_off（每任务重复 3 次）
python -m benchmark run --arm routing_off --repeat 3

# 双臂对照（routing_on + routing_off，各 3 次重复）
python -m benchmark run --both

# 双臂 + 对抗任务集（10 默认 + 7 对抗）× 2 arms × 3 repeats = 102 次执行
python -m benchmark run --both --adversarial
```

### Arm 对比报告示例

生成的 MD/HTML 报告包含 Arm 对比章节：

| 指标 | routing_on | routing_off |
|------|-----------|-------------|
| 成功率 | 85% | 72% |
| 结果一致率 | 90% | 80% |
| Average Tokens | 12,345 | 14,000 |
| 平均耗时 | 14.2s | 16.8s |

### 对抗任务集（7 个）

| ID | 类别 | 描述 |
|----|------|------|
| ADV-01 | EOQ 标准说法 | "年需求1000，订货成本50，持有成本2，帮我算EOQ" |
| ADV-02 | EOQ 口语化 | "每年要卖1000件，每次下单花50..." |
| ADV-03 | EOQ 数学符号 | "D=1000, S=50, H=2, 算一下经济订货批量" |
| ADV-04 | EOQ 中文数字 | "年需求量一千，订货成本五十，单位持有成本二" |
| ADV-05 | EOQ 英文参数 | "EOQ计算：annual_demand=1000, ordering_cost=50..." |
| ADV-06 | 模板外 | "写一个函数判断字符串是否为回文并测试" |
| ADV-07 | 模板外 | "产品原价100元，打8折后参加满300减50..." |

### 一致率计算

同一任务同一 arm 的 3 次重复中，核心数值结果（中位数参考）偏差在 ±5% 内的比例。
仅对含确定性数值输出的任务（EOQ/安全库存/补货点/需求预测）进行提取和比较。

## 架构组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `BenchmarkTask` | [models.py](../src/benchmark/models.py) | 任务数据模型（id/query/keywords/timeout） |
| `BenchmarkResult` | [models.py](../src/benchmark/models.py) | 执行结果模型（status/elapsed/retry_count/output） |
| `MetricsCollector` | [models.py](../src/benchmark/models.py) | 指标聚合 + 分类统计 |
| `BenchmarkRunner` | [runner.py](../src/benchmark/runner.py) | 逐个任务执行 + 超时控制 + JSONL 输出 |
| `ReportGenerator` | [reporter.py](../src/benchmark/reporter.py) | Markdown + HTML 报告生成器 |
| `get_default_tasks()` | [tasks.py](../src/benchmark/tasks.py) | 返回 10 个预定义任务 |
| `validate_task_result()` | [runner.py](../src/benchmark/runner.py) | 关键词匹配验证 |

---

> **下一步**：阅读 [architecture.md](architecture.md) 了解整体架构，或返回 [README.md](../README.md) 查看项目概览。

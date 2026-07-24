# Benchmark 使用与治理手册

> v0.8 | 2026-07-24 | 三臂实验完成

## 1. 快速上手

```bash
# 单臂执行（默认 routing_on）— 10 基础任务
python -m benchmark run
python -m benchmark run --rich                    # 带 Rich 终端 UI

# 双臂对照 — routing_on + routing_off，各 3 次重复
python -m benchmark run --both --repeat 3

# 双臂 + 全部对抗任务 — routing_on + routing_off，各 ×3，17 任务
python -m benchmark run --both --adversarial --repeat 3

# 从已有 JSONL 生成 MD + HTML 报告（不重新执行）
python -m benchmark report results/benchmark_<batch_id>.jsonl
```

**控制台落盘惯例**：推荐使用 Tee-Object 同时输出到终端与文件：

```bash
python -m benchmark run --both --adversarial --repeat 3 2>&1 | tee results/run_$(date +%Y%m%d_%H%M%S).log
```

JSONL 结果自动写入 `results/benchmark_<batch_id>.jsonl`，报告写入 `results/benchmark_<batch_id>_report.md` / `.html`。CLI 用法详见 `python -m benchmark --help` 或 [src/benchmark/__main__.py](../src/benchmark/__main__.py)。

## 2. 任务集

任务定义在 [src/benchmark/tasks.py](../src/benchmark/tasks.py)——`get_default_tasks()` 返回基础任务、`get_adversarial_tasks()` 返回对抗任务。

### 2.1 主任务 10（BA / CG）

| 类别 | 任务 ID | 描述 | 超时 | 数据文件 |
|------|--------|------|------|---------|
| 数据分析 | BA-01 | Sales 描述统计（均值/中位数/标准差） | 60s | sales.csv |
| 数据分析 | BA-02 | 数据质量检查（缺失值/异常值/评分） | 60s | sales.csv |
| 数据分析 | BA-03 | 区域柱状图（HTML 保存） | 60s | sales.csv |
| 数据分析 | BA-04 | Text-to-SQL 区域查询 | 60s | sales.csv |
| 数据分析 | BA-05 | 一键分析报告 | 60s | inventory.csv |
| 代码生成 | CG-01 | EOQ 经济订货批量 | 60s | — |
| 代码生成 | CG-02 | 需求预测（demand_forecast 模板） | 60s | — |
| 代码生成 | CG-03 | 安全库存（safety_stock 模板） | 60s | — |
| 代码生成 | CG-04 | 补货点计算（reorder_point 模板） | 60s | — |
| 代码生成 | CG-05 | 库存管道流水线（inventory_pipeline） | 60s | sku_inventory.csv |

### 2.2 对抗任务 7（ADV）

| 类别 | 任务 ID | 描述 | 超时 | needs_manual_review |
|------|--------|------|------|-------------------|
| 对抗 | ADV-01~05 | 同任务多说法（EOQ × 5 种表述） | 30s | 否 |
| 对抗 | ADV-06 | 回文函数（写函数并测试） | 30s | **是** |
| 对抗 | ADV-07 | 满减算法（打 8 折后满 300 减 50） | 30s | **是** |

ADV-01~05 使用 5 种不同中文表述要求同一个 EOQ 计算——测试规则路由对不同措辞的鲁棒性。每个任务的 `expected_keywords`（结果词）与 `template_keywords`（机制词）详见 [tasks.py](../src/benchmark/tasks.py) 的完整定义。

ADV-06/07 标记 `needs_manual_review=true`——关键词过少（各 2 个），机器判定不足以区分正确/错误，**每次实验后必须人工复核**。

## 3. 判定规则

判定逻辑实现于 [src/benchmark/validators.py](../src/benchmark/validators.py) `validate_task_result()`。

### 3.1 结果词 AND 匹配

`expected_keywords`（结果词）全部命中 ⇒ `success=true`。关键词匹配不区分大小写，支持浮点数宽松匹配（"223" 匹配 "223.61"）。

### 3.2 失败否决

以下任一条件触发时，**无论结果词命中情况如何**，`success=false`：

- `human_feedback == "ABORT"`（graph 状态机中止）
- `workspace/reports/fail_*.md` 存在（兜底检测，防止 feedback 未透传）
- 超时（`threading.Event.wait(timeout)` 返回 False）

参见 [validators.py:47-55](../src/benchmark/validators.py#L47-L55)。

### 3.3 机制词（不计入 success）

`template_keywords`（机制词）单独统计 `template_hit_rate`——任一机制词命中即计 1 分，除以总数。机制词量化规则路由的模板命中比例，用于区分"模板强制完整性"与"通用脚手架"的输出差异。

### 3.4 数值一致率

`numeric_extractor.py` 从执行输出（stdout）中提取核心数值（仅对含确定性数值结果的任务：CG-01~04 + ADV-01~05）。同一 (task, arm) 组内多次运行的数值，与组内中位数偏差在 ±5% 内的比例即为一致率。详见 [numeric_extractor.py](../src/benchmark/numeric_extractor.py)。

### 3.5 Token 追踪

`token_tracker.py` 通过 monkey-patch `langchain_deepseek.ChatDeepSeek.invoke` 捕获每次 LLM 调用的 `usage_metadata`（input_tokens / output_tokens / total_tokens），线程安全。详见 [token_tracker.py](../src/benchmark/token_tracker.py)。

## 4. 归档与追溯

### 4.1 Batch ID

每次 `run_all()` / `run_both()` 生成 batch_id：`<YYYYmmdd_HHMMSS>_<git 短哈希>`。该 ID 写入 JSONL 文件名、manifest.json、artifact 目录路径。`run_both()` 中两个 arm 共享同一 batch_id。

### 4.2 归档目录

```
results/artifacts/<batch_id>/
├── manifest.json                          # 批级元数据
├── <task_id>/<arm>/run<N>/
│   ├── report_*.md                        # 成功报告
│   ├── fail_*.md                          # 失败报告
│   └── charts/*.html                      # 图表文件
└── ...
```

归档由 `BenchmarkRunner._archive_artifacts()` ([runner.py:555-616](../src/benchmark/runner.py#L555-L616)) 在每个任务完成后、`_cleanup_workspace()` 清理前执行。

**已知局限**：当前归档仅覆盖 `reports/` 下的 `.md` 和 `.html` 文件。Python 子进程 stdout（`execution_result`）与生成的代码文件（`_dc_exec_*.py`）不在归档范围内，仅存在于内存中的 AgentState，`graph.invoke()` 结束后随进程消失。参见 [CLAUDE.md 已知问题](../CLAUDE.md) 第 2 条。

### 4.3 Manifest

`manifest.json` 包含：

- `batch_id`、`git_commit`、`git_dirty`（来自 `git rev-parse HEAD` / `git status --porcelain`）
- `cli_args`：调用参数
- `tasks`：任务清单（id / category / query / timeout）
- `arm_config`：实验臂名称与重复次数
- `metrics_summary`：完成率 / 成功率 / 平均重试 / 平均耗时 / token 总量
- `generated_at`：ISO 8601 时间戳

### 4.4 JSONL

单文件追加模式写入，每行一条 BenchmarkResult JSON。线程安全（`threading.Lock`）。支持断点续跑——若 JSONL 已存在且非空，新结果追加写入；若 JSONL 不存在或为空，清空旧文件后写入。

## 5. 复核规程

每次 Benchmark 实验完成后，按以下步骤复核：

### 5.1 第一轮：AI 初审

1. **读取 JSONL**：`python -m benchmark report <jsonl>` 生成报告
2. **筛选 `success=false` 运行**：逐条读取归档报告，比照基准真值独立重算
3. **抽样 success=true**：每个 task × 每批次至少抽查 1 条的数值正确性
4. **ADV-06/07 必复核**：因 `needs_manual_review=true`，逐条检查代码实现与测试质量
5. 输出初审报告 + 终审待决条目清单

### 5.2 第二轮：人类终审

1. 对初审的待决条目逐条裁决（措辞假失败 / 真失败 / 存疑 / 剔除）
2. 至少抽查 20% 的 `success=true` 运行
3. ADV-06/07 必复核，逐一评估实现质量
4. 输出终审报告，记录裁决清单与汇总对照

### 5.3 ADV-07 特殊处理（维持 v1 裁决）

ADV-07（满减算法）已在 2026-07-23 复核中裁决为**任务设计缺陷**——题目未明确满减门槛计算基数（折扣前 vs 折扣后总价），导致两种合理解读（190 / 240）。该任务所有运行从成功率与一致率分母中**整体剔除**。若后续保留类促销计算任务，需在 query 中显式规定计算顺序。

## 6. A 臂（Claude Code 裸用基线）

### 6.1 脚本用法

```bash
python scripts/run_arm_a.py --smoke                      # 冒烟：CG-01 × 1，验证字段与端点
python scripts/run_arm_a.py --full                       # 全量：17 任务 × 3 = 51 次
python scripts/run_arm_a.py --full --timeout-cap 600     # 全量，统一 600s 超时
```

脚本位于 [scripts/run_arm_a.py](../scripts/run_arm_a.py)，通过 `claude -p --output-format json --dangerously-skip-permissions` 子进程调用。

### 6.2 隔离工作目录

A 臂在仓库外空目录 `arm_a_workspace/` 运行，仅复制 3 个 CSV 数据文件（sales.csv / inventory.csv / sku_inventory.csv）。运行前扫描隔离目录及其父级目录链中的 CLAUDE.md，报告但不中止。运行前检查用户级 `~/.claude/CLAUDE.md` 是否含 DecisionCoder 相关引用，报告但不中止。

### 6.3 公平性控制

与 B/C 臂的对照协议：

- **query 逐字一致**：任务定义拷贝自 `src/benchmark/tasks.py`，不增删不改写
- **重复次数一致**：每任务 3 次运行
- **判定算法一致**：`_keyword_found()` 与 B/C 臂的 `validators.py` 算法完全相同（不区分大小写 substring + 浮点数宽松匹配）
- **同一基座模型**：三臂均通过同一本地代理（ccswitch）调用同一后端模型。B/C 臂通过 DeepSeek API → ccswitch → 后端模型；A 臂通过 claude CLI（`claude-sonnet-4-6`）+ ccswitch → 同一后端模型
- **判定域差异（已知）**：A 臂仅扫描 `claude` 返回的 `result` 字段（最终答复文本），B/C 臂扫描 `execution_result`（完整 stdout）+ `final_report`（Markdown 报告全文）。此差异导致 A 臂可能丢失 Python 脚本 stdout 中出现的中间输出关键词。

### 6.4 --timeout-cap

`--timeout-cap <秒>` 统一覆盖所有任务的超时上限。正式实验使用 600s（消除超时瓶颈）。首批数据使用 60s 口径，保留作敏感性对照。

## 7. 测量学教训

以下发现来自三臂实验的复核过程，详细信息见 [docs/experiment_three_arm.md](experiment_three_arm.md)。

### 7.1 中文关键词偏置（三臂同病）

`expected_keywords` 中的英文缩写（"bar" / "ROP" / "MAPE" / "SELECT" / "AVG"）对使用中文自然语言回复的系统不友好——它们用"柱状图"/"Reorder Point"替换英文词是函数正确的行为，但在 substring 匹配中被判为缺失。BA-01 的"销量"缺失是实验中最高频的措辞假失败。详见实验报告 F5 节。

### 7.2 判定域差异

A 臂扫描 `claude` 最终答复文本；B/C 臂扫描 `execution_result`（stdout）+ `final_report`（Markdown 报告）。此差异导致：当关键词出现在 Python 脚本的中间 stdout 输出、出现在生成的代码文件内容中、或出现在被后续运行覆写的图表文件名中时，不同臂的判定结果不可直接比较。ADV-06 run3（A 臂）的 `palindrome` 存在于代码文件中而非答复文本，即受此影响。

### 7.3 超时截断

A 臂 60s 口径下，BA-02×3 / BA-05×3 / CG-03×1 / CG-05×1 共 8 条超时截断（elapsed ≈ 65.0s）。改为 600s 后超时问题消除。说明含数据文件读取或复杂多步任务的 A 臂运行需要超过 60s 的超时预算，且 A 臂的行为模式（探索性多轮对话）使其单任务耗时显著高于 B/C 臂（模板单次执行）。

### 7.4 机制词与任务设计偏置

`template_keywords`（如 `SELECT`/`AVG` 用于 BA-04、`bar_chart` 用于 BA-03）是 B/C 臂专有模板函数的输出——A 臂无这些函数，用等价的 pandas 操作和 Chart.js 达成同等结果，但机制词不命中。这些关键词不应混入 `expected_keywords`（结果词）——混入会导致对 A 臂的结构性偏置。

---

> 相关文档：[DEV_DESIGN.md](../DEV_DESIGN.md)（架构决策）、[CLAUDE.md](../CLAUDE.md)（代码库指南）、
> [experiment_three_arm.md](experiment_three_arm.md)（三臂实验报告）、
> [results/review_log_20260723.md](../results/review_log_20260723.md)（B/C 臂复核日志）、
> [results/review_arm_a_20260724.md](../results/review_arm_a_20260724.md)（A 臂复核终审报告）

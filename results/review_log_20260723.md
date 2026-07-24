# Benchmark 复核日志

**初审人**: Claude Code (Opus 4.8, 1M context)
**日期**: 2026-07-23
**量规版本**: v1（三问量规：数据列名 / 计算正确性 / 任务覆盖）
**主批次 ID**: `20260723_175230_9c54231`
**对抗批次 ID**: `20260723_182224_9c54231`

---

## 一、源数据基准真值（独立重算）

### sales.csv（workspace/data/sales.csv）
- 列名：`date`, `sku`, `region`, `sales_volume`, `unit_price`
- 120 行，sales_volume 非空 108 行（12 个 NaN）
- **均值 = 139.06**，**中位数 = 86.50**，**标准差 = 241.75**（ddof=1）

### inventory.csv（workspace/data/inventory.csv）
- 列名：`sku`, `product_name`, `warehouse`, `current_stock`, `safety_stock`, `reorder_point`
- 55 行，14 个唯一 SKU，4 个仓库
- current_stock 均值 = 886.38，标准差 = 546.76。无日期列，无需求列。

### sku_inventory.csv（workspace/data/sku_inventory.csv）
- 列名：`month`, `sku_id`, `demand`, `unit_cost`
- 24 行，demand 均值 = 112.00，标准差 = 21.64，总和 = 2688
- EOQ（D=2688, S=100, H=10）：231.86
- Pipeline 基准 EOQ（mean×12=1344）：163.95，安全库存：35.59，ROP：147.59

### 代码生成基准真值
| 指标 | 公式 | 基准值 |
|------|------|--------|
| CG-01 EOQ | √(2×1000×50/2) | **223.61** |
| CG-03 安全库存 | 1.64485×20×√2 | **46.52** |
| CG-04 补货点 | 100×2+50 | **250.00** |

---

## 二、复核明细表

### 图例
- 判定列：🟢 措辞假失败 / 🔴 真失败 / 🟡 存疑 / ⬜ 无判定（ADV-07 仅证据提取）
- 机器判定列取自 JSONL `success` 字段

### 2.1 全部 success=False 的运行（18 条）

#### 主批次（5 条）

| # | 批次 | Task | Arm | Run | 机器判定 | 复核判定 | 证据 |
|---|------|------|-----|-----|---------|---------|------|
| 1 | 主 | BA-01 | routing_on | run1 | ❌ | 🟢 措辞假失败 | `175230/BA-01/routing_on/run1/report_20260723_175244.md`：使用 sales.csv + sales_volume 列 ✓；均值 139.06/中位数 86.50/标准差 241.75 与基准一致 ✓；三项统计量均计算 ✓。仅文本未出现中文"销量"。 |
| 2 | 主 | BA-01 | routing_off | run1 | ❌ | 🟢 措辞假失败 | `175230/BA-01/routing_off/run1/report_20260723_180046.md`：同上，三值均正确。仅缺"销量"。 |
| 3 | 主 | BA-01 | routing_off | run3 | ❌ | 🟢 措辞假失败 | `175230/BA-01/routing_off/run3/report_20260723_180602.md`：额外打印了列名确认。三值均正确。仅缺"销量"。 |
| 4 | 主 | BA-05 | routing_on | run3 | ❌ | 🔴 真失败 | `175230/BA-05/routing_on/run3/fail_20260723_175924.md`：中止。代码将 sku 列当作日期列做 `pd.to_datetime`，抛出 DateParseError。**归因：数据列名**——inventory.csv 无日期列，Planner 错误编排时间序列预测流水线，列名启发式回退到 `df.columns[0]` = `sku`。重试 2 次耗尽。 |
| 5 | 主 | BA-05 | routing_off | run3 | ❌ | 🔴 真失败 | `175230/BA-05/routing_off/run3/report_20260723_180658.md`：非中止但缺内容。代码仅一行 `run_analysis("data/inventory.csv")`，报告正文仅显示"分析报告已生成: ..."路径，未内联任何分析结果。LLM 分析为推测性套话（"如果报告显示……"）。实际列名 sku/warehouse 未出现在报告正文中，关键词仅命中 "inventory"。**归因：缺内容**——分析存在于外部子报告文件但未捕获回决策报告。 |

#### 对抗批次（13 条）

| # | 批次 | Task | Arm | Run | 机器判定 | 复核判定 | 证据 |
|---|------|------|-----|-----|---------|---------|------|
| 6 | 对抗 | BA-01 | routing_on | run1 | ❌ | 🟢 措辞假失败 | `182224/BA-01/routing_on/run1/report_20260723_182236.md`：sales.csv + sales_volume ✓；三值正确。仅缺"销量"。 |
| 7 | 对抗 | BA-01 | routing_on | run3 | ❌ | 🟢 措辞假失败 | `182224/BA-01/routing_on/run3/report_20260723_182935.md`：同上，三值正确。仅缺"销量"。 |
| 8 | 对抗 | BA-01 | routing_off | run1 | ❌ | 🔴 真失败 | `182224/BA-01/routing_off/run1/report_20260723_183322.md`：**中位数 = nan**，**标准差 = 240.63**。代码使用 `np.mean()/np.median()/np.std(…, ddof=0)` 而非 Pandas 的 `.mean()/.median()/.std()`。数据有 12 个 NaN，`np.median()` 返回 nan（不自动跳过 NaN）。`np.std(ddof=0)` 给出总体标准差 240.63 而非样本标准差 241.75。**归因：方法错误**——NumPy 代替 Pandas，对缺失值不鲁棒。 |
| 9 | 对抗 | BA-05 | routing_on | run2 | ❌ | 🔴 真失败 | `182224/BA-05/routing_on/run2/report_20260723_182703.md`：非中止但缺内容。与 #5 同模式——`run_analysis()` 一行，报告仅路径输出，LLM 分析为推测性套话。关键词仅命中 "inventory"。 |
| 10 | 对抗 | BA-05 | routing_on | run3 | ❌ | 🔴 真失败 | `182224/BA-05/routing_on/run3/fail_20260723_183049.md`：中止。代码将 sku→日期列（`errors='coerce'` 清空全列），product_name→需求列（非数值）。history 变为 `[]`，触发 `ValueError: 历史数据至少需要 2 个数据点`。**归因：数据列名**——与 #4 同根因，回退列选择更差（product_name 作为需求列）。 |
| 11 | 对抗 | BA-05 | routing_off | run1 | ❌ | 🔴 真失败 | `182224/BA-05/routing_off/run1/report_20260723_183412.md`：与 #5/#9 同模式——`run_analysis()` 空壳报告。关键词仅命中 "inventory"。 |
| 12 | 对抗 | BA-05 | routing_off | run2 | ❌ | 🔴 真失败 | `182224/BA-05/routing_off/run2/report_20260723_183749.md`：同上——`run_analysis()` 空壳报告。 |
| 13 | 对抗 | BA-05 | routing_off | run3 | ❌ | 🔴 真失败 | `182224/BA-05/routing_off/run3/report_20260723_184117.md`：同上——`run_analysis()` 空壳报告。 |
| 14 | 对抗 | CG-05 | routing_off | run1 | ❌ | 🟢 措辞假失败 | `182224/CG-05/routing_off/run1/report_inventory_20260723_183515.md`：Pipeline 全部 8 步成功完成：EOQ=163.95、安全库存=35.59、ROP=147.59、2 张图表。所有计算数值与基准一致。报告文件为完整的 MD 格式（9 节）。唯一错误是后处理打印 `result.forecast_method`（应为 `forecast_result`）的 AttributeError——发生在所有工作完成后。 |
| 15 | 对抗 | CG-05 | routing_off | run2 | ❌ | 🔴 真失败 | `182224/CG-05/routing_off/run2/fail_20260723_183856.md`：中止。`from src.domain.templates.inventory_pipeline import run_pipeline` → ImportError。正确函数名为 `run_inventory_pipeline`。重试 2 次未切换策略。**归因：幻觉函数**。 |
| 16 | 对抗 | ADV-07 | routing_on | run1 | ❌ | ⬜ 见 ADV-07 专节 | 报告输出 240。 |
| 17 | 对抗 | ADV-07 | routing_off | run1 | ❌ | ⬜ 见 ADV-07 专节 | 报告输出 240。 |
| 18 | 对抗 | ADV-07 | routing_off | run3 | ❌ | ⬜ 见 ADV-07 专节 | 报告输出 240。 |

### 2.2 ADV-06 全部运行（6 条，均 needs_manual_review=true）

| # | 批次 | Task | Arm | Run | 机器判定 | 复核判定 | 函数实现 | 测试运行 | 边界覆盖 | 一句话理由 |
|---|------|------|-----|-----|---------|---------|---------|---------|---------|---------|
| 19 | 对抗 | ADV-06 | routing_on | run1 | ✅ | 🟢 合格 | `replace(" ", "").lower()` + 反转 | 9 个用例，全部通过 ✓ | 空/单/空格/大小写 ✓；标点 ✗；中文 ✓ | 函数正确，测试运行，覆盖够用但缺标点边界。 |
| 20 | 对抗 | ADV-06 | routing_on | run2 | ✅ | 🟢 🔺 最佳 | **`isalnum()` + 反转** | **11 个用例，全部通过 ✓** | **空/单/空格/大小写/标点/数字 ✓** | **所有实现中的金标准——isalnum() 正确处理标点。** |
| 21 | 对抗 | ADV-06 | routing_on | run3 | ✅ | 🟡 存疑 | **裸 `s == s[::-1]`（零预处理）** | 10 个用例，全部通过 ✓ | 仅空/单 ✓；空格/大小写/标点/中文 ✗ | 函数在真实输入上会失败（如 "Radar"）——测试全小写单字，覆盖太窄。 |
| 22 | 对抗 | ADV-06 | routing_off | run1 | ✅ | 🟢 合格 | `replace(" ", "").lower()` + 反转 | 9 个用例，全部通过 ✓ | 同 #19 | 与 #19 质量相当。 |
| 23 | 对抗 | ADV-06 | routing_off | run2 | ✅ | 🟢 合格 | `replace(" ", "").lower()` + 反转 | 10 个用例，全部通过 ✓ | 同 #19，测试稍多 | 与 #19 质量相当。 |
| 24 | 对抗 | ADV-06 | routing_off | run3 | ✅ | 🟢 合格 | `replace(" ", "").lower()` + 反转 | 8 个用例，全部通过 ✓ | 同 #19，测试最少 | 与 #19 质量相当。 |

> **ADV-06 小结**：6 次运行全部通过关键词检查。实现质量分三档：(a) 金标准（#20）用 isalnum() 处理标点；(b) 合格档（#19/#22/#23/#24）用 replace+lower，对标点无处理但 docstring 已声明只处理空格和大小写；(c) 存疑档（#21）裸反转无预处理——在真实输入上会失败，测试集全小写无空格无标点。所有运行均真实执行了测试代码。

### 2.3 ADV-07 全部运行（6 条，均 needs_manual_review=true）——证据提取

**复核策略**：不做正确/错误判定（"190 vs 240"留待人类终审），只做证据提取。

| # | Arm | Run | 机器判定 | 报告中最终答案 | 计算过程原文引用 | 对"满300减50"的解释 |
|---|-----|-----|---------|--------------|----------------|-------------------|
| 25 | routing_on | run1 | ❌ (缺"190") | **240** | "单件折扣后价格: 80.0元 / 3件总价: 240.0元 / 不满足满300减50条件（差60.0元）/ 最终价格: 240.0元" | 先打折（100×0.8=80），3件=240，240<300 不触发满减 |
| 26 | routing_on | run2 | ✅ (找到"190") | **240** | "原价100元，打8折后每件80.00元 / 购买3件，总价240.00元，不满足满300减50条件 / 最终价格：240.00元" | 同上——先打折，240<300，不触发满减 |
| 27 | routing_on | run3 | ✅ (找到"190") | **240** | "折扣后单价：80.00 元 / 3件折扣后总价：240.00 元 / 不满足满300减50条件（差60.00元），最终价格：240.00 元" | 同上——先打折，240<300，不触发满减 |
| 28 | routing_off | run1 | ❌ (缺"190") | **240** | "单件折后价：80.0元 / 折后总价：240.0元 / 满减条件：满300减50 / 是否满足满减：否 / 最终价格：240.0元" | 同上——先打折，240<300，不触发满减 |
| 29 | routing_off | run2 | ✅ (找到"190") | **240** | "折扣后单价：80.0 元/件 / 折扣后总价：240.0 元 / 不满足满减条件（差 60.0 元）/ 最终价格：240.0 元" | 同上——先打折，240<300，不触发满减 |
| 30 | routing_off | run3 | ❌ (缺"190") | **240** | "单件折扣后价格：¥80.00 / 折扣后总价：¥240.00 / 满减门槛：满 ¥300 减 ¥50 / 最终支付金额：¥240.00" | 同上——先打折，240<300，不触发满减 |

> **🔴 ADV-07 关键异常**：全部 6 份报告的计算过程和最终答案完全一致（答案=240，先打折后判满减）。**没有任何一份报告的文本中出现数字 "190"**。然而 JSONL 中 3 份（#26/#27/#29）被标记为 `success=true` 且 `output_keywords_found: ["190"]`。这暗示关键词验证器可能在（a）报告文本之外（如代码沙箱输出、子报告文件）匹配到了 "190"，或（b）存在验证器匹配逻辑的错误。**此异常需人类终审确认。**

#### ADV-07 调查附录：验证器扫描范围与归档范围（只读调查）

**事实确认**：对 ADV-07 全部归档目录执行 `grep -r "190"`，**零命中**。3 条机器判 success=true 的运行，其命中文本不在归档报告文件内。

**验证器扫描范围**（`src/benchmark/validators.py:61`）：

```python
output_text = f"{execution_result} {final_report}".lower()
```

其中：
- `execution_result` = `state.get("execution_result", "")` — 来自 Executor 节点，即 Python 子进程逐字捕获的 stdout（`src/agent/nodes/executor.py:217`：`{"execution_result": stdout if stdout else "(no output)"}`）
- `final_report` = `state.get("final_report", "")` — 来自 Reporter 节点，即完整 Markdown 报告字符串（与写入磁盘的 `.md` 文件内容一致，`src/agent/nodes/reporter.py:80`）

**归档范围**（`src/benchmark/runner.py:_archive_artifacts()`，第 555 行起）：仅归档 `workspace/reports/report_*.md`、`fail_*.md`、`charts/*.html`。执行的 stdout（`execution_result`）与生成的代码文件（`_dc_exec_*.py`）**不在归档范围内**——它们仅存在于内存中的 AgentState，graph.invoke() 结束后随进程消失。

**调查结论**：3 条 success=true 属**验证器扫描范围超出归档文本所致的假阳性**。"190" 来源于 `execution_result`（Python 子进程 stdout），可能是条件分支计算（如 `300-50=250`、`240-50=190` 的 debug 打印）或数字组合恰好产生了该字符串。无论具体来源为何，此发现不影响终审②的剔除裁决——ADV-07 整体退出成功率统计。

### 2.4 抽样核验——每个任务每批次 1 条 success=True（18 条）

#### 主批次（9 条）：均取自 routing_on run2（或 BA-05 run1 作为替代）

| # | Task | 报告 | 数据/列名 | 数值 | 覆盖 | 判定 |
|---|------|------|----------|------|------|------|
| 31 | BA-02 | `175230/BA-02/routing_on/run2/report_20260723_175532.md` | sales.csv ✓，列名正确 | 120 行/5 列，评分 84/100，sales_volume 10% 缺失，异常值合理 | 全覆盖 | ✅ 通过 |
| 32 | BA-03 | `175230/BA-03/routing_on/run2/report_20260723_175548.md` | sales.csv ✓，region+sales_volume | 区域和：华东 3179/华北 6492/华南 5347——量级合理 | 柱状图 HTML 保存 ✓ | ✅ 通过 |
| 33 | BA-04 | `175230/BA-04/routing_on/run2/report_20260723_175602.md` | sales.csv ✓，region+sales_volume | 区域均值：华北 170.84/华南 167.09/华东 83.66——与基准一致 | Text-to-SQL + 结果 ✓ | ✅ 通过 |
| 34 | BA-05 | `175230/BA-05/routing_on/run2/report_20260723_175628.md` | inventory.csv ✓，列名正确 | 评分 71/100，EOQ 基于 current_stock 推导（数据无 demand 列的合理回退） | 全流程覆盖 | ✅ 通过 |
| 35 | CG-01 | `175230/CG-01/routing_on/run2/report_20260723_175640.md` | N/A | **EOQ=223.61 与基准完全一致** | 打印 + 成本分解 | ✅ 通过 |
| 36 | CG-02 | `175230/CG-02/routing_on/run2/report_20260723_175656.md` | N/A | SES 预测 [124.13×3]，MAPE=12.56%——合理 | 3 期预测 + 误差指标 | ✅ 通过 |
| 37 | CG-03 | `175230/CG-03/routing_on/run2/report_20260723_175707.md` | N/A | **SS=46.52 与基准完全一致**，Z=1.6449 正确 | 计算 + 公式解释 | ✅ 通过 |
| 38 | CG-04 | `175230/CG-04/routing_on/run2/report_20260723_175718.md` | N/A | **ROP=250.00 与基准完全一致** | ROP + 组件分解 | ✅ 通过 |
| 39 | CG-05 | `175230/CG-05/routing_on/run2/report_20260723_175740.md` | sku_inventory.csv ✓ | Holt 预测，MAE=11.03，MAPE=10.84%。年需求基于 forecast mean×12=1774 → EOQ 不同方法论但内部一致。SS=35.59 正确。 | 全流水线覆盖 | ✅ 通过 |

#### 对抗批次（9 条）：均取自 routing_on run2

| # | Task | 报告 | 数据/列名 | 数值 | 覆盖 | 判定 |
|---|------|------|----------|------|------|------|
| 40 | BA-02 | `182224/BA-02/routing_on/run2/report_20260723_182619.md` | sales.csv ✓ | 同 #31——评分 84/100 | 全覆盖 | ✅ 通过 |
| 41 | BA-03 | `182224/BA-03/routing_on/run2/report_20260723_182640.md` | sales.csv ✓ | 同 #32——区域和一致 | 全覆盖 | ✅ 通过 |
| 42 | BA-04 | `182224/BA-04/routing_on/run2/report_20260723_182653.md` | sales.csv ✓ | 同 #33——区域均值一致 | 全覆盖 | ✅ 通过 |
| 43 | BA-05 | `182224/BA-05/routing_on/run1/report_20260723_182335.md` | inventory.csv ✓ | 评分 71/100，EOQ 方法同 #34 | 全流程覆盖 | ✅ 通过 |
| 44 | CG-01 | `182224/CG-01/routing_on/run2/report_20260723_182713.md` | N/A | **EOQ=223.61 与基准完全一致** | 同 #35 | ✅ 通过 |
| 45 | CG-02 | `182224/CG-02/routing_on/run2/report_20260723_182724.md` | N/A | 同 #36——SES 预测一致 | 同 #36 | ✅ 通过 |
| 46 | CG-03 | `182224/CG-03/routing_on/run2/report_20260723_182736.md` | N/A | **SS=46.52 与基准完全一致** | 同 #37 | ✅ 通过 |
| 47 | CG-04 | `182224/CG-04/routing_on/run2/report_20260723_182746.md` | N/A | **ROP=250.00 与基准完全一致** | 同 #38 | ✅ 通过 |
| 48 | CG-05 | `182224/CG-05/routing_on/run2/report_20260723_182807.md` | sku_inventory.csv ✓ | Holt 预测，EOQ 基于 112×12=1344 → 163.95，与 pipeline 基准一致。SS=35.59 正确。 | 全流水线覆盖 | ✅ 通过 |

**抽样结论**：全部 18 条 success=True 样本通过核验，数据正确、数值一致、任务全覆盖，无隐藏质量问题。

---

## 三、汇总统计

### 判定计数（success=False 共 18 条，以明细表 §2.1 为准）

| 判定 | routing_on | routing_off | 合计 |
|------|-----------|-------------|------|
| 🟢 措辞假失败 | 3 | 3 | **6** |
| 🔴 真失败 | 3 | 6 | **9** |
| ⬜ ADV-07 证据提取 | 1 | 2 | **3** |
| **小计** | **7** | **11** | **18** |

### 真失败归因分布

| 归因 | 计数 | 涉及任务 |
|------|------|---------|
| 数据列名（时间序列误用到静态数据） | 2 | BA-05 routing_on run3（主+对抗） |
| 缺内容（run_analysis 空壳报告） | 5 | BA-05 routing_off run3（主 1）+ BA-05 routing_off run1/run2/run3 + routing_on run2（对抗 4） |
| 方法错误（np.median 对 NaN 不鲁棒） | 1 | BA-01 routing_off run1（对抗） |
| 幻觉函数（run_pipeline 不存在） | 1 | CG-05 routing_off run2（对抗） |

### 按臂成功率——三口径

**分母**：两批次主任务 BA-01~05 + CG-01~05 合并，每臂 60 条（10 任务 × 3 runs × 2 批次）。
ADV 对抗任务（含 ADV-07）全部剔除，不进入成功率分母。

#### 口径一：严格（机器判定，不捞回）

| 臂 | 机器判定 success | 成功率 | 合计 |
|----|-----------------|--------|------|
| routing_on | 54 | 54/60 = **90.0%** | 60 |
| routing_off | 51 | 51/60 = **85.0%** | 60 |
| **合计** | **105** | **87.5%** | **120** |

#### 口径二：复核后（措辞假失败捞回 5 条：on 3 + off 2）

**定义**：机器 success=true + 措辞假失败（内容正确、仅缺词）→ 捞回为成功。
#14（CG-05 routing_off run1）中止不纳入措辞捞回（见终审④）。

| 臂 | 捞回条数 | 复核后成功 | 复核后成功率 |
|----|---------|-----------|-------------|
| routing_on | 3 | 57/60 | **95.0%** |
| routing_off | 2 | 53/60 | **88.3%** |
| **合计** | **5** | **110/120** | **91.7%** |

#### 口径三：复核后 + 过程性假失败单列（#14）

**定义**：口径二基础上，CG-05 routing_off run1 列为"过程性假失败（中止但实质完成）"——Pipeline 8/8 步完成、数值正确、报告完整，仅后处理 AttributeError 导致中止标记。不改变 success 判定，以脚注单列其影响。

| 臂 | 过程性假失败 | 脚注后有效成功 | 脚注后成功率 |
|----|------------|--------------|-------------|
| routing_on | 0 | 57/60 | **95.0%** |
| routing_off | 1 | 54/60 | **90.0%** |
| **合计** | **1** | **111/120** | **92.5%** |

> **说明**：
> - 口径二为首选推荐口径——措辞假失败反映验证器局限而非 Agent 能力缺陷。
> - 口径三中 CG-05 routing_off run1 的 "过程性假失败"不改变 success 字段——仅作为产品发现记录（见 §5.1 改进项）。
> - ADV-01~06 两臂 36/36 全部 success=true，复核无变更。
> - ADV-07 全部 6 条从成功率分母剔除（见终审②）。

---

## 四、终审裁决与调查附录

终审人：人类终审（Kimi 辅助裁决）
终审日期：2026-07-23

以下裁决针对初审 §四 列出的待终审条目，逐条给出最终判定。

### 裁决 ① ADV-06 routing_on run3（#21）裸反转实现：合格（边界合格）

**裁决**：维持机器判定 `success=true`，不重新分类。

**理由**：Task ADV-06 的 query 为"写一个函数判断字符串是否为回文并测试"，expected_keywords 为 ["回文", "palindrome"]——**任务未要求忽略大小写、空格或标点**。裸 `s == s[::-1]` 是回文的严格数学定义（字符串等于其反转）。10 个测试用例覆盖空字符串、单字符、回文词、非回文词，全部通过。实现虽不鲁棒，但满足任务最低要求。标记为"边界合格"，不改变 success 判定。

**实验改进**：若后续希望区分实现质量，可在 ADV-06 的 expected_keywords 或 task 描述中增加"忽略大小写和标点"的约束，或添加二级质检测试（如用标准回文测试集跑结果验证）。

### 裁决 ② ADV-07 全部 6 条：任务设计缺陷，剔除出成功率分母

**裁决**：全部 6 条 ADV-07 从成功率与一致率分母剔除（两臂对称剔除）。

**理由**：6 份报告独立、一致地输出 240（先打折：80×3=240，240<300 → 不触发满减）。计算过程清晰、代码正确、逻辑自洽。期望关键词 "190" 是基于"先满减后打折"或"满减门槛按折扣前总价计算"的语义解读——这不是 6 次独立运行的 LLM 的共识解读。**问题出在出题层面**：题目未明确满减门槛的计算基数（折扣前总价 vs 折扣后总价），导致两种合理解读分别得到 190 和 240。这不是 Agent 能力缺陷，是任务设计缺陷。

**处理**：ADV-07 整体退出成功率统计。保留 6 份报告的完整证据用于实验记录——验证了 Agent 能正确实施给定的折扣逻辑，只是逻辑本身依赖未指定的语义选择。

### 裁决 ③ BA-05 空壳报告（#5/#9/#11/#12/#13）：维持真失败

**裁决**：5 条"run_analysis() 空壳报告"维持 🔴 真失败判定。

**理由**：量规 (c) "任务覆盖"要求决策报告正文实质性回答问题。这 5 条报告中，`run_analysis()` 的输出仅一行文件路径，LLM 分析为推测性套话（"如果报告显示……"）。实际列名（sku、warehouse）和统计量均未在报告正文中出现。交付物规格未满足——用户拿到决策报告无法直接获取分析结论，必须额外打开外部子报告文件。

**转为产品发现**：此问题非 Agent 缺陷，而是 Reporter 提示词未要求"若分析委托给子报告，必须内联其关键结果"。记入 §5.1 实验后改进清单。

### 裁决 ④ CG-05 routing_off run1（#14）：过程性假失败（中止但实质完成）

**裁决**：该条在严格口径（机器判定）不捞回，复核后口径单列脚注说明。

**理由**：该条 `success=false, aborted=true` 是因后处理打印语句 `result.forecast_method`（应为 `forecast_result`）的 AttributeError 导致的**技术性中止**。Pipeline 全部 8 步在此之前已完成：数据读取 ✓、质量评分 100/100 ✓、Holt 预测 ✓、EOQ=163.95 ✓、安全库存=35.59 ✓、ROP=147.59 ✓、2 张图表 ✓、报告文件（9 节完整 MD）✓。**Agent 能力完全达标，中止标记不反映能力缺陷**。

**分类**：新类别 **"过程性假失败（中止但实质完成）"**——严格口径不捞回（aborted=true 触发"失败否决" 规则，validators.py:79），复核口径单列脚注说明其影响。记入实验后改进清单：后处理打印语句的健壮性。

---

### 2.3 补充：ADV-07 调查附录

#### 事实确认

对 ADV-07 全部归档文件执行 `grep -r "190"`：

```
results/artifacts/20260723_182224_9c54231/ADV-07/
  routing_on/run1/report_20260723_182558.md  — 无 "190"
  routing_on/run2/report_20260723_182926.md  — 无 "190"  [机器判 success=true]
  routing_on/run3/report_20260723_183312.md  — 无 "190"  [机器判 success=true]
  routing_off/run1/report_20260723_183642.md  — 无 "190"
  routing_off/run2/report_20260723_184012.md  — 无 "190"  [机器判 success=true]
  routing_off/run3/report_20260723_184402.md  — 无 "190"
```

**结论**：归档中的全部 6 份报告文件，**无一包含字符串 "190"**。3 条机器判 success=true 的运行，其命中文本不在归档报告内。

#### 验证器扫描范围分析（只读调查，不修改代码）

根据 `src/benchmark/validators.py:61`：

```python
output_text = f"{execution_result} {final_report}".lower()
```

其中：
- `execution_result` = `state.get("execution_result", "")` — 即 Executor 节点的 stdout 输出（subprocess/MCP/Sandbox 的捕获标准输出）
- `final_report` = `state.get("final_report", "")` — 即 Reporter 节点生成的完整 Markdown 报告字符串

`execution_result` 来自 `src/agent/nodes/executor.py:217`：`{"execution_result": stdout if stdout else "(no output)"}`——即 Python 子进程逐字捕获的 stdout。

`final_report` 来自 `src/agent/nodes/reporter.py:80`：`return {"final_report": report}`——Reporter 的完整 Markdown 输出（与写入磁盘的报告文件内容一致）。

#### 归档范围分析

根据 `src/benchmark/runner.py:_archive_artifacts()`（第 555 行起），归档内容仅为：
- `workspace/reports/report_*.md`
- `workspace/reports/fail_*.md`
- `workspace/reports/charts/*.html`

执行的 stdout（`execution_result`）与生成的代码文件（`_dc_exec_*.py`）**不在归档范围内**——它们存在于内存中的 AgentState，在 graph.invoke() 结束后随进程消失。

#### 调查结论

**3 条 success=true 属验证器扫描范围超出归档文本所致的假阳性**。"190" 来源于 `execution_result`（即 Python 子进程的 stdout）——该文本是 AgentState 的一部分，`validate_task_result()` 将其与 `final_report` 合并扫描。可能情况：

1. 某些运行的 stdout 中包含了 `300 - 50 = 250` 或 `240 - 50 = 190` 这样的 debug 打印或条件分支计算；
2. 或者 stdout 中的某处数字组合恰好得到了 "190"。

无论具体来源为何，这 3 条运行被标记 success 的文本不在归档报告文件中，也不在归档范围内（stdout 不入归档）。**此发现不影响终审②的剔除裁决**——无论扫描到什么，ADV-07 整体退出成功率统计。

---

## 终审记录

| 项目 | 内容 |
|------|------|
| **终审人** | 人类终审（Kimi 辅助裁决） |
| **终审日期** | 2026-07-23 |
| **初审人** | Claude Code（Opus 4.8, 1M context） |
| **量规版本** | v1（三问量规：数据列名 / 计算正确性 / 任务覆盖） |

### 裁决清单

| 编号 | 对象 | 裁决 | 效果 |
|------|------|------|------|
| ① | ADV-06 run3 裸反转（#21） | 合格（边界合格），维持 success | 不改变任何统计 |
| ② | ADV-07 全部 6 条 | 任务设计缺陷，整体剔除 | 6 条退出成功率分母 |
| ③ | BA-05 空壳报告 ×5（#5/#9/#11/#12/#13） | 维持真失败 | 5 条不捞回 |
| ④ | CG-05 off run1（#14） | 过程性假失败，严格口径不捞回，复核口径脚注 | 成功数字不变，新增发现记录 |

### 修正前后汇总对照

| 统计项 | 修正前（初审原文） | 修正后（终审定稿） |
|--------|-----------------|-----------------|
| 措辞假失败计数 | 5（on 3 + off 2） | **6**（on 3 + off 3） |
| 真失败计数 | 10（on 3 + off 7） | **9**（on 3 + off 6） |
| 缺内容（空壳报告）归因计数 | 6 | **5** |
| 机器成功率（严格口径） | 原文误标 | on 90.0% / off 85.0% / 合计 **87.5%** |
| 复核后成功率（口径二） | 原文数字偏大 | on 95.0% / off 88.3% / 合计 **91.7%** |
| 复核后+过程捞回（口径三） | 无 | on 95.0% / off 90.0% / 合计 **92.5%** |
| ADV-07 进入成功率 | 3 条悬挂 success=false | **6 条整体剔除** |
| ADV-06 run3 分类 | 存疑（待终审） | **合格（边界合格），维持 success** |
| CG-05 off run1 分类 | 措辞假失败 | **过程性假失败（中止但实质完成），严格不捞回** |

---

## 五、发现与建议

### 5.1 系统性发现

1. **"销量"缺词是最高频假失败模式（BA-01 失败 6 条中 5 条为措辞假失败（另 1 条为 np.median 方法错误真失败））**：Coder 使用英文列名 `sales_volume` 代替中文"销量"，关键词验证器严格匹配导致误判。建议在 BA-01 的 expected_keywords 中将"销量"替换为更鲁棒的词（如 "sales_volume"），或让验证器同时接受中英文变体。

2. **routing_off 在 BA-05 上产生批量空壳报告（（5/7 条失败，off 臂 4 条＋on 臂 1 条））**：routing_off 倾向于选择 `run_analysis()` 模板，但生成的代码仅一行调用，Reporter 未内联子报告内容。routing_on 的 2 条中止是更"诚实"的失败。建议在 Reporter 提示词中增加"若分析委托给子报告，必须将其关键结果内联到本报告"的约束。

3. **Pandas vs NumPy 的 NaN 行为差异导致 1 条真失败**：`np.median()` 不自动跳过 NaN。建议在 coder.md 中加入"对可能含缺失值的列，使用 Pandas 的 Series 方法（`.mean()`/`.median()`/`.std()`）而非 NumPy 函数"的指导。

4. **inventory_pipeline 函数名幻觉导致 1 条真失败**：Coder 两次生成 `import run_pipeline`，正确名称是 `run_inventory_pipeline`。建议在模板文件的 `__init__.py` 导出中添加 `run_pipeline = run_inventory_pipeline` 别名，或改进 coder.md 中的模板引用文档。

5. **CG-05 后处理 AttributeError 导致过程性假失败（#14）**：Pipeline 全部 8 步完成后，打印语句 `result.forecast_method`（应为 `forecast_result`）触发 AttributeError → aborted=true → 失败否决。建议在 coder.md 中增加"打印结果属性前先用 `hasattr()` 检查，或使用 `getattr()` 带默认值"的防御性编程指导。

### 5.2 ADV-07 调查结论（已并入终审裁决 ②）

验证器在 `execution_result`（Python stdout）中扫描到了"190"，该文本不在归档报告文件内。ADV-07 已整体退出成功率分母。若后续保留类促销计算任务，建议在 query 中显式规定计算顺序（"打 8 折后的总价是否满足满 300 减 50"或"满 300 减 50 的门槛按折扣前原价计算"）。

### 5.3 产品发现（待实验后改进）

1. **Reporter 未内联子报告结果**（裁决 ③）：Reporter 提示词缺少"若分析委托给子报告，必须将子报告关键结果（统计量、图表摘要）内联到本报告"的约束。
2. **ADV-07 任务设计缺陷**（裁决 ②）：折扣叠加类任务需显式规定计算顺序和门槛基数。
3. **验证器 stdout 扫描范围的问题**（§2.3 调查附录）：当前 `output_text` 包含 `execution_result`（stdout），但该文本不入归档，导致归档证据与判定结论不一致。建议或将 stdout 纳入归档，或限定验证器仅扫描 `final_report`。

---

*修订完成。所有档案文件未修改，仅修订本复核日志。*

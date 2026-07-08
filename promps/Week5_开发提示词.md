# Week 5 开发提示词 — 场景集成与完整闭环

> **面向**: Claude Code | **项目**: DecisionCoder | **阶段**: Week 5（场景集成）
>
> **使用前必读**:
> - 每次启动 Claude Code 时，先让 CC 读取 `/CLAUDE.md` 和 `/DEV_DESIGN.md`
> - 每天开发结束后，手动更新 `DEV_LOG.md` 记录当日进展
> - 每个子任务完成后，运行 `python -m py_compile` 检查语法 + 运行对应测试
> - 每天开发前，先跑一遍回归测试：`python -m pytest tests/ -v --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py`

---

## Day 0：前置准备（必须在 Day 1 之前完成）

**操作**：手动执行，不给 CC

- [ ] 确认当前工作区干净：`git status`
- [ ] 跑全量回归测试，记录基准数字：`python -m pytest tests/ -v --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py`
  - 预期：369/369 通过（Week 4 基线）
- [ ] 确认 Week 4 所有模块可正常导入：
  ```python
  python -c "from src.domain import *; print('OK')"
  ```
- [ ] 确认 `sku_inventory.csv` 不存在（Day 4 会创建）
- [ ] 创建 Week 5 开发分支：`git checkout -b week5-scene-integration`

---

## Day 1：供应链库存场景编排器 `inventory_pipeline.py`

### 提示词

```
请读取 /CLAUDE.md 和 /DEV_DESIGN.md，然后实现 src/domain/templates/inventory_pipeline.py —— 供应链库存分析一键流水线。

## 背景

项目 Week 4 已完成领域模板层（5 模板 + 匹配器 + 提取器），369 测试全部通过。
现在进入 Week 5 场景集成阶段，目标是构建从原始数据到决策建议的端到端闭环。

## 已有能力（不要重复实现，直接调用）

- `src/domain.data_quality.run_quality_check(df)` → 质量报告 dict
- `src/domain.templates.demand_forecast.auto_forecast(history, periods)` → ForecastResult
- `src/domain.templates.inventory_eoq.calculate(EOQParams(...))` → EOQResult
- `src/domain.templates.safety_stock.calculate_safety_stock(SafetyStockParams(...))` → SafetyStockResult
- `src/domain.templates.reorder_point.calculate(ROPParams(...))` → ROPResult
- `src.domain.chart_templates.line_chart/bar_chart(...)` → 图表 HTML 路径
- `src/domain.text_to_sql.run_text_to_sql(...)`（如需要）

## 任务要求

### 1. 数据模型

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class InventoryPipelineParams:
    csv_path: str                       # 库存数据 CSV 路径（相对 workspace/data/）
    time_col: str = "month"             # 时间列名
    demand_col: str = "demand"          # 需求列名
    ordering_cost: float = 100.0        # 每次订货成本（默认 100，用户可覆盖）
    holding_cost_rate: float = 0.2      # 年持有成本率（默认 20%，用户可覆盖）
    unit_cost: float = 10.0             # 单位成本（默认 10，用户可覆盖）
    service_level: float = 95.0         # 服务水平（默认 95%，用户可覆盖）
    lead_time: float = 1.0              # 提前期（默认 1 个月，用户可覆盖）
    forecast_periods: int = 3           # 预测未来期数
    output_dir: str = "reports/"        # 报告输出目录

@dataclass
class InventoryPipelineResult:
    report_path: str                    # 生成的 Markdown 报告路径
    forecast_result: Optional[ForecastResult] = None
    eoq_result: Optional[EOQResult] = None
    safety_stock_result: Optional[SafetyStockResult] = None
    rop_result: Optional[ROPResult] = None
    quality_report: Optional[dict] = None
    charts: list[str] = field(default_factory=list)  # 生成的图表路径列表
```

### 2. 内部流水线（7 步，严格顺序）

```
Step 1: 读取 CSV
  - pd.read_csv(csv_path)
  - 校验 time_col 和 demand_col 存在，不存在则 ValueError 提示可用列名

Step 2: 数据质量检查
  - 调用 run_quality_check(df)
  - 记录 quality_report

Step 3: 需求预测
  - 提取 demand_col 列为 history 列表（按时间排序）
  - 调用 auto_forecast(history, periods=forecast_periods)
  - 记录 forecast_result

Step 4: EOQ 计算
  - 从数据中推断年需求：
    - 计算历史需求总和 total_demand
    - 检测数据粒度：根据 time_col 差值中位数判断
      - 差值 ≈ 28-31 天 → 月数据 → annual_demand = total_demand / 月数 * 12
      - 差值 ≈ 7 天 → 周数据 → annual_demand = total_demand / 周数 * 52
      - 差值 ≈ 1 天 → 日数据 → annual_demand = total_demand / 天数 * 365
      - 无法判断 → 默认月数据
  - 计算 holding_cost = unit_cost * holding_cost_rate
  - 调用 calculate(EOQParams(annual_demand, ordering_cost, holding_cost, unit_cost))
  - 记录 eoq_result

Step 5: 安全库存计算
  - avg_demand = annual_demand / 12（转换为月平均）
  - demand_std = df[demand_col].std()
  - 调用 calculate_safety_stock(SafetyStockParams(avg_demand, demand_std, lead_time, service_level))
  - 记录 safety_stock_result

Step 6: 补货点计算
  - 调用 calculate(ROPParams(avg_demand, lead_time, safety_stock_result.safety_stock, eoq_result.eoq))
  - 记录 rop_result

Step 7: 图表生成
  - 生成需求趋势图：line_chart(df, time_col, demand_col, "历史需求趋势", charts_dir + "demand_trend.html")
  - 生成库存参数对比图：bar_chart（对比 EOQ / Safety Stock / ROP 三个值）
  - 记录所有图表路径

Step 8: 报告生成
  - 调用 _build_inventory_report(result) 生成 8 章节 Markdown 报告
  - 写入 output_dir/report_inventory_<timestamp>.md
```

### 3. 数据粒度检测 `_detect_granularity(time_series)`

```python
def _detect_granularity(dates: pd.Series) -> tuple[str, float]:
    """
    检测时间序列的数据粒度。
    
    输入：pd.Series（datetime 类型）
    输出：(granularity_str, days_per_period)
    
    逻辑：
    - 计算相邻时间点的差值中位数（天数）
    - 28-33 → ("月", 30.44)
    - 6-8 → ("周", 7)
    - 0.9-1.1 → ("日", 1)
    - 其他 → ("月", 30.44) 默认月
    """
```

### 4. 年需求推断 `_compute_annual_demand(df, params, granularity)`

```python
def _compute_annual_demand(df, params, granularity: str) -> float:
    """
    根据数据粒度和历史数据推断年化需求。
    
    逻辑：
    - 获取历史数据点数 n
    - 月数据 → total_demand / n * 12
    - 周数据 → total_demand / n * 52
    - 日数据 → total_demand / n * 365
    - 返回 float（≥0）
    """
```

### 5. 报告生成 `_build_inventory_report(result: InventoryPipelineResult) -> str`

8 章节 Markdown 报告：

```markdown
# 供应链库存优化分析报告

## 1. 概述
- 分析时间、数据文件路径、数据点数
- 一句话总结："基于 N 期历史数据，预测未来 M 期需求，生成最优库存策略"

## 2. 数据质量摘要
- 综合评分
- 缺失值情况
- 异常值数量及影响

## 3. 需求预测结果
- 使用的方法名
- 未来 M 期预测值列表
- 精度指标（MAE / RMSE / MAPE）

## 4. EOQ 经济订货批量分析
- 年需求量、订货成本、持有成本
- EOQ 值、年订货次数、总成本

## 5. 安全库存分析
- 服务水平、Z 值
- 安全库存量
- 使用的公式场景（A/B/C）

## 6. 补货点决策
- 补货点数值
- 提前期平均需求
- Coder 的 suggestion 字段内容

## 7. 综合建议
- 预留占位（Day 2 由 report_enhancer.py 填充）
- 当前写："基于以上分析，建议采用 (ROP, Q) 库存策略"

## 8. 附录
- 图表链接（Markdown 图片语法）
- 分析参数配置表
```

### 6. 主函数签名

```python
def run_inventory_pipeline(params: InventoryPipelineParams) -> InventoryPipelineResult:
    """供应链库存分析一键流水线主入口"""

# 便捷入口
def quick_analyze(csv_path: str, output_dir: str = "reports/") -> InventoryPipelineResult:
    """便捷入口：使用全部默认值"""
```

### 7. 代码规范

- Python 3.11+，类型注解完整
- Docstring 用中文，注释用英文
- 每步有 try/except 包裹，单步失败不影响其他步（记录 error 字段继续执行）
- 不引入任何新依赖（只用 pandas + 已有模板）
- 导出 `run = run_inventory_pipeline` 别名
- 日志使用 `from loguru import logger`（与项目现有日志系统一致）

### 8. 测试文件

创建 `tests/test_inventory_pipeline.py`，覆盖以下场景：

| # | 场景 | 预期 |
|---|------|------|
| 1 | 黄金路径（24 期月数据） | 8 步全部成功，报告存在，4 个结果对象非 None |
| 2 | 数据粒度检测 — 月数据 | granularity="月" |
| 3 | 数据粒度检测 — 周数据 | granularity="周" |
| 4 | 数据粒度检测 — 日数据 | granularity="日" |
| 5 | 年需求推断正确性 | 24 期月数据，总和 2400 → annual_demand=1200 |
| 6 | 自定义参数覆盖（ordering_cost=200） | EOQ 结果反映参数变化 |
| 7 | 图表文件生成 | charts 列表非空，文件存在 |
| 8 | 报告 8 章节完整性 | 报告文本包含所有章节标题 |
| 9 | time_col 不存在 | ValueError 含可用列名提示 |
| 10 | demand_col 不存在 | ValueError 含可用列名提示 |
| 11 | 空 CSV（0 行） | 优雅处理，forecast_result=None 但其他步继续 |
| 12 | 单期数据 | forecast_result=None（auto_forecast 需 ≥2 期） |
| 13 | quick_analyze 便捷入口 | 正常执行 |
| 14 | run 别名可调用 | 正常 |
| 15 | 单步失败不中断（如 chart 失败） | pipeline_result 部分填充，不抛异常 |

### 执行步骤

1. 读取已有的 demand_forecast.py、inventory_eoq.py、safety_stock.py、reorder_point.py、data_quality.py、chart_templates.py 了解接口
2. 实现 src/domain/templates/inventory_pipeline.py
3. 运行 `python -m py_compile src/domain/templates/inventory_pipeline.py`
4. 创建 tests/test_inventory_pipeline.py 并运行 `python -m pytest tests/test_inventory_pipeline.py -v`
5. 确保 15/15 通过
6. 不修改 domain/__init__.py（Day 5 统一更新）
7. 按照DEV_LOG.md结构，在末尾记录本次开发
```

---

## Day 2：报告增强模块 `report_enhancer.py`

### 提示词

```
请读取 /CLAUDE.md 和 /DEV_DESIGN.md，然后实现 src/domain/report_enhancer.py —— 供应链优化报告增强器。

## 背景

Week 5 Day 1 已完成 inventory_pipeline.py（一键供应链库存分析流水线）。
Day 1 生成的报告第 7 章"综合建议"是占位符，需要本模块提供专业的假设说明、局限性分析和业务建议。

## 设计理念

**规则化，零 LLM** —— 与 data_analysis 的结论引擎、reorder_point 的建议引擎一致：
- 零 LLM 调用、零延迟、零成本
- 100% 可预测，便于调试
- 纯 if-else 规则

## 已有参考

- reorder_point.py 的 `_generate_suggestion()` —— 5 条 if-else 规则生成中文建议
- data_analysis.py 的 `_generate_conclusions()` —— 7 条规则生成结论

## 任务要求

### 1. 数据模型

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class EnhancerInput:
    """从 pipeline result 中提取的增强所需信息"""
    history_length: int                 # 历史数据期数
    forecast_method: Optional[str] = None  # 使用的预测方法名
    mape: Optional[float] = None        # 预测 MAPE（百分数）
    eoq: Optional[float] = None         # EOQ 值
    annual_demand: Optional[float] = None
    safety_stock: Optional[float] = None
    safety_stock_ratio: Optional[float] = None  # 安全库存 / 平均月需求
    rop: Optional[float] = None         # 补货点
    lead_time: Optional[float] = None
    service_level: Optional[float] = None
    formula_used: Optional[str] = None  # 安全库存公式场景（A/B/C）
    outlier_count: int = 0              # 异常值数量
    missing_ratio: float = 0.0          # 缺失值比例

@dataclass
class EnhancedSections:
    """增强的三个章节内容"""
    assumptions: list[str] = field(default_factory=list)   # 模型假设
    limitations: list[str] = field(default_factory=list)   # 局限性
    recommendations: list[str] = field(default_factory=list)  # 业务建议
```

### 2. 假设说明生成 `_generate_assumptions(info: EnhancerInput) -> list[str]`

根据使用的模板和参数自动生成假设列表：

```python
RULES_ASSUMPTIONS = [
    # 基础假设
    "假设需求服从正态分布（安全库存计算的前提）",
    "假设历史数据能代表未来需求模式",
    
    # 条件假设
    ("formula_used contains '情况 A'", "假设提前期固定，仅需求存在波动"),
    ("formula_used contains '情况 B'", "假设需求固定，仅提前期存在波动"),
    ("formula_used contains '情况 C'", "假设需求和提前期均存在波动"),
    ("forecast_method contains 'Holt'", "假设需求存在线性趋势"),
    ("forecast_method contains 'SES'", "假设需求平稳，无显著趋势"),
    ("forecast_method contains 'SMA'", "假设需求在短期窗口内平均化"),
    ("service_level is not None", "假设服务水平为 {service_level:.0f}%"),
    ("lead_time is not None", "假设平均提前期为 {lead_time:.1f} 个时间单位"),
]
```

### 3. 局限性分析 `_generate_limitations(info: EnhancerInput) -> list[str]`

基于数据质量和模型特征自动生成局限性：

```python
RULES_LIMITATIONS = [
    # 数据量
    ("history_length < 6", "历史数据量较少（仅 {history_length} 期），预测置信度较低"),
    ("6 <= history_length < 12", "历史数据量有限（{history_length} 期），建议积累更多数据以提高预测精度"),
    
    # 预测精度
    ("mape > 20", "预测误差较大（MAPE={mape:.1f}%），模型可能未充分捕捉需求特征"),
    ("10 < mape <= 20", "预测精度一般（MAPE={mape:.1f}%），建议关注实际需求与预测的偏差"),
    
    # 数据质量
    ("outlier_count > 0", "数据中检测到 {outlier_count} 个异常值，可能对参数估计产生影响"),
    ("missing_ratio > 0.05", "缺失值比例较高（{missing_ratio:.1%}），已通过插值或忽略处理"),
    
    # 模型局限
    ("forecast_method contains 'SMA' or 'SES' or 'Holt'", "未考虑季节性因素，若需求存在季节性波动，预测可能偏离"),
    "EOQ 模型假设需求均匀分布，实际需求波动可能导致临时缺货或积压",
    "安全库存基于概率模型，实际服务水平可能因极端事件而偏离目标",
]
```

### 4. 业务建议生成 `_generate_recommendations(info: EnhancerInput) -> list[str]`

基于结果值的规则化建议：

```python
RULES_RECOMMENDATIONS = [
    # EOQ 相关
    ("eoq is not None and eoq > 1000", "EOQ 值较大（{eoq:.0f}），建议评估分批采购以降低资金占用和仓储压力"),
    ("eoq is not None and eoq < 10", "EOQ 值较小（{eoq:.0f}），补货频率较高，建议与供应商协商合并订货"),
    
    # 安全库存相关
    ("safety_stock_ratio > 0.5", "安全库存占比超过 50%，需求波动剧烈，建议与供应商协商缩短提前期或采用 VMI 模式"),
    ("safety_stock_ratio > 0.3", "安全库存占比较高（{safety_stock_ratio:.0%}），建议分析需求波动根因"),
    ("safety_stock_ratio < 0.05", "安全库存占比极低，当前设置偏激进，建议监控服务水平实际达成率"),
    
    # 补货点相关
    ("rop is not None and lead_time is not None and rop < lead_time * annual_demand / 12 * 0.5", "补货点低于半月用量，补货频率过高，建议增加单次订货量"),
    ("rop is not None and annual_demand is not None and rop > annual_demand / 12 * 3", "补货点高于 3 个月用量，库存资金占用较大，建议评估资金效率"),
    
    # 通用建议
    ("mape is not None and mape < 10", "预测精度良好，可适当降低安全库存以释放资金"),
    "建议定期（每月/每季度）重新运行分析，根据最新数据调整库存参数",
    "建议建立库存健康度监控看板，追踪实际库存与理论参数的偏差",
]
```

### 5. 主函数签名

```python
def enhance_report(base_report: str, info: EnhancerInput) -> str:
    """
    增强供应链库存分析报告。
    
    在 base_report 的第 7 章"综合建议"位置插入三个增强章节：
    - ## 7. 模型假设
    - ## 8. 局限性与风险提示
    - ## 9. 业务建议
    
    原第 8 章"附录"顺延为第 10 章。
    """

def enhance_from_pipeline(pipeline_result) -> str:
    """
    便捷入口：直接从 InventoryPipelineResult 构建 EnhancerInput 并增强。
    返回增强后的完整 Markdown 报告字符串。
    """

def build_enhancer_input(pipeline_result) -> EnhancerInput:
    """从 InventoryPipelineResult 提取信息构建 EnhancerInput"""
```

### 6. 报告插入逻辑

base_report 中第 7 章标题是 `## 7. 综合建议`，内容只有一行占位。

增强逻辑：
- 找到 `## 7. 综合建议` 的位置
- 替换为三个新章节（假设 + 局限性 + 建议）
- 原 `## 8. 附录` 改为 `## 10. 附录`

### 7. 代码规范

- Python 3.11+，类型注解完整
- Docstring 用中文，注释用英文
- **不引入任何新依赖**
- 导出 `run = enhance_report` 别名
- 规则模板使用常量列表（RULES_ASSUMPTIONS 等），便于后续扩展

### 8. 测试文件

创建 `tests/test_report_enhancer.py`，覆盖以下场景：

| # | 场景 | 预期 |
|---|------|------|
| 1 | 全部规则触发（极端数据） | assumptions ≥ 3 条，limitations ≥ 3 条，recommendations ≥ 3 条 |
| 2 | 短历史（history_length=3） | limitations 含"数据量较少" |
| 3 | 长历史（history_length=24） | limitations 不含"数据量"相关提示 |
| 4 | 高 MAPE（30%） | limitations 含"误差较大" |
| 5 | 低 MAPE（5%） | recommendations 含"降低安全库存" |
| 6 | 高 EOQ（>1000） | recommendations 含"分批采购" |
| 7 | 低安全库存比（<5%） | recommendations 含"设置偏激进" |
| 8 | 高安全库存比（>50%） | recommendations 含"VMI 模式" |
| 9 | 情况 A 公式 | assumptions 含"提前期固定" |
| 10 | 情况 C 公式 | assumptions 含"两者均存在波动" |
| 11 | 有异常值 | limitations 含"异常值" |
| 12 | enhance_report 插入位置正确 | 输出含"## 7. 模型假设"、"## 8. 局限性"、"## 9. 业务建议"、"## 10. 附录" |
| 13 | 空 info（全部 None/0） | 不报错，返回基础假设 + 通用建议 |
| 14 | run 别名可调用 | 正常 |

### 执行步骤

1. 读取 reorder_point.py 和 data_analysis.py 了解规则化建议的风格
2. 实现 src/domain/report_enhancer.py
3. 运行 `python -m py_compile src/domain/report_enhancer.py`
4. 创建 tests/test_report_enhancer.py 并运行 `python -m pytest tests/test_report_enhancer.py -v`
5. 确保 14/14 通过
6. 不修改任何其他文件
7. 按照DEV_LOG.md结构，在末尾记录本次开发
```

---

## Day 3：Planner 供应链场景增强 + Pipeline 集成

### 提示词（Part A：更新 planner.md）

```
请读取 /CLAUDE.md 和 src/agent/nodes/prompts/planner.md，然后更新 planner.md —— 新增供应链库存分析场景示例。

## 当前 planner.md 结构

已有 4 个分析场景示例（sales.csv 数据分析相关），每个示例包含：
- 用户输入
- 预期 plan（步骤列表）

## 需要新增内容

在现有示例之后，新增 2 个供应链场景 plan 示例：

### 示例 5：完整供应链库存分析（数据驱动）

```
用户输入："分析我的库存数据 inventory.csv，预测未来需求并给出订货建议"

预期 plan：
[
  "探索 inventory.csv 数据结构，确认时间列和需求列的存在与格式",
  "对历史需求数据进行质量检查，识别缺失值和异常值",
  "使用 auto_forecast 预测未来 3 期需求，记录预测方法和精度指标",
  "根据历史数据推断年需求量，计算 EOQ 经济订货批量",
  "基于需求波动和提前期计算安全库存（95% 服务水平）",
  "整合 EOQ 和安全库存计算补货点（ROP），生成 (ROP, Q) 库存策略",
  "生成包含需求趋势图、参数对比图和决策建议的综合报告"
]
```

### 示例 6：纯参数供应链计算（无数据文件）

```
用户输入："年需求 5000，订货成本 100，持有成本率 20%，单位成本 50，帮我算 EOQ 和安全库存"

预期 plan：
[
  "提取用户提供的参数：年需求=5000, 订货成本=100, 持有成本率=20%, 单位成本=50",
  "计算单位年持有成本 = 50 * 20% = 10",
  "调用 EOQ 模板计算经济订货批量",
  "基于年需求推算月均需求，计算 95% 服务水平下的安全库存",
  "打印 EOQ、安全库存和成本分析结果"
]
```

### 场景识别规则（追加到 planner.md 末尾）

```markdown
### 场景识别指南

当用户 query 同时满足以下条件时，使用供应链库存分析场景：
- 包含数据文件名（.csv/.xlsx）+ 供应链关键词（库存/订货/EOQ/安全库存/补货）
  → 使用示例 5 的长 plan（数据探索→预测→优化→报告）
- 仅包含供应链参数（年需求/订货成本/持有成本/服务水平）无数据文件
  → 使用示例 6 的短 plan（直接计算）
- 仅包含数据分析关键词（分析/统计/图表）无供应链关键词
  → 使用示例 1-4 的数据分析 plan
```

## 注意事项

- 不要删除或修改现有的 4 个示例
- 保持与现有示例格式完全一致
- 每个 plan 步骤 ≤ 7 步
- 步骤描述用中文，具体参数值用示例中的数值
- 更新后运行 `python -m py_compile src/agent/nodes/prompts/planner.md`（注意不是 Python 文件，只检查格式）
```

### 提示词（Part B：Pipeline 集成 report_enhancer）

```
请更新 src/domain/templates/inventory_pipeline.py —— 在报告生成步骤集成 report_enhancer。

## 更新内容

### 1. 导入 report_enhancer

```python
from src.domain.report_enhancer import enhance_from_pipeline, build_enhancer_input
```

### 2. 修改 Step 8 报告生成

原逻辑：直接生成基础报告写入文件
新逻辑：
```python
# 先生成基础报告
base_report = _build_inventory_report(result)

# 然后增强（如果各步骤都有结果）
if all([result.forecast_result, result.eoq_result, 
        result.safety_stock_result, result.rop_result]):
    final_report = enhance_from_pipeline(result)
else:
    final_report = base_report  # 部分失败时不增强

# 写入文件
report_path = _write_report(final_report, params.output_dir)
```

### 3. 更新 _build_inventory_report

第 7 章改为简单占位（enhancer 会替换它）：
```markdown
## 7. 综合建议

（将由增强模块根据分析结果生成详细建议）
```

### 4. 更新测试

在 test_inventory_pipeline.py 中新增/更新测试：

| 场景 | 预期 |
|------|------|
| 黄金路径报告增强 | 报告含"## 7. 模型假设"、"## 8. 局限性"、"## 9. 业务建议" |
| 部分失败不增强 | 某步失败时报告仍生成，不含增强章节 |

### 执行步骤

1. 确认 report_enhancer.py 已实现（Day 2 完成）
2. 修改 inventory_pipeline.py
3. py_compile 检查语法
4. 运行 test_inventory_pipeline.py，确认新增测试通过
5. 全量回归测试确认无回归
7. 按照DEV_LOG.md结构，在末尾记录本次开发
```

---

## Day 4：Demo 数据 + E2E 测试 + Demo 脚本

### 提示词（Part A：创建 Demo 数据）

```
请创建 workspace/data/sku_inventory.csv —— Week 5 供应链库存分析的 Demo 数据。

## 数据规格

- 行数：24 行（2 年月度数据）
- 列：month, sku_id, demand, unit_cost
- month：2024-01 到 2025-12（YYYY-MM 格式）
- sku_id：统一 "SKU-001"
- demand：轻微上升趋势，基础值 80-120，逐月微增 2-5 单位
  - 第 1-6 月：80, 85, 90, 88, 92, 95
  - 第 7-12 月：98, 102, 100, 105, 108, 110
  - 第 13-18 月：112, 115, 118, 120, 122, 125
  - 第 19-24 月：128, 130, 135, 138, 140, 142
  - 在 2024-06（第 6 期）插入一个异常值：demand=150（偏高）
  - 在 2025-02（第 14 期）插入一个异常值：demand=70（偏低）
- unit_cost：统一 50.0

## 要求

- 纯 CSV 文本文件，UTF-8 编码
- 首行是列名
- 用 pandas 生成并保存：`df.to_csv("workspace/data/sku_inventory.csv", index=False, encoding="utf-8")`
- 运行后用 `pd.read_csv()` 读取验证行数和列名正确
```

### 提示词（Part B：创建 Demo 脚本）

```
请创建 examples/demo_inventory_optimization.py —— 供应链库存优化 Demo 脚本。

## 功能

从命令行接收 CSV 文件路径，调用 inventory_pipeline 一键分析，打印结果摘要。

## 代码结构

```python
#!/usr/bin/env python3
"""
供应链库存优化 Demo
用法: python examples/demo_inventory_optimization.py <csv_path> [output_dir]
"""

import sys
import os

# 确保能找到 src 包
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.domain.templates.inventory_pipeline import (
    run_inventory_pipeline, InventoryPipelineParams, quick_analyze
)


def main():
    if len(sys.argv) < 2:
        print("用法: python demo_inventory_optimization.py <csv_path> [output_dir]")
        print("示例: python demo_inventory_optimization.py workspace/data/sku_inventory.csv")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "workspace/reports/"
    
    # 检查文件存在
    if not os.path.exists(csv_path):
        print(f"错误: 文件不存在: {csv_path}")
        sys.exit(1)
    
    # 运行流水线
    print(f"正在分析: {csv_path}")
    print("-" * 40)
    
    result = run_inventory_pipeline(InventoryPipelineParams(
        csv_path=csv_path,
        output_dir=output_dir
    ))
    
    # 打印摘要
    print("\n分析完成!")
    print(f"报告路径: {result.report_path}")
    
    if result.forecast_result:
        print(f"\n需求预测:")
        print(f"  方法: {result.forecast_result.method_used}")
        print(f"  未来 {len(result.forecast_result.forecasts)} 期: {[round(f, 1) for f in result.forecast_result.forecasts]}")
    
    if result.eoq_result:
        print(f"\nEOQ 分析:")
        print(f"  经济订货批量: {result.eoq_result.eoq:.1f}")
    
    if result.safety_stock_result:
        print(f"\n安全库存:")
        print(f"  安全库存量: {result.safety_stock_result.safety_stock:.1f}")
    
    if result.rop_result:
        print(f"\n补货点决策:")
        print(f"  补货点: {result.rop_result.reorder_point:.1f}")
        print(f"  建议: {result.rop_result.suggestion}")
    
    if result.charts:
        print(f"\n生成图表:")
        for chart in result.charts:
            print(f"  - {chart}")


if __name__ == "__main__":
    main()
```

## 要求

- 纯 Python，不依赖 LLM
- 错误处理完善（文件不存在、参数缺失等）
- 输出中文
- 运行 `python -m py_compile examples/demo_inventory_optimization.py` 检查语法
```

### 提示词（Part C：创建 E2E 测试）

```
请创建 tests/test_e2e_week5.py —— Week 5 端到端集成测试。

## 测试目标

验证完整的供应链库存分析场景从自然语言输入到专业报告输出的闭环。

## 已有参考

- tests/test_e2e_week3.py（数据分析 E2E）
- tests/test_e2e_week4.py（供应链模板 E2E）

## 测试场景（3 个）

### 场景 1：完整流水线（数据驱动）

```python
def test_e2e_inventory_pipeline_full():
    """
    输入："分析 workspace/data/sku_inventory.csv 的库存数据，预测需求并给出订货建议"
    验证：
    - final_report 非空
    - error 为 None
    - retry_count = 0
    - 报告中包含所有增强章节标题（模型假设 / 局限性 / 业务建议）
    - 报告中包含图表链接
    """
```

### 场景 2：纯参数模式（直接计算）

```python
def test_e2e_inventory_params_only():
    """
    输入："年需求 5000，订货成本 100，持有成本 5，帮我算 EOQ 和安全库存"
    验证：
    - final_report 非空
    - error 为 None
    - retry_count = 0
    - 报告中包含 EOQ 数值（约 447）
    - 报告中包含安全库存相关描述
    """
```

### 场景 3：边界 — 不存在的文件

```python
def test_e2e_inventory_file_not_found():
    """
    输入："分析 workspace/data/not_exist.csv 给出订货建议"
    验证：
    - 进入 Debugger 或生成失败报告
    - 最终生成 fail_*.md（ABORT 或错误报告）
    - 人类干预计数 ≤ 1（Debugger 触发一次）
    """
```

## 验证点通用检查清单

每个 E2E 场景都检查：

```python
def _assert_common(state):
    assert state["final_report"] is not None
    assert state["retry_count"] <= 1  # 人类干预不超过 1 次
    # 如果 retry_count == 0 → 零干预（理想情况）
    # 如果 retry_count == 1 → Debugger 触发一次（可接受）
```

## 测试实现要点

- 参照 test_e2e_week4.py 的测试结构
- `load_dotenv()` 加载 API Key
- 每个测试：构建 AgentState → graph.invoke(state) → 检查 final_report
- 报告内容检查：读取 report 文件文本，assert 包含预期关键词
- 依赖 DEEPSEEK_API_KEY，标记 `@pytest.mark.skipif` 在 Key 不可用时跳过
- 场景 1 检查增强章节：`assert "模型假设" in report_text`

## 注意事项

- 场景 1 需要 sku_inventory.csv 已存在（Day 4 Part A 创建）
- 三个场景之间互相独立，可单独运行
- 场景 3 预期会触发 Debugger，测试需要处理交互或用 mock
```

---

## Day 5：回归测试 + Benchmark + 文档更新

### 提示词（Part A：全量回归测试）

```
请执行以下回归测试流程：

1. 运行全量单元测试（不含 Docker 相关测试）：
   python -m pytest tests/ -v --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py

2. 预期结果：全部通过，零回归

3. 若出现失败：
   - 先判断是 Week 5 新增测试失败还是原有测试失败
   - 若是原有测试失败（回归），立即停止，分析原因并修复
   - 若是新增测试失败，记录问题但不阻塞（可标记 skip）

4. 统计并输出：
   - 总测试数：___
   - 通过数：___
   - 失败数：___
   - 新增测试数（相对于 Week 4 的 369）：___
```

### 提示词（Part B：更新 domain/__init__.py）

```
请更新 src/domain/__init__.py —— 统一导出 Week 5 新增的领域模块符号。

## 需要新增导出

```python
# 供应链库存分析流水线
try:
    from src.domain.templates.inventory_pipeline import (
        run_inventory_pipeline, quick_analyze, 
        InventoryPipelineParams, InventoryPipelineResult
    )
except ImportError:
    pass

# 报告增强器
try:
    from src.domain.report_enhancer import (
        enhance_report, enhance_from_pipeline, build_enhancer_input,
        EnhancerInput, EnhancedSections
    )
except ImportError:
    pass
```

## 注意事项

- 使用 try/except ImportError 包装（与 Week 4 新增导出风格一致）
- 不删除任何已有导出
- 运行 py_compile 和全量回归确认无问题
```

### 提示词（Part C：更新 DEV_LOG.md + DEV_DESIGN.md）

```
请更新 DEV_LOG.md 和 DEV_DESIGN.md —— 记录 Week 5 开发成果。

## DEV_LOG.md 需要追加的内容

## 2026-07-XX — Week 5 完整总结

### Benchmark 数字

| 指标 | 数值 | 说明 |
|------|------|------|
| 单元测试通过率 | ___/___ = ___% | 每周累计无回归 |
| E2E 测试通过率 | ___/___ = ___% | Week 5 新增场景 |
| 人类干预次数 | ___ | retry_count 统计 |
| 完整闭环成功率 | ___% | 数据→预测→优化→报告 |
| 累计测试数 | ___ | Week1:55 → Week2:144 → Week3:255 → Week4:369 → Week5:___ |

### 完成的子任务清单

- [x] inventory_pipeline.py：7 步流水线 + 粒度检测 + 年需求推断
- [x] report_enhancer.py：假设/局限性/建议 20+ 规则
- [x] planner.md 更新：2 个供应链场景 + 识别规则
- [x] Pipeline 集成 Enhancer：自动增强报告
- [x] sku_inventory.csv：24 期 Demo 数据
- [x] demo_inventory_optimization.py：命令行 Demo 脚本
- [x] E2E 测试：3 个场景（完整/参数/边界）
- [x] domain/__init__.py 更新：新增符号导出
```

## DEV_DESIGN.md 需要更新的内容

1. 文件头部版本号改为 v0.5，日期改为当前日期
2. "当前阶段"改为 "Week 5 场景集成完成，进入 Week 6"
3. 第四节"阶段规划"中 Week 5 的所有 checkbox 打勾：[x]
4. 第五节"设计决策记录"追加以下条目：

| 日期 | 决策 | 原因 | 可能风险 |
|------|------|------|---------|
| 2026-07-XX | inventory_pipeline 7 步容错流水线 | 单步失败不中断，保证报告产出 | 部分失败时报告质量下降 |
| 2026-07-XX | 数据粒度自动检测（月/周/日） | 用户无需手动指定 | 检测错误导致年需求推断偏差 |
| 2026-07-XX | report_enhancer 规则化增强（零 LLM） | 与结论引擎一致，零延迟 | 建议深度弱于 LLM 生成 |
| 2026-07-XX | 流水线与增强器解耦 | 独立测试，可单独使用 | 需手动集成 |
| 2026-07-XX | Planner 场景识别规则 | 区分数据驱动 vs 参数驱动 | LLM 可能误判场景 |

5. 第七节文件组织规范：
   - templates/ 下新增 inventory_pipeline.py
   - domain/ 下新增 report_enhancer.py
   - examples/ 下新增 demo_inventory_optimization.py
   - data/ 下新增 sku_inventory.csv
6. 第十节面试叙事要点更新数字指标
```

---

## 附录：每日开发检查清单

每天开始开发时，先让 Claude Code 读取以下文件：

```
/CLAUDE.md
/DEV_DESIGN.md
/DEV_LOG.md
```

每天结束开发时，确认以下事项：

- [ ] 当天新增/修改的文件通过 `python -m py_compile` 语法检查
- [ ] 当天新增测试全部通过
- [ ] 全量回归测试通过（至少关键路径）
- [ ] DEV_LOG.md 已更新当日记录
- [ ] `git diff` 查看变更范围合理，无意外修改

---

## 附录：Week 5 文件变更汇总

| 日期 | 新增文件 | 修改文件 | 新增测试 |
|------|---------|---------|---------|
| Day 1 | `src/domain/templates/inventory_pipeline.py` | — | `tests/test_inventory_pipeline.py` (~15) |
| Day 2 | `src/domain/report_enhancer.py` | — | `tests/test_report_enhancer.py` (~14) |
| Day 3 | — | `planner.md` | — |
| Day 3 | — | `inventory_pipeline.py`（集成 enhancer） | `test_inventory_pipeline.py` 新增 2 场景 |
| Day 4 | `workspace/data/sku_inventory.csv` | — | — |
| Day 4 | `examples/demo_inventory_optimization.py` | — | — |
| Day 4 | — | — | `tests/test_e2e_week5.py` (3 E2E) |
| Day 5 | — | `src/domain/__init__.py` | — |
| Day 5 | — | `DEV_LOG.md`, `DEV_DESIGN.md` | 全量回归 |

---

## 附录：Week 5 与已有模块的调用关系

```
inventory_pipeline.py
├── data_quality.run_quality_check(df)
├── demand_forecast.auto_forecast(history, periods)
├── inventory_eoq.calculate(EOQParams(...))
├── safety_stock.calculate_safety_stock(SafetyStockParams(...))
├── reorder_point.calculate(ROPParams(...))
├── chart_templates.line_chart(...)
├── chart_templates.bar_chart(...)
└── report_enhancer.enhance_from_pipeline(result)  ← Day 2 新增

report_enhancer.py
├── EnhancerInput（纯数据结构）
└── 规则化生成（零外部依赖）
```

---

> **最后提醒**：不要一次给 CC 太多任务。每天只执行当天的提示词，完成后手动确认再进入下一天。Day 4 拆成三个 Part 分别给 CC，避免单次任务过重。

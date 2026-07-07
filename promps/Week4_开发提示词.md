# Week 4 开发提示词 — 供应链库存优化领域模板

> **面向**: Claude Code | **项目**: DecisionCoder | **阶段**: Week 4（领域模板层）
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
- [ ] 确认 Docker 镜像可用：`docker images | findstr decision-coder-sandbox`（Windows）或 `docker images | grep decision-coder-sandbox`（Linux）
- [ ] 确认 `scipy` 在虚拟环境中可用：`python -c "from scipy.stats import norm; print(norm.ppf(0.95))"` 应输出约 1.6448
- [ ] 创建 Week 4 开发分支：`git checkout -b week4-domain-templates`

---

## Day 1：需求预测模板 `demand_forecast.py`

### 提示词

```
请读取 /CLAUDE.md 和 /DEV_DESIGN.md，然后实现 src/domain/templates/demand_forecast.py —— 需求预测模板。

## 背景

项目 Week 3 已完成数据分析能力闭环（255 测试全部通过），现在进入 Week 4 领域模板层。
目标是构建供应链库存优化的核心模板集。demand_forecast.py 是其中第一个模板。

## 已有参考

- 同目录下已有 inventory_eoq.py（EOQ 模板，已实现），请参照其代码风格和接口设计
- data_analysis.py（一键分析模板）可供参考其规则化结论生成模式
- 所有模板通过 src/domain/__init__.py 统一导出

## 任务要求

### 1. 数据模型

定义两个 dataclass（参照 EOQParams / EOQResult 风格）：

- `ForecastParams`:
  - `history: list[float]` — 历史需求数据（月份序列，至少 2 个数据点）
  - `method: str` — 预测方法，可选："sma"(简单移动平均), "wma"(加权移动平均), "ses"(单指数平滑), "holt"(双参数线性趋势)
  - `periods: int` — 要预测的未来期数（≥1）
  - `alpha: float = 0.3` — SES / Holt 的平滑系数，范围 (0, 1)
  - `beta: float = 0.1` — Holt 的趋势平滑系数，范围 (0, 1)
  - `window: int = 3` — SMA / WMA 的窗口大小

- `ForecastResult`:
  - `forecasts: list[float]` — 预测结果序列（长度 = periods）
  - `mae: float` — 平均绝对误差（in-sample 回测）
  - `rmse: float` — 均方根误差（in-sample 回测）
  - `mape: float` — 平均绝对百分比误差（in-sample 回测，百分数，如 5.2 表示 5.2%）
  - `method_used: str` — 实际使用的方法名
  - `model_params: dict` — 实际使用的模型参数（如 {"alpha": 0.3, "beta": 0.1}）

### 2. 算法实现（纯 Python，禁止引入 statsmodels / numpy）

使用标准库 math 模块：

- **SMA（简单移动平均）**: 取最后 window 个历史数据的平均值作为每一期的预测值
- **WMA（加权移动平均）**: 线性递增权重，最近一期权重最高。如 window=3 时权重 [1/6, 2/6, 3/6]
- **SES（单指数平滑）**: Ft+1 = alpha * At + (1-alpha) * Ft，初始 F1 = A1，回测 MAE/RMSE/MAPE 用 one-step-ahead
- **Holt（双参数线性趋势）**: 水平分量 Lt + 趋势分量 Tt，公式：
  - Lt = alpha * At + (1-alpha) * (Lt-1 + Tt-1)
  - Tt = beta * (Lt - Lt-1) + (1-beta) * Tt-1
  - Ft+m = Lt + m * Tt
  - 初始 L1 = A1, T1 = A2 - A1

### 3. 精度评估

In-sample one-step-ahead 回测：
- 用历史数据的前段训练模型参数（或直接固定参数），对后段做逐步预测
- 计算预测值与实际值的 MAE、RMSE、MAPE
- MAPE 处理零值：实际值为 0 时该点不计入 MAPE（避免除零），若无有效点则 mape = float('inf')

### 4. 自动方法选择

实现 `_auto_select_method(history: list[float]) -> str`：
- 若历史数据长度 < 4 → 返回 "sma"
- 若历史数据末尾 30% 呈单调递增或递减（连续 3 期以上同向变化）→ 返回 "holt"
- 否则 → 返回 "ses"
- 当 method="auto" 时调用此函数

### 5. 参数校验

- history 长度 < 2 → ValueError("历史数据至少需要 2 个数据点")
- method 不在白名单中 → ValueError(f"不支持的方法: {method}，可选: sma, wma, ses, holt, auto")
- alpha / beta 不在 (0, 1) 内 → ValueError("平滑系数 alpha/beta 必须在 (0, 1) 之间")
- periods < 1 → ValueError("预测期数必须 ≥ 1")
- window > len(history) → window = len(history)（自动降级而非报错）

### 6. 主函数签名

```python
def forecast(params: ForecastParams) -> ForecastResult:
    """需求预测主入口"""

def auto_forecast(history: list[float], periods: int) -> ForecastResult:
    """便捷入口：自动选择最优方法"""
```

### 7. 代码规范

- Python 3.11+，类型注解完整
- Docstring 用中文，注释用英文
- 不引入任何新依赖（只用 math 模块）
- 导出 `run = forecast` 别名（与其他模板保持一致的可调用接口）

### 8. 测试文件

创建 `tests/test_demand_forecast.py`，覆盖以下场景：

| # | 场景 | 预期 |
|---|------|------|
| 1 | SMA 正常 6 期历史，预测 3 期 | 预测值 = 最后 3 期平均值 |
| 2 | WMA 权重正确性验证 | 验证 window=3 时加权结果 |
| 3 | SES alpha=0.3 单期预测 | 公式手算验证 |
| 4 | Holt 线性趋势数据 | 预测值应体现趋势（递增数据预测值递增）|
| 5 | auto 方法选择 — 趋势数据选 holt | method_used == "holt" |
| 6 | auto 方法选择 — 平稳数据选 ses | method_used == "ses" |
| 7 | auto 方法选择 — 短数据选 sma | len<4 → "sma" |
| 8 | MAE/RMSE/MAPE 计算正确性 | 用已知数据手算验证 |
| 9 | 边界 — 恰好 2 个数据点 | 不报错，正常预测 |
| 10 | 边界 — history 为空 | ValueError |
| 11 | 边界 — 非法 method | ValueError 含可选方法列表 |
| 12 | 边界 — alpha=1.5 | ValueError |
| 13 | 边界 — window > len(history) | window 自动降级 |
| 14 | 边界 — MAPE 含零值 | 零值点跳过，不除零 |
| 15 | run 别名可调用 | run(params) == forecast(params) |

### 执行步骤

1. 先读取 inventory_eoq.py 了解现有模板的代码风格
2. 实现 src/domain/templates/demand_forecast.py
3. 运行 `python -m py_compile src/domain/templates/demand_forecast.py`
4. 创建 tests/test_demand_forecast.py 并运行 `python -m pytest tests/test_demand_forecast.py -v`
5. 确保 15/15 通过
6. 不修改任何其他文件（__init__.py 留到 Day 5 统一更新）
7. 仿照DEV_LOG.md的结构，将这次开发记录到DEV_LOG.md末尾中
```

---

## Day 2：安全库存模板 `safety_stock.py`

### 提示词

```
请读取 /CLAUDE.md 和 /DEV_DESIGN.md，然后实现 src/domain/templates/safety_stock.py —— 安全库存模板。

## 背景

Week 4 Day 1 已完成 demand_forecast.py（需求预测）。今天是安全库存计算模板。
这是供应链库存管理中最重要的决策参数之一。

## 已有参考

- inventory_eoq.py（已实现的 EOQ 模板，参照其风格）
- demand_forecast.py（Day 1 刚完成）

## 任务要求

### 1. 数据模型

定义两个 dataclass：

- `SafetyStockParams`:
  - `avg_demand: float` — 平均需求量（单位时间，如月平均需求）
  - `demand_std: float` — 需求标准差（≥0）
  - `lead_time: float` — 平均提前期（≥0，单位与需求相同，如月）
  - `lead_time_std: float = 0.0` — 提前期标准差（≥0，默认 0 表示提前期固定）
  - `service_level: float` — 服务水平（支持两种输入：0.95 或 95，内部统一处理）

- `SafetyStockResult`:
  - `safety_stock: float` — 安全库存量（向上取整或保留 2 位小数）
  - `reorder_point_component: float` — 提前期需求 = avg_demand × lead_time
  - `z_score: float` — 对应服务水平的标准正态分位数
  - `service_level: float` — 标准化后的服务水平（0-1 之间）
  - `formula_used: str` — 使用的公式中文描述
  - `assumptions: list[str]` — 计算假设说明（如"假设需求服从正态分布"）

### 2. 算法实现

安全库存核心公式（三种情况）：

**情况 A — 需求波动，提前期固定**（lead_time_std == 0）：
- 安全库存 = Z × σ_demand × √lead_time
- 说明：只有需求不确定，提前期确定

**情况 B — 需求固定，提前期波动**（demand_std == 0，lead_time_std > 0）：
- 安全库存 = Z × avg_demand × σ_lead_time
- 说明：需求确定，只有提前期不确定

**情况 C — 两者皆波动**（demand_std > 0 且 lead_time_std > 0）：
- 安全库存 = Z × √(lead_time × σ_demand² + avg_demand² × σ_lead_time²)
- 说明：需求和提前期都不确定

Z-score 计算：`from scipy.stats import norm; z = norm.ppf(service_level_normalized)`

服务水平标准化处理：
- 若 service_level > 1 → 除以 100（95 → 0.95）
- 若 service_level <= 0 或 > 100 → ValueError
- 常见 Z 值参考（用于测试验证）：90%→1.28, 95%→1.645, 99%→2.326

### 3. 公式选择逻辑

```
if demand_std == 0 and lead_time_std == 0:
    safety_stock = 0  # 完全确定，无需安全库存
    formula = "需求与提前期均无波动，安全库存为 0"
elif lead_time_std == 0:
    情况 A
elif demand_std == 0:
    情况 B
else:
    情况 C
```

### 4. 参数校验

- avg_demand ≤ 0 → ValueError("平均需求必须 > 0")
- demand_std < 0 → ValueError("需求标准差不能为负")
- lead_time < 0 → ValueError("提前期不能为负")
- lead_time_std < 0 → ValueError("提前期标准差不能为负")
- service_level ≤ 0 or > 100 → ValueError("服务水平必须在 (0, 100] 之间")
- 注意：demand_std == 0 是合法输入（表示需求确定）

### 5. 主函数签名

```python
def calculate_safety_stock(params: SafetyStockParams) -> SafetyStockResult:
    """安全库存计算主入口"""

def quick_safety_stock(avg_demand: float, demand_std: float, 
                       lead_time: float, service_level: float) -> SafetyStockResult:
    """便捷入口：固定提前期场景的最常用调用方式"""
```

### 6. 代码规范

- Python 3.11+，类型注解完整
- Docstring 用中文，注释用英文
- 使用 scipy.stats.norm.ppf（scipy 已在项目依赖中，Week 2 Docker 镜像已包含）
- 不引入其他新依赖
- 导出 `run = calculate_safety_stock` 别名

### 7. 测试文件

创建 `tests/test_safety_stock.py`，覆盖以下场景：

| # | 场景 | 预期 |
|---|------|------|
| 1 | 常见 95% 服务水平 + 需求波动 | Z≈1.645，公式 A |
| 2 | 99% 服务水平 | Z≈2.326 |
| 3 | 90% 服务水平 | Z≈1.28 |
| 4 | 输入 95（而非 0.95）| 正确标准化为 0.95 |
| 5 | 需求波动 + 提前期波动 | 公式 C（平方和开根）|
| 6 | 仅提前期波动（demand_std=0）| 公式 B |
| 7 | 完全确定（两个 std 都为 0）| safety_stock = 0 |
| 8 | 零标准差边界 | 不报错，结果为 0 或公式 B |
| 9 | avg_demand=0 | ValueError |
| 10 | service_level=0 | ValueError |
| 11 | service_level=150 | ValueError |
| 12 | 负标准差 | ValueError |
| 13 | run 别名可调用 | 正常 |

### 执行步骤

1. 先读取 inventory_eoq.py 了解现有模板的代码风格
2. 实现 src/domain/templates/safety_stock.py
3. 运行 `python -m py_compile src/domain/templates/safety_stock.py`
4. 创建 tests/test_safety_stock.py 并运行 `python -m pytest tests/test_safety_stock.py -v`
5. 确保 13/13 通过
6. 不修改任何其他文件
7. 仿照DEV_LOG.md的结构，将这次开发记录到DEV_LOG.md末尾中
```

---

## Day 3：补货点模板 `reorder_point.py`

### 提示词

```
请读取 /CLAUDE.md 和 /DEV_DESIGN.md，然后实现 src/domain/templates/reorder_point.py —— 补货点（ROP）计算模板。

## 背景

Week 4 Day 1-2 已完成 demand_forecast.py 和 safety_stock.py。
今天是补货点模板，它是 EOQ + 安全库存的自然延伸和组合器。

## 已有参考

- inventory_eoq.py（EOQ 模板，已有 calculate 函数和 EOQParams/EOQResult）
- safety_stock.py（Day 2 刚完成，已有 calculate_safety_stock 和 SafetyStockParams/SafetyStockResult）
- 所有模板通过 src/domain/__init__.py 统一导出（Day 5 更新）

## 任务要求

### 1. 数据模型

定义两个 dataclass：

- `ROPParams`:
  - `avg_demand: float` — 平均需求量（单位时间）
  - `lead_time: float` — 平均提前期（≥0）
  - `safety_stock: float` — 安全库存量（≥0）
  - `eoq: float | None = None` — 经济订货批量（可选，若提供则一并输出）

- `ROPResult`:
  - `reorder_point: float` — 补货点（= lead_time_demand + safety_stock）
  - `lead_time_demand: float` — 提前期平均需求（= avg_demand × lead_time）
  - `safety_stock: float` — 安全库存量
  - `eoq: float | None` — 经济订货批量（若输入提供）
  - `suggestion: str` — 规则化生成的中文业务建议

### 2. 算法实现

核心公式：
- `reorder_point = avg_demand * lead_time + safety_stock`
- `lead_time_demand = avg_demand * lead_time`

### 3. 规则化业务建议生成

根据输入参数生成中文建议字符串（零 LLM，纯 if-else 规则）：

```python
def _generate_suggestion(result: ROPResult) -> str:
    parts = []
    parts.append(f"当库存降至 {result.reorder_point:.0f} 时触发补货")
    if result.eoq:
        parts.append(f"每次订货量为 {result.eoq:.0f}")
    parts.append(f"其中提前期平均消耗 {result.lead_time_demand:.0f}，安全库存 {result.safety_stock:.0f}")
    return "；".join(parts) + "。"
```

扩展规则（可选，增强建议质量）：
- 若 safety_stock == 0 → 建议末尾追加"（当前安全库存为 0，建议评估需求波动风险）"
- 若 eoq 存在 → 追加"建议采用 (ROP, Q) 库存策略"
- 若 eoq 不存在 → 追加"建议结合 EOQ 模型确定最优订货量"

### 4. 复合接口（展示模板间协作）

```python
def from_eoq_and_safety_stock(
    eoq_result,  # EOQResult 类型
    safety_stock_result,  # SafetyStockResult 类型
    params: ROPParams | None = None
) -> ROPResult:
    """
    从 EOQ 和安全库存结果直接构建 ROP。
    展示模板间的协作关系，是面试中可以强调的设计亮点。
    
    用法：
        eoq = calculate(EOQParams(...))
        ss = calculate_safety_stock(SafetyStockParams(...))
        rop = from_eoq_and_safety_stock(eoq, ss)
    """
```

### 5. 参数校验

- avg_demand ≤ 0 → ValueError
- lead_time < 0 → ValueError
- safety_stock < 0 → ValueError
- 允许 safety_stock = 0（无安全库存的确定性场景）
- 允许 eoq = None

### 6. 代码规范

- Python 3.11+，类型注解完整
- Docstring 用中文，注释用英文
- **不引入任何新依赖**
- 导出 `run = calculate` 别名
- `from_eoq_and_safety_stock` 中的参数类型可以用字符串前向引用或 `from __future__ import annotations`，避免循环导入问题

### 7. 测试文件

创建 `tests/test_reorder_point.py`，覆盖以下场景：

| # | 场景 | 预期 |
|---|------|------|
| 1 | 正常计算 ROP | rop = lead_time_demand + safety_stock |
| 2 | ROP 含 EOQ | eoq 字段正确传递 |
| 3 | ROP 不含 EOQ | eoq = None |
| 4 | safety_stock = 0 | rop = lead_time_demand，建议含风险提示 |
| 5 | 复合接口 from_eoq_and_safety_stock | 正确使用 EOQResult 和 SafetyStockResult 构建 ROP |
| 6 | suggestion 包含补货点数字 | 字符串包含 reorder_point 的整数值 |
| 7 | suggestion 含 EOQ 时提到订货量 | 字符串包含 eoq 值 |
| 8 | suggestion 无 EOQ 时建议结合 EOQ | 字符串含"EOQ" |
| 9 | 零提前期 | lead_time_demand = 0, rop = safety_stock |
| 10 | 负 safety_stock | ValueError |
| 11 | run 别名可调用 | 正常 |

### 执行步骤

1. 读取 inventory_eoq.py 和 safety_stock.py 了解接口风格
2. 实现 src/domain/templates/reorder_point.py
3. 运行 `python -m py_compile src/domain/templates/reorder_point.py`
4. 创建 tests/test_reorder_point.py 并运行 `python -m pytest tests/test_reorder_point.py -v`
5. 确保 11/11 通过
6. 不修改任何其他文件
7. 仿照DEV_LOG.md的结构，将这次开发记录到DEV_LOG.md末尾中
```

---

## Day 4：模板匹配器 `template_matcher.py` + 参数提取器 `param_extractor.py`

### 提示词

```
请读取 /CLAUDE.md 和 /DEV_DESIGN.md，然后实现两个新模块：
1. src/domain/template_matcher.py —— 模板匹配器（意图分类）
2. src/domain/param_extractor.py —— 参数提取器（从自然语言提取数值参数）

## 背景

Week 4 Day 1-3 已完成三个供应链模板：demand_forecast、safety_stock、reorder_point，
加上已有的 inventory_eoq 和 data_analysis，现在需要让用户能通过自然语言调用这些模板。

模板匹配器和参数提取器是领域模板层的"大脑"，负责：
- 识别用户想调用哪个模板（意图分类）
- 从自然语言中提取模板的数值参数

## 设计理念

**规则化而非 LLM 化** —— 与 data_analysis 的结论引擎设计理念一致：
- 零 LLM 调用、零延迟、零成本
- 100% 可预测，便于调试
- 正则表达式提取数值，关键词匹配分类

## 任务 4a：template_matcher.py

### 1. 意图分类体系

```python
class TemplateType(Enum):
    EOQ = "eoq"                          # 经济订货批量
    FORECAST = "forecast"                # 需求预测
    SAFETY_STOCK = "safety_stock"        # 安全库存
    REORDER_POINT = "reorder_point"      # 补货点
    DATA_ANALYSIS = "data_analysis"      # 一键数据分析
    UNKNOWN = "unknown"                  # 无法匹配
```

### 2. 匹配逻辑（多关键词打分制）

每个 TemplateType 配置一组关键词和权重：

```python
KEYWORDS: dict[TemplateType, list[tuple[str, float]]] = {
    TemplateType.EOQ: [
        ("订货", 2.0), ("eoq", 2.0), ("批量", 1.5), ("订货成本", 2.0), 
        ("持有成本", 2.0), ("经济", 1.0), ("最优订货", 1.5), ("order", 1.0)
    ],
    TemplateType.FORECAST: [
        ("预测", 2.0), ("forecast", 2.0), ("需求预测", 2.5), ("预测需求", 2.5),
        ("趋势", 1.0), ("平滑", 1.0), ("未来", 0.5), ("forecasting", 2.0)
    ],
    TemplateType.SAFETY_STOCK: [
        ("安全库存", 2.5), ("safety", 1.5), ("服务水平", 2.0), ("service level", 2.0),
        ("库存安全", 2.0), ("缺货", 1.0), ("缓冲", 1.0), ("buffer", 1.0)
    ],
    TemplateType.REORDER_POINT: [
        ("补货点", 2.5), ("订货点", 2.5), ("reorder", 1.5), ("rop", 2.0),
        ("补货", 1.5), ("再订货", 2.0), ("库存降到", 1.5), ("触发订货", 1.5)
    ],
    TemplateType.DATA_ANALYSIS: [
        ("分析", 1.5), ("analysis", 1.5), ("数据分析", 2.0), ("统计", 1.0),
        ("报表", 1.0), ("可视化", 1.0), ("图表", 1.0), ("质量检查", 1.5)
    ],
}
```

匹配算法：
- 对用户 query 做分词（或直接子串匹配）
- 每个关键词在 query 中出现则累加对应权重
- 总分最高的 TemplateType 为匹配结果
- 若最高分 < 阈值（如 1.5）→ TemplateType.UNKNOWN
- 若多个同分 → 取关键词更具体的（如"需求预测"比"预测"更具体）

### 3. 输出结构

```python
@dataclass
class MatchResult:
    template_type: TemplateType
    confidence: float  # 最高分
    matched_keywords: list[str]  # 命中的关键词列表
    all_scores: dict[TemplateType, float]  # 各类别完整打分（用于调试）
```

### 4. 主函数签名

```python
def match_template(query: str) -> MatchResult:
    """对用户自然语言 query 进行模板匹配"""

def match_with_fallback(query: str) -> MatchResult:
    """匹配 + 兜底：UNKNOWN 时返回推荐的可用模板列表"""
```

---

## 任务 4b：param_extractor.py

### 1. 参数提取逻辑

从自然语言中提取 `(参数名, 数值)` 对。

**数值正则模式**：
- 整数：`r'(\d+)'`
- 小数：`r'(\d+\.\d+)'`
- 百分比：`r'(\d+\.?\d*)\s*%'`

**参数名→字段映射**（支持别名）：

```python
PARAM_ALIASES: dict[str, list[str]] = {
    # EOQ 参数
    "annual_demand": ["年需求", "年需求量", "annual demand", "demand", "需求", "需求量", "年消耗"],
    "ordering_cost": ["订货成本", "订购成本", "order cost", "ordering cost", "每次订货", "订货费"],
    "holding_cost": ["持有成本", "库存成本", "存储成本", "holding cost", "storage cost", "库存持有", "持有费率"],
    "unit_cost": ["单价", "unit cost", "单位成本", "价格"],
    
    # 安全库存参数
    "avg_demand": ["平均需求", "avg demand", "平均需求量", "平均消耗"],
    "demand_std": ["需求标准差", "demand std", "需求波动", "标准差", "σ"],
    "lead_time": ["提前期", "lead time", "交货期", "供货期", "leadtime"],
    "lead_time_std": ["提前期标准差", "lead time std", "提前期波动"],
    "service_level": ["服务水平", "service level", "服务率", "满足率"],
    
    # 预测参数
    "periods": ["预测期数", "periods", "预测几期", "未来几期"],
    "alpha": ["平滑系数", "alpha", "α", "平滑常数"],
}
```

### 2. 提取算法

```python
def extract_params(query: str) -> dict[str, float]:
    """
    从自然语言中提取参数。
    
    算法：
    1. 找出 query 中所有数值（整数/小数/百分比）
    2. 对每个数值，向前查找最近的参数别名（在数值前 10 个字符内）
    3. 将别名映射到标准参数名
    4. 返回 {标准参数名: 数值}
    
    例：
        "年需求1000，订货成本50，持有成本2" 
        → {"annual_demand": 1000.0, "ordering_cost": 50.0, "holding_cost": 2.0}
    """
```

### 3. 智能单位处理

- 百分比自动转换："服务水平 95%" → `{"service_level": 95.0}`（留由模板层标准化为 0.95）
- 千位识别："年需求 1万" → 暂不处理，只提取数字部分
- 多值冲突：同一参数出现多次 → 取第一个或最后一个（文档说明策略）

### 4. 辅助函数

```python
def extract_params_for_template(query: str, template_type: TemplateType) -> dict[str, float]:
    """结合模板类型，只提取该模板需要的参数"""

def describe_missing_params(template_type: TemplateType, extracted: dict[str, float]) -> list[str]:
    """返回缺失的必填参数列表（中文描述，用于提示用户）"""
```

各模板必填参数：
- EOQ: annual_demand, ordering_cost, holding_cost
- FORECAST: history（无法从文本提取，标记为特殊）
- SAFETY_STOCK: avg_demand, demand_std, lead_time, service_level
- REORDER_POINT: avg_demand, lead_time, safety_stock

### 5. 主函数签名

```python
def extract_params(query: str) -> dict[str, float]:
    """通用参数提取"""

def extract_params_for_template(query: str, template_type: TemplateType) -> dict[str, float]:
    """模板定向参数提取"""

def describe_missing_params(template_type: TemplateType, extracted: dict[str, float]) -> list[str]:
    """描述缺失的必填参数"""
```

### 6. 代码规范

- Python 3.11+，类型注解完整
- Docstring 用中文，注释用英文
- **不引入任何新依赖**（只用 re 模块）
- template_matcher.py 导出 `run = match_template` 别名
- param_extractor.py 导出 `run = extract_params` 别名

### 7. 测试文件

创建 `tests/test_template_matcher.py` 和 `tests/test_param_extractor.py`。

test_template_matcher.py 场景（~12 个）：

| # | Query | 预期匹配 |
|---|-------|---------|
| 1 | "帮我算 EOQ，年需求 1000" | EOQ |
| 2 | "预测一下下月需求" | FORECAST |
| 3 | "安全库存怎么定，服务水平 95%" | SAFETY_STOCK |
| 4 | "库存降到多少要补货" | REORDER_POINT |
| 5 | "分析这个销售数据" | DATA_ANALYSIS |
| 6 | "经济订货批量" | EOQ |
| 7 | "reorder point 是多少" | REORDER_POINT |
| 8 | "buffer stock 计算" | SAFETY_STOCK |
| 9 | "毫无关系的query" | UNKNOWN |
| 10 | 混合关键词（"EOQ 和安全库存"）| 最高分者 |
| 11 | 空字符串 | UNKNOWN |
| 12 | 大小写不敏感 | "EOQ" == "eoq" |

test_param_extractor.py 场景（~18 个）：

| # | Query | 预期提取 |
|---|-------|---------|
| 1 | "年需求1000，订货成本50，持有成本2" | 3个参数全对 |
| 2 | "annual demand 1000, ordering cost 50" | 英文别名识别 |
| 3 | "服务水平 95%" | service_level=95.0 |
| 4 | "服务水平 0.95" | service_level=0.95 |
| 5 | "平均需求 100，标准差 20" | avg_demand + demand_std |
| 6 | "提前期 2 周" | lead_time=2.0 |
| 7 | "订货费 100，库存持有成本 5" | ordering_cost + holding_cost |
| 8 | "需求 500 成本 30" | 正确映射各值到对应参数 |
| 9 | 无数字的 query | 空 dict |
| 10 | 数字无前导参数名 | 空 dict 或不匹配 |
| 11 | 小数识别 "持有成本 2.5" | 2.5 |
| 12 | extract_params_for_template EOQ | 只提取 EOQ 相关参数 |
| 13 | describe_missing_params EOQ 全缺 | 列出 3 个缺失参数 |
| 14 | describe_missing_params EOQ 缺 1 个 | 列出 1 个缺失参数 |
| 15 | 中文逗号分隔 | 正常提取 |
| 16 | 含"万"单位 | 只提取数字部分（如"1"）|
| 17 | 同一参数多次出现 | 按文档策略处理 |
| 18 | run 别名可调用 | 正常 |

### 执行步骤

1. 实现 src/domain/template_matcher.py
2. 实现 src/domain/param_extractor.py
3. 分别运行 py_compile 检查语法
4. 分别创建测试文件并运行
5. 确保 template_matcher 12/12 通过，param_extractor 18/18 通过
6. 不修改任何其他文件
7. 仿照DEV_LOG.md的结构，将这次开发记录到DEV_LOG.md末尾中
```

---

## Day 5：集成到 Agent 闭环

### 提示词（Part A：更新 domain/__init__.py）

```
请读取 /CLAUDE.md，然后更新 src/domain/__init__.py —— 统一导出 Week 4 新增的领域模板符号。

## 当前导出（Week 3 结束时有 8 个符号）

```python
from src.domain.data_quality import run_quality_check
from src.domain.chart_templates import bar_chart, line_chart, histogram_chart, scatter_chart, heatmap_chart
from src.domain.text_to_sql import run_text_to_sql
from src.domain.templates.data_analysis import run_analysis
```

## 需要新增导出

```python
# 需求预测
from src.domain.templates.demand_forecast import forecast, auto_forecast, ForecastParams, ForecastResult

# 安全库存
from src.domain.templates.safety_stock import calculate_safety_stock, quick_safety_stock, SafetyStockParams, SafetyStockResult

# 补货点
from src.domain.templates.reorder_point import calculate, ROPParams, ROPResult, from_eoq_and_safety_stock

# 模板匹配
from src.domain.template_matcher import match_template, match_with_fallback, MatchResult, TemplateType

# 参数提取
from src.domain.param_extractor import extract_params, extract_params_for_template, describe_missing_params
```

## 注意事项

- 使用 `try/except ImportError` 包装每个导入，防止某个模块有问题影响其他模块
- 保持现有 8 个符号的导出不变（向后兼容）
- 运行 `python -m py_compile src/domain/__init__.py` 检查语法
- 运行 `python -m pytest tests/ -v --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py` 确认无回归
```

### 提示词（Part B：更新 coder.md 模板优先级）

```
请读取 /CLAUDE.md 和 src/agent/nodes/prompts/coder.md，然后更新 coder.md —— 新增供应链优化模板优先级。

## 当前 coder.md 模板优先级（4 级）

1. 数据分析整体 → run_analysis()
2. 数据质量/清洗 → run_quality_check()
3. 画图/可视化 → chart_templates
4. 自然语言问数 → run_text_to_sql()

## 需要新增第 5 级

5. **供应链优化** → 根据用户意图调用对应模板：

```markdown
### 5. 供应链库存优化模板（最高精度场景）

当用户需求涉及库存管理、订货决策、需求预测时，使用以下模板：

#### 5a. EOQ 经济订货批量
- 适用场景：用户提到"订货成本"、"持有成本"、"年需求"、"EOQ"、"经济订货批量"
- 调用方式：
  ```python
  from src.domain.templates.inventory_eoq import calculate, EOQParams
  result = calculate(EOQParams(annual_demand=1000, ordering_cost=50, holding_cost=2))
  print(f"EOQ = {result.eoq:.2f}")
  ```
- 参数：annual_demand（年需求量）、ordering_cost（每次订货成本）、holding_cost（单位年持有成本）
- 可选：unit_cost（单价，用于计算总成本）

#### 5b. 需求预测
- 适用场景：用户提到"预测需求"、"趋势"、"平滑"、"forecast"
- 调用方式：
  ```python
  from src.domain.templates.demand_forecast import forecast, ForecastParams
  result = forecast(ForecastParams(history=[100, 120, 110, 130, 125], method="auto", periods=3))
  print(f"未来3期预测: {result.forecasts}")
  ```
- 参数：history（历史需求列表）、method（方法名或"auto"）、periods（预测期数）

#### 5c. 安全库存
- 适用场景：用户提到"安全库存"、"服务水平"、"缺货风险"、"service level"
- 调用方式：
  ```python
  from src.domain.templates.safety_stock import calculate_safety_stock, SafetyStockParams
  result = calculate_safety_stock(SafetyStockParams(avg_demand=100, demand_std=20, lead_time=2, service_level=95))
  print(f"安全库存 = {result.safety_stock:.2f}")
  ```
- 参数：avg_demand（平均需求）、demand_std（需求标准差）、lead_time（提前期）、service_level（服务水平，支持 95 或 0.95）
- 可选：lead_time_std（提前期标准差，默认 0）

#### 5d. 补货点
- 适用场景：用户提到"补货点"、"订货点"、"reorder point"、"库存降到多少"
- 调用方式：
  ```python
  from src.domain.templates.reorder_point import calculate, ROPParams
  result = calculate(ROPParams(avg_demand=100, lead_time=2, safety_stock=50))
  print(f"补货点 = {result.reorder_point:.2f}")
  print(result.suggestion)
  ```
- 参数：avg_demand（平均需求）、lead_time（提前期）、safety_stock（安全库存）
- 可选：eoq（经济订货批量，若提供则建议中包含订货量）

#### 模板选择规则
- 如果用户只提到一个概念（如只问 EOQ），直接调用对应模板
- 如果用户提到多个概念（如"帮我算 EOQ 和安全库存"），按顺序分别计算
- 如果用户提供了具体数字但没有明确概念，尝试匹配最相关的模板
```

## 注意事项

- 不要删除或修改现有的 4 级优先级内容，只追加第 5 级
- 保持与现有文档格式一致
- 每个模板都要有完整的调用示例
- 更新后运行 `python -m py_compile src/agent/nodes/prompts/coder.md`（注意：coder.md 不是 Python 文件，不需要 py_compile，但要检查语法错误）
```

### 提示词（Part C：创建 E2E 测试）

```
请创建 tests/test_e2e_week4.py —— Week 4 端到端集成测试。

## 测试目标

验证 Agent 从自然语言输入到供应链模板输出的完整闭环。

## 测试场景（4 个）

```python
"""
任务 A：EOQ 完整链路
输入："年需求1000，订货成本50，持有成本2，帮我算EOQ"
预期：生成的代码调用 inventory_eoq.calculate，输出 EOQ≈223.6

任务 B：需求预测链路
输入："历史需求 [100,120,110,130,125,140]，预测未来3个月"
预期：生成的代码调用 demand_forecast.forecast 或 auto_forecast

任务 C：安全库存链路
输入："平均需求200，标准差30，提前期1周，服务水平95%"
预期：生成的代码调用 safety_stock.calculate_safety_stock

任务 D：补货点链路
输入："平均需求150，提前期2天，安全库存100"
预期：生成的代码调用 reorder_point.calculate，输出 suggestion
"""
```

## 测试实现要点

- 参照 tests/test_e2e_week3.py 的测试结构
- 每个测试：`load_dotenv()` → 构建 AgentState → `graph.invoke(state)` → 检查结果
- 检查点：final_report 非空、无 error（或 error 为 None）、retry_count=0
- 不需要检查具体数字精度（LLM 生成的代码可能有差异），但要检查报告中包含预期关键词
- 依赖 `DEEPSEEK_API_KEY`，测试脚本开头显式 `load_dotenv()`

## 注意事项

- 此测试需要 API Key，若 Key 不可用可以跳过（标记为 @pytest.mark.skipif）
- 保持与 test_e2e_week3.py 相同的错误处理和断言风格
- 运行 `python -m pytest tests/test_e2e_week4.py -v`（需要 API Key）
```

---

## Day 6：回归测试 + Benchmark + 文档更新

### 提示词（Part A：全量回归测试）

```
请执行以下回归测试流程：

1. 运行全量单元测试（不含 Docker 相关测试）：
   python -m pytest tests/ -v --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py

2. 预期结果：全部通过，零回归

3. 若出现失败：
   - 先判断是 Week 4 新增测试失败还是原有测试失败
   - 若是原有测试失败（回归），立即停止，分析原因并修复
   - 若是新增测试失败，记录问题但不阻塞（可标记 skip）

4. 统计并输出：
   - 总测试数：___
   - 通过数：___
   - 失败数：___
   - 新增测试数（相对于 Week 3 的 255）：___
```

### 提示词（Part B：Week 4 Benchmark 记录）

手动整理以下 Benchmark 数据并追加到 DEV_LOG.md：

```markdown
## 2026-07-XX — Week 4 完整总结

### Benchmark 数字

| 指标 | 数值 | 说明 |
|------|------|------|
| 单元测试通过率 | ___/___ = ___% | 每周累计无回归 |
| E2E 测试通过率 | ___/___ = ___% | Week 4 新增供应链场景 |
| 模板匹配准确率 | ___% | 手动测试 ___ 条 query |
| 参数提取成功率 | ___% | 手动测试 ___ 条 query |
| 供应链模板独立调用成功率 | 100% | EOQ/预测/安全库存/补货点各至少 1 次 |
| 代码运行成功率 | ___% | E2E 任务 |
| 平均重试次数 | ___ | |
| 累计测试数 | ___ | Week1:55 → Week2:144 → Week3:255 → Week4:___ |

### 完成的子任务清单

- [x] demand_forecast.py：SMA/WMA/SES/Holt + auto 选择 + 精度评估
- [x] safety_stock.py：三种波动场景 + 服务水平法 + Z-score
- [x] reorder_point.py：ROP 计算 + 复合接口 + 规则化建议
- [x] template_matcher.py：多关键词打分 + 6 类意图 + 兜底策略
- [x] param_extractor.py：正则数值提取 + 别名映射 + 缺失参数检测
- [x] domain/__init__.py 更新：新增符号统一导出
- [x] coder.md 更新：第 5 级供应链模板优先级
- [x] E2E 测试：4 个供应链场景

### 领域模板层 API 参考（新增）

[参照 DEV_DESIGN.md 第十节的格式，新增 Week 4 模板的 API 说明]
```

### 提示词（Part C：更新 DEV_DESIGN.md）

```
请更新 DEV_DESIGN.md：

1. 文件头部版本号改为 v0.4，日期改为当前日期
2. "当前阶段"改为 "Week 4 领域模板层完成，进入 Week 5"
3. 第四节"阶段规划"中 Week 4 的所有 checkbox 打勾：[x]
4. 第十节"Week 3 领域模板层 API 参考"更新为"Week 4 领域模板层 API 参考"，追加以下内容：

```markdown
### 需求预测

```python
from src.domain.templates.demand_forecast import forecast, auto_forecast, ForecastParams, ForecastResult

# 指定方法
result = forecast(ForecastParams(history=[100, 120, 110, 130], method="holt", periods=3))
# → ForecastResult(forecasts=[...], mae=..., rmse=..., mape=..., method_used="holt")

# 自动选择
result = auto_forecast(history=[100, 120, 110, 130, 125], periods=3)
```

### 安全库存

```python
from src.domain.templates.safety_stock import calculate_safety_stock, quick_safety_stock, SafetyStockParams

result = calculate_safety_stock(SafetyStockParams(
    avg_demand=100, demand_std=20, lead_time=2, service_level=95
))
# → SafetyStockResult(safety_stock=..., z_score=1.645, ...)
```

### 补货点

```python
from src.domain.templates.reorder_point import calculate, ROPParams

result = calculate(ROPParams(avg_demand=100, lead_time=2, safety_stock=50, eoq=224))
print(result.suggestion)  # "当库存降至 250 时触发补货；每次订货量为 224..."
```

### 模板匹配

```python
from src.domain.template_matcher import match_template, TemplateType

result = match_template("帮我算 EOQ，年需求 1000")
# → MatchResult(template_type=TemplateType.EOQ, confidence=4.5, ...)
```

### 参数提取

```python
from src.domain.param_extractor import extract_params

params = extract_params("年需求1000，订货成本50，持有成本2")
# → {"annual_demand": 1000.0, "ordering_cost": 50.0, "holding_cost": 2.0}
```
```

5. 第五节"设计决策记录"追加以下条目：

| 日期 | 决策 | 原因 | 可能风险 |
|------|------|------|---------|
| 2026-07-XX | 模板匹配器和参数提取器规则化（正则+关键词） | 零 LLM 延迟、100% 可预测、可调试 | 复杂自然语言理解能力弱于 LLM |
| 2026-07-XX | 安全库存三种波动场景分别处理 | 覆盖供应链管理的所有常见情况 | 公式复杂度递增 |
| 2026-07-XX | 补货点模板作为 EOQ + 安全库存的组合器 | 展示模板间协作，体现架构设计 | 依赖前两个模板必须先实现 |
| 2026-07-XX | 需求预测纯 Python 实现（不用 statsmodels） | 避免重量级依赖，保持项目轻量 | 算法精度可能低于专业库 |
| 2026-07-XX | Coder Prompt 新增第 5 级供应链模板 | 让用户自然语言直接触发领域模板 | LLM 可能选错模板或参数 |

6. 第七节的文件组织规范图中，在 templates/ 目录下追加 reorder_point.py
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

## 附录：Week 4 文件变更汇总

| 日期 | 新增文件 | 修改文件 | 新增测试 |
|------|---------|---------|---------|
| Day 1 | `src/domain/templates/demand_forecast.py` | — | `tests/test_demand_forecast.py` (~15) |
| Day 2 | `src/domain/templates/safety_stock.py` | — | `tests/test_safety_stock.py` (~13) |
| Day 3 | `src/domain/templates/reorder_point.py` | — | `tests/test_reorder_point.py` (~11) |
| Day 4 | `src/domain/template_matcher.py` | — | `tests/test_template_matcher.py` (~12) |
| Day 4 | `src/domain/param_extractor.py` | — | `tests/test_param_extractor.py` (~18) |
| Day 5 | — | `src/domain/__init__.py` | — |
| Day 5 | — | `src/agent/nodes/prompts/coder.md` | — |
| Day 5 | — | — | `tests/test_e2e_week4.py` (4 E2E) |
| Day 6 | — | `DEV_LOG.md`, `DEV_DESIGN.md` | 全量回归 |

---

> **最后提醒**：不要一次给 CC 太多任务。每天只执行当天的提示词，完成后手动确认再进入下一天。如果某天任务量太大，可以拆成两天完成。

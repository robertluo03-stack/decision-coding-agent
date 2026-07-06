# Week 3 开发提示词（Claude Code 版）

> **使用说明**：每天开始开发时，将对应提示词完整粘贴到 Claude Code 对话框。CC 会先读取 `CLAUDE.md` 和 `DEV_DESIGN.md` 获取上下文，然后按提示词执行。

> **项目背景**：DecisionCoder 是一个面向经营决策与运筹优化的垂直 Coding Agent。当前处于 **Week 2 完成、Week 3 启动** 节点。Week 2 的纵深防御体系（AST 安全、Docker 沙箱、MCP 协议、日志系统）已扎实落地，63/63 E2E 回归通过。Week 3 的核心命题是**让 Agent 真正具备数据分析和可视化能力**，从"能执行代码"进化到"能读懂数据、发现规律、画出图表"。

---

## 每日开发标准流程（给 Claude Code 的元指令）

每天开始开发时，请 Claude Code 遵循以下标准流程：

1. **读取** `CLAUDE.md`（项目指南）
2. **读取** `DEV_DESIGN.md` 中 Week 3 相关设计
3. **只修改**当天提示词指定的文件，不修改其他文件
4. **实现后**运行 `python -m py_compile <file>` 检查语法
5. **运行**当天对应的测试文件，确保通过
6. **更新** `DEV_LOG.md` 记录变更（按日期添加条目）

---

## Day 0：前置准备 + Week 2 遗留 Bug 修复

**目标**：完成 Week 3 开始前的所有准备工作，修复 3 个遗留问题，升级依赖，更新 Docker 镜像。

**需要修改的文件**：
- `src/agent/nodes/coder.py`（修复回退代码 f-string bug）
- `src/agent/sandbox/docker_runner.py`（OOM 日志增强）
- `tests/test_docker_runner.py` 或 `tests/test_executor.py`（Docker 模式完整 Graph 兼容性测试）
- `pyproject.toml`（新增依赖）
- `Dockerfile`（中文字体 + 新依赖）
- `.gitignore`（如有新增）
- `DEV_LOG.md`（参照文档结构，记录这次开发）

**实现要点**：

1. **修复回退代码 f-string 转义 bug（coder.py）**：
   - 定位 `_generate_fallback_code` 函数
   - 将 `{{query}}`、`{{idx}}`、`{{step}}` 改为 `{query}`、`{idx}`、`{step}`（外层是普通字符串，不需要 f-string 转义）
   - 确保回退代码执行时变量正确替换

2. **DockerRunner OOM 日志增强（docker_runner.py）**：
   - 在 `_build_error` 或 Docker 执行结果处理逻辑中，检测 `returncode == 137`
   - 当 returncode=137 时，在 `error` 字段中追加 `[OOM Killed] 容器因内存超限被强制终止`
   - 确保该错误信息能被 Executor 正确捕获并传入 AgentState.error

3. **Docker 模式下完整 Graph 兼容性测试**：
   - 编写一个测试脚本，设置 `USE_DOCKER=true`，调用 `build_graph().invoke()` 执行一个简单任务（如 `1+1`）
   - 验证异步事件循环（MCP Client 的 `anyio.run`）与 DockerRunner 的同步 `subprocess.run` 是否存在兼容性问题
   - 如有问题，在 `executor.py` 的 `_execute_via_docker_with_fallback` 中修复

4. **依赖升级（pyproject.toml）**：
   - 新增：`plotly>=5.0`, `duckdb>=0.10`, `openpyxl>=3.0`
   - 确认现有依赖版本约束不被破坏

5. **Dockerfile 更新**：
   - 新增 `fonts-noto-cjk` 包安装（中文字体支持）
   - 新增 `plotly`, `duckdb`, `openpyxl` 的 pip 安装
   - 重新构建镜像：`docker build -t decision-coder-sandbox:latest .`
   - 验证镜像内 `python -c "import plotly, duckdb, openpyxl; print('OK')"` 通过

6. **测试数据准备**：
   - 创建 `workspace/data/sales.csv`（>=100 行，包含：日期、SKU、区域、销量、单价；人工注入 10% 缺失值和 5 个异常值）
   - 创建 `workspace/data/inventory.csv`（>=50 行，包含：SKU、当前库存、安全库存、补货点）

**验收标准**：
- `python -m py_compile src/agent/nodes/coder.py src/agent/sandbox/docker_runner.py` 无报错
- 回退代码测试：强制触发 Planner 回退（如不提供 API Key），验证输出中变量已正确替换
- Docker OOM 测试：运行内存炸弹，确认 error 字段包含 `[OOM Killed]`
- `docker build` 成功，镜像大小可接受（<2GB）
- `sales.csv` 和 `inventory.csv` 存在且格式正确

**注意事项**：
- 不要修改 `AgentState` 字段定义
- 保持所有函数的类型注解和中文 docstring
- 新增依赖必须是轻量级的，禁止引入 PyTorch/Transformers

---

## Day 1：File Tool 增强（CSV/Excel 读取 + 类型推断）

**目标**：扩展 MCP `file_tools` 支持 CSV/Excel 结构化读取，并做数据类型推断，为后续数据分析提供基础。

**需要修改的文件**：
- `src/mcp/tools/file_tools.py`（新增 `file_read_csv` / `file_read_excel` 函数）
- `src/mcp/server.py`（注册 2 个新 Tool）
- `tests/test_file_tools.py`（新增测试）
- 可能新增：`src/mcp/tools/data_utils.py`（类型推断辅助函数）
- `DEV_LOG.md`（参照文档结构，记录这次开发）

**实现要点**：

1. **file_read_csv(file_path, preview_rows=5)**：
   - 使用 `pandas.read_csv(file_path)` 读取
   - 返回结构化 JSON：`{"columns": [...], "dtypes": {...}, "preview": [...], "shape": [rows, cols], "missing_summary": {...}}`
   - `dtypes`：使用 `infer_objects()` 后，将 pandas dtype 映射为简洁字符串（`int64`->`int`, `float64`->`float`, `object`->`str`, `datetime64`->`datetime`）
   - `preview`：前 `preview_rows` 行的字典列表（`df.head().to_dict('records')`）
   - `missing_summary`：每列缺失值数量

2. **file_read_excel(file_path, sheet_name=0, preview_rows=5)**：
   - 使用 `pandas.read_excel(file_path, sheet_name=sheet_name, engine='openpyxl')`
   - 返回格式与 `file_read_csv` 一致
   - 若 `sheet_name` 不存在，返回清晰错误

3. **类型推断增强（data_utils.py）**：
   - 自定义规则：字符串列中若所有非空值含 `%`，转为 `percentage` 类型
   - 日期格式正则：匹配 `YYYY-MM-DD`、`YYYY/MM/DD` 等常见格式，标记为 `datetime`
   - 混合类型检测：同一列中若数值和字符串共存，标记为 `mixed`

4. **路径安全**：
   - 复用 `_resolve_safe_path()`，限制在 `workspace/data/` 下
   - 禁止 `..` 和符号链接逃逸

5. **MCP Server 注册**：
   - 在 `server.py` 用 `@server.tool()` 注册 `file_read_csv` 和 `file_read_excel`
   - FastMCP 自动推断 inputSchema，确保参数类型正确（`preview_rows: int = 5`）

6. **测试覆盖**：
   - 正常 CSV / Excel 读取
   - 类型推断（int/float/str/datetime/percentage/mixed）
   - 越权路径拦截（`../../etc/passwd`）
   - 空文件 / 大文件预览截断（>1000 行只返回前 5 行预览）
   - 缺失值标记
   - 未知 sheet 报错

**验收标准**：
- `py_compile` 全部通过
- `test_file_tools.py` 新增 8+ 测试，全部通过
- MCP `list_tools()` 返回 8 个 Tool（原 6 + 新增 2）
- `file_read_csv` 对 `sales.csv` 返回正确列名和类型推断

**注意事项**：
- 不要向 stdout 打印进度消息（用 loguru 的 `logger.debug`）
- 保持与现有 `file_read` / `file_write` 的代码风格一致
- `preview_rows` 默认 5，防止大文件内存溢出

---

## Day 2：数据质量检查（Data Quality Engine）

**目标**：实现数据质量自动检测模块，识别缺失值、异常值、类型冲突、重复行。

**需要新增的文件**：
- `src/domain/data_quality.py`（核心检测引擎）
- `src/domain/__init__.py`（如不存在，导出 `run_quality_check`）
- `tests/test_data_quality.py`

**需要修改的文件**：
- `src/agent/nodes/prompts/coder.md`（新增数据质量检查模板说明）
- `src/agent/nodes/coder.py`（可选：让 Coder 识别"数据质量"意图时生成调用代码）
- `DEV_LOG.md`（参照文档结构，记录这次开发）

**实现要点**：

1. **data_quality.py 核心函数**：

```python
def run_quality_check(df: pd.DataFrame) -> dict:
    """
    返回数据质量报告
    """
```

- **缺失值检测**：`df.isnull().sum()`，输出每列缺失率和风险等级（>20% 为 high，5-20% 为 medium，<5% 为 low）
- **异常值检测**：
  - 数值列：IQR 法（Q1 - 1.5*IQR, Q3 + 1.5*IQR），标记异常值索引
  - 类别列：频率异常，出现次数 <=2 的标记为 suspicious
- **类型冲突**：遍历 object 列，尝试 `pd.to_numeric(errors='coerce')`，若部分成功部分失败则标记 mixed
- **重复行**：`df.duplicated().sum()`，输出重复行数和示例

2. **报告格式**：

```json
{
    "overall_score": 85,
    "columns": [
        {
            "name": "销量",
            "dtype": "float",
            "missing_rate": 0.05,
            "missing_level": "medium",
            "outlier_count": 3,
            "outlier_examples": [9999, -100],
            "duplicate_count": 0
        }
    ],
    "recommendations": ["建议对销量列的缺失值用均值填充", "异常值 9999 可能是录入错误"]
}
```

3. **与 Coder 集成**：
   - 在 `coder.md` 中新增段落：当用户需求涉及"数据质量"/"数据清洗"/"检查数据"时，Coder 应生成调用 `from src.domain.data_quality import run_quality_check` 的代码
   - 生成的代码模板：

```python
import pandas as pd
from src.domain.data_quality import run_quality_check

df = pd.read_csv("data/sales.csv")
report = run_quality_check(df)
print(report)
```

4. **测试覆盖**：
   - 正常数据（无问题）
   - 高缺失率（一列 50% 缺失）
   - 异常值（数值列含 99999）
   - 混合类型（同一列含 "123" 和 "abc"）
   - 重复行（10% 重复）
   - 空 DataFrame

**验收标准**：
- `py_compile` 通过
- `test_data_quality.py` 全部通过（>=6 个场景）
- 用 `sales.csv` 测试，检出人工注入的 10% 缺失值和 5 个异常值（检出率 >=80%）
- Coder 生成"检查数据质量"任务时，代码正确调用 `run_quality_check`

**注意事项**：
- 数据质量检查作为**领域模板**实现，不新增 Graph 节点（保持 LangGraph 结构简洁）
- 所有数值计算使用 pandas/numpy，避免纯 Python 循环（性能）
- 报告中的 `recommendations` 用中文，保持与用户语言一致

---

## Day 3：EDA 自动生成（探索性数据分析引擎）

**目标**：实现 EDA 自动生成模块，输出统计摘要、分布分析、相关性矩阵。

**需要新增的文件**：
- `src/domain/eda_engine.py`
- `tests/test_eda_engine.py`

**需要修改的文件**：
- `src/agent/nodes/prompts/coder.md`（新增 EDA 模板说明）
- `DEV_LOG.md`（参照文档结构，记录这次开发）

**实现要点**：

1. **eda_engine.py 核心函数**：

```python
def run_eda(df: pd.DataFrame, output_dir: str = "reports/") -> dict:
    """
    返回 EDA 报告和图表数据
    """
```

2. **统计摘要（statistical_summary）**：
   - 数值列：count, mean, std, min, 25%, 50%, 75%, max, skewness, kurtosis
   - 类别列：unique, top, freq
   - 时间列（如检测到 datetime）：min, max, range_days

3. **分布分析（distribution_analysis）**：
   - 数值列：直方图分箱数据（10 个 bins，用 `numpy.histogram`），返回 `{"bins": [...], "counts": [...]}`
   - 类别列：频率分布 Top10（`value_counts().head(10)`）
   - 时间列：按月/季度聚合（`df.resample('M').size()`）

4. **相关性分析（correlation_analysis）**：
   - 数值列 Pearson 相关系数矩阵（`df.corr()`）
   - 标记强相关对（|r| > 0.7），输出：`[{"col1": "A", "col2": "B", "corr": 0.85}]`
   - 忽略缺失值（`corr()` 默认行为）

5. **输出格式**：

```json
{
    "summary": {...},
    "distributions": {...},
    "correlations": {
        "matrix": [...],
        "strong_pairs": [...]
    },
    "chart_data": {
        "histograms": {...},
        "time_series": {...}
    }
}
```

6. **与 Coder 集成**：
   - 在 `coder.md` 中新增：当用户需求涉及"分析"/"统计"/"EDA"/"探索性分析"时，生成调用 `run_eda` 的代码
   - 生成的代码应保存 EDA 结果为 JSON，供后续 Reporter 使用

7. **测试覆盖**：
   - 空 DataFrame
   - 纯数值列
   - 纯类别列
   - 时间序列列
   - 混合列
   - 大数据量（>10k 行，验证性能 <5s）

**验收标准**：
- `py_compile` 通过
- `test_eda_engine.py` 全部通过（>=6 个场景）
- 输入 `sales.csv`，输出包含：5 维度统计摘要 + 3 列分布分析 + 相关性矩阵
- 执行时间 < 5 秒（subprocess 路径）

**注意事项**：
- 分布分析只输出**数据**（JSON），不直接画图（画图交给 Day 4 的 Plotly）
- 时间列检测：使用 `pd.to_datetime(errors='coerce')`，转换成功列数 >50% 则标记为时间列
- 保持模块独立，不依赖 Graph 状态

---

## Day 4：可视化图表生成（Plotly 模板）

**目标**：解决 Matplotlib 中文乱码问题，统一使用 Plotly 生成交互式 HTML 图表。

**需要新增的文件**：
- `src/domain/chart_templates.py`（5 种图表模板）
- `tests/test_chart_templates.py`

**需要修改的文件**：
- `src/agent/nodes/prompts/coder.md`（新增图表生成模板说明）
- `Dockerfile`（确认中文字体已安装，Day 0 已完成）
- `DEV_LOG.md`（参照文档结构，记录这次开发）

**实现要点**：

1. **chart_templates.py 核心函数**：
   每个函数接收 `df: pd.DataFrame, x_col: str, y_col: str, title: str, output_path: str`，返回 `output_path`。

   - `bar_chart()`：类别对比柱状图（`plotly.graph_objects.Bar`）
   - `line_chart()`：时间序列折线图（`go.Scatter`, mode='lines'）
   - `histogram_chart()`：数值分布直方图（`px.histogram`）
   - `scatter_chart()`：相关性散点图（`go.Scatter`, mode='markers'）
   - `heatmap_chart()`：相关性矩阵热力图（`px.imshow`）

2. **Plotly 配置**：
   - 模板使用 `plotly.io.write_html` 输出完整 HTML 文件（含 JS CDN）
   - 图表尺寸：width=900, height=600
   - 中文字体：使用系统默认无衬线字体（Plotly 在浏览器端渲染，依赖系统字体，Docker 中已装 `fonts-noto-cjk`）
   - 标题、轴标签、图例均用中文

3. **输出路径**：
   - 所有图表保存到 `workspace/reports/charts/`
   - 文件名：`chart_<type>_<timestamp>.html`
   - 目录不存在时自动创建

4. **与 Coder 集成**：
   - 在 `coder.md` 中新增：当用户需求涉及"画图"/"可视化"/"图表"/"趋势"时，生成调用 `chart_templates` 的代码
   - 示例生成代码：

```python
import pandas as pd
from src.domain.chart_templates import line_chart

df = pd.read_csv("data/sales.csv")
df['日期'] = pd.to_datetime(df['日期'])
monthly = df.resample('M', on='日期')['销量'].sum().reset_index()
line_chart(monthly, x_col='日期', y_col='销量', title='月度销量趋势', output_path='reports/charts/monthly_sales.html')
print("图表已保存到 reports/charts/monthly_sales.html")
```

5. **与 Reporter 集成**：
   - Reporter 在生成 Markdown 时，若检测到 `workspace/reports/charts/` 下有 HTML 文件，在附录中插入链接：

```markdown
## 生成的图表
- [月度销量趋势](charts/monthly_sales.html)
```

6. **测试覆盖**：
   - 5 种图表各生成 1 张
   - 空数据（应生成空图表或报错优雅）
   - 单列数据
   - 大数据量（>10k 点，验证性能）
   - 中文字符显示（标题含中文）

**验收标准**：
- `py_compile` 通过
- `test_chart_templates.py` 全部通过（>=8 个场景）
- 5 种图表模板各生成 1 张示例，HTML 可用浏览器打开
- 中文字符（标题/轴标签）显示正常
- Docker 模式下图表生成成功（验证 `USE_DOCKER=true` 时 `plotly` 可用）

**注意事项**：
- 禁止引入 `kaleido`（Plotly 静态图片导出依赖，体积大且易出兼容问题），只输出 HTML
- 图表文件不直接嵌入 Markdown（HTML 太大），用链接引用
- 保持模板函数签名一致，方便 Coder 自动生成调用代码

---

## Day 5：自然语言问数（Text-to-SQL via DuckDB）

**目标**：用户用自然语言提问，Agent 自动生成 DuckDB SQL 并执行，返回结果表格。

**需要新增的文件**：
- `src/domain/text_to_sql.py`（核心引擎）
- `tests/test_text_to_sql.py`

**需要修改的文件**：
- `src/agent/nodes/prompts/coder.md`（新增 Text-to-SQL 约束）
- `src/agent/nodes/debugger.py`（新增 DuckDB 错误分类）
- `src/agent/sandbox/security_checker.py`（可选：SQL 危险关键字检查）
- `DEV_LOG.md`（参照文档结构，记录这次开发）

**实现要点**：

1. **text_to_sql.py 核心函数**：

```python
def run_text_to_sql(
    query: str,           # 自然语言问题
    csv_path: str,        # 数据文件路径
    output_dir: str = "reports/"
) -> dict:
    """
    返回 SQL、结果、自然语言摘要
    """
```

2. **Schema 提取**：
   - 读取 CSV 前 100 行，提取列名和推断类型
   - 生成 DuckDB `CREATE TABLE` 语句作为 Prompt 上下文
   - 示例：

```sql
CREATE TABLE sales (
  日期 DATE,
  SKU VARCHAR,
  区域 VARCHAR,
  销量 INTEGER,
  单价 FLOAT
);
```

3. **SQL 生成（Coder 调用 LLM）**：
   - 在 `coder.md` 中新增 Text-to-SQL 系统提示：
     - "你是数据分析专家，根据用户问题和表结构生成 DuckDB SQL"
     - "只返回 SELECT 查询，禁止 DELETE/DROP/UPDATE/INSERT/ALTER/CREATE"
     - "使用标准 SQL 语法，DuckDB 兼容"
     - "如果问题涉及时间，使用 DuckDB 的日期函数（如 EXTRACT(YEAR FROM 日期)）"
   - Coder 生成代码时，将自然语言问题 + Schema 拼接为 Prompt，调用 DeepSeek API 生成 SQL
   - 生成的 SQL 通过 `duckdb.execute()` 执行

4. **执行与结果返回**：
   - 使用 `duckdb.connect()` 内存模式
   - `con.execute(f"CREATE VIEW data AS SELECT * FROM read_csv_auto('{csv_path}')")`
   - 执行生成的 SQL，结果转 pandas DataFrame
   - 返回：

```json
{
  "sql": "SELECT 区域, AVG(销量) FROM data GROUP BY 区域",
  "result": [{"区域": "华北", "avg(销量)": 150.5}, ...],
  "summary": "各区域平均销量如下：华北 150.5，华东 230.2..."
}
```

5. **安全拦截**：
   - 在生成 SQL 后，用正则检查是否包含危险关键字：`/\b(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE)\b/i`
   - 若检测到，拒绝执行并返回错误
   - 可选：在 `security_checker.py` 中新增 `check_sql_safety()`，但保持简单（正则即可，SQL 不是 Python，不需要 AST）

6. **Debugger 增强**：
   - 新增 `DuckDBCatalogError`（表/列不存在）和 `DuckDBSyntaxError` 的规则回退
   - `DuckDBCatalogError` -> 提示检查列名，建议用 `DESCRIBE data`
   - `DuckDBSyntaxError` -> 提示检查 SQL 语法，特别是日期函数

7. **测试覆盖**：
   - 简单聚合（SUM/AVG/COUNT）
   - 分组排序（GROUP BY + ORDER BY）
   - 时间过滤（WHERE 日期 > '2024-01-01'）
   - 多条件筛选
   - 非法 SQL 拦截（DROP TABLE）
   - 列不存在错误（触发 Debugger）

**验收标准**：
- `py_compile` 通过
- `test_text_to_sql.py` 全部通过（>=8 个场景）
- 10 个自然语言问题，SQL 生成正确率 >=70%
- 危险 SQL（如含 DROP）被拦截，返回错误
- 结果能被 Reporter 渲染为 Markdown 表格

**注意事项**：
- DuckDB 的 `read_csv_auto` 会自动推断类型，但中文列名需确认兼容性
- SQL 生成依赖 LLM，可能产生幻觉列名，需在 Debugger 中优雅处理
- 保持只读：DuckDB 连接不写入任何文件，仅内存操作

---

## Day 6：数据分析领域模板（一键分析）

**目标**：将 Day 2-5 的能力封装为"一键数据分析"领域模板，实现从数据读取到完整报告的闭环。

**需要新增的文件**：
- `src/domain/templates/data_analysis.py`
- `tests/test_data_analysis_template.py`

**需要修改的文件**：
- `src/agent/nodes/planner.py`（意图识别：关键词匹配触发数据分析模板）
- `src/agent/nodes/coder.py`（生成调用模板的代码）
- `src/agent/nodes/prompts/planner.md`（新增数据分析意图示例）
- `src/agent/nodes/prompts/coder.md`（新增模板调用示例）
- `DEV_LOG.md`（参照文档结构，记录这次开发）

**实现要点**：

1. **data_analysis.py 核心函数**：

```python
def run_analysis(
    file_path: str,
    output_dir: str = "reports/",
    target_columns: list[str] | None = None,
    time_column: str | None = None
) -> str:
    """
    一键数据分析，返回生成的报告文件路径
    """
```

内部流水线：

```python
df = pd.read_csv(file_path)
quality_report = run_quality_check(df)
eda_report = run_eda(df)
# 自动生成 2 张核心图表
chart_paths = []
if time_column and time_column in df.columns:
    chart_paths.append(line_chart(...))
# 生成 Markdown 报告
report_path = generate_analysis_report(quality_report, eda_report, chart_paths, output_dir)
return report_path
```

2. **参数提取**：
   - 从用户 query 中提取：
     - 文件名（正则匹配 `\w+\.csv` 或 `\w+\.xlsx`）
     - 目标列（如"分析销量和单价" -> `target_columns=["销量", "单价"]`）
     - 时间列（如"按月份分析" -> 自动检测日期列）
   - 提取逻辑放在 Planner 或 Coder 中，使用 LLM + 正则混合策略

3. **报告生成**：
   - 生成的 Markdown 报告结构：

```markdown
# 数据分析报告
## 1. 数据概览
- 文件：sales.csv
- 行数：150，列数：5
## 2. 数据质量检查
（嵌入 quality_report 表格）
## 3. 统计摘要
（嵌入 eda_report 摘要）
## 4. 可视化图表
- [月度销量趋势](charts/xxx.html)
## 5. 结论与建议
（基于 EDA 结果自动生成 3-5 条结论）
```

4. **Planner 意图识别**：
   - 在 `planner.md` 中新增示例：
     - 用户输入"分析 sales.csv" -> Plan: `["使用数据分析模板读取 sales.csv", "执行数据质量检查", "执行 EDA 分析", "生成可视化图表", "汇总生成报告"]`
   - 关键词触发：`分析|统计|报表|可视化|探索|数据质量|检查数据`

5. **Coder 代码生成**：
   - 识别到数据分析意图时，不生成零散 pandas 代码，直接生成：

```python
from src.domain.templates.data_analysis import run_analysis
report_path = run_analysis("data/sales.csv", output_dir="reports/")
print(f"分析报告已生成: {report_path}")
```

6. **测试覆盖**：
   - 正常分析（黄金路径）
   - 空文件
   - 数据质量差（大量缺失，验证报告仍生成）
   - 用户指定特定列
   - 用户指定时间列

**验收标准**：
- `py_compile` 通过
- `test_data_analysis_template.py` 全部通过（>=5 个场景）
- 输入"分析 sales.csv"，输出包含：质量检查表 + 统计摘要 + 2 张图表 + 结论段落的完整 Markdown
- 全流程无需人类干预（黄金路径）
- 报告文件保存到 `workspace/reports/analysis_YYYYMMDD_HHMMSS.md`

**注意事项**：
- 模板放在 `src/domain/templates/` 下，与 `inventory_eoq.py` 同级
- 结论与建议部分用规则生成（基于 EDA 结果的 if-else），不依赖 LLM（避免额外调用和延迟）
- 保持模块化：`data_analysis.py` 内部调用 `data_quality.py`、`eda_engine.py`、`chart_templates.py`，不重复实现逻辑

---

## Day 7：E2E 集成测试 + Week 3 验收

**目标**：在 subprocess / MCP / Docker 三种模式下跑通完整数据分析闭环，产出 Benchmark 数字。

**需要新增的文件**：
- `tests/test_e2e_week3.py`（端到端集成测试）
- `tests/test_duckdb_sql.py`（Text-to-SQL 专项测试，如 Day 5 未写）
- `workspace/tests/benchmark_results.md`（手动或自动记录）

**实现要点**：

1. **测试任务定义**（3 个）：
   - **任务 A**：输入"分析 sales.csv" -> 验证输出报告包含 4 个章节（数据概览、质量检查、统计摘要、图表）
   - **任务 B**：输入"画 sales.csv 的月度销量趋势图和区域分布图" -> 验证生成 2 张 HTML 图表
   - **任务 C**：输入"各区域平均销量是多少" -> 验证生成正确 DuckDB SQL，结果表格包含各区域均值

2. **三模式测试矩阵**：
   - Phase 1（subprocess）：默认环境，9 个断言
   - Phase 2（MCP）：`USE_MCP=true`，9 个断言
   - Phase 3（Docker）：`USE_DOCKER=true`，9 个断言

3. **测试脚本结构**：

```python
def test_week3_data_analysis_subprocess():
    load_dotenv()
    state = build_graph().invoke({
        "user_query": "分析 workspace/data/sales.csv",
        "workspace_path": str(Path(__file__).parent.parent / "workspace")
    })
    assert state["final_report"] is not None
    assert "数据质量" in state["final_report"]
    assert "统计摘要" in state["final_report"]
    # 检查图表文件生成
    charts_dir = Path("workspace/reports/charts")
    assert len(list(charts_dir.glob("*.html"))) >= 2
```

4. **回归测试**：
   - 运行 `python -m pytest tests/ -v`
   - 确认 Week 1/2 测试全部通过：
     - `test_planner.py`（通过数 >=原有）
     - `test_coder.py` 45/45
     - `test_executor.py` 67/67
     - `test_debugger.py` 83/83
     - `test_graph.py` 55/55
   - 新增测试全部通过

5. **Benchmark 记录**：
   - 在 `DEV_LOG.md` 中记录：
     - 代码运行成功率：__%
     - 测试通过率：__%
     - 平均重试次数：__
     - 任务完成率：__%
     - SQL 生成正确率：__%
     - 图表生成成功率：__%

6. **文档更新**：
   - 更新 `DEV_DESIGN.md` 的"设计决策记录"表格，添加 Week 3 决策（Plotly/DuckDB/EDA 模板化）
   - 更新 `DEV_LOG.md` 记录 Week 3 每日完成情况

**验收标准**：
- 3 个任务 x 3 种模式 = 9 次执行，全部成功
- 报告质量：人工抽查 3 份报告，确认包含所有章节
- 图表可用性：HTML 文件可独立打开，中文正常
- SQL 正确率：>=70%（可用 10 个独立问题测试）
- 无回归：Week 1/2 原有测试全部通过
- 新增测试 >=100 项（累计），全部通过

**注意事项**：
- E2E 测试前确保 `.env` 已加载（测试脚本开头显式 `load_dotenv()`，避免 Week 2 坑 6 复现）
- Docker 测试前确认镜像已重新构建（Day 0 完成）
- 测试数据 `sales.csv` 必须存在且格式正确
- 记录所有踩坑到 `DEV_LOG.md` 的"踩坑记录"章节

---

## 附录 A：Week 3 设计决策记录（供 DEV_DESIGN.md 更新使用）

| 日期 | 决策 | 原因 | 可能风险 |
|------|------|------|---------|
| Week3-D4 | 可视化库选 Plotly 替代 Matplotlib | 无中文乱码、HTML 输出、交互性强、Docker 无需额外字体配置 | 静态图片嵌入 Markdown 稍复杂 |
| Week3-D5 | SQL 引擎选 DuckDB（内存模式） | 轻量、兼容 pandas、支持 CSV 直接查询、无需持久化数据库 | 大数据量（>1GB）可能内存不足 |
| Week3-D3 | EDA 实现为领域模板（eda_engine.py）而非 LLM 自由生成 | 保证统计正确性，减少 Debugger 触发，可复现 | 灵活性降低，需维护模板 |
| Week3-D2 | 数据质量检查作为 Coder 模板而非独立 Graph 节点 | 保持 LangGraph 结构简洁，避免节点膨胀 | 复杂多数据源场景可能需要独立节点 |
| Week3-D6 | 一键分析模板结论用规则生成（if-else）而非 LLM | 避免额外 LLM 调用延迟，保证确定性 | 结论智能化程度有限 |

---

## 附录 B：Week 3 前置依赖确认清单

- [ ] Python 3.11+（当前版本）
- [ ] Docker Desktop 29.2.1 + decision-coder-sandbox:latest (1.25 GB)（Day 0 重新构建）
- [ ] DeepSeek API Key
- [ ] MCP SDK (mcp>=1.0.0) + langgraph + langchain-deepseek
- [ ] plotly>=5.0 + duckdb>=0.10 + openpyxl>=3.0（Day 0 添加）
- [ ] 测试数据：sales.csv（>=100 行，含缺失值/异常值）+ inventory.csv（Day 0 准备）
- [ ] 中文字体：fonts-noto-cjk（Dockerfile 中安装）

---

## 附录 C：Week 3 重点风险预警

1. **DuckDB 与 pandas 版本冲突**：`duckdb>=0.10` 对 pandas 版本有要求，升级前确认兼容性。
2. **Plotly 在 Docker 中生成 HTML**：需验证 `plotly.offline.plot` 在只读容器 + tmpfs 环境下能否正常写 `/workspace/output/`。
3. **Text-to-SQL 幻觉**：LLM 可能生成不存在的列名，需在 Debugger 中新增 `DuckDBCatalogError`（列/表不存在）的规则回退。
4. **Week 2 测试回归**：新增依赖后，确认 `test_executor.py` 67/67、`test_graph.py` 55/55 仍全部通过。
5. **Matplotlib 中文乱码**：Week 1 踩坑记录已预警，Plotly 方案已规避，但需验证 Docker 容器内浏览器渲染效果。
6. **DuckDB 与 pandas DataFrame 互操作**：需验证 MCP file_tools 的 CSV 读取 -> DuckDB SQL 查询 -> DataFrame 返回的完整链路。

---

*文档版本：v1.0 | 日期：2026-07-04 | 对应开发阶段：Week 3*

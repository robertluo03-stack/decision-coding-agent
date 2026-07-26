# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

> **仓库规范名称**：本仓库在文档/链接中的规范名称为 **decision-coding-agent**（GitHub 仓库名），与本地目录名无关。任何文档提及仓库路径或 clone 地址时，一律使用 `decision-coding-agent`。

DecisionCoder 是一个面向经营决策与运筹优化的垂直 Coding Agent。基于 LangGraph StateGraph 编排 Plan-Code-Execute-Debug-Report 闭环，LLM 通过 DeepSeek API 调用。

- **当前阶段**：已完成 Week 8（规则路由接线 + 三臂实验，2026-07-24）
- **累计测试数**：569 tests（pytest --collect-only 全量收集, 2026-07-24, 全部通过零回归）
- **Commit 数**：75（首次提交 2026-06-21）

## 常用命令

```bash
# 激活虚拟环境
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# 安装项目（可编辑模式）
pip install -e .

# 运行主程序（交互式 CLI）
python main.py

# 带 Rich 终端 UI
python main.py --rich
# 或 USE_RICH=true python main.py

# Benchmark 评测
python -m benchmark run              # 运行全部 10 个任务
python -m benchmark run --rich       # 带 Rich 终端 UI
python -m benchmark report <jsonl>   # 从 JSONL 生成 MD + HTML 报告

# 用 pytest 运行全部单元测试
python -m pytest tests/ -v --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py

# 运行单个测试文件
python -m pytest tests/test_coder.py -v
python -m pytest tests/test_chart_templates.py -v
python -m pytest tests/test_text_to_sql.py -v
python -m pytest tests/test_data_analysis_template.py -v

# 运行 E2E 集成测试（需要 DEEPSEEK_API_KEY）
python tests/test_e2e_week3.py

# 检查单个 Python 文件语法
python -m py_compile src/domain/chart_templates.py
python -m py_compile src/agent/nodes/coder.py
```

## 核心架构

### LangGraph 状态机流转

```
Planner → Coder → Executor → [route_after_executor]
                                ├─ error 且非 ABORT → Debugger → [route_after_debugger]
                                │                              ├─ 非 ABORT → Coder（循环）
                                │                              └─ ABORT → Reporter
                                └─ 无 error 或 ABORT → Reporter → END
```

两个条件路由在 [src/agent/graph.py](src/agent/graph.py)：
- `route_after_executor`: error 且 `human_feedback != "ABORT"` → `"debug"`，否则 → `"report"`
- `route_after_debugger`: `human_feedback == "ABORT"` → `"report"`，否则 → `"code"`（回 Coder）

### UI 层（Week 6 新增）

[src/agent/ui/](src/agent/ui/) — Rich 终端 UI，可选启用：
- **ProgressPanel**：5 节点进度条（Planner/Coder/Executor/Debugger/Reporter）
- **StatusTable**：🟡等待 → 🔵运行中 → 🟢完成 → 🔴错误
- **LogPanel**：最多 50 条日志自动截断
- **DebugPanel**：Markdown 错误摘要 + 4 个选项
- **UIManager**：`queue.Queue` 线程安全缓冲，非 TTY 自动降级为 `print()`
- **NodeTracer**：函数包装器，零侵入追踪节点执行状态
- 启用方式：`main.py --rich` 或 `build_graph(use_ui=True, ui_manager=ui)`

### Benchmark 层（Week 6 新增，Week 8 扩展）

[src/benchmark/](src/benchmark/) — 自动化评测框架：
- **17 个预定义任务**：5 数据分析（BA-01~05）+ 5 代码生成（CG-01~05）+ 7 对抗（ADV-01~07，5 同任务多说法 + 2 模板外兜底）
- **BenchmarkRunner**：逐个执行任务，`threading.Event.wait(timeout)` 跨平台超时
- **MetricsCollector**：完成率/成功率/平均重试/平均耗时 + 按类别分组 + 按 arm 分组
- **ReportGenerator**：Markdown + HTML 报告（进度条/卡片/徽章，内联 CSS）
- **validate_task_result**：关键词匹配（不区分大小写 + 浮点数宽松匹配）
- **结果词/机制词双轨校验**：`expected_keywords`（结果词）全部命中 ⇒ success；`template_keywords`（机制词）单独统计 template_hit_rate
- **失败否决**：ABORT / fail_*.md 产出 → success=False
- JSONL 逐行追加，支持断点续跑
- **批次归档**：`results/artifacts/<时间戳>_<git哈希>/` 含 manifest.json
- **token_tracker.py**：monkey-patch `ChatDeepSeek.invoke` 捕获真实 token 用量
- **numeric_extractor.py**：数值一致率，中位数 ±5% 口径
- **HITL 自动应答**：`DECISIONCODER_HITL_AUTO` 环境变量，benchmark 无人值守
- **双臂对照**：`run_both()` — routing_on / routing_off 顺序执行，共享 batch_id
- CLI：`python -m benchmark run` / `python -m benchmark run --both` / `python -m benchmark run --both --adversarial` / `python -m benchmark report <jsonl>`

### AgentState

定义在 [src/agent/state.py](src/agent/state.py)。关键约束：
- `retry_count >= 2` → Debugger 入口直接返回 ABORT，不调用 LLM
- `human_feedback == "ABORT"` → Reporter 生成 `fail_*.md` 而非 `report_*.md`
- Executor 执行时注入 `PYTHONPATH` 指向项目根目录，使生成的代码能 `from src.domain.xxx import ...`

### 5 个节点 + Executor 三路径

Reporter 报告结构：1.任务描述 → 2.执行计划 → 3.执行结果 → 4.结果分析(LLM) → 5.错误与调试 → 附录(代码+图表+文件路径)。

| 节点 | 文件 | 职责 | 调用 LLM |
|------|------|------|---------|
| **Planner** | [planner.py](src/agent/nodes/planner.py) | 拆解需求为 ≤5 步骤 | ✅ DeepSeek（temperature=0.3）|
| **Coder** | [coder.py](src/agent/nodes/coder.py) | 生成 Python 代码 + 安全检查 + 回退代码 | ✅ DeepSeek（temp=0.3/0.1）|
| **Executor** | [executor.py](src/agent/nodes/executor.py) | Compose / MCP / subprocess 三路径执行 | ❌ |
| **Debugger** | [debugger.py](src/agent/nodes/debugger.py) | 14种规则错误分类 + LLM分析 + 人机交互 | ✅ DeepSeek（temp=0.3）|
| **Reporter** | [reporter.py](src/agent/nodes/reporter.py) | Markdown 报告 + 图表检测 + LLM 结果分析（DeepSeek）| ✅ DeepSeek（temp=0.3）|

Executor 三路径：
- **Compose Sandbox**（最高优先级）：`SANDBOX_URL` 或 `USE_COMPOSE=true` → SandboxClient HTTP 远程执行
- **MCP**：`USE_MCP=true` → MCP Client (stdio) 调用 python_exec Tool
- **subprocess**（默认/回退）：`subprocess.run(env={PYTHONPATH: project_root})`，30s 超时

### 提示词管理（已外置）

所有 LLM Prompt 在 [src/agent/nodes/prompts/](src/agent/nodes/prompts/)：
- **`.md` 文件** — 静态系统提示词（纯中文，直接编辑）：
  [planner.md](src/agent/nodes/prompts/planner.md)、[coder.md](src/agent/nodes/prompts/coder.md)、[debugger_analysis.md](src/agent/nodes/prompts/debugger_analysis.md)、[debugger_fix.md](src/agent/nodes/prompts/debugger_fix.md)、[reporter_analysis.md](src/agent/nodes/prompts/reporter_analysis.md)
- **`*_user.py` 文件** — 动态拼接用户消息的 builder 函数
- **[loader.py](src/agent/nodes/prompts/loader.py)** — `load_prompt(filename)` 从 disk 读取 `.md`，带 `@lru_cache` 缓存

**coder.md 模板优先级**（Coder 根据用户 intent 选择模板）：
1. **数据分析整体** → `run_analysis()`（一键分析模板）
2. **数据质量/清洗** → `run_quality_check()`（单一质量检查）
3. **画图/可视化** → `chart_templates`（5种图表，单一场景）
4. **自然语言问数** → `run_text_to_sql()`（Text-to-SQL，单一场景）
5. **供应链库存优化** → `inventory_eoq` / `demand_forecast` / `safety_stock` / `reorder_point`（领域模板）

### 领域模板层

所有模板在 [src/domain/](src/domain/)，通过 [src/domain/__init__.py](src/domain/__init__.py) 统一导出（36个符号）。

| 模块 | 主函数 | 用途 |
|------|--------|------|
| [data_quality.py](src/domain/data_quality.py) | `run_quality_check(df)` | 4维度质量检测 + 0-100评分 + 中文建议 |
| [chart_templates.py](src/domain/chart_templates.py) | `bar_chart/line_chart/histogram/scatter/heatmap(df, x, y, title, path)` | 5种 Plotly HTML 图表 |
| [text_to_sql.py](src/domain/text_to_sql.py) | `run_text_to_sql(query, csv_path)` | NL→Schema→LLM SQL→安全检查→DuckDB执行 |
| [templates/data_analysis.py](src/domain/templates/data_analysis.py) | `run_analysis(file_path)` | 一键分析：读取→质量→EDA→图表→报告 |
| [templates/inventory_eoq.py](src/domain/templates/inventory_eoq.py) | `calculate(EOQParams)` | EOQ 经济订货批量 |
| [templates/demand_forecast.py](src/domain/templates/demand_forecast.py) | `forecast(ForecastParams)` / `auto_forecast(history, periods)` | 需求预测（多元回归+ML+平均） |
| [templates/safety_stock.py](src/domain/templates/safety_stock.py) | `calculate_safety_stock(SafetyStockParams)` | 安全库存（Z分数法） |
| [templates/reorder_point.py](src/domain/templates/reorder_point.py) | `calculate(ROPParams)` | 补货点（ROP） |
| [templates/inventory_pipeline.py](src/domain/templates/inventory_pipeline.py) | `run_inventory_pipeline(InventoryPipelineParams)` | 库存分析流水线（多SKU/多仓） |

### 安全纵深防御

5 道防线（详见 [security_checker.py](src/agent/sandbox/security_checker.py)）：
1. **LLM 语义识别**（Planner）→ 拒绝危险意图
2. **AST 安全检查**（Coder 后置）→ 拦截 os.system/subprocess/eval/exec/__import__/compile
3. **Executor 执行前预检** → 空代码 + 危险代码(AST) + 语法(compile)
4. **DockerRunner AST 兜底**（DockerRunner.run 入口）→ 落地前再检
5. **Docker / Compose 容器沙箱** → --memory=512m --read-only --network none

SQL 安全（Text-to-SQL）：LLM 层约束 + 12种危险关键字正则 + SELECT-only 前缀检查。

### 两套回退机制

1. **LLM 调用失败** → 规则回退（Debugger: 14种 `_diagnose_by_rule` 含 DuckDB 错误 / 多种 `_fix_by_rule` 策略）
2. **LLM 生成不安全代码** → Coder 后置 `_has_dangerous_code()`（委托给 security_checker）→ 回退安全代码 `_generate_fallback_code()`

### 规则路由层（2026-07-22 接线）

在 Coder 调用 LLM 之前，先尝试模板匹配 + 参数提取：

- **`_run_rule_routing(query)`** (coder.py:223)：调用 `src.domain.template_matcher.match_template` 和 `src.domain.param_extractor.extract_params_for_template`
- **`_TEMPLATE_GUIDANCE`** (coder_user.py:16)：5 种模板类型（eoq / forecast / safety_stock / reorder_point / data_analysis），映射到 display_name + import 与调用指引
- **`_build_routing_guidance()`** (coder_user.py:96)：将命中结果以【规则路由信息】块注入 Coder user message，含识别任务类型、置信度、已提取参数、模板调用指引
- **未命中回退**：`template_type == UNKNOWN` → 返回 (None, None)，Coder 保持纯 LLM 自由路由
- **环境开关**：`DECISIONCODER_NO_ROUTING=true` 跳过规则路由（实验对照，见 coder.py:239）

template_matcher (template_matcher.py:130)：基于关键词加权评分的模板匹配，5 种模板类型（EOQ / FORECAST / DATA_ANALYSIS / SAFETY_STOCK / REORDER_POINT + UNKNOWN），`_CONFIDENCE_THRESHOLD = 1.5`，低于阈值返回 UNKNOWN。

### MCP 工具层

FastMCP server 在 [src/mcp/server.py](src/mcp/server.py)，8 个 Tool 通过 `@server.tool()` 注册，stdio transport。Tools: `file_read` / `file_write` / `file_read_csv` / `file_read_csv_legacy` / `file_read_excel` / `file_list_dir` / `file_exists` / `python_exec`。

### LLM 调用

全部节点通过 `langchain_deepseek.ChatDeepSeek` 调用：
- model = `deepseek-chat`, API Key 从 `DEEPSEEK_API_KEY` 环境变量
- temperature: 0.3（Planner/Coder/Debugger），0.1（Text-to-SQL 的 `_call_llm_for_sql`）

## 开发约定

- Python 3.11+，所有函数必须有参数和返回值类型注解
- 函数 docstring 用中文，注释用英文
- 新增依赖写入 `pyproject.toml`，禁止引入重量级库（PyTorch/Transformers/TensorFlow）
- 每个节点文件导出 `run = xxx_node` 别名（graph.py 的 `_ensure_imports()` 惰性加载依赖此约定）
- **不要修改 `AgentState` 字段定义**（除非确认）
- Coder 生成的代码必须禁止 `os.system` / `subprocess` / `eval` / `exec` / `__import__`
- 所有文件操作限定在 `workspace_path` 下（当前唯一工作区为 `workspace/`，由 `.env` 中 `WORKSPACE_PATH=./workspace` 指定）
- 新增领域模板放在 `src/domain/templates/`，通过 `src/domain/__init__.py` 统一导出
**图表模块**：5 种 Plotly HTML 图表，支持 `auto_open` 自动浏览器打开，`DECISIONCODER_NO_BROWSER` 环境变量关闭，pytest 环境自动跳过。
- **E2E 测试**：`tests/test_e2e_week3.py` 依赖 `DEEPSEEK_API_KEY`，测试脚本需显式 `load_dotenv()` 加载 `.env`
- 所有测试脚本可直接 `python tests/test_xxx.py` 运行，也可 `pytest tests/test_xxx.py -v`
- **Benchmark 任务**：新增任务定义在 `src/benchmark/tasks.py` 的 `get_default_tasks()` 函数中，保持 5+5 分类（BA-01~05 数据分析，CG-01~05 代码生成），每个任务必须包含 `expected_keywords`（3-5 个，不区分大小写）和明确的 query
- **UI 组件**：新增面板在 `src/agent/ui/panels.py`，通过 `UIManager` 管理。面板只接收状态更新不修改状态。NodeTracer 通过函数包装器注入不修改节点文件。
- **Benchmark 报告**：`ReportGenerator.generate_md/html()` 接受 `MetricsCollector`，零外部框架（内联 CSS），可从 Runner 或 JSONL 构建

### 环境变量清单

| 变量 | 用途 | 取值 |
|------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（必需） | 字符串 |
| `WORKSPACE_PATH` | 工作区根目录 | 路径，默认 `./workspace` |
| `USE_RICH` | 启用 Rich 终端 UI | `true` 启用 |
| `USE_MCP` | Executor 走 MCP Client 路径 | `true` 启用 |
| `USE_DOCKER` | Executor 走 Docker 容器路径 | `true` 启用 |
| `USE_COMPOSE` | Executor 走 Docker Compose HTTP 沙箱路径 | `true` 启用 |
| `SANDBOX_URL` | Compose 沙箱服务地址 | URL，如 `http://localhost:8080` |
| `DECISIONCODER_NO_BROWSER` | 关闭图表自动浏览器打开 | `true` / `1` / `yes` |
| `DECISIONCODER_NO_ROUTING` | 跳过规则路由，回退到纯 LLM 路由（实验对照） | `true` / `1` / `yes` |
| `DECISIONCODER_HITL_AUTO` | HITL 自动应答策略（benchmark 无人值守），值如 `"1,4"` 按序返回 | 逗号分隔的选择序号 |

## AI 写代码时的标准流程

1. 读取本文件（CLAUDE.md）
2. 读取 [DEV_DESIGN.md](DEV_DESIGN.md) 中相关阶段的设计
3. 只修改指定文件，不修改其他文件
4. 实现后运行 `python -m py_compile <file>` 检查语法
5. 运行相关测试确认无回归
6. 更新 [DEV_LOG.md](DEV_LOG.md) 记录变更

## 关键文档

- **[DEV_DESIGN.md](DEV_DESIGN.md)** — 设计决策记录（55条）、阶段规划、接口契约、安全体系、API参考、架构演进表
- **[DEV_LOG.md](DEV_LOG.md)** — 按日期记录的开发日志 + 25条踩坑记录 + Benchmark数据
- **[docs/experiment_three_arm.md](docs/experiment_three_arm.md)** — 三臂实验设计与结果报告
- **[results/review_arm_a_20260724.md](results/review_arm_a_20260724.md)** — A 臂复核终审报告（19 条逐条裁决）

## A 臂脚本（Claude Code 裸用基线）

[scripts/run_arm_a.py](scripts/run_arm_a.py) — 与 B/C 臂公平对照：
- `claude -p --output-format json --dangerously-skip-permissions` 子进程调用
- 隔离工作目录 `arm_a_workspace/`（仓库外，仅 3 个 CSV 数据文件）
- `--smoke` 冒烟（CG-01 × 1）/ `--full` 全量（17 任务 × 3 = 51 次）
- `--timeout-cap <秒>` 统一超时上限（正式口径 600s）
- 判定域差异：A 臂扫 claude 最终答复文本；B/C 臂扫 stdout + 报告全文

## 已知问题与迭代清单

取自 [results/review_arm_a_20260724.md](results/review_arm_a_20260724.md) 质性发现 §7：

1. **Reporter 内联子报告结果**：当前 `execution_result`（stdout）与 `final_report`（Markdown）分开存储，Reporter 未将执行阶段的关键数值内联到报告中，导致关键词扫描域仅覆盖 `execution_result + final_report` 合并文本而未在报告正文中重复关键数值。
2. **归档完整性**：A 臂生成的 HTML/脚本文件仍在 `arm_a_workspace/` 中，被后续运行覆写，未按 run 归档。B/C 臂的 `_archive_artifacts` 仅归档 reports/ 目录下的 `.md` 和 `.html` 图表文件，不包含 stdout 文本、生成的 Python 代码、其他生成文件。
3. **验证器判定域文档化**：A 臂扫描 `result` 字段（claude 最终答复文本）；B/C 臂扫描 `execution_result`（stdout）+ `final_report`（Markdown 报告）。ADV-06 run3 的关键词存在于代码文件（`palindrome.py`）不在答复文本，此差异需在 validators.py 与 run_arm_a.py 的 docstring 中明确记载。
4. **manifest 双臂记录**：当前 `run_both()` 共享一个 manifest，但仅记录 last-write 的 arm_config。应改为记录 arm_sequence 数组。
5. **关键词双语化**：`expected_keywords` 含英文缩写（"bar" / "ROP" / "MAPE" / "SELECT" / "AVG"）时，A 臂用自然语言替换这些词（"柱状图"/"Reorder Point"），属函数正确行为却被判失败。应补充等效中文关键词或放宽为 (keyword, weight) 评分制。
6. **`_find_generated_files` 按 task_id 过滤**：当前取 `workspace/reports/` 下全局 mtime 最新的文件，多任务顺序执行时可能将前一个任务的报告误归入当前任务。应改为按 task_id 前缀或文件名 timestamp 过滤。

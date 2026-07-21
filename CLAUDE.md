# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

DecisionCoder 是一个面向经营决策与运筹优化的垂直 Coding Agent。基于 LangGraph StateGraph 编排 Plan-Code-Execute-Debug-Report 闭环，LLM 通过 DeepSeek API 调用。

- **当前阶段**：已完成 Week 7（工程化）
- **累计测试数**：以 pytest 实跑为准（全部通过，零回归）

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

### Benchmark 层（Week 6 新增）

[src/benchmark/](src/benchmark/) — 自动化评测框架：
- **10 个预定义任务**：5 数据分析（BA-01~05）+ 5 代码生成（CG-01~05）
- **BenchmarkRunner**：逐个执行任务，`threading.Event.wait(timeout)` 跨平台超时
- **MetricsCollector**：完成率/成功率/平均重试/平均耗时 + 按类别分组
- **ReportGenerator**：Markdown + HTML 报告（进度条/卡片/徽章，内联 CSS）
- **validate_task_result**：关键词匹配（大小写不敏感 + 浮点数宽松匹配）
- JSONL 逐行追加，支持断点续跑
- CLI：`python -m benchmark run` / `python -m benchmark report <jsonl>`

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

## AI 写代码时的标准流程

1. 读取本文件（CLAUDE.md）
2. 读取 [DEV_DESIGN.md](DEV_DESIGN.md) 中相关阶段的设计
3. 只修改指定文件，不修改其他文件
4. 实现后运行 `python -m py_compile <file>` 检查语法
5. 运行相关测试确认无回归
6. 更新 [DEV_LOG.md](DEV_LOG.md) 记录变更

## 关键文档

- **[DEV_DESIGN.md](DEV_DESIGN.md)** — 设计决策记录（27条）、阶段规划、接口契约、安全体系、API参考、架构演进表
- **[DEV_LOG.md](DEV_LOG.md)** — 按日期记录的开发日志 + 25条踩坑记录 + Benchmark数据

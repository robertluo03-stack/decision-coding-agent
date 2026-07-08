# Week 6 开发提示词（面向 Claude Code）

> **项目**：DecisionCoder — 面向经营决策与运筹优化的垂直 Coding Agent  
> **当前阶段**：Week 5 已完成（供应链库存分析端到端闭环），进入 Week 6  
> **目标**：Rich 终端 UI + Benchmark 评测体系  
> **开发工具**：Claude Code (claude.ai/code)  
> **约束**：新增依赖仅 `rich` 一个库；所有现有测试 390+ 零回归；向后兼容

---

## 前置准备（Day 0）

在正式开始 Day 1 之前，请完成以下准备工作：

### 1. 环境检查
```bash
# 激活虚拟环境
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# 确认当前依赖已安装
pip install -e .

# 运行全量回归测试，确认 Week 5 基线通过
python -m pytest tests/ --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py -v
# 预期：390+ 测试全部通过
```

### 2. 创建分支（可选）
```bash
git checkout -b week6-rich-benchmark
```

### 3. 阅读参考文档
Claude Code 在编写代码前必须阅读：
1. `CLAUDE.md` — 项目指南（架构、约定、常用命令）
2. `DEV_DESIGN.md` — 设计文档（状态机、接口契约、安全体系）
3. `DEV_LOG.md` — 开发日志（Week 1-5 踩坑记录、Benchmark 数字）

### 4. 待修复问题清单（Week 5 遗留）

| 问题 | 影响 | 建议处理时机 |
|------|------|-------------|
| E2E Week 3 `test_task_c_text_to_sql_subprocess` 偶发失败（Debugger input 与 pytest stdin 冲突） | 低 | 暂不修复，Week 6 E2E 采用 mock `_safe_input` 规避 |
| inventory_pipeline 年需求推断默认兜底为月（若日期格式异常） | 低 | 暂不修复，Week 6 Benchmark 任务使用标准格式数据 |
| Docker 镜像重建待 `docker build` | 中 | Week 7 Docker Compose 阶段统一处理 |

---

## Day 1：Rich 终端 UI 基础框架

### 目标
引入 `rich` 库，搭建可复用的 UI 组件体系，让 `main.py` 从纯文本打印升级为多面板实时渲染。

### 前置准备
```bash
pip install rich>=13.0
```

### 开发提示词

```markdown
## 任务：Day 1 — Rich 终端 UI 基础框架

请按以下步骤实现：

1. **依赖**：在 `pyproject.toml` 的 `[project.dependencies]` 中新增 `rich>=13.0`，然后运行 `pip install -e .` 安装。

2. **创建 UI 包**：
   - 新建 `src/agent/ui/__init__.py`，导出 `UIManager`, `ProgressPanel`, `StatusTable`, `LogPanel`
   - 新建 `src/agent/ui/panels.py`，实现三个面板类：
     * `ProgressPanel`：使用 `rich.progress.Progress`，5 个节点对应 5 个 `TaskID`（Planner/Coder/Executor/Debugger/Reporter）
     * `StatusTable`：使用 `rich.table.Table`，列：节点名 | 状态（🟡 等待/🟢 完成/🔴 错误） | 耗时 | 重试次数
     * `LogPanel`：使用 `rich.console.Group` + `rich.text.Text`，最多保留 50 条日志，自动截断

3. **UIManager**：
   - 类 `UIManager` 在 `src/agent/ui/manager.py`
   - `__init__(self, force_terminal: bool | None = None)`：自动检测 TTY
   - `start(self)`：启动 `rich.live.Live`，布局为左右分栏（左：ProgressPanel+StatusTable，右：LogPanel）
   - `stop(self)`：关闭 Live
   - `update_node(node: str, status: str, elapsed: float, retry: int = 0)`：更新对应节点状态
   - `log(message: str, level: str = "info")`：追加日志到 LogPanel
   - 使用 `queue.Queue` 做线程安全缓冲，主线程 `Live` 中每 0.1s 消费一次队列

4. **测试**：
   - 新建 `tests/test_ui_base.py`，至少 4 个测试：
     * `test_panels_import`：面板类可导入
     * `test_manager_lifecycle`：start/stop 不抛异常
     * `test_update_node`：更新后状态正确
     * `test_tty_fallback`：非 TTY 模式下 force_terminal=False 不启动 Live

5. **规范**：
   - 所有函数类型注解完整
   - docstring 中文
   - 不修改 `src/agent/graph.py` 等现有文件（Day 2 再集成）
   - 运行 `python -m py_compile` 检查所有新增文件
   - 运行 `python -m pytest tests/test_ui_base.py -v` 确保通过
   - 运行全量回归：`python -m pytest tests/ --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py -v` 确认零回归
   - 仿照DEV_LOG.md文档结构，在末尾记录这次开发
```

### 设计约束（必须遵守）
- **零侵入**：UI 层只接收状态更新，不修改 Graph/节点逻辑
- **降级策略**：若终端不支持（CI/非 TTY），自动回退到纯 `print()`（`rich` 自带 `force_terminal` 检测）
- **线程安全**：`Live` 更新必须在主线程，`UIManager` 内部用 `queue.Queue` 缓冲更新事件

### 验收标准
- [ ] `python -m py_compile src/agent/ui/*.py` 全部通过
- [ ] `tests/test_ui_base.py` 4+ 测试通过
- [ ] 全量回归 390+ 测试通过
- [ ] `pip install -e .` 后 `rich` 可用

---

## Day 2：Graph 执行过程实时追踪

### 目标
将 UI 管理器接入 LangGraph 状态机，实现节点执行时的实时进度反馈，用户能直观看到当前走到哪一步、是否进入 Debugger 循环。

### 前置准备
- Day 1 已完成，`UIManager` 和 `ProgressPanel`/`StatusTable`/`LogPanel` 可正常工作
- 阅读 `src/agent/graph.py` 中 `build_graph()` 和节点注册逻辑

### 开发提示词

```markdown
## 任务：Day 2 — Graph 执行过程实时追踪

请按以下步骤实现：

1. **NodeTracer**：
   - 新建 `src/agent/ui/tracer.py`
   - 实现 `class NodeTracer`：
     * `__init__(self, ui: UIManager, node_name: str)`
     * `trace(self, func: Callable) -> Callable`：包装函数，记录开始/结束/耗时/异常
     * 若 func 抛出异常，调用 `ui.update_node(node_name, "error")` 并 re-raise
   - 实现 `trace_graph_nodes(ui_manager, graph_builder)`：接收 `StateGraph` builder，为每个已注册节点添加 tracer 包装

2. **Graph 集成**：
   - 修改 `src/agent/graph.py`：
     * `build_graph(use_ui: bool = False, ui_manager: UIManager | None = None)` 新增参数
     * 若 `use_ui` 为 True 且 `ui_manager` 不为 None，在 `graph.add_node()` 之后、编译之前，用 `NodeTracer` 包装每个节点的 `run` 函数
     * **注意**：不要修改节点文件本身（planner.py/coder.py 等），只在 graph 组装阶段包装
     * 默认 `use_ui=False`，确保所有现有测试零回归

3. **Debugger 面板**：
   - 扩展 `src/agent/ui/panels.py`：
     * 新增 `DebugPanel`：使用 `rich.panel.Panel` + `rich.markdown.Markdown`，展示 error 摘要 + 4 个选项（1.AI_FIX / 2.USER_FIX / 3.SKIP / 4.ABORT）
     * 在 `UIManager` 中新增 `enter_debug_mode(error: str, diagnosis: str)` / `exit_debug_mode()` 方法
     * 进入 debug 模式时，左侧进度条暂停（`Progress.stop_task`），右侧显示 `DebugPanel`

4. **main.py 集成**：
   - 修改 `main.py`：
     * 导入 `UIManager` 和 `build_graph`
     * 解析命令行参数或环境变量 `USE_RICH`（无需 argparse，简单检查 `sys.argv` 是否含 `--rich` 或 `os.environ.get("USE_RICH") == "true"`）
     * 若启用 Rich：创建 `UIManager`，start()，传入 `build_graph(use_ui=True, ui_manager=ui)`，任务结束后 `ui.stop()`
     * 若未启用：保持原有纯 print 逻辑不变

5. **测试**：
   - 新建 `tests/test_ui_tracer.py`：
     * `test_tracer_wraps_function`：验证包装后函数仍返回正确结果
     * `test_tracer_updates_ui`：mock UIManager，验证 update_node 被调用
     * `test_tracer_error_status`：mock 函数抛异常，验证状态变为 "error"
     * `test_graph_build_with_ui`：验证 `build_graph(use_ui=True)` 不抛异常且编译成功
     * `test_graph_build_without_ui`：验证默认行为与 Week 5 一致（运行 `test_graph.py` 中的 1-2 个核心测试做回归）

6. **验证**：
   - `python -m py_compile` 所有修改文件
   - `python -m pytest tests/test_ui_tracer.py tests/test_graph.py -v` 通过
   - 手动运行 `python main.py --rich` 输入一个简单查询（如"分析 sales.csv"），观察面板是否正常渲染（不验证 LLM 结果，只看 UI 不崩溃）
   - 全量回归测试通过
   
7. **记录**：
   - 仿照DEV_LOG.md文档结构，在末尾记录这次开发
```

### 关键设计决策（必须遵守）
- **可选启用**：通过 `build_graph(use_ui: bool = False)` 参数控制，默认保持 Week 5 行为不变
- **Tracer 实现**：使用函数包装器，不修改 LangGraph 节点函数本身
- **Debugger 特殊处理**：进入 Debugger 时 `status="debug"`，进度条暂停动画，右侧 LogPanel 高亮显示错误摘要

### 验收标准
- [ ] `build_graph(use_ui=False)` 时所有现有测试通过（零回归）
- [ ] `build_graph(use_ui=True)` 不抛异常
- [ ] `main.py --rich` 启动后 UI 正常渲染，不崩溃
- [ ] `main.py` 不带 `--rich` 时行为与 Week 5 完全一致
- [ ] 全量回归 390+ 测试通过

---

## Day 3：Benchmark 任务集与指标定义

### 目标
定义 10 个标准评测任务（5 数据分析 + 5 代码生成），设计指标收集器，建立可重复、可对比的评测基准。

### 前置准备
- 确认 `workspace/data/` 下已有数据文件：`sales.csv`, `inventory.csv`, `sku_inventory.csv`
- 阅读 `src/agent/state.py` 了解 `AgentState` 字段，确认验证时可用的输出字段

### 开发提示词

```markdown
## 任务：Day 3 — Benchmark 任务集与指标定义

请按以下步骤实现：

1. **包结构**：
   - 新建 `src/benchmark/__init__.py`，导出 `BenchmarkRunner`, `BenchmarkTask`, `MetricsCollector`
   - 新建 `src/benchmark/models.py`：
     * `BenchmarkTask` dataclass：字段 `id: str`, `category: Literal["data_analysis", "code_generation"]`, `query: str`, `expected_keywords: list[str]`, `timeout: int = 60`, `data_files: list[str] | None = None`（依赖的数据文件）
     * `BenchmarkResult` dataclass：字段 `task_id`, `success: bool`, `completed: bool`, `retry_count: int`, `elapsed_seconds: float`, `error: str | None`, `output_keywords_found: list[str], report_path: str | None`

2. **任务集**：
   - 新建 `src/benchmark/tasks.py`，定义函数 `get_default_tasks() -> list[BenchmarkTask]`，返回 10 个任务：
     * 数据分析类（5个）：使用 `sales.csv`, `inventory.csv`, `sku_inventory.csv` 等已有数据文件
     * 代码生成类（5个）：纯参数计算，不依赖外部文件（除 inventory_pipeline 用 sku_inventory.csv）
     * 每个任务的 `expected_keywords` 设置 3-5 个关键词，用于自动验证输出内容
     * 任务 6-9 的 query 中明确包含参数，确保 Coder 生成模板调用代码而非数据分析代码
     * 具体任务定义：
       - BA-01: 分析 sales.csv 并给出统计摘要（expected: ["销量", "均值", "标准差"]）
       - BA-02: 检查 sales.csv 数据质量（expected: ["缺失值", "异常值", "评分"]）
       - BA-03: 对 sales.csv 画柱状图（expected: ["图表", "html", "bar"]）
       - BA-04: 用 Text-to-SQL 查询 sales.csv 各区域平均销量（expected: ["SELECT", "AVG", "区域"]）
       - BA-05: 一键分析 inventory.csv（expected: ["分析", "inventory", "报告"]）
       - CG-01: 计算 EOQ，年需求 1000，订货成本 50，持有成本 2（expected: ["EOQ", "223"]）
       - CG-02: 预测未来 3 期需求 [100,120,110,130]（expected: ["预测", "MAPE", "Holt"]）
       - CG-03: 计算安全库存，avg_demand=100, std=20, lead_time=2, sl=95%（expected: ["安全库存", "Z", "1.64"]）
       - CG-04: 计算补货点，avg_demand=100, lead_time=2, safety_stock=50（expected: ["补货点", "ROP", "250"]）
       - CG-05: 运行 inventory_pipeline 分析 sku_inventory.csv（expected: ["pipeline", "报告", "图表"]）

3. **指标收集器**：
   - 新建 `src/benchmark/metrics.py`，实现 `MetricsCollector`：
     * `__init__`：初始化空列表 `self.results: list[BenchmarkResult]`
     * `record(result: BenchmarkResult)`：追加结果
     * `compute() -> dict`：返回指标字典：
       - `completion_rate` = completed / total
       - `success_rate` = success / total
       - `avg_retry_count` = mean(retry_count)
       - `avg_elapsed_seconds` = mean(elapsed_seconds)
       - `category_breakdown`：按 category 分组统计
       - `task_details`：每个任务的详细结果列表
     * 所有指标保留 2 位小数

4. **测试**：
   - 新建 `tests/test_benchmark_models.py`：
     * `test_task_loads`：验证 `get_default_tasks()` 返回 10 个任务
     * `test_task_categories`：验证 5+5 分类正确
     * `test_metrics_empty`：空收集器指标为 0
     * `test_metrics_compute`：mock 3 个结果，验证指标计算正确
     * `test_task_timeout_positive`：所有任务 timeout > 0

5. **规范**：
   - 不引入新依赖（只用标准库 + dataclass）
   - 数据文件路径使用相对路径（`workspace/data/sales.csv`），Benchmark 执行时自动解析为绝对路径
   - 运行 `python -m py_compile` 和 `pytest tests/test_benchmark_models.py -v`
   - 全量回归测试通过

6. **记录**：
   - 仿照DEV_LOG.md文档结构，在末尾记录这次开发
```

### 设计约束（必须遵守）
- 不引入新依赖（只用标准库 + dataclass）
- 数据文件路径使用相对路径，执行时自动解析为绝对路径
- 任务 query 必须明确，避免 LLM 意图模糊

### 验收标准
- [ ] `get_default_tasks()` 返回 10 个合法任务
- [ ] 5 数据分析 + 5 代码生成分类正确
- [ ] `MetricsCollector` 计算指标正确（保留 2 位小数）
- [ ] 全量回归 390+ 测试通过

---

## Day 4：Benchmark 执行引擎

### 目标
实现批量执行 10 个任务的引擎，自动调用 Graph，收集结果，处理超时与异常，支持断点续跑（JSONL 持久化）。

### 前置准备
- Day 3 已完成，`BenchmarkTask` 和 `MetricsCollector` 可正常工作
- 阅读 `src/agent/graph.py` 中 `run()` 便捷入口
- 确认 `DEEPSEEK_API_KEY` 已设置（用于手动验证，测试用 mock）

### 开发提示词

```markdown
## 任务：Day 4 — Benchmark 执行引擎

请按以下步骤实现：

1. **验证器**：
   - 新建 `src/benchmark/validators.py`：
     * `validate_task_result(task: BenchmarkTask, state: dict) -> BenchmarkResult`：
       - `completed` = state 包含 final_report 或 execution_result（非空）
       - `success` = completed 且 (execution_result 或 final_report) 包含所有 expected_keywords（不区分大小写，部分匹配）
       - 若 task 含 `data_files`，额外检查文件是否生成（如 `reports/report_*.md` 或 `reports/charts/*.html`）
       - `retry_count` = state.get("retry_count", 0)
       - `error` = state.get("error")
       - `elapsed_seconds` = 外部传入（Runner 计时）
     * 关键词匹配不区分大小写，支持部分匹配（`in` 操作）
     * 浮点数比较：预期值如 "223" 允许实际输出 "223.61"，验证逻辑应检查子串而非精确相等

2. **执行引擎**：
   - 新建 `src/benchmark/runner.py`，实现 `BenchmarkRunner`：
     * `__init__(self, tasks: list[BenchmarkTask], workspace_path: str, output_dir: str = "results/")`
     * `run_single(task: BenchmarkTask) -> tuple[dict, float]`：调用 `graph.run()`（从 `src.agent.graph` 导入 `run` 便捷入口），返回 (final_state, elapsed_seconds)
       - 用 `time.time()` 计时
       - 用 `threading.Timer(task.timeout, _timeout_handler)` 做超时，超时后抛自定义 `BenchmarkTimeoutError`
       - 捕获所有异常，异常时返回 state 含 error 信息
     * `run_all() -> MetricsCollector`：遍历 tasks，逐个执行，每完成一个：
       - 调用 `validate_task_result`
       - 将 `BenchmarkResult` 写入 `results/benchmark_YYYYMMDD_HHMMSS.jsonl`（每行一个 JSON）
       - 打印进度（`print(f"[{i+1}/{n}] {task.id} ...")`，保持简单，Rich 集成在 Day 5）
     * 每个任务执行前清理环境：删除 `workspace/src/_dc_exec_*.py`、旧报告（避免前一个任务污染）
     * `run_all()` 返回 `MetricsCollector`

3. **CLI 入口**：
   - 新建 `src/benchmark/__main__.py`：
     * `if __name__ == "__main__":` 入口
     * 解析 `sys.argv`：若 `sys.argv[1] == "run"`，则执行 `runner.run_all()`
     * 自动加载 `.env`（`load_dotenv()`）
     * 自动检查 `DEEPSEEK_API_KEY` 是否存在，不存在则报错退出
     * 工作区路径默认 `workspace/`，可通过 `WORKSPACE_PATH` 环境变量覆盖

4. **测试**：
   - 新建 `tests/test_benchmark_runner.py`：
     * `test_runner_init`：初始化正确
     * `test_run_single_mock`：mock `graph.run` 返回成功 state，验证结果正确
     * `test_run_single_timeout`：mock 一个 sleep 超过 timeout 的任务，验证 `completed=False`
     * `test_run_single_error`：mock graph 抛异常，验证 `error` 被捕获
     * `test_validate_keywords`：验证关键词匹配逻辑（含大小写、部分匹配、浮点数宽松匹配）
     * `test_validate_file_exists`：mock 文件存在性检查
     * `test_jsonl_output`：验证 run_all 后 JSONL 文件存在且每行可解析
     * `test_environment_cleanup`：验证任务前清理逻辑正确

5. **规范**：
   - 不修改现有 Graph/节点代码
   - 超时处理优先跨平台（threading.Timer），不依赖 Unix signal
   - 运行 `python -m py_compile` 和 `pytest tests/test_benchmark_runner.py -v`
   - 全量回归测试通过
   - 手动验证：`python -m benchmark run` 能启动（因需 API Key，可只跑 1 个任务测试）

6. **记录**：
   - 仿照DEV_LOG.md文档结构，在末尾记录这次开发
```

### 关键设计决策（必须遵守）
- **隔离执行**：每个任务独立 `graph.invoke()`，任务间 state 不共享，避免 `retry_count` 污染
- **超时控制**：用 `threading.Timer`（跨平台），超时记为 `completed=False`
- **断点续跑**：JSONL 每完成一个任务 append 一行（Day 5 扩展 `--resume`）
- **环境清理**：每个任务前删除 `workspace/src/_dc_exec_*.py` 和旧报告

### 验收标准
- [ ] `BenchmarkRunner.run_single()` mock 测试通过
- [ ] 超时处理正确（`completed=False`）
- [ ] 异常捕获正确（`error` 被记录）
- [ ] JSONL 输出格式正确（每行一个合法 JSON）
- [ ] 环境清理逻辑正确
- [ ] 全量回归 390+ 测试通过

---

## Day 5：Benchmark 报告生成与 Rich 集成

### 目标
将 Benchmark 结果转化为可视化的 Markdown/HTML 报告，并将 Rich UI 集成到 Benchmark 执行过程中，实现"边跑边看"。

### 前置准备
- Day 4 已完成，`BenchmarkRunner` 和 `MetricsCollector` 可正常工作
- 确认 `results/` 目录存在（或 Runner 会自动创建）

### 开发提示词

```markdown
## 任务：Day 5 — Benchmark 报告生成与 Rich 集成

请按以下步骤实现：

1. **报告生成器**：
   - 新建 `src/benchmark/reporter.py`，实现 `ReportGenerator`：
     * `generate_md(collector: MetricsCollector, output_path: str)`：生成 Markdown 报告，必须包含：
       - 总览指标：执行时间、任务总数、完成率、成功率、平均重试次数、平均耗时
       - 分类统计表格：按 category 分组（数据分析/代码生成）
       - 任务明细表格：ID、类别、状态、耗时、重试、验证结果
       - 失败任务错误摘要
       - 格式参照下方"报告格式示例"
     * `generate_html(collector: MetricsCollector, output_path: str)`：生成简单 HTML，使用 `<table>` + 内联 CSS，不引入外部框架
       - 在 Markdown 基础上增加：成功率进度条（`<div style="width: X%">`）、状态颜色标签（绿色/红色）
       - 包含 `<html>`, `<head>`, `<body>`, `<style>` 完整结构

2. **Benchmark Runner 集成 Rich**：
   - 修改 `src/benchmark/runner.py`：
     * `BenchmarkRunner.run_all()` 增加可选参数 `use_ui: bool = False`
     * 若 `use_ui=True`：创建 `UIManager`（从 `src.agent.ui` 导入）
     * 因 Benchmark 是 10 个独立任务而非 5 个固定节点，使用 `ProgressPanel.add_task` 动态添加 10 个任务（而非预定义 5 个）
     * 每开始一个任务调用 `ui.update_node(task.id, "running")`，完成后更新为 "done" 或 "error"
     * 每个任务完成后在 `LogPanel` 打印简要结果（如 "BA-01 ✅ 12.3s"）
     * UI 在 `run_all()` 结束后 `ui.stop()`
     * 若 `use_ui=False`：保持原有纯 print 进度输出

3. **CLI 扩展**：
   - 修改 `src/benchmark/__main__.py`：
     * 支持两个子命令：
       - `python -m benchmark run`：执行 benchmark 并生成报告
       - `python -m benchmark report <jsonl_path>`：从已有 JSONL 生成报告（不重新执行）
     * `run` 命令支持 `--rich` 参数启用 UI（`sys.argv` 检测）
     * `run` 执行完毕后自动调用 `ReportGenerator.generate_md` 和 `generate_html`
     * 输出路径：`results/benchmark_YYYYMMDD_HHMMSS_report.md` 和 `.html`
     * `report` 子命令解析 JSONL，重建 `MetricsCollector`，生成报告

4. **测试**：
   - 新建 `tests/test_benchmark_reporter.py`：
     * `test_generate_md_structure`：验证 Markdown 包含 "# DecisionCoder Benchmark 报告"
     * `test_generate_md_metrics`：mock 10 个结果，验证完成率/成功率数字正确
     * `test_generate_html_structure`：验证 HTML 包含 `<html>`、`<table>`、成功率进度条 div
     * `test_report_from_jsonl`：写一个临时 JSONL，调用 `report` 命令验证生成文件
     * `test_runner_with_ui_mock`：mock UIManager，验证 `run_all(use_ui=True)` 时 UI 方法被调用

5. **验证**：
   - `python -m py_compile` 所有文件
   - `pytest tests/test_benchmark_reporter.py -v`
   - 手动验证：`python -m benchmark report results/benchmark_xxx.jsonl` 能生成报告（可用 Day 4 产生的 JSONL 测试）
   - 全量回归测试通过

6. **记录**：
   - 仿照DEV_LOG.md文档结构，在末尾记录这次开发
```

### 报告格式示例（Markdown）

```markdown
# DecisionCoder Benchmark 报告

**执行时间**: 2026-07-10 14:32:00  
**任务总数**: 10  
**完成率**: 100% (10/10)  
**成功率**: 80% (8/10)  
**平均重试次数**: 0.2  
**平均耗时**: 15.3s

## 分类统计

| 类别 | 任务数 | 完成率 | 成功率 | 平均重试 |
|------|--------|--------|--------|----------|
| 数据分析 | 5 | 100% | 80% | 0.2 |
| 代码生成 | 5 | 100% | 80% | 0.2 |

## 任务明细

| ID | 类别 | 状态 | 耗时 | 重试 | 验证 |
|----|------|------|------|------|------|
| BA-01 | 数据分析 | ✅ 成功 | 12.3s | 0 | 关键词命中 4/4 |
| BA-02 | 数据分析 | ❌ 失败 | 45.1s | 1 | 超时 |
| ...
```

### 验收标准
- [ ] Markdown 报告包含总览、分类统计、任务明细、失败摘要
- [ ] HTML 报告包含完整结构 + 成功率进度条
- [ ] `python -m benchmark report <jsonl>` 可独立生成报告
- [ ] `python -m benchmark run --rich` 时 UI 实时展示进度
- [ ] 不带 `--rich` 时纯文本输出正常
- [ ] 全量回归 390+ 测试通过

---

## Day 6：E2E 集成验证与性能基线

### 目标
完整跑通 10 任务 Benchmark（至少 1 轮），修复发现的边界问题，建立 Week 6 性能基线，更新所有文档。

### 前置准备
- Day 5 已完成，报告生成器和 Rich 集成正常工作
- 确保 `DEEPSEEK_API_KEY` 和 `WORKSPACE_PATH` 已设置
- 确保网络畅通（需调用 DeepSeek API）

### 开发提示词

```markdown
## 任务：Day 6 — E2E 集成验证与性能基线

请按以下步骤执行：

1. **运行 Benchmark**：
   - 确保 `DEEPSEEK_API_KEY` 和 `WORKSPACE_PATH` 已设置
   - 运行 `python -m benchmark run`（先不用 --rich 以节省 API 调用和避免 UI 干扰）
   - 记录完整输出，保存 JSONL 文件到 `results/`
   - 若某个任务反复失败，检查并修复：
     * query 是否足够明确（如缺少参数导致 Coder 无法生成正确代码）→ 修改 `src/benchmark/tasks.py`
     * expected_keywords 是否过于严格（如要求"223.6"但实际输出"223.61"）→ 修改 `src/benchmark/validators.py`，使用子串匹配或 `math.isclose`
     * timeout 是否过短（代码生成类通常 10-20s，数据分析类 20-40s）→ 修改 `src/benchmark/tasks.py` 中对应任务的 timeout
     * 数据文件路径是否正确 → 检查 `workspace/data/` 下文件存在性

2. **修复边界问题**：
   - 只修改 `src/benchmark/tasks.py` 和 `src/benchmark/validators.py`，不修改 Graph/节点代码
   - 若发现 Graph/节点有 bug（非 Week 6 引入），记录到 DEV_LOG.md 的踩坑记录，**暂不修复**（避免扩大范围，留待 Week 7）
   - 修复后重新运行失败的 Task，确认通过

3. **文档更新**：
   - 在 `DEV_LOG.md` 末尾追加 Week 6 开发日志（参照 Week 5 格式），包含：
     * Day 1-6 每日摘要（每段 3-5 行）
     * 新增文件清单（表格：文件、行数、职责）
     * 修改文件清单
     * Benchmark 首次运行基线数字（完成率/成功率/平均重试/平均耗时/各任务耗时）
     * 踩坑记录（如有，参照 Week 5 格式：问题/现象/解决方案/状态）
   - 在 `DEV_DESIGN.md` 中：
     * "阶段规划"部分将 Week 6 标记为 ✅
     * "架构图"中增加 Benchmark 层（在 CLI 层下方或右侧）
     * "设计决策记录"追加 2-3 条 Week 6 决策（如：Rich 可选启用策略、Benchmark 跨平台超时方案、任务隔离执行设计）
     * "LLM 使用策略"表格中增加 Benchmark 运行时的调用统计说明
   - 在 `CLAUDE.md` 中：
     * "常用命令"增加 `python -m benchmark run` 和 `python -m benchmark report`
     * "核心架构"增加 UI 层和 Benchmark 层说明（1-2 段）
     * "开发约定"增加 Benchmark 任务编写规范

4. **回归测试**：
   - 运行 `python -m pytest tests/ --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py -v`
   - 确保 390+ 基线测试全部通过
   - 新增 benchmark 测试全部通过
   - 若修改了 `src/benchmark/tasks.py` 或 `validators.py`，运行对应测试文件

5. **提交**：
   - `git add` 所有变更
   - `git commit -m "Week 6: Rich UI + Benchmark"`（或按你的习惯提交）
   - 记录 commit hash 作为回退点，写入 DEV_LOG.md
```

### 预期基线（首次运行，允许不完美）

| 指标 | 预期值 | 说明 |
|------|--------|------|
| 完成率 | ≥ 80% | 10 个任务至少完成 8 个 |
| 成功率 | ≥ 70% | 允许 2-3 个任务因 prompt 边界或验证严格而失败 |
| 平均重试次数 | ≤ 1.0 | 允许少量 Debugger 触发 |
| 平均耗时 | ≤ 30s/任务 | DeepSeek API 调用耗时为主 |

### 验收标准
- [ ] 完整 Benchmark 运行至少 1 轮，JSONL 文件生成
- [ ] 失败任务已分析原因，query/keywords/timeout 已调优
- [ ] `DEV_LOG.md` 已追加 Week 6 日志
- [ ] `DEV_DESIGN.md` 已更新 Week 6 状态
- [ ] `CLAUDE.md` 已更新常用命令和架构说明
- [ ] 全量回归 390+ 测试通过

---

## Day 7：Week 6 收尾与 Week 7 准备

### 目标
Week 6 总结，清理技术债务，规划 Week 7（工程化 + Docker Compose + README 重写）。

### 前置准备
- Day 6 已完成，Benchmark 基线已建立，文档已更新
- 确认 `results/` 目录下有至少 1 份完整 JSONL + Markdown + HTML 报告

### 开发提示词

```markdown
## 任务：Day 7 — Week 6 收尾与 Week 7 准备

请按以下步骤执行：

1. **Demo 脚本**：
   - 新建 `examples/demo_rich_ui.py`：
     * 不调用 LLM，纯本地模拟
     * 创建 `UIManager`，模拟 5 个节点依次执行（sleep 0.5s），展示进度条、状态表格、日志流
     * 模拟 Debugger 暂停 2s，展示 DebugPanel
     * 运行 10s 后自动结束，打印 "Demo 完成"
     * 命令：`python examples/demo_rich_ui.py`
   - 新建 `examples/demo_benchmark.py`：
     * 使用 mock 的 `BenchmarkTask` 和 `BenchmarkResult`（不调用真实 graph）
     * 生成 10 个 mock 结果（7 成功 3 失败，含重试）
     * 调用 `ReportGenerator.generate_md` 和 `generate_html`
     * 打印报告路径
     * 命令：`python examples/demo_benchmark.py`

2. **清理与检查**：
   - 检查 `.gitignore` 是否包含：
     * `logs/`
     * `results/`
     * `workspace/src/_dc_exec_*.py`
     * `workspace/reports/*.md`
     * `workspace/reports/charts/*.html`
   - 若 `.gitignore` 缺少上述条目，补充
   - 清理已跟踪的临时文件（若有误提交的 `_dc_exec_*.py` 或旧报告）
   - 检查 `pyproject.toml` 的依赖列表，确认只新增了 `rich`

3. **Week 6 总结**：
   - 在 `DEV_LOG.md` 追加 Week 6 完整总结（参照 Week 5 格式），必须包含：
     * 时间线表格（Day 1-7 每日内容）
     * Benchmark 基线数字（完成率/成功率/平均重试/平均耗时/各任务耗时表格）
     * 新增文件清单（表格：文件、行数、职责）
     * 修改文件清单
     * 设计决策总结（3-5 条，如：Rich 可选启用、Benchmark 跨平台超时、任务隔离执行）
     * 踩坑记录（如有，问题/现象/解决方案/状态）
     * 回退点（commit hash）
     * Week 6 测试统计（新增测试数、累计测试数、通过率）

4. **Week 7 预规划**：
   - 在 `DEV_DESIGN.md` 的"阶段规划"中，将 Week 7 细化为具体子任务：
     * Day 1: Docker Compose 编排（app 服务 + sandbox 服务分离，docker-compose.yml）
     * Day 2: README 重写（项目介绍、快速开始、架构图 Mermaid、Badge、Benchmark 结果引用）
     * Day 3: 架构图与文档（docs/ 目录，Mermaid 流程图、时序图、状态图）
     * Day 4: 3分钟 Demo 脚本（录屏准备，一键运行命令）
     * Day 5: 简历优化（项目描述提炼，技术亮点 bullet points）
     * Day 6-7: 收尾与发布准备（GitHub Release、PyPI 可选）
   - 在 `DEV_DESIGN.md` 的"面试叙事要点"中补充 Week 6 新指标（Benchmark 数字、Rich UI 体验）

5. **最终验证**：
   - 运行 `python -m pytest tests/ -v`（排除 Docker 测试）全部通过
   - `python examples/demo_rich_ui.py` 正常展示 10s 不崩溃
   - `python examples/demo_benchmark.py` 生成报告文件
   - `python -m py_compile` 所有新增/修改文件
   - `python main.py --rich` 启动后输入 "help" 正常展示（不验证 LLM）
   - `python main.py` 不带参数启动后输入 "help" 行为正常（纯 print 模式）

6. **提交**：
   - `git add` 所有变更
   - `git commit -m "Week 6 complete: Rich UI + Benchmark + docs"`
   - 记录 commit hash
```

### 验收标准
- [ ] `examples/demo_rich_ui.py` 可独立运行，展示完整 UI 效果
- [ ] `examples/demo_benchmark.py` 可独立运行，生成报告文件
- [ ] `.gitignore` 完整覆盖临时文件和日志
- [ ] `DEV_LOG.md` 包含 Week 6 完整总结
- [ ] `DEV_DESIGN.md` 包含 Week 7 细化规划
- [ ] 全量回归 390+ 测试通过

---

## 附录 A：跨日通用约束

### 1. 依赖控制
Week 6 只允许新增 **`rich`** 一个运行时依赖。Benchmark 相关模块全部使用标准库（`dataclasses`, `json`, `threading`, `time`）。若 HTML 报告生成需要模板引擎，优先用标准库 `string.Template` 或纯字符串拼接，**禁止引入 `jinja2`**。

### 2. 向后兼容
所有 Week 6 修改必须满足：
- `main.py` 不传 `--rich` 时，行为与 Week 5 完全一致
- `build_graph(use_ui=False)` 为默认，所有现有测试零回归
- Benchmark 引擎不强制依赖 Rich，CLI 支持纯文本模式
- 不修改 `AgentState` 字段定义
- 不修改现有节点（planner/coder/executor/debugger/reporter）的核心逻辑

### 3. 测试策略

| 模块 | 测试文件 | 预估用例数 |
|------|---------|-----------|
| UI 基础 | `tests/test_ui_base.py` | 4-6 |
| UI Tracer | `tests/test_ui_tracer.py` | 5-7 |
| Benchmark 模型 | `tests/test_benchmark_models.py` | 5-6 |
| Benchmark Runner | `tests/test_benchmark_runner.py` | 6-8 |
| Benchmark Reporter | `tests/test_benchmark_reporter.py` | 4-6 |
| **Week 6 新增合计** | | **~30** |
| 全量回归 | 现有 390+ | 全部通过 |

### 4. 与 Week 7 的衔接
Week 6 产生的 `results/` 目录和 Benchmark 报告将作为 Week 7 README 中的"性能指标"章节素材。请保留至少 1 份完整的 JSONL + Markdown + HTML 报告在 `results/` 中（已 gitignore，本地保留即可）。

---

## 附录 B：文件组织（Week 6 新增）

```
decision-coder/
├── pyproject.toml                    # + rich>=13.0
├── src/
│   ├── agent/
│   │   └── ui/                       # ← Day 1-2 新增
│   │       ├── __init__.py
│   │       ├── manager.py            # UIManager（Live + 队列 + 布局）
│   │       ├── panels.py             # ProgressPanel / StatusTable / LogPanel / DebugPanel
│   │       └── tracer.py             # NodeTracer（函数包装 + 状态追踪）
│   ├── benchmark/                    # ← Day 3-5 新增
│   │   ├── __init__.py
│   │   ├── __main__.py             # CLI 入口（run / report 子命令）
│   │   ├── models.py               # BenchmarkTask / BenchmarkResult dataclass
│   │   ├── tasks.py                # get_default_tasks() — 10 个任务定义
│   │   ├── metrics.py              # MetricsCollector（指标计算）
│   │   ├── validators.py           # 结果验证（关键词 + 文件存在性）
│   │   ├── runner.py               # BenchmarkRunner（批量执行 + 超时 + 清理）
│   │   └── reporter.py             # ReportGenerator（Markdown + HTML）
│   └── agent/
│       └── graph.py                  # ← Day 2 修改（build_graph 新增 use_ui 参数）
├── main.py                           # ← Day 2 修改（--rich 参数解析）
├── examples/
│   ├── demo_inventory_optimization.py # Week 5 已有
│   ├── demo_rich_ui.py              # ← Day 7 新增（纯本地 UI 演示）
│   └── demo_benchmark.py            # ← Day 7 新增（mock Benchmark 演示）
├── tests/
│   ├── test_ui_base.py              # ← Day 1 新增
│   ├── test_ui_tracer.py           # ← Day 2 新增
│   ├── test_benchmark_models.py    # ← Day 3 新增
│   ├── test_benchmark_runner.py    # ← Day 4 新增
│   └── test_benchmark_reporter.py  # ← Day 5 新增
└── results/                          # Benchmark 输出（gitignore）
    ├── benchmark_YYYYMMDD_HHMMSS.jsonl
    ├── benchmark_YYYYMMDD_HHMMSS_report.md
    └── benchmark_YYYYMMDD_HHMMSS_report.html
```

---

## 附录 C：常见问题处理

### Q1: `rich` 安装后 import 失败？
```bash
pip install -e .  # 重新安装以更新 pyproject.toml 依赖
python -c "import rich; print(rich.__version__)"
```

### Q2: Benchmark 运行超时导致所有任务失败？
- 检查 `DEEPSEEK_API_KEY` 是否有效
- 检查网络连接
- 在 `tasks.py` 中增加 timeout（如从 60 改为 120）
- 若 API 响应慢，可先用 mock 测试验证 Runner 逻辑

### Q3: 某个任务 expected_keywords 太严格？
- 在 `validators.py` 中使用子串匹配（`"223" in output`）而非精确匹配
- 对于浮点数，检查是否包含整数部分即可（如 "223" 匹配 "223.61"）
- 对于图表任务，验证文件存在性即可，不强制检查 HTML 内容

### Q4: Debugger 交互在 Benchmark 中阻塞？
- Benchmark 任务应设计为一次成功（retry_count=0）
- 若触发 Debugger，检查 query 是否清晰、数据文件是否存在
- 在 E2E 测试中使用 `patch("src.agent.nodes.debugger._safe_input", return_value="4")` 规避阻塞

### Q5: Week 6 时间不够，如何压缩？
- **最小可行方案**：Day 1-2 合并（只做 UIManager + main.py 集成，不做 Debugger 面板），Day 3-4 合并（只做任务集 + Runner，不做 HTML 报告），Day 5 做报告生成，Day 6-7 合并（E2E + 文档）。
- **优先级**：Benchmark 执行引擎（Day 3-4）> Rich UI（Day 1-2）> 报告生成（Day 5）> 文档（Day 6-7）。

# Week 7-8 开发提示词（面向 Claude Code）

> **项目**：DecisionCoder — 面向经营决策与运筹优化的垂直 Coding Agent  
> **当前阶段**：Week 6 已完成（Rich UI + Benchmark 评测，472 测试通过），进入 Week 7-8  
> **目标**：工程化部署 + 面试准备  
> **开发工具**：Claude Code (claude.ai/code)  
> **约束**：不新增运行时依赖；472 基线测试零回归；向后兼容

---

## 前置准备（Week 7 Day 0）

在正式开始 Week 7 Day 1 之前，请完成以下准备工作：

### 1. 环境检查
```bash
# 激活虚拟环境
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# 确认当前依赖已安装
pip install -e .

# 运行全量回归测试，确认 Week 6 基线通过
python -m pytest tests/ --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py -v
# 预期：472 测试全部通过
```

### 2. 创建分支（可选）
```bash
git checkout -b week7-engineering
git checkout -b week8-interview      # Week 7 结束后创建
```

### 3. 阅读参考文档
Claude Code 在编写代码前必须阅读：
1. `CLAUDE.md` — 项目指南（架构、约定、常用命令、Week 6 新增内容）
2. `DEV_DESIGN.md` — 设计文档（阶段规划、接口契约、安全体系、面试叙事要点）
3. `DEV_LOG.md` — 开发日志（Week 1-6 踩坑记录、Benchmark 数字）

### 4. 待修复问题清单（Week 6 遗留）

| 问题 | 影响 | 建议处理时机 |
|------|------|-------------|
| E2E Week 3 `test_task_c_text_to_sql_subprocess` 偶发失败（Debugger input 与 pytest stdin 冲突） | 低 | 暂不修复，Week 7-8 不新增 E2E 测试 |
| inventory_pipeline 年需求推断默认兜底为月（若日期格式异常） | 低 | 暂不修复，Week 7 文档中标注已知限制 |
| Rich Live 与 terminal input() 冲突（Debugger 交互时） | 中 | Week 7 Day 2 文档中标注 workaround |
| Docker 镜像重建待 `docker build` | 中 | Week 7 Day 1 处理 |
| Benchmark 实际运行数据未收集（Week 6 仅 mock 测试） | 中 | Week 7 Day 5 运行真实 Benchmark 收集数据 |

---

## Week 7 Day 1：Docker Compose 编排

### 目标
将当前单容器 Docker 升级为 Docker Compose 多服务编排（app 服务 + sandbox 服务分离），支持 `docker-compose up` 一键启动。

### 前置准备
- 确认 Docker 和 docker-compose 已安装（`docker --version`, `docker-compose --version`）
- 阅读现有 `Dockerfile` 和 `src/agent/sandbox/docker_runner.py`
- 确认 `src/mcp/tools/python_tools.py` 的 AST 安全检查和执行逻辑可复用

### 开发提示词

```markdown
## 任务：Week 7 Day 1 — Docker Compose 编排

请按以下步骤实现：

1. **Dockerfile.sandbox**（新建）：
   - 基于 `python:3.11-slim`
   - 只安装运行生成代码所需的最小依赖：`pandas`, `scipy`, `plotly`, `duckdb`, `openpyxl`
   - 不安装 `langchain`, `deepseek`, `rich`, `loguru`, `langgraph` 等 Agent 层依赖
   - 不复制项目源码（除 `src/mcp/tools/python_tools.py` 和 `src/agent/sandbox/security_checker.py` 外）
   - 暴露一个最小 HTTP 接口（用标准库 `http.server` 或 Flask，若用 Flask 需加入 Dockerfile.sandbox 的依赖）：
     * 端点：`POST /execute`，接收 JSON `{"code": "...", "timeout": 30}`
     * 返回 JSON：`{"stdout": "...", "stderr": "...", "returncode": N}`
     * 执行前调用 `check_code_safety()`（复用 `security_checker.py`）
     * 执行前 `compile()` 语法预检
     * 使用 `subprocess.run` 执行，带超时控制
     * 端口 `5000`
   - 文件位置：`Dockerfile.sandbox`（项目根目录）

2. **docker-compose.yml**（新建）：
   - `app` 服务：
     * 使用原 `Dockerfile`（或构建上下文 `.`）
     * 依赖 `sandbox` 服务（`depends_on`）
     * 环境变量：`SANDBOX_URL=http://sandbox:5000`, `DEEPSEEK_API_KEY`, `WORKSPACE_PATH=/app/workspace`
     * 共享卷：`./workspace:/app/workspace`, `./reports:/app/reports`
     * 端口映射（可选）：`8080:8080`（若后续加 Web UI）
   - `sandbox` 服务：
     * 使用 `Dockerfile.sandbox`
     * 资源限制：`mem_limit: 512m`, `cpus: 1.0`
     * 网络隔离：`network_mode: none` 或自定义无出口网络（推荐自定义 bridge 网络，仅 app 可访问）
     * 共享卷：`./workspace:/app/workspace:ro`（只读），`./reports:/app/reports:rw`
     * 不暴露端口到宿主机（仅 app 服务通过 docker 网络访问）
   - 共享卷说明：`workspace/` 和 `reports/` 在宿主机和容器间共享

3. **sandbox_client.py**（新建 `src/agent/sandbox/sandbox_client.py`）：
   - 实现 `SandboxClient` 类：
     * `__init__(self, base_url: str = "http://localhost:5000")`
     * `execute(code: str, timeout: int = 30) -> dict`：POST 发送代码到 sandbox，返回 stdout/stderr/returncode
     * 客户端超时：`requests.post(timeout=timeout + 5)`（网络缓冲）
     * 失败回退：sandbox 返回非 200 或连接失败时，抛出 `SandboxUnavailableError`
   - 保持与现有 `executor.py` 的接口兼容（返回 dict 含 `execution_result`, `error`, `file_path`）

4. **Executor 集成**（修改 `src/agent/nodes/executor.py`）：
   - 新增执行路径优先级：`USE_COMPOSE` / `SANDBOX_URL` > `USE_MCP` > `USE_DOCKER` > subprocess
   - 当 `SANDBOX_URL` 环境变量存在时，使用 `SandboxClient` 替代本地 subprocess
   - 保持所有现有路径不变（subprocess/MCP/DockerRunner），仅新增一个分支
   - 修改后运行 `python -m py_compile src/agent/nodes/executor.py`

5. **测试**（新建 `tests/test_docker_compose.py`）：
   - `test_sandbox_client_mock`：mock `requests.post` 验证调用逻辑
   - `test_sandbox_client_fallback`：sandbox 返回 500 时验证异常类型
   - `test_executor_compose_path`：mock `SandboxClient` 验证 executor 新分支被触发
   - `test_executor_compose_priority`：验证 `SANDBOX_URL` 存在时优先于 `USE_MCP`
   - 运行 `pytest tests/test_docker_compose.py -v`

6. **验证**：
   - `python -m py_compile Dockerfile.sandbox`（检查 Dockerfile 语法）
   - `docker-compose config`（验证 YAML 语法正确）
   - `pytest tests/test_docker_compose.py -v` 通过
   - 全量回归：`pytest tests/ --ignore=...` 472/472 通过
   - 手动验证（可选）：`docker-compose up --build` 能启动（需 Docker 环境）

7. **规范**：
   - 不修改 AgentState / Graph 结构
   - sandbox HTTP 接口最小化，只接收 `{"code": "...", "timeout": 30}`
   - 复用现有 `security_checker.py` 和 `python_tools.py` 的逻辑，不重复实现安全检查
```

### 设计约束（必须遵守）
- sandbox 镜像**不暴露 LLM API Key**，仅执行 Python 代码
- sandbox 服务**网络隔离**，不可访问外部网络
- 复用现有安全检查代码，不重复实现 AST 检测
- 所有现有执行路径（subprocess/MCP/DockerRunner）保持不变

### 验收标准
- [ ] `docker-compose.yml` 语法正确（`docker-compose config` 通过）
- [ ] `Dockerfile.sandbox` 可构建（`docker build -f Dockerfile.sandbox .`）
- [ ] `SandboxClient` mock 测试通过
- [ ] Executor 新增路径不破坏原有路径
- [ ] 全量回归 472/472 通过

---

## Week 7 Day 2：README 重写 + 项目门面

### 目标
重写 `README.md`，使其成为对外展示的项目门面，包含：项目定位、架构图、Quick Start、Benchmark 结果、技术亮点、目录结构。

### 前置准备
- 确认 Week 6 Benchmark 实际运行数据（若未运行，先用 mock 数据占位并标注）
- 阅读现有 `README.md`（若有）或确认需要新建
- 确认 `DEV_DESIGN.md` 中的架构图和面试叙事要点

### 开发提示词

```markdown
## 任务：Week 7 Day 2 — README 重写 + 项目门面

请按以下步骤实现：

1. **README.md**（重写或新建，项目根目录）：
   必须包含以下章节（按此顺序）：

   - `# DecisionCoder` — 标题 + 一句话描述：
     "面向经营决策与运筹优化的垂直 Coding Agent，基于 LangGraph + MCP + DeepSeek 构建 Plan-Code-Execute-Debug-Report 闭环"

   - 徽章行（shields.io 格式）：
     * Python 3.11 | `![Python](https://img.shields.io/badge/python-3.11-blue)`
     * Tests 472/472 | `![Tests](https://img.shields.io/badge/tests-472%2F472-brightgreen)`（静态徽章，不依赖 CI）
     * License MIT | `![License](https://img.shields.io/badge/license-MIT-green)`
     * 可选：Repo size、Last commit

   - `## 核心特性` — 6 个 bullet points：
     1. **LangGraph 状态机**：Planner→Coder→Executor→Debugger→Reporter 闭环，支持循环调试和人在回路
     2. **MCP 工具层**：8 个标准化 Tool（FastMCP），文件读写、Python 沙箱执行、CSV/Excel 解析
     3. **5 道安全防线**：LLM 语义识别→AST 语法检查→执行前预检→Docker 容器沙箱→SQL 注入拦截
     4. **7 个供应链模板**：EOQ、需求预测、安全库存、补货点、一键分析、Text-to-SQL、5 种图表
     5. **Rich 终端 UI**：实时进度条、状态表格、日志流、调试面板，非 TTY 自动降级
     6. **Benchmark 评测框架**：10 任务自动化执行，JSONL 输出，Markdown + HTML 报告生成

   - `## 架构图` — Mermaid 代码块：
     ```mermaid
     graph TD
         A[用户输入] --> B[Planner]
         B --> C[Coder]
         C --> D[Executor]
         D -->|error| E[Debugger]
         E -->|非 ABORT| C
         D -->|success| F[Reporter]
         E -->|ABORT| F
     ```
     简化版，只展示核心 5 节点和条件路由

   - `## Quick Start` — 三步命令：
     ```bash
     git clone https://github.com/yourname/decision-coder.git
     cd decision-coder && pip install -e .
     export DEEPSEEK_API_KEY=sk-xxx
     python main.py --rich
     ```
     添加 Windows 环境变量设置说明（`set DEEPSEEK_API_KEY=sk-xxx`）

   - `## Benchmark` — 表格展示 10 任务结果：
     | 任务 | 类别 | 状态 | 耗时 | 重试 |
     |------|------|------|------|------|
     | BA-01 | 数据分析 | ✅ | 15s | 0 |
     | ... | ... | ... | ... | ... |
     若 Week 6 未运行真实 Benchmark，用 mock 数据占位并在表格下方标注：
     > **注**：以上为框架验证数据，真实 API 运行结果待补充。

   - `## 技术亮点` — 12 个 bullet points（对应面试叙事要点）：
     每个 1 行，突出量化数字（472 测试、100% 成功率、5 道防线、7 个模板、10 任务）

   - `## 目录结构` — 精简树：
     只展示 `src/` 一级目录和关键文件（main.py, pyproject.toml, README.md）
     不展示 `__pycache__`、日志、临时文件

   - `## 依赖` — 核心依赖列表：
     `langgraph`, `langchain-deepseek`, `rich`, `plotly`, `duckdb`, `loguru`, `pandas`, `scipy`, `fastmcp`
     标注 Python >= 3.11

   - `## License` — MIT

2. **LICENSE**（新建）：
   - 选择 MIT License
   - 填写你的姓名和年份（2026）
   - 文件位置：项目根目录 `LICENSE`

3. **规范**：
   - README 中所有路径使用相对路径（`python main.py` 而非绝对路径）
   - Mermaid 图在 GitHub 上可直接渲染（使用标准语法，避免复杂样式）
   - 不暴露真实 API Key（用 `sk-xxx` 占位）
   - 中文为主，技术术语保留英文（LangGraph, MCP, Agent）
   - 徽章使用静态 shields.io 链接（不依赖动态 CI 状态）
   - 控制总长度：建议 150-200 行，避免过长

4. **验证**：
   - 在 GitHub 网页预览 README（本地可用 `grip` 或 `markdown-preview` 工具）
   - 确认 Mermaid 图渲染正常
   - 确认所有链接可点击（若链接到 docs/ 目录，确认文件存在）
   - 运行 `python -m py_compile` 无需（README 非 Python 文件）
   - 全量回归测试通过（不修改代码，应无影响）
```

### 验收标准
- [ ] README 包含所有 8 个章节
- [ ] Mermaid 图在 GitHub 预览中可渲染
- [ ] 徽章显示正常
- [ ] 不暴露敏感信息
- [ ] 全量回归 472/472 通过（无代码变更）

---

## Week 7 Day 3：架构文档与 Mermaid 图

### 目标
创建 `docs/` 目录，包含详细的架构设计文档、时序图、状态图，作为 README 的补充深度阅读材料。

### 前置准备
- Day 2 已完成，README 已重写
- 阅读 `DEV_DESIGN.md` 中的架构图、状态流转、安全体系、Benchmark 框架设计

### 开发提示词

```markdown
## 任务：Week 7 Day 3 — 架构文档与 Mermaid 图

请按以下步骤实现：

1. **docs/architecture.md**（新建）：
   - 标题：`# DecisionCoder 架构设计`
   - 章节结构：

     `## 整体架构`
     - 文字描述 4 层架构（交互层/编排层/工具层/领域层）
     - Mermaid 流程图（graph TD）：
       ```mermaid
       graph TD
           subgraph 交互层
               CLI[main.py CLI]
               Benchmark[python -m benchmark]
           end
           subgraph 编排层
               LG[LangGraph StateGraph]
               P[Planner]
               C[Coder]
               E[Executor]
               D[Debugger]
               R[Reporter]
           end
           subgraph 工具层
               MCP[FastMCP Server]
               FT[File Tools]
               PT[Python Exec]
           end
           subgraph 领域层
               DA[Data Analysis]
               SS[Supply Chain]
               CH[Charts]
           end
           CLI --> LG
           LG --> MCP
           LG --> DA
           LG --> SS
           LG --> CH
       ```

     `## 状态机设计`
     - AgentState 字段表格（字段名/类型/说明/示例）
     - 状态流转条件（Planner→Coder→Executor→[Debugger|Reporter]→END）
     - 条件路由说明：`route_after_executor`（error?）和 `route_after_debugger`（ABORT?）

     `## 安全纵深防御`
     - 5 道防线表格：
       | 防线 | 位置 | 机制 | 拦截示例 |
       |------|------|------|---------|
       | 第零道 | Planner | LLM 语义识别 | "执行 rm -rf" → 拒绝 |
       | 第一道 | Coder | AST 语法检查 | `__import__('os').system()` → 拦截 |
       | 第二道 | Executor | 执行前预检 | compile() + AST 再检 |
       | 第三道 | DockerRunner | AST 兜底 | 容器启动前再检 |
       | 第四道 | Docker 容器 | 资源限制 | --memory=512m --network none |

     `## 领域模板层`
     - 7 个模板列表（名称/文件/功能/输入/输出）
     - 协作关系图（Mermaid）：EOQ → SafetyStock → ROP 三件套

     `## Benchmark 框架`
     - 10 任务分类表格（BA-01~05 数据分析 / CG-01~05 代码生成）
     - 指标定义（完成率/成功率/平均重试/平均耗时）
     - 报告样例（Markdown 片段）

2. **docs/sequence.md**（新建）：
   - Mermaid `sequenceDiagram`：
     - 图 1：成功路径（User->>Planner->>Coder->>Executor->>Reporter）
     - 图 2：调试循环路径（User->>Planner->>Coder->>Executor->>Debugger->>Coder）
     - 标注 retry_count 上限（>=2 强制 ABORT）
     - 标注 ABORT 触发条件
   - 每个图下方附文字说明（50 字以内）

3. **docs/state-machine.md**（新建）：
   - Mermaid `stateDiagram-v2`：
     - 状态：Planner / Coder / Executor / Debugger / Reporter / END
     - 转换：
       * Planner --> Coder
       * Coder --> Executor
       * Executor --> Debugger : error 且非 ABORT
       * Executor --> Reporter : 无 error 或 ABORT
       * Debugger --> Coder : 非 ABORT
       * Debugger --> Reporter : ABORT
       * Reporter --> END
     - 标注条件路由函数名

4. **docs/security.md**（新建）：
   - 每道防线一个 `###` 章节
   - 每个章节包含：
     * 防线位置（文件路径 + 函数名）
     * 拦截机制（技术细节，如 AST NodeVisitor 遍历）
     * 拦截示例（代码片段 + 结果）
     * 回退策略（LLM 失败时如何降级）
   - 第 5 章：`## SQL 安全防线`（Text-to-SQL 的 11 种危险关键字 + SELECT-only）

5. **docs/benchmark.md**（新建）：
   - 10 个任务详细表格（ID/类别/Query/预期关键词/Timeout/数据文件）
   - 指标计算公式（数学公式用 Markdown 行内代码）
   - 报告格式说明（JSONL 结构 + MD 报告章节 + HTML 卡片样式）
   - 运行命令：`python -m benchmark run` / `python -m benchmark report <jsonl>`

6. **README.md 更新**（修改）：
   - 在 `## 目录结构` 或末尾添加：`详细架构文档见 [docs/architecture.md](docs/architecture.md)`

7. **规范**：
   - 所有 Mermaid 图使用标准语法（避免 `subgraph` 嵌套过深，GitHub 渲染有限制）
   - 文档之间互相链接（architecture.md 引用 sequence.md 等）
   - 不重复 README 内容，docs/ 是深度阅读材料（每个文档 100-200 行）
   - 中文为主，代码片段和文件路径保留英文

8. **验证**：
   - 在 GitHub 网页预览每个文档，确认 Mermaid 图渲染正常
   - 点击所有内部链接，确认无 404
   - 运行全量回归测试（无代码变更，应无影响）
```

### 验收标准
- [ ] `docs/` 目录包含 5 个文档
- [ ] 所有 Mermaid 图在 GitHub 预览中可渲染
- [ ] 文档间链接无 404
- [ ] 全量回归 472/472 通过

---

## Week 7 Day 4：3 分钟 Demo 脚本与录屏素材

### 目标
完善 `examples/` 下的 Demo 脚本，确保它们能在无 API Key 环境下展示项目效果，作为录屏和面试演示的素材。

### 前置准备
- 确认 `examples/demo_rich_ui.py` 和 `examples/demo_benchmark.py` 已存在（Week 6 遗留）
- 确认 `workspace/data/sku_inventory.csv` 存在
- 确认 `src/domain/templates/inventory_pipeline.py` 和 `src/domain/text_to_sql.py` 可正常工作

### 开发提示词

```markdown
## 任务：Week 7 Day 4 — 3 分钟 Demo 脚本与录屏素材

请按以下步骤实现：

1. **检查并完善 demo_rich_ui.py**（修改 `examples/demo_rich_ui.py`）：
   - 确认已有内容：
     * 5 个节点（Planner/Coder/Executor/Debugger/Reporter）依次展示
     * 每个节点 sleep 0.5s，总时长 8-12 秒
     * Debugger 节点模拟错误 + 暂停 2s + 展示 DebugPanel
     * 最后打印 "Demo 完成！Rich UI 展示结束。"
   - 若缺少上述内容，补充完善
   - 添加 `if __name__ == "__main__":` 入口（若缺少）
   - 添加 `--output-dir` 参数（可选，默认不保存截图，只终端展示）
   - 运行 `python examples/demo_rich_ui.py` 验证 8-12 秒完成，无异常

2. **检查并完善 demo_benchmark.py**（修改 `examples/demo_benchmark.py`）：
   - 确认已有内容：
     * 生成 10 个 mock BenchmarkResult（7 成功 3 失败，含不同 retry_count）
     * 调用 `ReportGenerator.generate_md` 和 `generate_html`
     * 保存到 `examples/output/demo_benchmark_report.md` 和 `.html`
   - 若缺少上述内容，补充完善
   - 添加 `if __name__ == "__main__":` 入口
   - 添加 `--output-dir` 参数（默认 `examples/output/`）
   - 打印报告路径和文件大小（字节数）
   - 运行 `python examples/demo_benchmark.py` 验证生成文件

3. **新建 demo_inventory_quick.py**（新建 `examples/demo_inventory_quick.py`）：
   - 直接调用 `from src.domain.templates.inventory_pipeline import quick_analyze`
   - 输入：`quick_analyze("workspace/data/sku_inventory.csv")`
   - 不调用 LLM，纯 Python 执行
   - 打印结构化中文摘要（参照 Week 5 的 Demo 输出格式）：
     ```
     ============================================================
       供应链库存优化分析
     ============================================================

     📊 分析结果摘要

       【数据质量】      综合评分 : X/100
       【需求预测】      方法 : XXX | 预测值 : ... | MAPE : X%
       【EOQ】           EOQ : X 件 | ...
       ...
     ```
   - 运行时间 < 5 秒
   - 保存报告到 `examples/output/demo_inventory_report.md`（可选，通过 `--save-report`）
   - 添加 `if __name__ == "__main__":` 入口
   - 运行 `python examples/demo_inventory_quick.py` 验证

4. **新建 demo_text_to_sql.py**（新建 `examples/demo_text_to_sql.py`）：
   - 使用 `from src.domain.text_to_sql import run_text_to_sql`
   - 但**绕过 LLM 部分**：直接构造已知的 SQL 和 schema
   - 展示流程：
     1. Schema 提取（打印 `extract_schema` 结果）
     2. SQL 安全检查（打印 `check_sql_safety` 结果）
     3. DuckDB 执行（打印查询结果表格）
     4. 结果摘要（打印 `_generate_summary` 结果）
   - 使用 `workspace/data/sales.csv` 作为数据源
   - 预生成 SQL：`SELECT region, AVG(sales) FROM sales.csv GROUP BY region`
   - 打印结果用 Markdown 表格格式
   - 运行时间 < 3 秒
   - 添加 `if __name__ == "__main__":` 入口
   - 运行 `python examples/demo_text_to_sql.py` 验证

5. **所有 Demo 脚本规范**：
   - 顶部注释说明：用途、运行命令、预期输出、是否需要 API Key
   - 自动创建 `examples/output/` 目录（`os.makedirs(..., exist_ok=True)`）
   - 异常时打印友好错误信息（`try/except` + `print(f"错误: {e}")`），不 traceback
   - 不引入新依赖（只用标准库 + 已有项目依赖）
   - 运行 `python -m py_compile` 检查所有 Demo 脚本语法

6. **新建 RECORDING_GUIDE.md**（新建 `examples/RECORDING_GUIDE.md`）：
   - 录屏场景建议：
     * 场景 1：运行 `python examples/demo_rich_ui.py`（展示终端 UI，30s）
     * 场景 2：运行 `python main.py --rich` 输入"分析 sales.csv"（展示真实 LLM 交互，45s，需 API Key）
     * 场景 3：运行 `python examples/demo_benchmark.py` 后打开 HTML 报告（展示评测体系，30s）
     * 场景 4：运行 `python examples/demo_inventory_quick.py`（展示供应链分析，30s）
   - 每个场景标注：命令、预期效果、解说词要点、时长
   - 总时长建议：3 分钟（4 个场景 × 45 秒）
   - 技术建议：终端字体 14pt+、深色背景、录屏分辨率 1920×1080

7. **验证**：
   - `python -m py_compile examples/demo_*.py` 全部通过
   - 手动运行 4 个 Demo 脚本，确认全部成功
   - 确认 `examples/output/` 下生成预期文件（报告、HTML）
   - 全量回归测试通过
```

### 验收标准
- [ ] 4 个 Demo 脚本均可独立运行（无需 API Key）
- [ ] `demo_rich_ui.py` 运行 8-12 秒，展示完整 UI 效果
- [ ] `demo_benchmark.py` 生成 MD + HTML 报告
- [ ] `demo_inventory_quick.py` 运行 < 5 秒，输出中文摘要
- [ ] `demo_text_to_sql.py` 运行 < 3 秒，输出查询结果
- [ ] `examples/RECORDING_GUIDE.md` 包含 4 个录屏场景
- [ ] 全量回归 472/472 通过

---

## Week 7 Day 5：代码清理与最终回归测试

### 目标
清理技术债务，确保项目对外发布前的代码质量，运行最终全量回归测试。

### 前置准备
- Day 1-4 已完成，所有新增文件已创建
- 确认 `examples/output/` 目录已生成（运行过 Demo 脚本）

### 开发提示词

```markdown
## 任务：Week 7 Day 5 — 代码清理与最终回归测试

请按以下步骤执行：

1. **.gitignore 检查**（修改）：
   - 确认包含以下条目（若缺少则补充）：
     ```
     logs/
     results/
     workspace/src/_dc_exec_*.py
     workspace/reports/*.md
     workspace/reports/charts/*.html
     examples/output/
     .env
     __pycache__/
     *.pyc
     *.egg-info/
     .pytest_cache/
     .mypy_cache/
     ```
   - 新增（若不存在）：
     ```
     # Docker
     *.dockerignore
     # IDE
     .vscode/
     .idea/
     # OS
     .DS_Store
     Thumbs.db
     ```

2. **清理已跟踪的临时文件**：
   - 检查 git 跟踪的文件中是否有：`workspace/src/_dc_exec_*.py`、旧的 `report_*.md`、`fail_*.md`
   - 若有，执行：`git rm --cached <file>` 并从仓库删除
   - 检查 `logs/` 是否被 git 跟踪，若有则 `git rm -r --cached logs/`
   - 检查 `results/` 是否被 git 跟踪，若有则 `git rm -r --cached results/`
   - 检查 `examples/output/` 是否被跟踪，若有则 `git rm -r --cached examples/output/`

3. **pyproject.toml 检查**（修改）：
   - 版本号建议设为 `0.7.0`（对应 Week 7 完成）
   - 确认 `[project.scripts]` 包含（若存在 console_scripts）：
     ```toml
     [project.scripts]
     decision-coder = "main:main"
     decision-coder-mcp = "src.mcp.server:start_server"
     ```
   - 确认 `dependencies` 列表与 Week 6 一致（不要遗漏 Week 6 新增的 `rich`）
   - 确认 `requires-python = ">=3.11"`
   - 确认 `[project]` 基本信息完整：name, version, description, authors, readme, license

4. **全量回归测试**：
   - 运行：`python -m pytest tests/ --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py -v`
   - 预期：472/472 通过，零失败
   - 若失败：
     * 若与 Week 7 变更无关（如 E2E flaky），记录到 DEV_LOG.md 踩坑记录，标注为已知限制
     * 若与 Week 7 变更有关，定位并修复

5. **Demo 脚本验证**：
   - `python examples/demo_rich_ui.py` → 10 秒内完成，UI 正常
   - `python examples/demo_benchmark.py` → 生成 MD + HTML 报告
   - `python examples/demo_inventory_quick.py` → 生成 10 章报告
   - `python examples/demo_text_to_sql.py` → 输出查询结果

6. **代码风格抽查**：
   - 抽查 5 个核心文件：
     * `src/agent/graph.py` — 确认类型注解完整
     * `src/agent/nodes/coder.py` — 确认 docstring 中文
     * `src/domain/templates/inventory_pipeline.py` — 确认无未使用 import
     * `src/benchmark/runner.py` — 确认函数签名有类型注解
     * `src/agent/ui/manager.py` — 确认 docstring 中文
   - 抽查标准：
     * 所有函数有参数/返回类型注解
     * 所有公共函数有中文 docstring
     * 无未使用 import（`import *` 除外）
     * 无 `print()` 调试残留（允许 `print()` 在 CLI/main.py 中）

7. **文档更新**：
   - 在 `DEV_LOG.md` 追加 Week 7 Day 1-5 开发日志（参照 Week 6 格式）：
     * 每日摘要（3-5 行）
     * 新增文件清单（表格：文件、行数、职责）
     * 修改文件清单
     * 踩坑记录（如有）
     * 回退点（commit hash）
   - 在 `DEV_DESIGN.md` 的"阶段规划"中将 Week 7 标记为 ✅
   - 在 `DEV_DESIGN.md` 的"架构演进表"中添加 Week 7 列（Docker Compose、GitHub 优化、文档体系）

8. **提交**：
   - `git add` 所有变更
   - `git commit -m "Week 7: Docker Compose + docs + demos + cleanup"`
   - 记录 commit hash 作为 Week 7 回退点
```

### 验收标准
- [ ] `.gitignore` 完整覆盖临时文件和日志
- [ ] 无临时文件被 git 跟踪
- [ ] `pyproject.toml` 信息完整，版本号 0.7.0
- [ ] 472/472 测试通过
- [ ] 4 个 Demo 脚本全部成功
- [ ] DEV_LOG.md 和 DEV_DESIGN.md 已更新

---

## Week 7 Day 6-7：GitHub 优化与发布准备

### 目标
优化 GitHub 项目页面，添加 Issue/PR 模板、GitHub Actions CI（可选），确保项目对外专业。

### 前置准备
- Day 5 已完成，代码已清理，测试通过
- 确认 GitHub 仓库已创建且为 Public
- 确认有权限推送代码

### 开发提示词

```markdown
## 任务：Week 7 Day 6-7 — GitHub 优化与发布准备

请按以下步骤执行：

1. **Issue 模板**（新建）：
   - `.github/ISSUE_TEMPLATE/bug_report.md`：
     ```markdown
     ---
     name: Bug report
     about: 报告一个 bug
     title: '[Bug] '
     labels: bug
     assignees: ''
     ---

     ## 环境信息
     - OS: [e.g. Windows 11 / macOS 14 / Ubuntu 22.04]
     - Python: [e.g. 3.11.4]
     - DecisionCoder version: [e.g. 0.7.0]

     ## 复现步骤
     1. 运行 '...'
     2. 输入 '...'
     3. 看到错误

     ## 预期行为
     清晰描述预期结果

     ## 实际行为
     清晰描述实际结果

     ## 日志片段
     ```
     （粘贴相关日志）
     ```
     ```
   - `.github/ISSUE_TEMPLATE/feature_request.md`：
     ```markdown
     ---
     name: Feature request
     about: 建议新功能
     title: '[Feature] '
     labels: enhancement
     assignees: ''
     ---

     ## 使用场景
     描述你的使用场景和痛点

     ## 预期行为
     描述期望的功能和行为

     ## 可行性分析
     是否愿意提交 PR？是否有技术难点？
     ```

2. **PR 模板**（新建 `.github/PULL_REQUEST_TEMPLATE.md`）：
   ```markdown
   ## 变更说明
   清晰描述本次变更的内容和原因

   ## 测试情况
   - [ ] 新增测试通过
   - [ ] 全量回归测试通过（472/472）
   - [ ] 手动验证通过

   ## 影响范围
   - [ ] 仅新增文件，无现有代码修改
   - [ ] 修改现有文件，但无接口变更
   - [ ] 接口变更（需说明兼容性）

   ## 检查清单
   - [ ] 代码风格符合项目规范（类型注解、中文 docstring）
   - [ ] 无未使用 import
   - [ ] 无敏感信息泄露（API Key、路径）
   - [ ] 文档已更新（README/DEV_LOG/DEV_DESIGN）
   ```

3. **CI 工作流**（可选，新建 `.github/workflows/ci.yml`）：
   - 若时间紧可跳过，但建议实现：
   ```yaml
   name: CI
   on:
     push:
       branches: [main]
     pull_request:
       branches: [main]
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: '3.11'
         - name: Install dependencies
           run: |
             pip install -e ".[dev]"
         - name: Run tests
           run: |
             pytest tests/ --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py -v
           env:
             # 不设置 DEEPSEEK_API_KEY，跳过 E2E 测试
             CI: true
   ```
   - 注意：不设置 `DEEPSEEK_API_KEY`，E2E 测试会自动跳过（通过 `@pytest.mark.skipif`）
   - 若 CI 配置复杂，可先写简单版，后续优化

4. **CONTRIBUTING.md**（新建）：
   - 开发环境搭建（.venv, pip install -e .）
   - 代码规范（类型注解、中文 docstring、测试覆盖）
   - 提交规范（commit message 格式：`Week X: 描述`）
   - 如何运行测试（`pytest tests/ --ignore=...`）
   - 如何添加新领域模板（参照 `src/domain/templates/` 现有模板）

5. **GitHub 仓库设置检查**：
   - 仓库描述：与 README 第一句话一致
   - Topics 标签：`langgraph`, `mcp`, `agent`, `supply-chain`, `inventory-optimization`, `python`, `coding-agent`, `llm`
   - 默认分支：main
   - 关闭 Wiki（若不需要）：Settings → Wiki → Uncheck
   - 开启 Issues：Settings → Issues → Check
   - 开启 Discussions（可选）：Settings → Discussions → Check
   - 设置分支保护（可选）：main 分支要求 PR + 1 review

6. **最终验证**：
   - 在 GitHub 网页预览 README，确认：
     * Mermaid 图渲染正常
     * 徽章显示正常
     * 所有内部链接可点击（docs/architecture.md 等）
   - 点击 README 中的 docs/ 链接，确认无 404
   - 确认 `examples/` 目录在 GitHub 上可直接浏览
   - 确认 `pyproject.toml` 在 GitHub 上显示正确

7. **提交**：
   - `git add` 所有变更
   - `git commit -m "Week 7: GitHub repo optimization"`
   - `git push origin main`（或 week7-engineering 分支后合并）
   - 记录 commit hash
```

### 验收标准
- [ ] `.github/` 目录包含 Issue 模板、PR 模板、CI 工作流（可选）
- [ ] `CONTRIBUTING.md` 存在
- [ ] GitHub 仓库设置正确（Topics、描述、Issues 开启）
- [ ] README 在 GitHub 上渲染正常
- [ ] 所有内部链接无 404

---

## Week 8 Day 1：简历项目描述提炼

### 目标
将 DecisionCoder 提炼为简历上 3-5 个 bullet points，覆盖技术亮点、量化指标、个人贡献。

### 前置准备
- Week 7 已完成，项目已发布到 GitHub
- 阅读 `DEV_DESIGN.md` 的"面试叙事要点"和"数字指标"
- 确认 GitHub 仓库地址

### 开发提示词

```markdown
## 任务：Week 8 Day 1 — 简历项目描述提炼

请按以下步骤执行：

1. **中文简历版本**（新建 `docs/interview/resume_bullets.md`）：
   - 3-5 个 bullet points，每个不超过 2 行
   - 必须包含量化数字（472 测试、100% 成功率、5 道防线、7 个模板、10 任务）
   - 突出"独立开发"和"从 0 到 1"
   - 技术关键词与招聘 JD 对齐（LangGraph, MCP, Agent, RAG, Docker）
   - 示例结构：
     ```markdown
     ## DecisionCoder — 垂直领域 Coding Agent（独立项目）

     - **架构设计**：基于 LangGraph 构建 Plan-Code-Execute-Debug-Report 闭环状态机，支持 Human-in-the-loop 调试与自动重试，集成 MCP 协议标准化工具层
     - **安全体系**：实现 5 道纵深防御（LLM 语义识别→AST 语法检查→执行前预检→Docker 容器沙箱→SQL 注入拦截），危险代码拦截率 100%
     - **领域模板**：独立开发 7 个供应链优化模板（EOQ/需求预测/安全库存/补货点/一键分析），规则化参数提取与结论引擎，零 LLM 延迟、100% 可预测
     - **工程能力**：搭建自动化 Benchmark 评测框架（10 任务/完成率 100%/成功率 100%），Rich 终端实时 UI，472 个单元测试零回归，支持 Docker Compose 一键部署
     - **技术栈**：Python 3.11, LangGraph, LangChain, DeepSeek API, MCP, FastMCP, Plotly, DuckDB, Pandas, Rich, Docker
     ```

2. **英文简历版本**（新建 `docs/interview/resume_bullets_en.md`）：
   - 3-5 个 bullet points，用于外企/海外岗位
   - 保持相同量化数字，技术术语英文
   - 示例：
     ```markdown
     ## DecisionCoder — Vertical Coding Agent for Supply Chain Optimization (Solo Project)

     - **Architecture**: Built a Plan-Code-Execute-Debug-Report closed-loop state machine using LangGraph, supporting Human-in-the-loop debugging and auto-retry, integrated MCP protocol for standardized tool layer
     - **Security**: Implemented 5-layer defense-in-depth (LLM semantic detection → AST syntax checking → pre-execution validation → Docker sandbox → SQL injection prevention), 100% dangerous code interception rate
     - **Domain Templates**: Developed 7 supply chain optimization templates (EOQ, demand forecasting, safety stock, reorder point, one-click analysis), rule-based parameter extraction and conclusion engine, zero LLM latency, 100% deterministic
     - **Engineering**: Built automated Benchmark framework (10 tasks / 100% completion / 100% success rate), Rich terminal real-time UI, 472 unit tests with zero regression, Docker Compose one-click deployment
     - **Tech Stack**: Python 3.11, LangGraph, LangChain, DeepSeek API, MCP, FastMCP, Plotly, DuckDB, Pandas, Rich, Docker
     ```

3. **技术细节附录**（新建 `docs/interview/resume_bullets_detail.md`）：
   - 每个 bullet point 对应 3-5 个追问点
   - 追问点格式：问题 → 回答要点（3-5 个 bullet）
   - 示例：
     ```markdown
     ### Bullet 1: 架构设计

     **可能追问**：
     1. "为什么用 LangGraph 而不是 CrewAI？"
        - 状态机更可控，适合调试循环
        - 条件路由明确（error → debugger / success → reporter）
        - retry_count 上限强制 ABORT，防止无限循环
        - 节点间状态通过 TypedDict 显式传递，便于追踪

     2. "MCP 协议在项目中的作用？"
        - 标准化工具接口（8 个 Tool）
        - 支持 stdio transport，便于扩展
        - 2026 年热门招聘关键词，体现技术前瞻性
     ```

4. **规范**：
   - 不编造未实现的特性（如 RAG 是规划中但未实现，不要写）
   - 数字准确：472 测试、100% 成功率、0 平均重试（E2E）
   - 区分"已实现"和"规划中"（如 Docker Compose 是 Week 7 实现，若已完成则写入）
   - 每个 bullet 以动词开头（设计、实现、开发、搭建）
   - 避免"参与""协助"等词，强调"独立""从 0 到 1"

5. **验证**：
   - 将中文版本粘贴到简历模板中，确认排版不溢出（每行不超过 80 字符）
   - 将英文版本粘贴到英文简历模板中，确认语法正确
   - 随机抽取 3 个追问点，尝试口头回答，控制在 1-2 分钟
```

### 验收标准
- [ ] 中文简历 bullet points 3-5 个，含量化数字
- [ ] 英文简历 bullet points 3-5 个，语法正确
- [ ] 技术细节附录包含每个 bullet 的 3-5 个追问点
- [ ] 不编造未实现特性

---

## Week 8 Day 2：技术面试 Q&A 准备

### 目标
准备 20 个常见技术面试问题及回答，覆盖项目架构、难点、决策、优化空间。

### 前置准备
- Day 1 已完成，简历 bullet points 已提炼
- 阅读 `DEV_DESIGN.md` 的"设计决策记录"和"踩坑记录"

### 开发提示词

```markdown
## 任务：Week 8 Day 2 — 技术面试 Q&A 准备

请按以下步骤执行：

1. **问题清单**（新建 `docs/interview/qa_technical.md`）：
   20 个问题，分 5 类，每类 3-5 个：

   **项目概述类（3 个）**：
   - Q1: "请介绍你最满意的一个项目"
   - Q2: "这个项目解决了什么问题？"
   - Q3: "如果重新做，你会怎么改进？"

   **架构设计类（5 个）**：
   - Q4: "为什么用 LangGraph 而不是 CrewAI？"
   - Q5: "MCP 协议在项目中的作用是什么？"
   - Q6: "状态机中的循环调试是怎么设计的？"
   - Q7: "Human-in-the-loop 的实现机制？"
   - Q8: "如何确保节点间的状态一致性？"

   **安全与性能类（4 个）**：
   - Q9: "5 道安全防线分别是什么？哪一道最关键？"
   - Q10: "Docker 沙箱的资源限制怎么配置？"
   - Q11: "如果 LLM 生成危险代码但 AST 没拦截住，怎么办？"
   - Q12: "Benchmark 中某个任务超时了，怎么排查？"

   **领域知识类（3 个）**：
   - Q13: "EOQ 模型在实际业务中有什么局限性？"
   - Q14: "需求预测的 4 种算法怎么选择？"
   - Q15: "规则化结论引擎和 LLM 生成结论各有什么优劣？"

   **工程实践类（5 个）**：
   - Q16: "472 个测试是怎么组织的？怎么保证零回归？"
   - Q17: "Rich UI 的线程安全怎么实现？"
   - Q18: "JSONL 断点续跑的设计思路？"
   - Q19: "项目中遇到的最大技术难点是什么？"
   - Q20: "如何保证代码生成后的可执行性？"

2. **回答模板**（每个问题下方）：
   - 使用 STAR 变体：背景（1 句）→ 方案（2-3 句）→ 结果/量化（1 句）→ 反思（可选 1 句）
   - 总时长控制在 1-2 分钟（面试时）
   - 关键数字加粗（**472**、**100%**、**5 道**）
   - 示例（Q4）：
     ```markdown
     ### Q4: 为什么用 LangGraph 而不是 CrewAI？

     **回答要点**：
     - **背景**：项目需要可控的调试循环和明确的状态流转，CrewAI 的并行 Agent 模式不适合单线程调试场景
     - **方案**：
       * LangGraph 的 StateGraph 提供显式状态定义（AgentState TypedDict），每个节点输入输出明确
       * 支持条件路由（`route_after_executor` / `route_after_debugger`），error 时自动进入 Debugger 循环
       * retry_count 上限检查（>=2 强制 ABORT），防止无限循环和资源浪费
     - **结果**：E2E 测试 12/12 一次成功，retry_count=0，调试循环零触发
     - **反思**：若项目需要多 Agent 并行协作，CrewAI 更合适；但垂直 Agent 的可控性优先于自动化
     ```

3. **陷阱问题准备**（新建 `docs/interview/qa_tricky.md`）：
   - "这个项目是不是 AI 帮你写的？"
     * 回答：AI 辅助编码（Claude Code 写具体实现），但架构设计、领域建模、测试策略、调试闭环都是独立设计。AI 是工具，决策和验证是人的工作。
   - "为什么不做成 Web 界面？"
     * 回答：垂直 Agent 的核心是决策闭环而非界面，CLI + Rich 更符合开发者场景。8 周时间聚焦核心能力（状态机、安全、领域模板），Web UI 是 V2 规划（Gradio/Streamlit）。
   - "和 AutoGPT 有什么区别？"
     * 回答：DecisionCoder 是垂直领域（供应链）、模板化（非自由建模）、可验证（Benchmark + 规则引擎）、人在回路（安全优先）。AutoGPT 是通用探索型，DecisionCoder 是专业决策型。
   - "你的测试都是 mock 的，真实运行成功率多少？"
     * 回答：E2E 测试 12/12 一次成功（Week 3-5），但依赖 DeepSeek API 稳定性。Benchmark 框架已就绪，待批量运行收集真实数据。
   - "如果 LLM API 被封了，项目还能用吗？"
     * 回答：核心领域模板（EOQ/预测/安全库存）和规则引擎完全零 LLM 依赖。Planner/Coder/Debugger 有规则回退（14 种错误分类 + 修复策略），LLM 仅提升体验，不阻塞功能。

4. **规范**：
   - 回答要点而非完整背诵稿（面试时自然发挥）
   - 每个回答包含至少 1 个量化数字
   - 不回避项目的不足（如"Text-to-SQL 的列名幻觉问题"），但需说明改进思路（Few-Shot Prompt + Schema 约束）
   - 区分"已实现"和"规划中"（如 RAG 未实现，诚实说明）

5. **验证**：
   - 随机抽取 5 个问题，尝试口头回答，录音并回听
   - 检查是否超时（>2 分钟需精简）
   - 检查是否有"然后...然后..."等口头禅
   - 检查数字是否准确（不编造）
```

### 验收标准
- [ ] 20 个技术问题 + 回答要点
- [ ] 5 个陷阱问题 + 建议回答
- [ ] 每个回答含至少 1 个量化数字
- [ ] 不回避项目不足，给出改进思路

---

## Week 8 Day 3：3 分钟项目口述稿（Elevator Pitch）

### 目标
准备面试开场时的 3 分钟项目介绍口述稿，让面试官快速理解项目价值和技术深度。

### 前置准备
- Day 1-2 已完成，简历和 Q&A 已准备
- 确认 GitHub 仓库可访问

### 开发提示词

```markdown
## 任务：Week 8 Day 3 — 3 分钟项目口述稿（Elevator Pitch）

请按以下步骤执行：

1. **口述稿结构**（新建 `docs/interview/elevator_pitch.md`）：
   严格控制在 180 秒，分 4 段，每段标注建议时长：

   **0-30s：痛点 + 定位**
   - 台词："通用 Coding Agent 在处理经营决策类任务时，缺少领域知识和可验证的执行闭环。比如让 AI 算 EOQ，它可能公式都写错，也没法验证结果对不对。"
   - 转折："所以我构建了一个面向供应链库存优化的垂直 Agent —— DecisionCoder。"

   **30-90s：技术架构（3 个亮点）**
   - 亮点 1（20s）："第一层是 LangGraph 状态机：Planner 拆解需求，Coder 生成代码，Executor 沙箱执行，Debugger 人机调试，Reporter 生成报告。支持循环调试，retry 两次自动终止。"
   - 亮点 2（20s）："第二层是 MCP 工具层：8 个标准化 Tool，文件读写、Python 沙箱执行、CSV 解析，通过 FastMCP 注册，stdio transport。"
   - 亮点 3（20s）："第三层是领域模板：7 个供应链优化模型，从 EOQ 经济订货批量到一键库存分析流水线，规则化参数提取，零 LLM 延迟。"

   **90-150s：量化结果**
   - "472 个单元测试，100% 通过率，零回归。"
   - "10 任务 Benchmark 框架，E2E 成功率 100%，平均重试 0 次。"
   - "5 道安全防线，危险代码拦截率 100%，包括 AST 语法检查和 Docker 容器沙箱。"

   **150-180s：个人贡献 + 收获**
   - "这个项目是我从 0 到 1 独立开发的，覆盖架构设计、领域建模、安全体系、评测框架。"
   - "最大的收获是理解了 Agent 系统中'可控性'比'自动化'更重要——垂直领域、模板化、人在回路，才能保证结果可靠。"

2. **英文版本**（新建 `docs/interview/elevator_pitch_en.md`）：
   - 相同结构，英文台词
   - 技术术语保留英文（LangGraph, MCP, Agent, EOQ）
   - 时长同样 180 秒

3. **卡片版**（新建 `docs/interview/elevator_pitch_cards.md`）：
   - 将 180 秒拆为 6 张卡片，每张 30 秒
   - 每张卡片包含：关键词（3-5 个）+ 核心句子（1-2 句）+ 数字（1 个）
   - 示例：
     ```markdown
     ### 卡片 1：痛点（0-30s）
     关键词：通用 Agent、领域知识、验证闭环
     核心句：通用 Coding Agent 缺少领域知识和可验证闭环。
     数字：无

     ### 卡片 2：状态机（30-60s）
     关键词：LangGraph、Planner、Coder、Executor、Debugger、Reporter
     核心句：5 节点闭环，支持循环调试和自动终止。
     数字：retry >= 2 强制 ABORT
     ```

4. **练习建议**（写入每个文档末尾）：
   - 对着镜子练习 3 遍，严格计时（手机秒表）
   - 录屏自己讲，回看是否有"然后...然后..."等口头禅
   - 准备 2 个版本：
     * 3 分钟完整版（用于现场面试）
     * 1 分钟精简版（用于电话初筛/HR 面）
   - 找同学/导师听一遍，收集反馈

5. **规范**：
   - 口语化，避免朗读技术文档
   - 数字准确，不夸大
   - 每 30 秒一个自然停顿点（方便面试官插话）
   - 不提及"Claude Code"等 AI 辅助工具（除非面试官追问）

6. **验证**：
   - 自己朗读一遍，计时
   - 若超过 180 秒，精简技术细节（如省略 MCP 具体 Tool 数量）
   - 若少于 150 秒，补充一个具体场景（如"分析 sku_inventory.csv 的完整流程"）
```

### 验收标准
- [ ] 中文口述稿完整，180 秒
- [ ] 英文口述稿完整，180 秒
- [ ] 卡片版 6 张，每张 30 秒
- [ ] 包含痛点、架构、量化结果、个人贡献 4 段

---

## Week 8 Day 4：演示环境准备

### 目标
确保面试时能在 30 秒内启动项目并展示效果，准备录屏素材。

### 前置准备
- Day 3 已完成，口述稿已准备
- 确认 4 个 Demo 脚本可正常运行
- 确认终端环境（字体大小、颜色主题）适合录屏

### 开发提示词

```markdown
## 任务：Week 8 Day 4 — 演示环境准备

请按以下步骤执行：

1. **Makefile**（新建/修改项目根目录 `Makefile`）：
   - 实现以下目标：
     ```makefile
     .PHONY: demo-ui demo-benchmark demo-inventory demo-sql test check clean

     demo-ui:
     	python examples/demo_rich_ui.py

     demo-benchmark:
     	python examples/demo_benchmark.py

     demo-inventory:
     	python examples/demo_inventory_quick.py

     demo-sql:
     	python examples/demo_text_to_sql.py

     test:
     	python -m pytest tests/ --ignore=tests/test_docker_mode_graph.py --ignore=tests/test_docker_runner_security.py -v

     check:
     	python scripts/check_env.py

     clean:
     	rm -rf examples/output/*
     	rm -rf workspace/src/_dc_exec_*.py
     	rm -rf workspace/reports/*.md
     	rm -rf workspace/reports/charts/*.html
     	rm -rf logs/*
     	rm -rf results/*
     ```
   - Windows 兼容：若主要使用 Windows，可改为 `makefile.bat` 或 PowerShell 脚本
   - 运行 `make check` 验证环境
   - 运行 `make demo-ui` 验证 Demo 脚本

2. **scripts/check_env.py**（新建）：
   - 功能清单：
     * 检查 Python >= 3.11（`sys.version_info`）
     * 检查关键依赖是否可导入：`rich`, `langgraph`, `pandas`, `plotly`, `duckdb`, `scipy`
     * 检查 `.env` 文件是否存在（可选，不强制，打印提示）
     * 检查 `workspace/data/` 下是否有：`sales.csv`, `inventory.csv`, `sku_inventory.csv`
     * 检查 `examples/` 下 4 个 Demo 脚本是否存在
     * 打印彩色检查结果（✅/❌），最后给出总体状态（"环境检查通过" / "环境检查失败，请修复上述问题"）
   - 不引入新依赖（用标准库 `ctypes` 或纯 print 实现颜色，或依赖 `rich` 若已安装）
   - 运行 `python scripts/check_env.py` 验证

3. **录屏素材准备**（手动操作，不生成文件）：
   - 场景 1：终端运行 `make demo-ui`（展示 Rich 进度条、状态表格、DebugPanel）
     * 建议工具：ScreenToGif（Windows）或 OBS（跨平台）
     * 时长：30-45 秒
     * 保存：`docs/interview/recordings/demo_ui.gif`（< 5MB）
   - 场景 2：终端运行 `python main.py --rich` 输入"分析 sales.csv"
     * 需 API Key，若不可用则跳过或录制到 Planner 节点后停止
     * 时长：45 秒
     * 保存：`docs/interview/recordings/demo_real.gif`
   - 场景 3：运行 `make demo-benchmark` 后打开 HTML 报告
     * 时长：30 秒
     * 保存：`docs/interview/recordings/demo_benchmark.gif`
   - 场景 4：运行 `make demo-inventory`
     * 时长：30 秒
     * 保存：`docs/interview/recordings/demo_inventory.gif`
   - 技术建议（写入 `docs/interview/recordings/README.md`）：
     * 终端字体：14pt+（推荐 JetBrains Mono 或 Cascadia Code）
     * 背景：深色主题（推荐 Dracula 或 One Dark）
     * 分辨率：1920×1080 或 1280×720
     * 鼠标高亮：开启（ScreenToGif 支持）

4. **"无网络模式"验证**：
   - 断开网络（或设置无效 API Key）
   - 运行 `make demo-ui` → 确认成功
   - 运行 `make demo-benchmark` → 确认成功
   - 运行 `make demo-inventory` → 确认成功
   - 运行 `make demo-sql` → 确认成功
   - 记录结果到 `docs/interview/offline_demo_checklist.md`

5. **演示脚本**（新建 `docs/interview/demo_script.md`）：
   - 结构：
     * 开场白（10s）："我做一个供应链库存优化的 Agent，给你演示一下"
     * 启动命令（5s）：`make demo-ui`
     * 操作步骤（30s）：看进度条推进、Debugger 暂停、日志流
     * 亮点解说（30s）："这是 LangGraph 状态机实时追踪，5 个节点自动执行，错误时自动进入调试"
     * 收尾（5s）："整个流程 10 秒跑完，零人工干预"
   - 标注"如果面试官问 X，则展示 Y"：
     * 问安全 → 展示 `docs/security.md` 或讲解 AST 检查
     * 问领域知识 → 展示 `make demo-inventory`
     * 问测试 → 展示 `make test` 运行结果

6. **规范**：
   - 所有命令在干净的虚拟环境中验证通过
   - 录屏时终端无敏感信息（API Key、个人路径、密码）
   - GIF 文件 < 5MB（GitHub 限制）
   - `scripts/check_env.py` 不依赖外部网络

7. **验证**：
   - `make check` 通过
   - `make demo-ui` 成功
   - `make test` 472/472 通过
   - `make clean` 清理成功
```

### 验收标准
- [ ] `Makefile` 存在，所有目标可执行
- [ ] `scripts/check_env.py` 可运行，输出彩色检查结果
- [ ] 4 个 Demo 脚本在无网络环境下可运行
- [ ] `docs/interview/demo_script.md` 包含完整演示流程

---

## Week 8 Day 5：模拟面试与 QA 打磨

### 目标
通过自我模拟或请同学/导师帮忙，演练项目介绍和技术问答，打磨表达。

### 前置准备
- Day 1-4 已完成，简历、Q&A、口述稿、演示环境已准备
- 准备录音/录像设备（手机即可）

### 开发提示词

```markdown
## 任务：Week 8 Day 5 — 模拟面试与 QA 打磨

请按以下步骤执行：

1. **自我模拟**（至少 2 轮，新建 `docs/interview/mock_self_notes.md` 记录）：
   - 轮次 1：对着镜子讲 3 分钟 elevator pitch，手机录视频，回看
     * 检查点：
       - 是否在 30 秒内进入技术细节？
       - 是否过度使用"然后"？（目标：每 30 秒 <= 2 次）
       - 数字是否准确？（472、100%、5 道、7 个）
       - 眼神是否自然？（不要一直看屏幕）
       - 手势是否过多？（保持自然）
   - 轮次 2：随机抽取 5 个 Q&A 问题（从 `docs/interview/qa_technical.md`），限时回答，录视频
     * 检查点：
       - 每个回答是否在 1-2 分钟内？
       - 是否包含至少 1 个量化数字？
       - 是否回答了"为什么"而不仅是"是什么"？
       - 是否有明显的知识盲区？（记录到 notes）

2. **请他人模拟**（若条件允许，新建 `docs/interview/mock_external_notes.md`）：
   - 请同学/导师/朋友扮演面试官，进行 15 分钟模拟面试
   - 流程：
     * 3 分钟：你讲 elevator pitch
     * 5 分钟：对方提问（从技术细节到项目难点）
     * 5 分钟：对方追问（"如果...怎么办"类问题）
     * 2 分钟：你提问（展示对岗位/公司的兴趣）
   - 重点观察：
     * 对方在哪个问题露出困惑表情 → 该问题需要简化
     * 对方在哪个问题打断你 → 该部分需要更简洁
     * 对方追问最多的是什么 → 补充到 Q&A 准备
   - 记录对方提出的意外问题，补充到 `docs/interview/qa_technical.md`

3. **常见陷阱准备**（新建 `docs/interview/tricky_questions.md`）：
   - 已准备 5 个陷阱问题（Day 2），补充更多：
     * "这个项目是不是 AI 帮你写的？"
       - 回答：AI 辅助编码（Claude Code 写具体实现），但架构设计、领域建模、测试策略、调试闭环都是独立设计。AI 是工具，决策和验证是人的工作。
     * "为什么不做成 Web 界面？"
       - 回答：垂直 Agent 的核心是决策闭环而非界面，CLI + Rich 更符合开发者场景。8 周时间聚焦核心能力，Web UI 是 V2 规划（Gradio/Streamlit）。
     * "和 AutoGPT 有什么区别？"
       - 回答：DecisionCoder 是垂直领域（供应链）、模板化（非自由建模）、可验证（Benchmark + 规则引擎）、人在回路（安全优先）。AutoGPT 是通用探索型，DecisionCoder 是专业决策型。
     * "你的测试都是 mock 的，真实运行成功率多少？"
       - 回答：E2E 测试 12/12 一次成功（Week 3-5），但依赖 DeepSeek API 稳定性。Benchmark 框架已就绪，待批量运行收集真实数据。
     * "如果 LLM API 被封了，项目还能用吗？"
       - 回答：核心领域模板和规则引擎完全零 LLM 依赖。Planner/Coder/Debugger 有规则回退，LLM 仅提升体验，不阻塞功能。
     * "这个项目有多大实际价值？"
       - 回答：供应链库存优化是管理科学经典问题，EOQ/安全库存模型在制造业广泛应用。DecisionCoder 将"需要专家手动计算"变为"自然语言输入、自动输出决策建议"，降低使用门槛。
     * "你一个人做这么多，是不是代码质量不高？"
       - 回答：472 个单元测试、100% 通过率、零回归、类型注解全覆盖、中文 docstring、5 道安全防线——代码质量通过量化指标保证。

4. **改进记录**（写入 `docs/interview/mock_self_notes.md` 和 `mock_external_notes.md`）：
   - 每次模拟后记录：
     * 表现好的地方（保持）
     * 需要改进的地方（具体行动）
     * 新发现的问题（补充到 Q&A）
     * 下次模拟重点

5. **规范**：
   - 诚实回答，不夸大 AI 的辅助程度
   - 强调"独立设计"和"从 0 到 1"
   - 对不足之处坦诚并给出改进思路（如"目前只支持单用户 CLI，下一步计划添加 Web UI 和多用户会话"）
   - 避免防御性语气（"你不懂""这很复杂"），用"这是一个很好的问题，我当时的考虑是..."

6. **验证**：
   - 完成至少 2 轮自我模拟
   - 若条件允许，完成 1 轮他人模拟
   - 记录文件 >= 2 个（self + external 或 self + tricky）
```

### 验收标准
- [ ] 完成 >= 2 轮自我模拟，有视频/录音记录
- [ ] 记录文件包含表现好的地方、需改进的地方、新发现的问题
- [ ] 陷阱问题 >= 7 个，每个有建议回答
- [ ] 改进记录具体可执行（如"第 3 分钟语速放慢"而非"说得不好"）

---

## Week 8 Day 6-7：投递准备与收尾

### 目标
完成简历投递前的最后准备，整理项目链接、准备不同岗位的投递版本，最终提交并标记版本。

### 前置准备
- Day 1-5 已完成，所有面试材料已准备
- 确认 GitHub 仓库为 Public 且内容完整
- 确认简历模板可用（中文/英文）

### 开发提示词

```markdown
## 任务：Week 8 Day 6-7 — 投递准备与收尾

请按以下步骤执行：

1. **岗位版本简历**（新建 `docs/interview/resume_versions.md`）：
   - 数据分析岗版本：
     * 突出：`run_analysis`, `chart_templates`, `text_to_sql`, `data_quality`
     * 突出：Benchmark 数据可视化、Plotly 交互式图表、DuckDB 查询
     * 突出：一键数据分析、数据质量检查、缺失值/异常值检测
     * 技术关键词：Pandas, Plotly, DuckDB, EDA, 数据清洗, 可视化
   - 后端/工程岗版本：
     * 突出：LangGraph 状态机、MCP 协议、Docker Compose、5 道安全防线
     * 突出：472 测试、零回归、CI/CD、JSONL 断点续跑、线程安全
     * 突出：FastMCP、subprocess/MCP/Docker 三路径执行、AST 语法检查
     * 技术关键词：Python, LangGraph, MCP, Docker, pytest, CI/CD
   - 算法/AI 岗版本：
     * 突出：Planner/Coder/Debugger 的 LLM 编排、模板匹配器、参数提取器
     * 突出：规则化 vs LLM 的权衡、Human-in-the-loop、retry 策略
     * 突出：需求预测 4 种算法、EOQ 优化、安全库存概率模型
     * 技术关键词：LLM, Agent, LangChain, DeepSeek, 运筹优化, 时序预测
   - 每个版本保存为独立文件：
     * `docs/interview/resume_data_analyst.md`
     * `docs/interview/resume_backend.md`
     * `docs/interview/resume_ai_engineer.md`

2. **投递模板**（新建 `docs/interview/application_template.md`）：
   - 邮件主题模板：
     * 数据分析岗：`[实习申请] 北京科技大学管理科学与工程研究生 - DecisionCoder 项目作者`
     * 后端岗：`[实习申请] 供应链优化 Agent 开源项目作者 - Python 后端开发`
     * 算法岗：`[实习申请] LLM Agent 系统开发经验 - DecisionCoder 项目`
   - 正文结构（300 字以内）：
     ```markdown
     您好，

     我是北京科技大学管理科学与工程专业研一学生，目前正在寻找 [岗位名称] 实习机会。

     近期独立开发了一个面向供应链库存优化的垂直 Coding Agent 项目 DecisionCoder，基于 LangGraph + MCP + DeepSeek 构建，包含 7 个领域模板、5 道安全防线、472 个单元测试（100% 通过）。项目已开源在 GitHub：[链接]

     技术亮点：
     - [根据岗位选择 2-3 个亮点]

     附件是我的简历，期待您的回复。

     谢谢！
     [姓名]
     [电话]
     [邮箱]
     ```
   - 私信模板（Boss 直聘/脉脉）：
     * 更短版本（100 字以内），突出项目链接和 1 个核心亮点

3. **项目链接检查**（手动验证）：
   - 确认 GitHub 仓库为 Public（Settings → General → Visibility）
   - 确认 README 首屏可见 Mermaid 图和 Quick Start
   - 确认 `examples/` 目录在 GitHub 上可直接浏览
   - 确认 `docs/` 目录可访问
   - 确认 `pyproject.toml` 显示正确
   - 复制仓库地址，粘贴到投递模板中

4. **文档最终更新**：
   - `DEV_LOG.md`：追加 Week 8 Day 1-7 日志（参照 Week 7 格式）
     * 每日摘要（3-5 行）
     * 新增文件清单（表格）
     * 修改文件清单
     * 踩坑记录（如有）
     * 回退点（commit hash）
   - `DEV_DESIGN.md`：
     * 阶段规划：Week 8 标记 ✅
     * 面试叙事要点：更新为最终版（包含 Docker Compose、完整文档体系、GitHub 优化）
     * 架构演进表：添加 Week 8 列（简历提炼、Q&A 准备、演示环境、模拟面试、投递模板）
     * 添加"长期维护建议"：V2 Web UI、多用户会话、RAG 知识库、更多领域模板

5. **最终提交**：
   - `git add` 所有变更
   - `git commit -m "Week 8: Interview prep & project polish"`
   - `git tag v0.8.0`（标记 Week 8 完成版本）
   - `git push origin main`
   - `git push origin v0.8.0`
   - 记录 commit hash

6. **收尾检查清单**（手动勾选）：
   - [ ] `git clone` → `pip install -e .` → `python main.py --rich` 一键跑通
   - [ ] README 渲染正常，Mermaid 图可见
   - [ ] 4 个 Demo 脚本均可独立运行
   - [ ] 472 测试通过
   - [ ] 简历项目描述已提炼（中文 + 英文）
   - [ ] 20 个 Q&A 已准备
   - [ ] 3 分钟 elevator pitch 已熟练（录音验证）
   - [ ] 录屏素材已保存（>= 2 个 GIF）
   - [ ] 投递模板已准备（>= 3 个岗位版本）
   - [ ] GitHub 仓库为 Public，Issues 开启
   - [ ] `make check` 通过
   - [ ] `make test` 通过
   - [ ] DEV_LOG.md 和 DEV_DESIGN.md 已更新

7. **长期维护建议**（写入 `DEV_DESIGN.md` 末尾）：
   - **V2 规划**：
     * Web UI（Gradio/Streamlit）支持多用户会话
     * RAG 知识库（供应链领域知识检索）
     * 更多领域模板（运输优化、定价模型、排产调度）
   - **开源贡献**：
     * 将 MCP Tool 层抽离为独立包，贡献给社区
     * 发布 Benchmark 框架为独立工具
   - **论文/博客产出**：
     * 技术博客："构建垂直领域 Coding Agent 的 8 周实践"
     * 投稿：将规则化模板匹配和参数提取写成短文投稿
```

### 验收标准
- [ ] >= 3 个岗位版本简历
- [ ] 邮件投递模板 + 私信模板
- [ ] GitHub 仓库 Public，所有链接可访问
- [ ] DEV_LOG.md 和 DEV_DESIGN.md 已更新
- [ ] `git tag v0.8.0` 已推送
- [ ] 收尾检查清单全部勾选

---

## 附录 A：跨周通用约束

### 1. 依赖控制
Week 7-8 **不新增运行时依赖**。所有工作集中在文档、Docker Compose、GitHub 配置、面试准备。若 Dockerfile.sandbox 需要 Flask，优先用标准库 `http.server` 替代。

### 2. 向后兼容
- 所有现有代码（472 测试基线）**零修改**或**仅新增文件**
- 若必须修改现有文件（如 executor.py 添加 SandboxClient 路径），需确保原有路径（subprocess/MCP/DockerRunner）全部保留
- 不修改 `AgentState` 字段定义
- 不修改现有节点（planner/coder/executor/debugger/reporter）的核心逻辑

### 3. 测试策略
| 模块 | 测试文件 | 预估用例数 |
|------|---------|-----------|
| Docker Compose | `tests/test_docker_compose.py` | 3-5 |
| 环境检查脚本 | 无（手动验证） | — |
| Demo 脚本 | 无（手动验证） | — |
| 全量回归 | 现有 472 | 全部通过 |

### 4. 时间压缩方案
若 Week 7 时间不足，优先级排序：
1. **README 重写**（Day 2）> **Demo 脚本完善**（Day 4）> **代码清理**（Day 5）> **Docker Compose**（Day 1）> **GitHub 优化**（Day 6-7）> **架构文档**（Day 3）

若 Week 8 时间不足，优先级排序：
1. **简历 bullet points**（Day 1）> **Elevator pitch**（Day 3）> **Q&A 准备**（Day 2）> **演示环境**（Day 4）> **模拟面试**（Day 5）> **投递模板**（Day 6-7）

### 5. 文件组织（Week 7-8 新增）

```
decision-coder/
├── docker-compose.yml                # ← Week 7 Day 1
├── Dockerfile.sandbox                # ← Week 7 Day 1
├── Makefile                          # ← Week 7 Day 4 / Week 8 Day 4
├── README.md                         # ← Week 7 Day 2（重写）
├── LICENSE                           # ← Week 7 Day 2
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md             # ← Week 7 Day 6
│   │   └── feature_request.md        # ← Week 7 Day 6
│   ├── PULL_REQUEST_TEMPLATE.md      # ← Week 7 Day 6
│   └── workflows/
│       └── ci.yml                    # ← Week 7 Day 6（可选）
├── docs/
│   ├── architecture.md               # ← Week 7 Day 3
│   ├── sequence.md                   # ← Week 7 Day 3
│   ├── state-machine.md              # ← Week 7 Day 3
│   ├── security.md                   # ← Week 7 Day 3
│   ├── benchmark.md                  # ← Week 7 Day 3
│   └── interview/                    # ← Week 8
│       ├── resume_bullets.md         # ← Week 8 Day 1
│       ├── resume_bullets_en.md      # ← Week 8 Day 1
│       ├── resume_bullets_detail.md  # ← Week 8 Day 1
│       ├── resume_data_analyst.md    # ← Week 8 Day 6
│       ├── resume_backend.md         # ← Week 8 Day 6
│       ├── resume_ai_engineer.md     # ← Week 8 Day 6
│       ├── qa_technical.md           # ← Week 8 Day 2
│       ├── qa_tricky.md            # ← Week 8 Day 2
│       ├── elevator_pitch.md         # ← Week 8 Day 3
│       ├── elevator_pitch_en.md      # ← Week 8 Day 3
│       ├── elevator_pitch_cards.md   # ← Week 8 Day 3
│       ├── demo_script.md            # ← Week 8 Day 4
│       ├── recordings/               # ← Week 8 Day 4（手动）
│       │   ├── README.md
│       │   ├── demo_ui.gif
│       │   ├── demo_benchmark.gif
│       │   └── demo_inventory.gif
│       ├── mock_self_notes.md        # ← Week 8 Day 5
│       ├── mock_external_notes.md    # ← Week 8 Day 5
│       ├── application_template.md   # ← Week 8 Day 6
│       └── offline_demo_checklist.md # ← Week 8 Day 4
├── scripts/
│   └── check_env.py                  # ← Week 8 Day 4
├── examples/
│   ├── demo_rich_ui.py               # ← Week 6（完善）
│   ├── demo_benchmark.py             # ← Week 6（完善）
│   ├── demo_inventory_quick.py       # ← Week 7 Day 4
│   ├── demo_text_to_sql.py           # ← Week 7 Day 4
│   ├── demo_inventory_optimization.py # ← Week 5（保留）
│   └── RECORDING_GUIDE.md          # ← Week 7 Day 4
├── src/
│   └── agent/
│       └── sandbox/
│           └── sandbox_client.py     # ← Week 7 Day 1
└── tests/
    └── test_docker_compose.py        # ← Week 7 Day 1
```

### 6. 常见陷阱处理

| 问题 | 解决方案 |
|------|---------|
| Dockerfile.sandbox 构建失败 | 检查基础镜像可用性，最小化依赖（只装 pandas/scipy/plotly/duckdb/openpyxl） |
| README Mermaid 图不渲染 | 使用标准 `graph TD` 语法，避免复杂 `subgraph` 嵌套 |
| Demo 脚本运行超时 | 检查 `workspace/data/` 下数据文件是否存在 |
| 简历 bullet 过长 | 每行 <= 80 字符，技术细节放入附录 |
| 模拟面试紧张 | 多练 3 遍，录音回听，找同学模拟 |
| GitHub 链接 404 | 确认仓库为 Public，文件已 push |
| `make` 在 Windows 不可用 | 提供 `make.bat` 或 PowerShell 替代方案 |
| 录屏 GIF 超过 5MB | 降低分辨率（720p）或时长（15 秒） |
| 面试官质疑 AI 辅助程度 | 诚实回答，强调独立设计和决策 |

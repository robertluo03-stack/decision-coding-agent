# DecisionCoder — 开发设计文档

> **面向自己**：这份文档会随着开发不断修改，记录设计决策、接口变更和踩坑记录。
> **版本**：v0.3 | **日期**：2026-07-06 | **当前阶段**：Week 3 数据分析能力完成，进入 Week 4

---

## 一、项目定位（一句话）

**DecisionCoder** 是一个面向经营决策与运筹优化场景的垂直 Coding Agent，基于 MCP 协议构建工具层，使用 LangGraph 编排 Plan-Code-Execute-Debug-Report 闭环，支持 Human-in-the-loop 调试。

---

## 二、核心架构

```
┌─────────────────────────────────────────────────────────────┐
│  交互层 (CLI)                                                │
│  - 接收自然语言需求                                          │
│  - 展示执行进度与调试选项                                     │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  编排层 (LangGraph StateGraph)                              │
│  ┌─────────┐  ┌──────┐  ┌─────────┐  ┌───────┐  ┌────────┐│
│  │ Planner │→│ Coder │→│ Executor │→│ Router│  │Reporter││
│  │ 任务拆解 │  │代码生成│  │沙箱执行  │  │条件分支│  │报告生成 ││
│  └─────────┘  └──────┘  └─────────┘  └──┬────┘  └────────┘│
│                                         │                   │
│                              ┌──────────┘                   │
│                              ▼                              │
│  ┌──────────────────────────────────────┐                   │
│  │ Debugger (Human-in-the-loop)         │                   │
│  │ - AI分析错误原因（DeepSeek + 规则回退）│                  │
│  │ - 人类选择：接受修复 / 输入指令 / 跳过 / 中止 │          │
│  │ - retry_count>=2 强制 ABORT          │                   │
│  └──────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  工具层 (MCP Protocol)                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │File I/O  │ │Python    │ │Data Read │ │File Mgmt     │  │
│  │(读写)    │ │Exec(沙箱) │ │(CSV/Excel)│ │(list/exists) │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
│  共 8 个 Tool（FastMCP stdio transport）                    │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  安全层（纵深防御）                                          │
│  第零道: LLM 语义识别（Planner）                              │
│  第一道: AST 安全检查（security_checker，Coder后置）         │
│  第二道: Executor 执行前预检（compile + AST）                 │
│  第三道: DockerRunner AST 兜底（USE_DOCKER=true 时）         │
│  第四道: Docker 容器沙箱（--memory=512m --network none ...）  │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  领域模板层（管科核心壁垒）                                   │
│  ┌──────────────────────┐ ┌──────────────────────────────┐ │
│  │ 数据分析管道          │ │ 供应链优化                   │ │
│  │ • data_quality       │ │ • inventory_eoq (EOQ)       │ │
│  │ • chart_templates    │ │ • safety_stock              │ │
│  │ • text_to_sql        │ │ • demand_forecast           │ │
│  │ • data_analysis(一键) │ │                              │ │
│  └──────────────────────┘ └──────────────────────────────┘ │
│  使用 Pandas / Plotly / DuckDB / OR-Tools / PuLP / Scipy   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  LLM 后端 (可切换)                                           │
│  DeepSeek-chat（开发）+ 规则回退（LLM 不可用时）             │
│  调用节点: Planner / Coder / Debugger                       │
│  temperature: 0.3（Planner/Coder） / 0.1（Text-to-SQL）     │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、接口契约（State TypedDict）

```python
class AgentState(TypedDict):
    user_query: str           # 用户原始需求
    workspace_path: str       # 工作区绝对路径
    plan: List[str]          # 执行计划（Planner输出）
    generated_code: str      # 生成的Python代码（Coder输出）
    file_path: Optional[str] # 临时执行文件路径（Executor输出）
    execution_result: Optional[str]  # stdout（Executor输出）
    error: Optional[str]     # stderr / 异常信息（Executor输出）
    retry_count: int         # 当前重试次数（初始0，上限2）
    human_feedback: Optional[str]  # 人在回路反馈：
                                   # "AI_FIX:<code>" / "USER_FIX:<指令>" / "SKIP" / "ABORT"
    final_report: Optional[str]    # Markdown格式报告（Reporter输出）
```

**关键约束**：
- `retry_count >= 2` 时强制进入 Reporter，不再循环（Debugger 入口上限检查）
- `human_feedback == "ABORT"` 时 Reporter 生成失败报告（fail_*.md）
- 所有节点返回 partial state，LangGraph 自动合并
- Executor 执行时注入 `PYTHONPATH` 指向项目根目录，确保生成的代码能 `from src.domain.xxx import ...`

### 状态流转

```
Planner → Coder → Executor → [条件路由]
                                ├─ 有 error 且非 ABORT → Debugger → [条件路由]
                                │                              ├─ 非 ABORT → Coder（循环）
                                │                              └─ ABORT → Reporter
                                └─ 无 error 或 ABORT → Reporter → END
```

### 路由规则

| 路由函数 | 条件 | 返回 |
|----------|------|------|
| `route_after_executor` | error 存在 且 human_feedback != "ABORT" | "debug" |
| `route_after_executor` | 否则 | "report" |
| `route_after_debugger` | human_feedback == "ABORT" | "report" |
| `route_after_debugger` | 否则 | "code"（回到 Coder） |

---

## 四、阶段规划

### Week 1：骨架 + 基础闭环 ✅
- [x] State定义 + Graph编译通过
- [x] Planner：任务拆解为步骤列表
- [x] Coder：生成可执行Python代码
- [x] Executor：subprocess执行，30秒超时，捕获stdout/stderr
- [x] Router：根据error和human_feedback路由
- [x] Debugger：分析错误 + 人类选择（1接受/2指令/3跳过/4中止）
- [x] Reporter：生成Markdown报告，写入reports/
- **验收**：3个任务完整闭环，55个测试全部通过 ✅

### Week 2：沙箱安全 + 调试稳定 ✅
- [x] MCP工具封装（FastMCP + 8个 Tool 注册）
- [x] Docker沙箱执行（DockerRunner 类 + 资源限制 + 网络隔离 + 只读文件系统）
- [x] AST 语法级安全检查（security_checker.py，替代字符串匹配）
- [x] 资源限制（--memory=512m --cpus=1.0 --pids-limit=64 --read-only）
- [x] Debugger 增强：规则回退 12→14 种错误类型 + DuckDB 错误分类
- [x] retry_count 上限强制 ABORT → fail_*.md 失败报告
- [x] 日志系统（loguru 双通道 debug.log + error.log，rotation + compression）
- [x] Executor 双路径：subprocess（默认）/ MCP Client（USE_MCP=true）/ Docker（USE_DOCKER=true）
- **验收**：危险代码被多层拦截、死循环30s超时、OOM bomb returncode=137，144个测试全部通过 ✅

### Week 3：数据分析能力 ✅
- [x] File Tool支持CSV/Excel结构化读取 + 类型推断（5种规则）
- [x] 数据质量检查（缺失值/异常值IQR/类型冲突/重复行 + 0-100评分引擎）
- [x] EDA自动生成（数值describe + 类别unique_count/mode + 规则化结论）
- [x] 可视化图表生成（5种Plotly交互式HTML图表，解决Matplotlib中文乱码）
- [x] 自然语言问数（Text-to-SQL via DuckDB + 11种危险SQL拦截）
- [x] 一键数据分析模板（run_analysis: 读取→质量→EDA→图表→报告 7步闭环）
- **验收**：E2E 6/6 通过，255个测试全部通过，3个分析任务全部一次成功（retry_count=0） ✅

### Week 4：领域模板（核心差异化）
- [ ] 模板匹配器：识别用户意图 → 匹配预定义模板
- [ ] 模板1：需求预测（移动平均/指数平滑）— 已有骨架 `demand_forecast.py`
- [ ] 模板2：安全库存计算（服务水平法）— 已有骨架 `safety_stock.py`
- [ ] 模板3：EOQ经济订货批量 — 已实现 `inventory_eoq.py`
- [ ] 模板4：补货点计算
- [ ] 参数提取：从自然语言中提取模板参数
- **验收**：输入"年需求1000，订货成本50，持有成本2"，输出EOQ=223.6

### Week 5：场景集成 + 完整闭环
- [ ] 多节点协作：Explorer → Analyst → Optimizer → Reviewer
- [ ] 供应链库存场景：数据读取→预测→优化→报告
- [ ] 报告增强：包含假设、局限性、业务建议
- [ ] 测试用例生成（pytest）
- **验收**：一个完整Demo任务，从输入到报告，人类干预不超过2次

### Week 6：CLI美化 + 评测
- [ ] Rich终端UI（进度条、面板、表格）
- [ ] 10个任务Benchmark（5数据分析 + 5代码生成）
- [ ] 指标：完成率、运行成功率、平均重试次数
- **验收**：能展示数字（如"代码运行成功率80%"）

### Week 7-8：工程化 + 面试准备
- [ ] Docker Compose部署
- [ ] README + 架构图（Mermaid）
- [ ] 3分钟Demo视频
- [ ] 简历优化
- **验收**：GitHub项目可克隆、可运行、可演示

---

## 五、设计决策记录（Decision Log）

| 日期 | 决策 | 原因 | 可能风险 |
|------|------|------|---------|
| 2026-06-21 | 使用LangGraph而非CrewAI | 状态机更可控，适合调试循环 | 学习曲线稍陡 |
| 2026-06-21 | 人在回路而非全自动修复 | 演示稳定性优先，符合企业安全需求 | 交互体验稍慢 |
| 2026-06-21 | MCP协议封装工具层 | 2026最热招聘关键词，可扩展性强 | 需要理解MCP SDK |
| 2026-06-21 | 优化模板化而非自由建模 | 保证正确率，体现领域知识 | 灵活性降低 |
| 2026-06-21 | RAG推迟到V3 | 先用结构化Prompt，降低初期复杂度 | 知识检索能力弱于完整RAG |
| 2026-06-23 | AST语法级安全检查替代字符串匹配 | 精确识别变形写法，放行合法open() | 误杀概率极低 |
| 2026-06-23 | Executor MCP集成双路径架构 | USE_MCP默认false向后兼容，不可用时回退subprocess | 双路径代码维护成本 |
| 2026-06-30 | Docker沙箱作为第二道安全防线 | --memory=512m --cpus=1.0 --read-only --network none | Docker依赖 |
| 2026-06-30 | Debugger规则回退12→14种错误类型 | LLM不可用时保证可用性，增加DuckDB错误分类 | 规则刚性 |
| 2026-07-06 | Plotly 替代 Matplotlib | 中文乱码根本解决（浏览器端渲染 vs 服务端字体），交互式 HTML 体验更好 | HTML文件大（~5MB），CDN依赖 |
| 2026-07-06 | DuckDB 作为 Text-to-SQL 引擎 | 嵌入式零配置（pip install 即用），read_csv_auto 自动推断类型，pandas 互操作无缝 | LLM 可能生成幻觉列名 |
| 2026-07-06 | 结论引擎规则化（7条规则，0 LLM调用） | 零延迟、零成本、100% 可预测 | 无法理解业务语义 |
| 2026-07-06 | 领域模板分层：run_analysis 调用 run_quality_check + chart_templates | 模块化复用，不重复实现逻辑 | 模板间耦合通过函数调用 |
| 2026-07-06 | Executor subprocess PYTHONPATH 注入 | Coder 生成的 `from src.domain.xxx` 在 subprocess 中可用 | 环境隔离性弱于 Docker |
| 2026-07-06 | Coder Prompt 模板体系（4级优先级） | 全局分析→run_analysis，单一质量→run_quality_check，单一图表→chart_templates，单一问数→run_text_to_sql | LLM 可能选错模板 |

---

## 六、踩坑记录（Trouble Log）

| 日期 | 问题 | 现象 | 解决方案 | 状态 |
|------|------|------|---------|------|
| 2026-06-21 | 生成初始依赖环境时，生成具体代码 | AI 直接写实现而非创建骨架 | 明确告诉 AI 先不要生成具体代码，只创建文件 | ✅ |
| 2026-06-22 | Matplotlib中文乱码 | 图表中文显示为方块 | Week 3 统一改用 Plotly（浏览器端渲染），彻底解决 | ✅ |
| 2026-06-22 | 临时文件路径在系统 Temp 而非 workspace/src/ | 调试不便 | Week 2 Docker沙箱时统一处理，保留在 workspace/src/ 便于调试 | ✅ |
| 2026-06-22 | Coder Prompt 禁止 try/except 后又要求添加 | 异常被吞掉，Debugger 不触发 | Prompt 明确：只生成纯业务逻辑代码，异常由上层处理 | ✅ |
| 2026-06-23 | sys.executable 问题 | subprocess 调用系统 Python 而非虚拟环境 | 全部改用 `sys.executable` | ✅ |
| 2026-06-23 | BLOCKED_KEYWORDS 包含 "open(" 误杀合法文件操作 | 所有文件读写被拦截 | 改用 AST 语法级分析，精确识别危险调用，放行 open() | ✅ |
| 2026-06-23 | MCP Server stdio transport 导致子进程 hang（Windows） | subprocess.run 继承 transport pipe | 所有 subprocess.run 添加 `stdin=subprocess.DEVNULL` | ✅ |
| 2026-06-30 | Docker 镜像 scipy 编译失败 | 缺少 gcc/g++/make | Dockerfile 新增 `apt-get install gcc g++ make` | ✅ |
| 2026-06-30 | --pids-limit 在某些 Docker 版本不支持 | 容器启动报 unknown flag | DockerRunner 实现 graceful fallback（flag_levels 循环） | ✅ |
| 2026-06-30 | OOM Kill 后 stdout/stderr 为空 | 无法从输出判断 OOM | 依赖 returncode=137 信号 + DockerRunner 追加 [OOM Killed] | ✅ |
| 2026-07-04 | .env 在 graph.invoke() 直接调用时不自动加载 | DEEPSEEK_API_KEY 未设置 | 测试脚本显式 `load_dotenv()`（Week 2 坑6） | ✅ |
| 2026-07-04 | 回退代码 f-string 转义 bug | `{{query}}` 输出字面量而非变量 | 改为单花括号 `{query}`（普通字符串中无需转义） | ✅ |
| 2026-07-06 | pandas 3.0 StringDtype | str(dtype)="str" 而非 "object" | 判断扩展为 `in ("object", "str") or startswith("str")` | ✅ |
| 2026-07-06 | pandas 3.0 infer_objects(copy=False) deprecation | copy 参数已废弃 | 改为无参 `infer_objects()` | ✅ |
| 2026-07-06 | Windows Excel 文件锁 | pd.ExcelFile 未 close 导致 teardown 锁文件 | try/finally 确保 ExcelFile.close() | ✅ |
| 2026-07-06 | Coder 生成 `from src.domain.xxx import` 在 subprocess 中 ModuleNotFoundError | E2E 4/4 任务全部失败，No module named 'src' | Executor 注入 PYTHONPATH 指向项目根目录 | ✅ |
| 2026-07-06 | pandas df.to_markdown() 依赖 tabulate 包 | ModuleNotFoundError: No module named 'tabulate' | 手动构建 Markdown 表格（遍历列+行），消除额外依赖 | ✅ |
| 2026-07-06 | DuckDB 列不存在抛 BinderException 而非 CatalogException | 测试断言用错了异常类型 | CatalogException=表不存在，BinderException=列不存在，Debugger同时覆盖 | ✅ |

---

## 七、文件组织规范

```
decision-coder/
├── pyproject.toml                    # 依赖管理（9个运行时 + 2个dev）
├── .env                              # API密钥（不提交git）
├── .env.example                      # 环境变量模板
├── .gitignore
├── Dockerfile                        # Docker沙箱镜像（python:3.11-slim + 中文字体）
├── main.py                           # CLI 入口（交互式主程序）
├── README.md                         # 对外项目介绍
├── CLAUDE.md                         # Claude Code 项目指南
├── DEV_DESIGN.md                     # 本文件（面向自己）
├── DEV_LOG.md                        # 每日开发日志
├── promps/                           # Week 开发提示词（参考文档）
│   └── Week3_开发提示词.md
├── src/
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py                  # LangGraph 状态机组装 + build_graph() + run()
│   │   ├── state.py                  # AgentState TypedDict 定义
│   │   ├── logger_config.py          # loguru 统一配置（双通道 + rotation + compression）
│   │   ├── sandbox/
│   │   │   ├── __init__.py
│   │   │   ├── security_checker.py   # AST 语法级安全检查（5种危险模式 + 属性链识别）
│   │   │   └── docker_runner.py      # Docker 容器沙箱执行器（资源限制 + 网络隔离 + OOM检测）
│   │   └── nodes/
│   │       ├── __init__.py
│   │       ├── planner.py            # Planner：DeepSeek API 拆解需求为 ≤5 步
│   │       ├── coder.py              # Coder：DeepSeek API 生成代码 + 安全检查 + 回退代码
│   │       ├── executor.py           # Executor：subprocess/MCP/Docker 三路径沙箱执行
│   │       ├── debugger.py           # Debugger：14种规则错误分类 + LLM分析 + Human-in-the-loop
│   │       ├── reporter.py           # Reporter：Markdown 报告生成（报告/失败）+ 图表检测
│   │       └── prompts/              # 提示词管理（已外置）
│   │           ├── __init__.py
│   │           ├── loader.py         # load_prompt() 从 disk 读取 .md（@lru_cache 缓存）
│   │           ├── planner.md        # Planner 系统约束（含4个分析示例）
│   │           ├── planner_user.py   # Planner 用户消息 builder
│   │           ├── coder.md          # Coder 系统约束（含4级模板优先级）
│   │           ├── coder_user.py     # Coder 用户消息 builder
│   │           ├── debugger_analysis.md  # Debugger 错误分析系统提示
│   │           ├── debugger_fix.md       # Debugger 代码修复系统提示
│   │           └── debugger_user.py      # Debugger 用户消息 builders
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py                 # FastMCP 服务端（8个Tool注册 + stdio transport）
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── file_tools.py         # 文件读写工具（路径安全 + 二进制检测 + CSV/Excel增强）
│   │       ├── file_tools.py         # 6个Tool: file_read / file_write / file_read_csv / file_read_csv_legacy / file_read_excel / file_list_dir / file_exists
│   │       ├── python_tools.py       # Python 沙箱执行（AST安全检查 + compile预检 + 保留临时文件）
│   │       └── data_utils.py         # 类型推断辅助（5种规则: datetime/percentage/mixed/generic）
│   └── domain/
│       ├── __init__.py               # 领域层统一导出（8个符号: run_quality_check + 5图表 + run_text_to_sql）
│       ├── schema.py                 # 领域数据模型
│       ├── data_quality.py           # 数据质量检测引擎（4维度检测 + 0-100评分 + 中文建议）
│       ├── chart_templates.py        # Plotly 图表模板（5种: bar/line/histogram/scatter/heatmap）
│       ├── text_to_sql.py            # Text-to-SQL 引擎（Schema提取→LLM SQL→安全检查→DuckDB执行）
│       └── templates/                # 预定义领域模板
│           ├── __init__.py
│           ├── inventory_eoq.py      # EOQ 经济订货批量（calculate函数，已实现）
│           ├── safety_stock.py       # 安全库存计算（骨架）
│           ├── demand_forecast.py    # 需求预测（骨架）
│           └── data_analysis.py      # 一键数据分析（7步流水线 + 5章节报告 + 规则结论）
├── tests/                            # 项目级测试（18个文件，249用例）
│   ├── __init__.py
│   ├── test_planner.py               # 1 场景
│   ├── test_coder.py                 # 10 场景（结构/边界/执行/安全/AI_FIX）
│   ├── test_executor.py              # 14 场景（执行/超时/安全/文件/错误处理）
│   ├── test_debugger.py              # 16 场景（4种选择/回退/修复/边界/格式）
│   ├── test_debugger_enhanced.py     # 28 场景（诊断/修复/提取函数/DuckDB错误）
│   ├── test_reporter.py              # 10 场景（成功/中止/错误/文件/格式/幂等）
│   ├── test_graph.py                 # 11 场景（编译/节点/边/路由/完整流程/线程隔离）
│   ├── test_security.py              # 7 场景（5种危险 + 2种安全）
│   ├── test_abort_flow.py            # 6 场景（retry限制/ABORT报告/文件名/端到端）
│   ├── test_docker_runner_security.py # 11 场景（DockerRunner安全检查集成）
│   ├── test_docker_mode_graph.py     # 3 场景（Docker模式Graph兼容性）
│   ├── test_file_tools.py            # 28 场景（CSV/Excel/安全/utils）
│   ├── test_data_quality.py          # 10 场景（正常/缺失/异常/混合/重复/空/真实数据）
│   ├── test_chart_templates.py       # 18 场景（5种图表 + 空/单行/大数据/中文/边界）
│   ├── test_text_to_sql.py           # 30 场景（Schema/SQL安全/清理/执行/端到端/中文列名）
│   ├── test_data_analysis_template.py # 19 场景（黄金路径/脏数据/空/中文/检测函数/结论）
│   └── test_e2e_week3.py             # 6 场景（分析/图表/问数/质量检查/边界）
├── workspace/                        # 工作区（不提交git）
│   ├── data/                         # 用户数据文件
│   │   ├── sales.csv                 # 120行销售数据（含缺失值+异常值）
│   │   └── inventory.csv             # 55行库存数据
│   ├── src/                          # Agent 生成的临时代码文件（_dc_exec_*.py）
│   ├── reports/                      # 生成的 Markdown 报告 + HTML 图表
│   │   ├── report_*.md               # 成功报告
│   │   ├── fail_*.md                 # 失败/中止报告
│   │   ├── analysis_*.md             # 一键分析报告
│   │   └── charts/                   # Plotly HTML 图表
│   ├── output/                       # 执行输出
│   └── tests/                        # 工作区测试脚本
├── examples/                         # Demo 示例
├── docs/                             # 文档
└── logs/                             # 日志文件（不提交git）
    ├── debug.log                     # DEBUG+ 级别（按天轮转，zip压缩，保留7天）
    └── error.log                     # ERROR+ 级别（同上）
```

---

## 八、LLM使用策略

| 阶段 | 模型 | 用途 | temperature | 成本预估 |
|------|------|------|-------------|---------|
| Planner | DeepSeek-chat | 任务拆解为步骤列表 | 0.3 | ~0.1元/千token |
| Coder | DeepSeek-chat | 代码生成 + SQL生成 | 0.3（常规）/ 0.1（SQL） | ~0.1元/千token |
| Debugger(分析) | DeepSeek-chat | 错误原因分析 | 0.3 | ~0.1元/千token |
| Debugger(修复) | DeepSeek-chat | 基于指令修复代码 | 0.3 | ~0.1元/千token |
| 结论引擎 | ❌ 规则化 | if-else 生成中文结论 | — | 免费 |
| 图表渲染 | ❌ 浏览器端 | Plotly JS CDN | — | 免费 |
| 日常开发 | Claude / DeepSeek | 代码生成、调试、文档 | — | — |

### LLM 调用节点汇总

| 节点 | 调用位置 | 调用次数/次流程 | 回退策略 |
|------|---------|---------------|---------|
| Planner | `_generate_plan_with_llm()` | 1 | plan=["错误：Planner 调用失败"] |
| Coder | `_generate_code_with_llm()` | 1（非AI_FIX路径）| 回退安全代码 `_generate_fallback_code()` |
| Debugger | `_analyze_error_with_llm()` | 1（非retry>=2时）| `_diagnose_by_rule()` 14种规则 |
| Debugger | `_generate_fix_with_llm()` | 0-1（选项1/2时）| `_fix_by_rule()` 规则修复 |
| Text-to-SQL | `_call_llm_for_sql()` | 0-1（问数时）| 抛 ValueError |

---

## 九、安全纵深防御体系

```
第零道防线：LLM 语义识别（Planner）
  └─ DeepSeek 在语义层面识别并拒绝危险意图

第一道防线：AST 安全检查（Coder._has_dangerous_code）
  └─ 代码生成后立即检查：os.system / subprocess.* / eval / exec / __import__ / compile

第二道防线：Executor 执行前预检
  └─ 空代码 → 危险代码(AST) → 语法预检(compile) → 写入文件

第三道防线：DockerRunner AST 兜底检查（USE_DOCKER=true 时）
  └─ 落地执行前再次调用 check_code_safety()

第四道防线：Docker 容器沙箱
  └─ --memory=512m --cpus=1.0 --pids-limit=64 --read-only --network none

SQL 安全防线（Text-to-SQL）：
  └─ 第一道：LLM System Prompt 约束"只生成 SELECT"
  └─ 第二道：11种危险关键字正则匹配 + SELECT-only 前缀检查
```

---

## 十、面试叙事要点（提前准备）

### 项目动机
> 通用Coding Agent在处理经营决策类任务时缺少领域知识和可验证的执行闭环。我构建了一个面向供应链库存优化的垂直Agent，能真正读数据、写代码、运行调试，并输出可落地的决策建议。

### 技术亮点
1. **MCP协议**：工具层基于 FastMCP 封装8个标准化 Tool，支持 stdio transport
2. **LangGraph状态机**：Plan-Code-Execute-Debug-Report 闭环，2个条件路由，支持循环调试
3. **Human-in-the-loop**：14种规则错误分类 + LLM分析 + 4种人类选择，retry_count上限强制ABORT
4. **领域模板体系**：一键分析（数据质量+EDA+图表+报告）、Text-to-SQL（自然语言→DuckDB SQL）、5种Plotly图表模板
5. **沙箱安全**：5道纵深防线（LLM语义→AST检查→执行前预检→DockerRunner兜底→Docker容器隔离）
6. **结论引擎规则化**：7条if-else规则生成中文结论，零LLM调用、零延迟、100%可预测

### 数字指标（Week 3 实际数据）
- 代码运行成功率：**100%**（E2E 4/4 任务全部一次成功，retry_count=0）
- 测试通过率：**100%**（255/255，零回归）
- 平均重试次数：**0**（E2E 无 Debugger 触发）
- 任务完成率：**100%**
- 图表生成成功率：**100%**（18单元 + 1 E2E）
- SQL 安全检查拦截率：**100%**（11种危险模式全拦截）
- 累计测试数：**255**（Week1: 55 → Week2: 144 → Week3: 255）

### Week 1 → Week 3 架构演进

| 维度 | Week 1 | Week 2 | Week 3 |
|------|--------|--------|--------|
| 执行方式 | subprocess | subprocess / MCP / Docker 三选一 | 同 Week 2 + PYTHONPATH 注入 |
| 安全检查 | 字符串匹配（2套规则） | AST 语法级分析（统一） | 同 Week 2 + SQL 正则安全 |
| 工具层 | 纯 Python 函数 | MCP 协议（6 Tool） | MCP 协议（8 Tool） |
| 沙箱隔离 | 仅 subprocess 超时 | Docker 容器 5 维限制 | 同 Week 2 |
| 日志系统 | print() | loguru 双通道 + rotation + compression | 同 Week 2 |
| 错误诊断 | 6 种规则 | 14 种规则 + DuckDB 分类 | 同 Week 2 |
| 报告类型 | 单一 report_*.md | report_*.md / fail_*.md | 同 Week 2 + 图表链接检测 |
| 数据能力 | 无 | 无 | 质量检查 + 5图表 + Text-to-SQL + 一键分析 |
| 依赖库 | 5个 | 6个 | 9个（+plotly +duckdb +openpyxl） |
| 测试数 | 55 | 144 | **255** |

---

## 十一、Week 3 领域模板层 API 参考

### 数据质量检查

```python
from src.domain.data_quality import run_quality_check
report = run_quality_check(df)  # → dict: overall_score, columns[], recommendations[]
```

### 图表生成（5种，统一签名）

```python
from src.domain.chart_templates import bar_chart, line_chart, histogram_chart, scatter_chart, heatmap_chart
path = bar_chart(df, x_col="区域", y_col="销量", title="标题", output_path="reports/charts/xxx.html")
```

### Text-to-SQL

```python
from src.domain.text_to_sql import run_text_to_sql
result = run_text_to_sql("各区域平均销量？", "data/sales.csv")
# → {"sql": "SELECT ...", "columns": [...], "rows": [...], "row_count": N, "summary": "..."}
```

### 一键数据分析

```python
from src.domain.templates.data_analysis import run_analysis
report_path = run_analysis("data/sales.csv", output_dir="reports/")
# → reports/analysis_YYYYMMDD_HHMMSS.md（5章节完整报告）
```

### EOQ 经济订货批量

```python
from src.domain.templates.inventory_eoq import calculate, EOQParams
result = calculate(EOQParams(annual_demand=1000, ordering_cost=50, holding_cost=2))
# → EOQResult(eoq=223.61, ...)
```

### MCP Tools（8个）

| Tool 名称 | 功能 |
|-----------|------|
| `file_read` | 读文本文件（路径安全校验 + 二进制检测） |
| `file_write` | 写文本文件（overwrite 保护） |
| `file_read_csv` | CSV 增强读取（类型推断 + 缺失值 + preview） |
| `file_read_csv_legacy` | CSV 简单读取（向后兼容） |
| `file_read_excel` | Excel 读取（sheet 选择 + 安全校验） |
| `file_list_dir` | 列出目录内容 |
| `file_exists` | 检查文件是否存在 |
| `python_exec` | Python 沙箱执行（AST 安全 + compile 预检） |

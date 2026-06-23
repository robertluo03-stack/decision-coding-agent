# DecisionCoder — 开发设计文档

> **面向自己**：这份文档会随着开发不断修改，记录设计决策、接口变更和踩坑记录。
> **版本**：v0.1 | **日期**：2026-06-21 | **当前阶段**：Week 1 骨架搭建

---

## 一、项目定位（一句话）

**DecisionCoder** 是一个面向经营决策与运筹优化场景的垂直 Coding Agent，基于 MCP 协议构建工具层，使用 LangGraph 编排 Plan-Code-Execute-Debug-Report 闭环，支持 Human-in-the-loop 调试。

---

## 二、核心架构

```
┌─────────────────────────────────────────────────────────────┐
│  交互层 (CLI / Streamlit)                                    │
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
│  │ - AI分析错误原因                      │                   │
│  │ - 人类选择：接受修复 / 输入指令 / 跳过 / 中止 │          │
│  └──────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  工具层 (MCP Protocol)                                       │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐ │
│  │File I/O │ │Python Exec│ │Shell     │ │Optimization     │ │
│  │(文件读写)│ │(沙箱执行)  │ │(受限命令) │ │(OR-Tools/PuLP)  │ │
│  └─────────┘ └──────────┘ └──────────┘ └─────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────┐
│  领域模板层（管科核心壁垒）                   │
│  需求预测 │ 安全库存 │ EOQ │ 补货点 │ ABC    │
│  使用 OR-Tools / PuLP / Scipy               │
└─────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  LLM 后端 (可切换)                                           │
│  DeepSeek-V3 (开发) / Claude 3.5 Sonnet (演示)              │
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
- `retry_count >= 2` 时强制进入 Reporter，不再循环
- `human_feedback == "ABORT"` 时 Reporter 生成失败报告
- 所有节点必须返回完整的 `AgentState` 子集（不能只返回修改的字段）

---

## 四、阶段规划（务实版）

### Week 1：骨架 + 基础闭环
- [ ] State定义 + Graph编译通过
- [ ] Planner：任务拆解为步骤列表
- [ ] Coder：生成可执行Python代码
- [ ] Executor：subprocess执行，30秒超时，捕获stdout/stderr
- [ ] Router：根据error和human_feedback路由
- [ ] Debugger：分析错误 + 人类选择（1接受/2指令/3跳过/4中止）
- [ ] Reporter：生成Markdown报告，写入reports/
- **验收**：输入3个不同任务，能走完完整流程，至少1个成功执行

### Week 2：沙箱安全 + 调试稳定
- [ ] MCP工具封装（把现有File/Executor工具升级为MCP Server）
- [ ] Docker沙箱执行（替代裸subprocess）
- [ ] 命令白名单 + 网络隔离
- [ ] 资源限制（CPU/内存/磁盘）
- [ ] 调试节点稳定性：连续3次错误后强制退出
- [ ] 日志系统（loguru，记录每个节点的输入输出）
- **验收**：故意输入危险代码（rm -rf /），确认被拦截；故意输入死循环，确认30秒终止

### Week 3：数据分析能力
- [ ] File Tool支持CSV/Excel读取
- [ ] 数据质量检查（缺失值、异常值、类型推断）
- [ ] EDA自动生成（统计摘要、分布分析）
- [ ] 可视化图表生成（Plotly/Matplotlib）
- [ ] 自然语言问数（Text-to-SQL via DuckDB）
- **验收**：用真实销售数据跑通"读取→分析→图表→报告"全流程

### Week 4：领域模板（核心差异化）
- [ ] 模板匹配器：识别用户意图 → 匹配预定义模板
- [ ] 模板1：需求预测（移动平均/指数平滑）
- [ ] 模板2：安全库存计算（服务水平法）
- [ ] 模板3：EOQ经济订货批量
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

---

## 六、踩坑记录（Trouble Log）

> 开发过程中遇到的问题和解决方案，持续更新。

| 日期 | 问题 | 现象 | 解决方案 | 状态 |
|------|------|------|---------|------|
| 20260621| 生成初始依赖环境时，生成具体的代码| |要明确告诉ai先不要生成具体代码，只创建文件| |
| 20260622| Matplotlib中文乱码| |最终演示前统一处理（换字体或改用Plotly）| |
| 20260622| 测试输出中临时文件路径是系统Temp目录下的子目录，而不是workspace/src/| |临时文件路径待统一，"Week 2做Docker沙箱时一并处理| |
Coder异常吞掉问题（已修复：Prompt禁止try/except）
sys.executable问题（subprocess调用虚拟环境Python）
---

## 七、文件组织规范

```
decision-coder/
├── pyproject.toml              # 依赖管理
├── .env                        # API密钥（不提交git）
├── .env.example                # 环境变量模板
├── .gitignore
├── main.py                     # CLI 入口（交互式主程序）
├── README.md                   # 对外项目介绍
├── CLAUDE.md                   # Claude Code 项目指南
├── DEV_DESIGN.md               # 本文件（面向自己）
├── DEV_LOG.md                  # 每日开发日志
├── src/
│   ├── agent/
│   │   ├── graph.py            # LangGraph 状态机组装 + run() 便捷入口
│   │   ├── state.py            # AgentState TypedDict 定义
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── planner.py      # Planner：需求拆解为步骤列表
│   │   │   ├── coder.py        # Coder：生成可执行 Python 代码
│   │   │   ├── executor.py     # Executor：subprocess 沙箱执行
│   │   │   ├── debugger.py     # Debugger：AI 分析 + Human-in-the-loop
│   │   │   ├── reporter.py     # Reporter：生成 Markdown 报告
│   │   │   └── prompts/        # 提示词管理（已外置）
│   │   │       ├── __init__.py
│   │   │       ├── loader.py             # load_prompt() 从 disk 读取 .md
│   │   │       ├── planner.md            # Planner 系统约束（静态 .md）
│   │   │       ├── planner_user.py       # Planner 用户消息 builder
│   │   │       ├── coder.md              # Coder 系统约束（静态 .md）
│   │   │       ├── coder_user.py         # Coder 用户消息 builder
│   │   │       ├── debugger_analysis.md  # Debugger 错误分析提示
│   │   │       ├── debugger_fix.md       # Debugger 代码修复提示
│   │   │       └── debugger_user.py      # Debugger 用户消息 builders
│   ├── mcp/
│   │   ├── server.py           # MCP 服务端入口
│   │   └── tools/
│   │       ├── file_tools.py   # 文件读写工具
│   │       └── python_tools.py # Python 沙箱执行工具
│   ├── domain/
│   │   ├── schema.py           # 领域数据模型
│   │   └── templates/          # 预定义优化模板
│   │       ├── inventory_eoq.py     # EOQ 经济订货批量
│   │       ├── safety_stock.py      # 安全库存计算
│   │       └── demand_forecast.py   # 需求预测
│   └── workspace/              # 工作区（不提交git）
│       ├── data/               # 用户数据文件
│       ├── src/                # Agent 生成的代码文件
│       ├── reports/            # 生成的 Markdown 报告
│       └── tests/              # 生成的测试文件
├── tests/                      # 项目级测试
│   ├── test_planner.py
│   ├── test_coder.py
│   ├── test_executor.py
│   ├── test_debugger.py
│   ├── test_reporter.py
│   └── test_graph.py
├── examples/                   # Demo 示例
└── docs/                       # 文档
```

---

## 八、LLM使用策略

| 阶段 | 模型 | 用途 | 成本预估 |
|------|------|------|---------|
| 日常开发 | DeepSeek-V4-pro | 代码生成、调试 | ~0.1元/千token |
| 文档撰写 | Kimi | 中文文档、Prompt优化 | 免费额度 |

---

## 九、面试叙事要点（提前准备）

### 项目动机
> 通用Coding Agent在处理经营决策类任务时缺少领域知识和可验证的执行闭环。我构建了一个面向供应链库存优化的垂直Agent，能真正读数据、写代码、运行调试，并输出可落地的决策建议。

### 技术亮点
1. **MCP协议**：工具层基于MCP封装，支持标准化扩展
2. **LangGraph状态机**：Plan-Code-Execute-Debug-Report闭环，条件分支可控
3. **Human-in-the-loop**：错误分析+人类确认，符合企业安全合规
4. **领域模板**：预定义EOQ/安全库存/需求预测模板，保证优化正确性
5. **沙箱安全**：Docker隔离+超时机制+资源限制

### 数字指标（完成后填写）
- 代码运行成功率：__%
- 测试通过率：__%
- 平均重试次数：__
- 任务完成率：__%

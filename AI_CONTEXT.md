# AI_CONTEXT — 项目上下文（给 Claude Code / Kimi Code 看）

> **用途**：放在项目根目录，每次让AI写代码前，先让它读取此文件，确保理解项目架构和约束。

---

## 项目概述

**DecisionCoder** 是一个面向经营决策与运筹优化场景的垂直 Coding Agent。

- **核心能力**：接收自然语言需求 → 自动规划 → 生成Python代码 → 沙箱执行 → 错误调试 → 生成报告
- **技术栈**：Python 3.11+, LangGraph, MCP, DeepSeek/Claude/GPT, Docker
- **目标用户**：管理科学与工程领域的分析师（供应链、库存、排产）
- **当前阶段**：Week 1 骨架搭建（Plan-Code-Execute-Debug-Report 基础闭环）

---

## 架构约束（必须遵守）

### 1. Agent状态机（LangGraph）

```
Planner → Coder → Executor → Router → [Debug → Coder] → Reporter
```

- **Planner**：将用户需求拆解为步骤列表（`List[str]`）
- **Coder**：生成完整可执行的Python代码（`str`）
- **Executor**：用subprocess/Docker执行代码，30秒超时，捕获stdout/stderr
- **Router**：根据`error`和`human_feedback`决定下一步
  - 有error且未中止 → Debug
  - 无error或已中止 → Reporter
- **Debugger**：AI分析错误，人类选择（1接受AI修复/2输入指令/3跳过/4中止）
- **Reporter**：生成Markdown报告，写入`workspace/reports/`

### 2. 状态定义（TypedDict）

所有节点必须返回完整的`AgentState`子集：

```python
class AgentState(TypedDict):
    user_query: str
    workspace_path: str
    plan: List[str]
    generated_code: str
    file_path: Optional[str]
    execution_result: Optional[str]
    error: Optional[str]
    retry_count: int          # 上限2，超限强制进入Reporter
    human_feedback: Optional[str]  # "AI_FIX" / "USER_FIX" / "SKIP" / "ABORT"
    final_report: Optional[str]
```

### 3. MCP工具层

所有工具必须通过MCP协议封装，当前阶段实现：
- `read_file(path)`：读取工作区文件
- `write_file(path, content)`：写入工作区文件
- `list_files(directory)`：列出目录
- `execute_python(code)`：沙箱执行Python代码（30秒超时）

### 4. 工作区约定

```
workspace/
├── data/          # 用户数据（CSV/Excel）
├── src/           # Agent生成的代码文件
├── reports/       # 生成的Markdown报告和图表
└── tests/         # 生成的pytest测试文件
```

- 所有文件操作必须在`workspace_path`下进行
- 禁止访问`workspace`以外的目录
- 禁止网络请求（沙箱隔离）

### 5. 代码风格

- Python 3.11+ 语法
- 类型注解：所有函数必须有参数和返回类型注解
- 错误处理：使用try/except，错误信息必须传递给`state["error"]`
- 日志：使用loguru（如已安装）或print，关键节点必须打印状态
- 注释：英文注释，函数docstring用中文
- 依赖：新增依赖必须写入`pyproject.toml`，禁止随意引入重量级库

---

## 当前阶段任务（Week 1）

### 已实现
- [ ] 项目目录结构
- [ ] 虚拟环境配置
- [ ] `pyproject.toml` 基础依赖

### 待实现（按优先级）
1. `src/agent/state.py` — AgentState TypedDict定义
2. `src/agent/nodes/planner.py` — 任务拆解节点
3. `src/agent/nodes/coder.py` — 代码生成节点
4. `src/agent/nodes/executor.py` — 沙箱执行节点
5. `src/agent/nodes/debugger.py` — 人在回路调试节点
6. `src/agent/nodes/reporter.py` — 报告生成节点
7. `src/agent/graph.py` — LangGraph状态机组装
8. `src/mcp/tools/file_tools.py` — MCP文件工具
9. `src/mcp/tools/python_tools.py` — MCP Python执行工具
10. `main.py` — CLI入口

### 验收标准
- 输入3个不同任务，能走完完整流程
- 至少1个任务成功执行并生成报告
- 错误任务能进入Debugger节点，人类可干预

---

## 禁止事项

1. **不要引入未授权的依赖**：如PyTorch、Transformers、TensorFlow等重量级库
2. **不要修改State定义**：除非经过人工确认，所有节点必须兼容现有AgentState
3. **不要绕过沙箱**：execute_python必须通过subprocess/Docker，禁止eval/exec
4. **不要硬编码路径**：所有路径从`workspace_path`或环境变量读取
5. **不要生成破坏性代码**：Coder生成的代码禁止包含`rm -rf`、`os.system`、`subprocess`等系统调用

---

## 开发约定



### Prompt模板（给AI的指令格式）

```
## 任务
[具体功能，一句话]

## 输入
- 类型：[如 TypedDict / dict / str]
- 示例：[具体例子]

## 输出
- 类型：[如 dict / str / None]
- 示例：[具体例子]

## 约束
- [不要引入新依赖]
- [错误处理必须返回特定格式]
- [只修改指定文件]
- [必须兼容现有AgentState接口]

## 上下文
[粘贴相关已有代码，只给必要的部分]
```

---

## 项目关键词（简历/面试用）

LLM Agent, Coding Agent, MCP Protocol, LangGraph, Tool Calling, Function Calling, 
Human-in-the-loop, Python Sandbox, Docker, Data Analysis Agent, Operations Research, 
Inventory Optimization, OR-Tools, PuLP, ReAct, Multi-step Reasoning, Auto Debugging, 
FastAPI, Rich CLI, Streamlit, Pandas, Plotly

---

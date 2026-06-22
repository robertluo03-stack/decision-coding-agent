# Week 1 开发提示词集

> **使用说明**：每个任务独立使用，不要一次性给AI多个任务。每次使用前让AI先读取`AI_CONTEXT.md`。

---

## 任务 1：AgentState 定义

```markdown
## 任务
实现 `src/agent/state.py`，定义Agent状态机的TypedDict。

## 输入
无（纯类型定义）

## 输出
一个 `src/agent/state.py` 文件，包含 `AgentState` 类。

## 约束
- 使用 `typing.TypedDict` 和 `typing.Optional`
- 所有字段必须有类型注解
- 不要引入其他依赖
- 文件必须能通过 `python -m py_compile src/agent/state.py`

## 状态字段要求
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
    human_feedback: Optional[str]  # 人在回路反馈
    final_report: Optional[str]    # Markdown格式报告（Reporter输出）
```

## 上下文
本项目使用LangGraph作为Agent编排框架，StateGraph的状态类型就是AgentState。
每个Graph节点接收AgentState字典，返回修改后的子集。
```

---

## 任务 2：Planner 节点

```markdown
## 任务
实现 `src/agent/nodes/planner.py`，将用户需求拆解为可执行步骤列表。

## 输入
- `state["user_query"]`：str，例如 "读取data/sales.csv，统计每个sku的总销量"
- `state["workspace_path"]`：str，工作区路径

## 输出
- 返回字典：`{"plan": ["步骤1", "步骤2", ...]}`
- plan必须是字符串列表，每个元素是一个具体动作

## 约束
- 使用 DeepSeek API（`langchain_deepseek.ChatDeepSeek`）
- 模型用 "deepseek-chat"
- API Key从环境变量 `DEEPSEEK_API_KEY` 读取
- 步骤最多5个，必须具体可执行
- 如果用户query为空，返回plan=["错误：输入为空"]
- 不要在工作区读写文件，只返回plan

## 上下文
AgentState定义在 `src/agent/state.py` 中。

示例输入："读取data/sales.csv，统计每个sku的总销量，并画出柱状图"
示例输出：{"plan": ["读取data/sales.csv文件", "按sku分组统计总销量", "使用matplotlib绘制柱状图", "保存图表到reports/", "输出统计摘要"]}
```

---

## 任务 3：Coder 节点

```markdown
## 任务
实现 `src/agent/nodes/coder.py`，根据用户需求和执行计划生成可执行的Python代码。

## 输入
- `state["user_query"]`：str，用户原始需求
- `state["plan"]`：List[str]，执行计划
- `state["workspace_path"]`：str，工作区路径

## 输出
- 返回字典：`{"generated_code": "完整Python代码字符串"}`
- 代码必须是完整可执行的，包含所有import

## 约束
- 使用 DeepSeek API（`langchain_deepseek.ChatDeepSeek`）
- 代码必须假设数据文件在 `./data/` 目录下（相对于workspace_path）
- 输出结果必须用 `print()` 展示
- 只使用标准库 + pandas + numpy + matplotlib（假设已安装）
- 禁止生成 `os.system`、`subprocess`、`eval`、`exec` 等危险代码
- 如果plan为空或错误，生成一个打印错误信息的代码

## 上下文
AgentState定义在 `src/agent/state.py` 中。
Planner节点在 `src/agent/nodes/planner.py` 中。

## 测试要求：
1. 正常场景：输入"读取CSV统计销量"，验证生成的代码：
   - 包含import pandas
   - 包含print()输出
   - 不包含os.system/subprocess/eval/exec
   - 使用相对路径data/xxx
2. 边界场景：
   - plan为空列表时，代码是否优雅处理（打印错误信息而非崩溃）
   - user_query为空时，代码是否返回提示
3. 执行验证：
   - 把生成的代码写入临时文件，用subprocess执行
   - 验证是否为SyntaxError-free
   - 如果是数据分析任务，验证是否能读取测试数据并输出结果
4. 所有测试数据在脚本中自动生成（创建临时CSV）

示例输入：
- user_query: "读取data/sales.csv，统计每个sku的总销量"
- plan: ["读取data/sales.csv文件", "按sku分组统计总销量", "输出统计摘要"]

示例输出：
{"generated_code": "import pandas as pd\n\ndf = pd.read_csv('data/sales.csv')\nresult = df.groupby('sku')['qty'].sum()\nprint(result)\n"}
```

---

## 任务 4：Executor 节点

```markdown
## 任务
实现 `src/agent/nodes/executor.py`，安全执行生成的Python代码，捕获输出和错误。

## 输入
- `state["generated_code"]`：str，Python代码
- `state["workspace_path"]`：str，工作区路径

## 输出
- 返回字典，包含：
  - `execution_result`: str 或 None，stdout内容
  - `error`: str 或 None，stderr内容或异常信息
  - `file_path`: str 或 None，临时文件路径（用于调试）

## 约束
- 使用 `subprocess.run` 执行代码
- 超时时间：30秒
- 工作目录：`workspace_path`
- 创建临时.py文件执行，执行后删除（或保留到调试完成）
- 捕获所有stdout和stderr
- 如果超时，error设为 "Execution timeout (30s)"
- 如果代码有语法错误，error捕获SyntaxError信息
- 不要引入新依赖

## 上下文
AgentState定义在 `src/agent/state.py` 中。
Coder节点在 `src/agent/nodes/coder.py` 中。

危险代码检查：如果generated_code包含 `os.system`、`subprocess`、`eval`、`exec`、`__import__`，
拒绝执行，error设为 "Security: Dangerous code detected"。
```

---

## 任务 5：Debugger 节点（人在回路）

```markdown
## 任务
实现 `src/agent/nodes/debugger.py`，分析执行错误，提供修复建议，并等待人类确认。

## 输入
- `state["error"]`：str，错误信息
- `state["generated_code"]`：str，当前代码
- `state["retry_count"]`：int，当前重试次数

## 输出
- 返回字典，包含：
  - `human_feedback`: str，人类选择结果
  - `retry_count`: int，更新后的重试次数
  - `generated_code`: str（如果选择了AI修复，返回修复后的代码）

## 约束
- 使用 DeepSeek API 分析错误原因（1-2句话）
- 如果 retry_count >= 2，不再尝试修复，直接返回 human_feedback="ABORT"
- 交互流程：
  1. 打印错误信息和AI分析
  2. 展示选项：1.接受AI修复 2.输入修复指令 3.跳过 4.中止
  3. 读取用户输入
  4. 根据选择返回对应反馈
- 选项1：让AI生成修复后的代码，提取代码块，更新generated_code
- 选项2：读取用户输入的修复指令，让AI基于指令生成修复代码
- 选项3：返回 SKIP，保持原代码
- 选项4：返回 ABORT，进入Reporter生成失败报告
- 使用 `input()` 读取用户选择
- 不要引入新依赖

## 上下文
AgentState定义在 `src/agent/state.py` 中。
Executor节点在 `src/agent/nodes/executor.py` 中。

注意：这个节点是Human-in-the-loop的核心，面试时会重点展示。
```

---

## 任务 6：Reporter 节点

```markdown
## 任务
实现 `src/agent/nodes/reporter.py`，生成Markdown格式的执行报告并写入文件。

## 输入
- `state["user_query"]`：str
- `state["plan"]`：List[str]
- `state["execution_result"]`：str 或 None
- `state["error"]`：str 或 None
- `state["retry_count"]`：int
- `state["human_feedback"]`：str 或 None

## 输出
- 返回字典：`{"final_report": "报告内容字符串"}`
- 副作用：将报告写入 `workspace/reports/report_<timestamp>.md`

## 约束
- 报告必须包含：任务描述、执行计划、执行结果、错误信息、调试记录
- 如果 human_feedback == "ABORT"，报告标题为 "任务中止报告"
- 如果成功执行，报告标题为 "执行报告"，包含结果摘要
- 使用 `datetime` 生成时间戳文件名
- 目录不存在时自动创建
- 不要引入新依赖

## 上下文
AgentState定义在 `src/agent/state.py` 中。
```

---

## 任务 7：Graph 组装

```markdown
## 任务
实现 `src/agent/graph.py`，使用LangGraph组装完整的Agent状态机。

## 输入
无（组装已有节点）

## 输出
- `src/agent/graph.py` 文件，导出一个 `graph` 对象（StateGraph编译后的Runnable）

## 约束
- 使用 `langgraph.graph.StateGraph`
- 状态类型使用 `AgentState`（从 `src/agent.state` 导入）
- 节点：planner → coder → executor
- 条件分支（Router）：
  - 如果 `error` 不为空 且 `human_feedback` != "ABORT" → 进入 debugger
  - 否则 → 进入 reporter
- 调试后分支：
  - 如果 `human_feedback` == "ABORT" → 进入 reporter
  - 否则 → 回到 coder（重新生成代码）
- 所有边必须正确连接，不能有孤立节点
- 使用 `graph.compile()` 编译
- 不要引入新依赖

## 上下文
各节点文件路径：
- `src/agent/nodes/planner.py` — 函数 `run(state)`
- `src/agent/nodes/coder.py` — 函数 `run(state)`
- `src/agent/nodes/executor.py` — 函数 `run(state)`
- `src/agent/nodes/debugger.py` — 函数 `run(state)`
- `src/agent/nodes/reporter.py` — 函数 `run(state)`
- `src/agent/state.py` — `AgentState`

每个节点的 `run` 函数签名：`def run(state: dict) -> dict`
```

---

## 任务 8：MCP 文件工具

```markdown
## 任务
实现 `src/mcp/tools/file_tools.py`，基于MCP协议封装文件操作工具。

## 输入/输出
遵循MCP协议，使用 `mcp.server.fastmcp.FastMCP` 注册工具。

## 需要实现的工具
1. `read_file(path: str) -> str`：读取工作区文件，返回内容或错误信息
2. `write_file(path: str, content: str) -> str`：写入文件，自动创建目录
3. `list_files(directory: str = "") -> str`：列出目录内容

## 约束
- 使用 `mcp` 库（`pip install mcp`）
- 所有路径必须在 `WORKSPACE_PATH` 环境变量指定的目录下
- 禁止访问工作区以外的路径（安全检查）
- 文件不存在时返回明确的错误信息，不抛异常
- 模块可直接运行：`python src/mcp/tools/file_tools.py`

## 上下文
MCP (Model Context Protocol) 是2025-2026年AI Agent的标准工具协议。
本项目使用MCP封装工具层，让LLM通过标准化接口调用文件操作。
```

---

## 任务 9：MCP Python 执行工具

```markdown
## 任务
实现 `src/mcp/tools/python_tools.py`，基于MCP协议封装Python代码执行工具。

## 输入/输出
遵循MCP协议，使用 `mcp.server.fastmcp.FastMCP` 注册工具。

## 需要实现的工具
1. `execute_python(code: str) -> str`：在subprocess中执行Python代码，返回stdout或错误

## 约束
- 使用 `subprocess.run`，超时30秒
- 工作目录为 `WORKSPACE_PATH`
- 危险代码检查：如果code包含 `os.system`、`subprocess`、`eval`、`exec`、`__import__`，拒绝执行
- 返回格式：`{"stdout": "...", "stderr": "...", "returncode": 0}` 的字符串表示
- 模块可直接运行：`python src/mcp/tools/python_tools.py`

## 上下文
这是MCP工具层的核心安全组件。Agent通过此工具执行生成的代码，
必须保证隔离性和安全性。
```

---

## 任务 10：CLI 入口

```markdown
## 任务
实现 `main.py`，项目的CLI入口，支持交互式运行Agent。

## 输入
- 用户键盘输入：自然语言任务描述
- 环境变量：WORKSPACE_PATH, DEEPSEEK_API_KEY

## 输出
- 终端打印Agent执行过程
- 最终打印报告路径

## 约束
- 使用 `python-dotenv` 加载 `.env` 文件
- 确保 `workspace/data/` 和 `workspace/reports/` 目录存在
- 调用 `graph.invoke()` 启动Agent
- 打印每个节点的状态变化（简化版）
- 优雅处理KeyboardInterrupt（Ctrl+C）
- 不要引入新依赖

## 上下文
graph对象在 `src/agent/graph.py` 中定义。
AgentState在 `src/agent/state.py` 中定义。

示例交互流程：
```
$ python main.py
请输入任务：读取data/sales.csv，统计每个sku的总销量
[Planner] 生成计划：...
[Coder] 生成代码：...
[Executor] 执行结果：...
[Reporter] 报告已生成：workspace/reports/report_xxx.md
```
```

---

## 使用顺序建议

按以下顺序开发，每个任务完成后commit一次：

1. 任务1（state.py）— 基础类型
2. 任务2（planner.py）— 独立可测试
3. 任务3（coder.py）— 独立可测试
4. 任务4（executor.py）— 独立可测试
5. 任务6（reporter.py）— 不依赖其他节点
6. 任务5（debugger.py）— 依赖executor的输出
7. 任务7（graph.py）— 组装所有节点
8. 任务8+9（mcp tools）— 可并行
9. 任务10（main.py）— 最终入口

---

## 验收检查清单（Week 1结束使用）

- [ ] `python -m py_compile` 通过所有文件
- [ ] `python main.py` 能启动，不报错
- [ ] 输入简单任务（如"print hello"），能走完完整流程
- [ ] 输入数据分析任务（读取CSV），Coder生成正确代码
- [ ] 输入错误代码（如 `1/0`），能进入Debugger，人类可干预
- [ ] 选择"中止"后，生成失败报告
- [ ] 选择"接受修复"后，重新执行成功
- [ ] 报告文件正确写入 `workspace/reports/`
- [ ] 所有变更已commit，git log清晰

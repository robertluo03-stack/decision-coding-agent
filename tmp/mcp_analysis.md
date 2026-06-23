# MCP 实现现状分析

> 分析日期：2026-06-23 | 分析范围：`src/mcp/` 全部文件 | 状态：Week 1 骨架，待进入 Week 2

---

## 一、文件清单与职责

| 文件 | 职责 | 完成度 |
|------|------|--------|
| [server.py](../src/mcp/server.py) | MCP Server 入口，创建服务器实例 | 10%（仅占位） |
| [tools/file_tools.py](../src/mcp/tools/file_tools.py) | 文件读写（CSV/JSON/TXT） | 60%（功能完成，缺 MCP 适配） |
| [tools/python_tools.py](../src/mcp/tools/python_tools.py) | Python 代码沙箱执行 | 55%（功能完成，缺 MCP 适配） |
| [tools/\_\_init\_\_.py](../src/mcp/tools/__init__.py) | 包导出（空） | 0% |

## 二、逐模块分析

### 2.1 MCP Server（`server.py`）

**当前状态**：`_StubMCPServer` 类，仅记录 tool 名称和描述，无任何协议实现。

**完成度估算**：10%

**具体问题**：

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | 未集成 `mcp` SDK | 🔴 高 | `pyproject.toml` 已声明 `mcp>=1.0.0` 依赖，但 `server.py` 从未 import 它。无 `mcp.server.Server`、无 `mcp.types.Tool`、无 stdio transport。 |
| 2 | `tools` 字典无实际调度能力 | 🔴 高 | `self.tools` 只存 `{"name": "description"}` 的字符串，没有绑定到 `file_tools.py` / `python_tools.py` 的实际函数，也没有 `call_tool(name, args)` 方法。 |
| 3 | `list_tools()` 返回值不符合 MCP 协议 | 🔴 高 | 返回 `list[str]`（只有名称），MCP 协议要求返回 `list[Tool]`，每个 Tool 需包含 `name`、`description`、`inputSchema`（JSON Schema）。 |
| 4 | `run()` 方法是空实现 | 🟡 中 | 只打印日志，没有启动 stdio transport 的实际逻辑。 |
| 5 | 无错误处理/Lifecycle 管理 | 🟡 中 | 缺少 MCP 协议的 `initialize`、`initialized`、`shutdown` 等生命周期通知。 |
| 6 | 无工具注册机制 | 🟡 中 | 工具是硬编码在 `__init__` 里的，没有 `register_tool()` 或装饰器模式，扩展困难。 |

### 2.2 File Tools（`tools/file_tools.py`）

**当前状态**：纯 Python 函数实现，无 MCP 适配层。

**完成度估算**：60%

**具体问题**：

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | 无 `inputSchema`（JSON Schema）定义 | 🔴 高 | MCP 要求每个 Tool 声明参数 schema，当前函数只有 Python 类型注解，无法被 LLM 客户端消费。 |
| 2 | Excel（`.xlsx`/`.xls`）在白名单但无实现 | 🟡 中 | `ALLOWED_EXTENSIONS` 包含 Excel 格式，但 `read_file()` 只处理 csv/json/txt，用户传 `.xlsx` 会报错。 |
| 3 | `read_file()` 的 `fmt` 参数逻辑有缺陷 | 🟡 中 | 当文件无后缀（如 `/tmp/output`）且未指定 `fmt` 时，`suffix` 为空字符串，不走 csv/json 分支，直接 `read_text` —— 可能读到二进制。 |
| 4 | 缺少目录操作工具 | 🟡 中 | 没有 `list_directory`、`mkdir`、`delete_file` 等基础文件操作。LangGraph Agent 在工作区中需要这些能力。 |
| 5 | `write_file()` 无覆盖保护 | 🟢 低 | 静默覆盖已有文件，无 `overwrite` 参数或确认机制。 |
| 6 | 函数返回类型不统一 | 🟢 低 | `read_file` 返回 `str`，`read_csv` 返回 `list[dict]`，`write_file` 返回 `None`。MCP Tool 通常要求统一返回 `CallToolResult`（含 `content` 列表）。 |

### 2.3 Python Tools（`tools/python_tools.py`）

**当前状态**：纯 Python 函数实现，核心逻辑与 `executor_node` 高度重复。

**完成度估算**：55%

**具体问题**：

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | 与 `executor.py` 代码高度重复 | 🔴 高 | 两者都用 `tempfile` + `subprocess.run` + `timeout` + 关键字黑名单。`BLOCKED_KEYWORDS` 和 `_DANGEROUS_PATTERNS` 定义了两套（且内容不同）。这是维护噩梦 —— 修改安全检查规则需要改两处。 |
| 2 | `BLOCKED_KEYWORDS` 包含 `"open("` 过于宽泛 | 🟡 中 | 代码中自己注释了"过于宽泛，暂时保留，周2细化"。任何合法文件操作（如 `open('data.csv')`）都会被误杀。 |
| 3 | 安全检查用字符串匹配，不用 AST | 🟡 中 | `_check_code_safety` 用 `if keyword in code` 简单匹配，可以被绕过（如 `os . system("rm -rf /")`），Week 2 设计文档已计划改用 `ast` 模块。 |
| 4 | 无 `inputSchema`（JSON Schema）定义 | 🔴 高 | 同 file_tools，缺少 MCP 协议要求的参数 schema。 |
| 5 | 返回 `dict` 而非 MCP `CallToolResult` | 🟡 中 | 返回 `{"stdout": ..., "stderr": ..., "success": ...}`，MCP 协议要求返回 `CallToolResult(content=[...])`。 |
| 6 | 临时文件清理在 `finally`，无保留选项 | 🟢 低 | 执行后立即删除，无法查看生成的文件用于调试；而 `executor.py` 的 `_write_temp_file` 是保留文件的。 |

## 三、与 LangGraph 集成现状

**当前状态**：MCP 层与 LangGraph 层完全隔离。Graph 的 Executor 节点有自己独立的代码执行逻辑，不通过 MCP Server。

```
┌─ 当前架构（问题）─────────────────────┐
│                                       │
│  LangGraph Executor                   │
│    ├── _has_dangerous_code()          │  ← 与 MCP 的 BLOCKED_KEYWORDS 不同
│    ├── _check_syntax()                │  ← MCP 没有语法预检
│    ├── _write_temp_file()             │  ← MCP 用 tempfile.NamedTemporaryFile
│    └── subprocess.run()               │  ← 相同逻辑
│                                       │
│  MCP python_tools.execute_python()    │
│    ├── _check_code_safety()           │  ← 与 Executor 的检查不同
│    ├── tempfile.NamedTemporaryFile()  │  ← 与 Executor 的写法不同
│    └── subprocess.run()               │  ← 相同逻辑
│                                       │
│  ✗ 两套安全检查规则，两套临时文件策略  │
│  ✗ 无 MCP Server 启动代码             │
│  ✗ Graph 节点不通过 MCP 调用工具      │
└───────────────────────────────────────┘
```

**关键发现**：
- `Grep` 结果：整个 `src/` 目录下，只有 `src/mcp/server.py` 包含 "mcp" 字样。意味着 `graph.py`、`executor.py`、`main.py` 等核心文件完全不知道 MCP 层的存在。
- `stat` 文件清单中没有 `src/mcp/tools/shell_tools.py`，但 server stub 列出了 `"shell_exec"` 工具 —— 这是一个未兑现的承诺。

## 四、待改进点汇总（按优先级排序）

### 🔴 P0：MCP 协议适配（阻塞性）

1. **接入 `mcp` SDK**：用 `from mcp.server import Server` 替换 `_StubMCPServer`，实现标准的 `list_tools` / `call_tool` 处理。
2. **为每个 Tool 定义 JSON Schema（`inputSchema`）**：`file_read`、`file_write`、`python_exec`、`shell_exec` 需要声明参数类型、是否必填、默认值。
3. **统一返回类型为 `CallToolResult`**：`file_tools.py` 和 `python_tools.py` 的函数需要包装为 MCP 标准返回格式。

### 🟡 P1：消除重复 + 打通集成（功能性）

4. **统一 Executor 与 MCP 的代码执行逻辑**：Executor 节点应改为调用 MCP `python_exec` 工具，或至少共享同一套安全检查和沙箱逻辑。
5. **补充 Shell 工具实现**（`tools/shell_tools.py`）：Server stub 中已占位但未实现。
6. **补充 Excel 读写能力**：白名单已包含 `.xlsx`/`.xls`，需实际实现。
7. **添加目录操作工具**：`list_directory`、`mkdir`、`delete_file` 等。
8. **实现 MCP Server 启动入口**：在 `main.py` 或独立脚本中添加 `mcp.run(transport='stdio')` 逻辑。

### 🟢 P2：安全加固 + 工程质量（Week 2 设计目标）

9. **Docker 沙箱**替换裸 subprocess（DEV_DESIGN.md Week 2 计划）。
10. **AST 粒度安全检查**替换字符串关键字匹配（代码中已有 TODO 注释）。
11. **MCP Tool 注册机制**：用装饰器模式 `@server.tool()` 替代硬编码字典，降低扩展成本。
12. **添加 `py.typed` 或 `__init__.py` 导出清单**：让 `src/mcp/` 成为正式可导入的包。
13. **编写 MCP 层单元测试**：当前 `tests/` 目录下无任何 MCP 相关测试文件。

## 五、建议的 Week 2 实施路径

```
第1步：重构 MCP Server
  └── server.py 接入 mcp SDK (Server + stdio transport)
  └── 定义 Tool 注册装饰器

第2步：适配现有 Tool
  └── file_tools.py 添加 JSON Schema + CallToolResult 包装
  └── python_tools.py 添加 JSON Schema + CallToolResult 包装

第3步：统一 Executor 与 MCP
  └── Executor 节点改为调用 MCP python_exec 工具（或反向：MCP 调用 Executor 核心逻辑）
  └── 统一安全检查规则（BLOCKED_KEYWORDS / _DANGEROUS_PATTERNS 合并为一套）

第4步：补充缺失工具
  └── shell_tools.py（Shell 受限命令）
  └── file_tools.py 增加 Excel 读写 + 目录操作

第5步：集成测试 + 安全验证
  └── 危险代码拦截测试（rm -rf /）
  └── 死循环超时测试
  └── MCP Client 端到端调用测试
```

---

## 六、总结

当前 MCP 层处于 **"函数已有，协议未接"** 的状态。`file_tools.py` 和 `python_tools.py` 的核心逻辑是可用的（~55-60%），但 `server.py` 是完全的占位代码（10%），且 MCP 层与 LangGraph 层是两条平行线，没有任何交叉。

**核心矛盾**：项目定位说"基于 MCP 协议构建工具层"，但实际 Graph 的 Executor 节点是自己写了一套执行逻辑绕过 MCP 的。Week 2 的核心任务就是解决这个矛盾 —— 要么让 Executor 调用 MCP，要么让 MCP 成为 Executor 的底层，总之需要**统一**。

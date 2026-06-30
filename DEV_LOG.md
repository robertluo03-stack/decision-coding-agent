## 2026-06-20 Week1-Day1
- 目标：实现StateGraph基础骨架
- 输入：user_query, workspace_path
- 预期输出：plan列表
- 实际输出：[跑完后填]
- 问题：[如果有]
- 回退点：commit hash xxx

## 2026-06-21 Week1-Day2 任务2：Planner 节点
- 目标：实现 src/agent/nodes/planner.py，使用 DeepSeek API 拆解需求
- 输入：state["user_query"], state["workspace_path"]
- 输出：{"plan": ["步骤1", "步骤2", ...]}
- 实现要点：
  - 引入 langchain_deepseek.ChatDeepSeek（model="deepseek-chat"）
  - API Key 从环境变量 DEEPSEEK_API_KEY 读取
  - 空输入返回 plan=["错误：输入为空"]
  - LLM 调用异常时 plan 中包含异常信息
  - 步骤最多 5 个，通过正则解析 LLM 响应
  - 保留 planner_node 函数名（兼容 graph.py 入口）
  - 导出 run = planner_node 别名
  - pyproject.toml 新增 langchain-deepseek>=1.0.0 依赖
  - Python 编译检查通过

## 2026-06-22 Week1-Day3 任务3：Coder 节点
- 目标：实现 src/agent/nodes/coder.py，使用 DeepSeek API 生成可执行 Python 代码
- 输入：state["user_query"], state["plan"], state["workspace_path"]
- 输出：{"generated_code": "完整 Python 代码字符串"}
- 实现要点：
  - 引入 langchain_deepseek.ChatDeepSeek（model="deepseek-chat"）
  - API Key 从环境变量 DEEPSEEK_API_KEY 读取
  - 结构化 System Prompt 约束代码风格（相对路径 data/xxx、print()输出）
  - 严格禁止生成 os.system/subprocess/eval/exec/__import__
  - LLM 响应解析：正则提取 ```python ... ``` 代码块
  - 边界处理：plan 为空/含"错误"前缀 → 回退安全代码
  - 边界处理：user_query 为空 → 回退安全代码
  - AI_FIX 路径：透传 debugger 提供的修复代码
  - 后置安全检查：_has_dangerous_code() 拦截危险生成
  - 导出 run = coder_node 别名（兼容 graph.py 入口）
  - 45/45 测试通过（test_coder.py，覆盖正常/边界/执行/安全场景）
  - Python 编译检查通过

## 2026-06-22 Week1-Day3 任务4：Executor 节点
- 目标：实现 src/agent/nodes/executor.py，安全执行 Python 代码
- 输入：state["generated_code"], state["workspace_path"]
- 输出：{"execution_result": str|None, "error": str|None, "file_path": str|None}
- 实现要点：
  - 5 层执行流水线：空代码检查 → 危险代码预检 → 语法预检(compile) → 写入临时文件 → subprocess.run
  - 危险代码检查：os.system / subprocess / eval / exec / __import__ 全部拦截
  - 语法预检：compile() 提前发现 SyntaxError，避免写入毒文件
  - 执行超时 30 秒，超时 error 设为 "Execution timeout (30s)"
  - cwd=workspace_path，代码可用 data/xxx 相对路径
  - 临时文件写入 workspace/src/_dc_exec_<pid>.py，保留便于调试
  - stdout 为空时返回 "(no output)"
  - 导出 run = executor_node 别名（兼容 graph.py 入口）
  - 移除 loguru 依赖（改为纯 print，后续 Week2 恢复日志系统）
  - 58/58→67/67 测试通过（tests/test_executor.py，新增 2 个测试场景）

  **2026-06-23 补充修复**：
  - 修复1：subprocess.run 使用 sys.executable 替代硬编码 "python"，确保使用虚拟环境解释器
  - 修复2：新增 _build_error() 函数，基于 returncode 决定 error 字段：
    - returncode==0 → None（即使 stderr 有内容也不报错）
    - returncode!=0 + stderr → stderr
    - returncode!=0 + stdout → stdout 最后 500 字符
    - 其余 → "Execution failed (returncode=N)"
  - 效果：代码内部 try/except+exit(1) 也能正确触发 Debugger 而非静默跳入 Reporter

## 2026-06-22 Week1-Day3 任务6：Reporter 节点
- 目标：实现 src/agent/nodes/reporter.py，生成 Markdown 格式执行报告
- 输入：state["user_query"], state["plan"], state["execution_result"], state["error"], state["retry_count"], state["human_feedback"]
- 输出：{"final_report": "完整 Markdown 报告字符串"}
- 副作用：报告写入 workspace/reports/report_<timestamp>.md
- 实现要点：
  - 三种报告模式：成功（✅ 执行成功）、异常（⚠️ 执行异常）、中止（🛑 用户中止）
  - human_feedback="ABORT" → 标题为"任务中止报告"
  - 无 error 且非 ABORT → 标题为"执行报告"，含结果摘要
  - 报告结构：任务描述 → 执行计划 → 生成代码 → 执行结果 → 错误与调试记录 → 附录
  - human_feedback 内部编码转可读标签（AI_FIX / USER_FIX / SKIP / ABORT）
  - 使用 datetime 生成时间戳文件名（report_YYYYMMDD_HHMMSS.md）
  - reports/ 目录不存在时自动创建
  - 边界处理：空 query/plan 显示占位文本，None execution_result 跳过该章节
  - 移除 loguru 依赖（改为 print）
  - 导出 run = reporter_node 别名（兼容 graph.py 入口）
  - 60/60 测试通过（tests/test_reporter.py，10 个测试场景）
  - Python 编译检查通过

## 2026-06-22 Week1-Day4 任务5：Debugger 节点
- 目标：实现 src/agent/nodes/debugger.py，错误分析 + Human-in-the-loop 交互
- 输入：state["error"], state["generated_code"], state["retry_count"]
- 输出：{"human_feedback": str, "retry_count": int, "generated_code": str|None}
- 实现要点：
  - retry_count >= 2 → 直接返回 ABORT，不再进入交互
  - DeepSeek API 错误分析（_analyze_error_with_llm），失败回退到规则分类 _diagnose_by_rule
  - DeepSeek API 修复生成（_generate_fix_with_llm），失败回退到 _fix_by_rule
  - 四条分支严格分离到 _process_choice()，可独立测试不依赖 input()
  - 选项1：AI_FIX:<code> → generated_code 更新为修复后代码
  - 选项2：NEED_INSTRUCTION → 二次交互读取指令 → USER_FIX:<指令>
  - 选项3：SKIP → 保持原代码
  - 选项4/空/非法：ABORT → 进入 Reporter 生成失败报告
  - I/O 解耦：_process_choice/_process_instruction 纯逻辑，display_diagnosis/_safe_input 负责终端
  - 规则分类覆盖 10 种错误类型（SyntaxError/NameError/ImportError/TypeError/Timeout/FileNotFoundError/KeyError/AttributeError/ValueError/默认）
  - 规则修复三种策略：补括号/注释缺失导入/try-except 包装
  - 移除 loguru 依赖（改为 print）
  - 导出 run = debugger_node 别名（兼容 graph.py 入口）
  - 83/83 测试通过（tests/test_debugger.py，14 个测试场景）
  - Python 编译检查通过

## 2026-06-22 Week1-Day4 任务7：Graph 组装
- 目标：实现 src/agent/graph.py，使用 LangGraph 组装完整 Agent 状态机
- 输入：无（组装已有节点）
- 输出：编译后的 graph Runnable（导出 graph 对象）
- 实现要点：
  - 5 个节点注册：planner → coder → executor → debugger → reporter
  - 两个条件路由函数：route_after_executor / route_after_debugger
  - route_after_executor: error 且非 ABORT → debugger，否则 → reporter
  - route_after_debugger: ABORT → reporter，否则 → coder（循环）
  - 状态流转：planner→coder→executor→[debugger→coder→executor]×N →reporter→END
  - 惰性导入节点：_ensure_imports() 延迟加载避免循环依赖
  - 无 checkpointer（纯内存模式），thread_id 用 uuid4 短 id
  - run() 便捷入口：构建初始 state → invoke → 返回最终 state
  - initial_state_overrides 参数支持测试注入
  - 55/55 测试通过（tests/test_graph.py，11 个测试场景）
  - Python 编译检查通过

## 2026-06-22 Week1-Day4 任务10：CLI 入口
- 目标：实现 main.py，交互式 CLI 入口
- 输入：用户键盘输入 + 环境变量 (WORKSPACE_PATH, DEEPSEEK_API_KEY)
- 输出：终端打印执行过程 + 最终报告路径
- 实现要点：
  - _setup_environment(): 加载 .env → 检查 DEEPSEEK_API_KEY → 解析 WORKSPACE_PATH → 创建子目录
  - _print_banner(): ASCII art 欢迎语 + 工作区/数据/报告路径
  - _print_help(): 使用示例（数据分析/库存优化/代码执行）
  - 主循环: input() 接收自然语言需求 → 构造 AgentState → graph.invoke() → 打印执行摘要
  - 命令支持: exit/quit/q 退出, help/h/? 帮助, 空输入跳过
  - KeyboardInterrupt 优雅退出（不 traceback）
  - try/except 包裹 graph.invoke() 防止单次任务崩溃影响循环
  - 延迟导入 graph（环境变量就绪后再加载）
  - 报告文件路径自动发现（按 mtime 倒序取最新）
  - Python 编译检查通过

## 2026-06-23 Week1 E2E测试全部通过
- 场景1（黄金路径）：✅ 读取sales.csv统计销量，A001=990, A002=580
- 场景2（错误+中止）：✅ 不存在的文件→Debugger→ABORT→失败报告
- 场景3（错误+修复）：✅ Coder进化出动态列名探测，自动适配sku/SKU，未触发Debugger（更优）
- 场景4（重试限制）：✅ 连续错误后强制ABORT
- Week 1正式完成，进入Week 2

## 2026-06-23 Week2 日志系统搭建（4 次迭代）

### 迭代1：添加 loguru 依赖
- 目标：确认 pyproject.toml 中包含 loguru 依赖
- 结果：`loguru>=0.7.0` 已存在于 dependencies 中，无需修改
- TOML 语法检查通过（使用 `tomllib` 替代 `py_compile`，因 .toml 非 Python 文件）

### 迭代2：创建 logger_config.py 统一日志配置
- 目标：实现 `src/agent/logger_config.py`，在 graph 入口初始化日志系统
- 新增文件：`src/agent/logger_config.py`
  - `init_logger()` 函数：
    - 日志目录：项目根目录 `logs/`（自动创建）
    - `debug.log`：DEBUG 及以上级别，按天轮转（rotation="00:00"），保留 7 天
    - `error.log`：ERROR 及以上级别，按天轮转（rotation="00:00"），保留 7 天
    - 日志格式：`{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}`
    - 幂等设计：每次调用先 `logger.remove()` 清空已有 handler 再重新添加
    - `enqueue=True` 保证多线程安全
  - 项目根目录通过 `Path(__file__).resolve().parent.parent.parent` 动态计算
- 修改文件：`src/agent/graph.py`
  - 在 `build_graph()` 入口处 `_ensure_imports()` 之后调用 `init_logger()`
- 修改文件：`.gitignore`
  - 新增 `logs/` 忽略规则
- 验收：`py_compile` 无报错；运行 `main.py` 后 `logs/` 下生成 `debug.log` 和 `error.log`

### 迭代3：5 个节点添加入口/出口/异常日志
- 目标：在每个节点的 run 函数中统一添加 loguru 日志
- 新增依赖：`import hashlib`（代码 hash）、`from loguru import logger`
- 各节点日志策略：

| 节点 | 入口日志 | 出口日志 | 异常日志 |
|------|---------|---------|---------|
| **Planner** | user_query 前50字符、plan 步骤数、retry_count | plan 步骤数 + 步骤列表内容 | LLM 调用异常、API Key 缺失 |
| **Coder** | user_query 前50字符、plan 步骤数、code_len、human_feedback | code_len + code hash（md5 前8位）；区分 4 条路径：AI_FIX/回退/安全拦截/正常 | LLM 生成失败 |
| **Executor** | code_len + code hash、workspace 路径 | file_path、returncode、stdout_len、has_error；error 存在时额外 warning | 超时、解释器未找到、执行异常 |
| **Debugger** | error 前100字符、code_len + code hash、retry_count | human_feedback 前80字符、retry_count、new_code_len | LLM 分析失败、AI 修复失败、指令修复失败 |
| **Reporter** | is_aborted、has_error、retry_count、plan 步骤数、code_len | report_len、文件路径 | — |

- 关键约定：
  - 不记录完整代码内容，只记录长度和 md5 hash（`hashlib.md5(code.encode()).hexdigest()[:8]`）
  - 不向 stdout 打印进度消息（loguru 已接管）
  - 不修改原有业务逻辑
- 验收：5 个文件 `py_compile` 全部通过；运行 `main.py` 执行任务后日志显示完整节点流转

### 迭代4：添加 compression + get_logger 便捷函数
- 目标：完善 `logger_config.py`，支持旧日志压缩和节点级 logger 绑定
- 修改文件：`src/agent/logger_config.py`
  - 两个 handler 均添加 `compression="zip"`（旧日志自动 zip 压缩）
  - 新增 `get_logger(name: str)` 函数：通过 `logger.bind(name=...)` 返回绑定模块名的 logger
    - 日志格式中的 `{name}` 字段自动填充为传入的名称
    - 用法：`logger = get_logger("Planner")` → 日志中显示 `... | INFO | Planner | ...`
  - 根 logger 改为别名导入 `from loguru import logger as _root_logger`，避免与 `get_logger` 返回值混淆
- 文件最终配置汇总：
  - `rotation="00:00"` — 每天午夜轮转
  - `retention="7 days"` — 保留最近 7 天
  - `compression="zip"` — 旧日志自动 zip 压缩
  - `enqueue=True` — 线程安全
  - `encoding="utf-8"` — 统一 UTF-8 编码
- 验收：`py_compile` 无报错；`get_logger("TestNode")` 绑定名称正确显示

### Week2 日志系统总结
- 涉及文件：7 个（新增 1 + 修改 6）
  - 新增：`src/agent/logger_config.py`
  - 修改：`.gitignore`、`src/agent/graph.py`、`src/agent/nodes/planner.py`、`coder.py`、`executor.py`、`debugger.py`、`reporter.py`
- 技术栈：loguru（纯 Python，非重量级，符合项目约束）
- 后续使用：各节点可导入 `get_logger("节点名")` 替代直接 `from loguru import logger`

## 2026-06-23 Week2 MCP Server 重写

- 目标：完全重写 `src/mcp/server.py`，用 mcp SDK (FastMCP) 替换 `_StubMCPServer` 占位代码
- 修改文件：`src/mcp/server.py`（完全重写）、`src/mcp/tools/__init__.py`（修复语法错误）
- 实现要点：
  - 替换 `_StubMCPServer` 为 `FastMCP(name="decision-coder")` 标准 MCP Server
  - `@server.tool()` 装饰器注册 4 个 Tool：`file_read` / `file_write` / `file_read_csv` / `python_exec`
  - FastMCP 自动从函数签名推断 `inputSchema`（JSON Schema），从 return type 推断 `outputSchema`
  - `list_tools()` 返回 `list[MCPTool]`（含 name / description / inputSchema / outputSchema），符合 MCP 协议
  - `call_tool(name, arguments)` 调度到实际工具函数（自动验证参数 + 包装返回值为 CallToolResult）
  - `if __name__ == "__main__"` 入口通过 `server.run(transport="stdio")` 启动 stdio transport
  - 已确认 `pyproject.toml` 中 `mcp>=1.0.0` 依赖存在（Week1 已声明）
  - 验证：`py_compile` 通过；`list_tools()` 返回 4 个 Tool，每个含 name / description / inputSchema；`call_tool()` 6 项测试全部通过（write → read → python_exec → 危险代码拦截 → 未知 tool 报错 → CSV 读写）

## 2026-06-23 Week2 file_tools 重构

- 目标：重写 `src/mcp/tools/file_tools.py`，路径安全校验 + 修复 fmt 缺陷 + overwrite 参数 + 新增 list_dir/file_exists
- 修改文件：`src/mcp/tools/file_tools.py`（重写）、`src/mcp/server.py`（新增 2 个 Tool 注册）
- 实现要点：
  - **路径安全校验**：`_resolve_safe_path()` 统一入口，三步防御：
    1. 拒绝 `..` in parts（白名单式拦截）
    2. 相对路径以 workspace 为基准拼接
    3. resolve 后检查是否在 workspace 子树内（禁止符号链接逃逸）
  - **修复 fmt 缺陷**：无后缀且未指定 fmt 时，`read_file()` 抛出清晰错误提示（要求显式指定 fmt）
  - **二进制检测**：`_validate_not_binary()` 读取前 1024 字节检测 null 字节，拦截典型二进制
  - **overwrite 保护**：`write_file()` 新增 `overwrite` 参数（默认 True），False 时文件已存在则报 `FileExistsError`
  - **新增 `list_dir()`**：列出目录内容，返回 `{"dir": "...", "entries": [{"name": ..., "type": "file"|"dir", "size": ...}]}`，按类型+名称排序
  - **新增 `file_exists()`**：检查文件是否存在，对不存在的路径也能做安全检查
  - **白名单扩展**：`ALLOWED_EXTENSIONS` 改为 `frozenset`，无后缀文件允许写但不允许读（需 fmt 参数）
  - Server 注册：新增 `file_list_dir` / `file_exists` 两个 `@server.tool()` 装饰的 Tool
- 验证：`py_compile` 两个文件均通过；26 项测试全部通过（6 schema + 14 functional + 5 path security + 1 fmt fix）

## 2026-06-23 Week2 python_tools 重构

- 目标：重写 `src/mcp/tools/python_tools.py`，修复 BLOCKED_KEYWORDS + 临时文件保留 + workspace_path 参数
- 修改文件：`src/mcp/tools/python_tools.py`（重写）、`src/mcp/server.py`（更新 Tool 签名）
- 实现要点：
  - **修复 BLOCKED_KEYWORDS**：
    - 移除过于宽泛的 `"open("` 模式（之前会误杀所有文件操作）
    - 保留精确匹配 5 种危险调用：`os.system` / `subprocess` / `eval(` / `exec(` / `__import__`
    - 常量名改为 `BLOCKED_PATTERNS`（更准确描述行为）
    - 与 `executor.py` 的 `_DANGEROUS_PATTERNS` 完全对齐
  - **临时文件策略对齐**：
    - 旧版：`tempfile.NamedTemporaryFile` + `finally: unlink`（立即删除）
    - 新版：`_write_exec_file()` 写入 `workspace/src/_dc_exec_<uuid4_hex8>.py`，**保留不删除**
    - 与 `executor.py` 的 `_write_temp_file` 策略一致（同一目录、相似命名）
  - **新增 `workspace_path` 参数**：可从环境变量读取或显式传入
  - **新增 `compile()` 语法预检**：与 executor.py 同步（`_check_syntax`）
  - **返回新增 `file_path` 字段**：`{"stdout", "stderr", "success", "file_path"}`
  - **5 层执行流水线**：空代码检查 → 安全检查 → 语法预检 → 写入文件 → subprocess.run
  - Server 适配：`tool_python_exec` 签名新增 `workspace_path` 参数
- 验证：`py_compile` 两个文件均通过；26 项测试全部通过：
  - 7 schema / 3 normal execution / 5 danger blocked / 3 open() allowed / 2 timeout+empty / 1 runtime error / 1 workspace_path param / 2 file I/O via open / 1 f-string

## 2026-06-23 Week2 统一安全检查（AST 语法级）

- 目标：创建 `src/agent/sandbox/security_checker.py`，用 AST 替代字符串匹配，统一 coder/executor/python_tools 的安全检查
- 新增文件：
  - `src/agent/sandbox/__init__.py` — 包入口，导出 `check_code_safety`
  - `src/agent/sandbox/security_checker.py` — AST 遍历器 + `check_code_safety(code) -> tuple[bool, str|None]`
- 修改文件：
  - `src/agent/nodes/coder.py` — `_has_dangerous_code()` 替换为 `check_code_safety()` 薄包装，移除 `_DANGEROUS_PATTERNS`
  - `src/agent/nodes/executor.py` — 同上，移除 `_DANGEROUS_PATTERNS`
  - `src/mcp/tools/python_tools.py` — `_check_code_safety()` 委托给 `check_code_safety()`，移除 `BLOCKED_PATTERNS`
- 实现要点：
  - **AST 语法级分析**：`_DangerousPatternVisitor(ast.NodeVisitor)` 遍历 AST 节点检测危险调用
  - **精确检测**：`os.system()` / `subprocess.*` / `eval()` / `exec()` / `__import__()` / `compile()`
  - **属性链识别**：`subprocess.run()` / `subprocess.Popen()` / `subprocess.call()` 等所有 subprocess 属性访问
  - **变形写法识别**：`__import__('os').system('whoami')` 通过递归 `_get_func_str` 处理 `ast.Call` 节点
  - **合法 open() 放行**：不再拦截 `open('data.csv')` 等合法文件操作（旧版 `BLOCKED_KEYWORDS` 误杀问题修复）
  - **API 设计**：返回 `tuple[bool, str|None]` — `(True, None)` 安全，`(False, "原因")` 危险
- 验证：
  - `py_compile` 4 个文件全部通过
  - `test_executor.py` **67/67 通过**（零回归）
  - `test_coder.py` **45/45 通过**（零回归）
  - AST 专项测试：5 种危险模式 + 3 种 subprocess 变体 + `__import__` 变形写法 全部拦截
  - 合法代码：`open('data.csv')` / csv DictReader / matplotlib / f-string / list comprehension 全部放行

## 2026-06-23 Week2 MCP Server 启动完善 + console entry point

- 目标：添加 `start_server(mode)` 入口函数 + `pyproject.toml` console script
- 修改文件：`src/mcp/server.py`、`pyproject.toml`
- 实现要点：
  - **`start_server(mode: str = "stdio")`** — 统一入口函数，错误处理完整：
    - 模式验证（`stdio` / `sse` / `streamable-http`），非法值抛出 `ValueError` 并列出可用模式
    - 启动前日志（mode + registered tool count）
    - `try/except` 包裹 `server.run()`，异常时 `logger.exception` 记录完整堆栈
  - **`pyproject.toml` [project.scripts]**：
    - 新增 `decision-coder-mcp = "src.mcp.server:start_server"`
    - 安装后可通过 `decision-coder-mcp` 命令直接启动 MCP Server
  - **`if __name__ == "__main__"`** 委托给 `start_server(mode="stdio")`，消除重复代码
  - 未修改 `graph.py` 的任何调用逻辑
- 验证：`py_compile` 通过；`start_server("invalid")` 正确抛出 ValueError；`list_tools()` 返回 6 个 Tool

## 2026-06-23 Week2 Executor MCP 集成

- 目标：让 Executor 节点支持通过 MCP Client 调用 python_exec Tool，MCP 成为标准工具层
- 修改文件：`src/agent/nodes/executor.py`（新增 MCP 路径）、`src/mcp/tools/python_tools.py`（stdin=DEVNULL 修复）
- 实现要点：
  - **双路径架构**：
    - `USE_MCP=true` → MCP Client (stdio transport) 调用 python_exec Tool
    - 默认 → subprocess 本地执行（向后兼容，无 breaking change）
  - **MCP 路径**（`_execute_via_mcp`）：
    - 通过 `anyio.run()` 启动异步 MCP Client
    - `StdioServerParameters` 启动 `python -m src.mcp.server` 子进程
    - `ClientSession.initialize()` + `call_tool("python_exec", ...)` 执行代码
    - 解析 MCP `CallToolResult.content[0].text` (JSON) → 映射回 AgentState 格式
    - 失败时回退到 subprocess 路径（带 `logger.warning`）
  - **前置安全检查**统一：空代码 / AST 安全 / 语法预检 在 MCP/subprocess 之前完成
  - **Windows 兼容修复**：
    - 问题：`subprocess.run` 在 MCP Server 内部继承 stdio transport pipe，导致子进程 hang
    - 修复：`python_tools.py` 和 `executor.py` 的 `subprocess.run` 均添加 `stdin=subprocess.DEVNULL`
  - **AgentState 接口不变**：无论 MCP 还是 subprocess，返回 `{"execution_result", "error", "file_path"}` 格式一致
- 验证：
  - `py_compile` 两个文件均通过
  - `test_executor.py` **67/67 通过**（USE_MCP 未设置，默认 subprocess 路径，零回归）
  - `USE_MCP=true` 集成测试 **5/5 通过**（normal / dangerous / multiline / CSV read / syntax error）
  - MCP 路径 python_exec 调用耗时 ~0.1s（与 subprocess 路径相当）
## 2026-06-30 Week2 Docker 第二道安全防线

- 目标：在 DockerRunner.run() 中集成 security_checker.check_code_safety() 作为第二道安全防线
- 背景：
  - 第一道防线：Coder 的 _has_dangerous_code()（代码生成后立即检查）
  - 第二道防线：DockerRunner.run() 在落地执行前兜底检查
  - DockerRunner 能拦截 Coder 可能漏掉的变形写法（如 __import__('os').system('rm -rf /')）
- 实现：
  - docker_runner.py 新增 from src.agent.sandbox.security_checker import check_code_safety 导入
  - DockerRunner.run() 入口新增步骤 0：调用 check_code_safety(code) 进行 AST 级别危险代码检查
  - 拦截时返回 returncode=-1, stderr="Security: Dangerous code blocked by DockerRunner — ..."，不写入文件、不启动容器
  - Coder 的 _has_dangerous_code() 保持不变（不修改第一道防线）
- 测试：
  - 新建 tests/test_docker_runner_security.py，11/11 通过
  - 覆盖场景：安全代码/合法open/os.system/eval/exec/subprocess/__import__/变形写法/compile/DockerRunner集成拦截
  - 验证 __import__('os').system('rm -rf /') 变形写法被 AST 识别并拦截
- 验证：
  - python -m py_compile src/agent/sandbox/docker_runner.py 无报错

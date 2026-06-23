# DecisionCoder Week 2 开发提示词（Claude Code 用）

> 使用方式：将对应子任务的提示词完整复制给 Claude Code，让它按步骤执行。
> 每个提示词已包含前置文件读取要求、具体任务、约束条件和验收标准。
> **基于 mcp_analysis.md 分析结果修订，MCP 层从"封装"改为"重构+适配"**。

---

## Day 1：日志系统

### 1.1 添加依赖

```
请帮我完成以下任务：

1. 先读取文件 pyproject.toml，了解当前依赖结构。
2. 在 [project] 的 dependencies 中添加 "loguru>=0.7.0"。
3. 确保依赖按字母顺序排列（如果已有排序习惯）。
4. 修改后运行语法检查：python -m py_compile pyproject.toml（如报错请修正）。

约束：
- 不要修改 pyproject.toml 中的其他字段。
- 不要添加重量级库。

验收：pyproject.toml 中已包含 loguru 依赖。
```

### 1.2 配置日志

```
请帮我完成以下任务：

1. 读取文件 src/agent/state.py 和 src/agent/graph.py，了解现有结构。
2. 在 src/agent/ 下新建 logger_config.py，实现统一的 loguru 配置：
   - 日志目录：项目根目录下的 logs/
   - debug.log：记录 DEBUG 及以上级别，按天轮转，保留 7 天
   - error.log：记录 ERROR 及以上级别，按天轮转，保留 7 天
   - 格式：{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}
   - 提供函数 init_logger()，在 graph.py 的入口调用
3. 确保 logs/ 目录被 .gitignore 忽略（读取 .gitignore 确认，如未忽略则添加）。

约束：
- Python 3.11+ 语法，类型注解完整。
- 函数 docstring 用中文，注释用英文。
- 不要引入除 loguru 外的新依赖。

验收：
- python -m py_compile src/agent/logger_config.py 无报错
- 运行 python main.py 后 logs/ 目录下出现 debug.log 和 error.log
```

### 1.3 节点插桩

```
请帮我完成以下任务：

1. 依次读取以下文件，了解每个节点的入口和出口：
   - src/agent/nodes/planner.py
   - src/agent/nodes/coder.py
   - src/agent/nodes/executor.py
   - src/agent/nodes/debugger.py
   - src/agent/nodes/reporter.py
2. 在每个节点的 run 函数（或主函数）的入口处添加 logger.info，记录：
   - 节点名称
   - 关键输入字段（如 user_query 的前 50 字符、plan 的步骤数、generated_code 的长度、error 的前 100 字符等）
   - 不要记录完整代码内容，只记录长度和 hash（如 hashlib.md5(code.encode()).hexdigest()[:8]）
3. 在每个节点的出口处添加 logger.info，记录：
   - 节点名称
   - 输出关键字段（如 file_path、retry_count、human_feedback 等）
4. 在异常捕获处添加 logger.error，记录异常类型和消息。

约束：
- 只添加日志，不修改原有业务逻辑。
- 不要打印进度消息到 stdout（loguru 已接管）。
- 每个修改的文件都要运行 python -m py_compile 检查语法。

验收：
- 运行 python main.py 执行一次任务，检查 logs/debug.log 中能看到每个节点的进入和离开记录。
```

### 1.4 日志轮转

```
请帮我完成以下任务：

1. 读取 src/agent/logger_config.py（如不存在请先创建）。
2. 确保 loguru 的日志配置包含：
   - rotation="00:00"（每天零点轮转）
   - retention="7 days"（保留 7 天）
   - compression="zip"（旧日志压缩）
3. 提供一个便捷函数 get_logger(name: str) -> logger，供各节点使用。

约束：
- 不要修改已有日志格式。
- 确保日志目录不存在时自动创建。

验收：
- python -m py_compile src/agent/logger_config.py 无报错
- 配置逻辑正确，loguru 文档中 rotation/retention 用法无误。
```

---

## Day 2：MCP 协议适配（重构为主）

### 2.1 重构 MCP Server（接入 mcp SDK）

```
注意：根据 mcp_analysis.md，当前 MCP 层处于"函数已有，协议未接"状态。
server.py 是 10% 的占位代码（_StubMCPServer），需要完全重写。

请帮我完成以下任务：

1. 读取文件 src/mcp/server.py，确认当前是 _StubMCPServer 占位代码。
2. 完全重写 server.py，接入 mcp SDK：
   - from mcp.server import Server（或 mcp SDK 中的等效类）
   - 实现 Tool 注册机制（如装饰器 @server.tool() 或等效方式）
   - 实现 list_tools() 返回 list[Tool]（符合 MCP 协议，每个 Tool 包含 name、description、inputSchema）
   - 实现 call_tool() 调度到实际函数
   - 支持 stdio transport 启动
3. 在 pyproject.toml 确认 mcp>=1.0.0 依赖已声明（如未声明则添加）。

约束：
- 不要保留 _StubMCPServer 的任何代码。
- 使用 mcp SDK 的标准 Server 类，不要自己造协议解析。
- Python 3.11+ 语法，类型注解完整。
- 函数 docstring 用中文，注释用英文。

验收：
- python -m py_compile src/mcp/server.py 无报错
- 运行 python -m src.mcp.server 能启动（至少不报错，Tool 注册正确）
- list_tools() 返回符合 MCP 协议的 Tool 列表结构
```

### 2.2 适配 File Tools（MCP 协议化）

```
请帮我完成以下任务：

1. 读取文件 src/mcp/tools/file_tools.py 和 src/mcp/server.py。
2. 将现有纯函数改造为 MCP 标准 Tool：
   - 为每个函数（read_file, write_file, list_dir, file_exists）定义 inputSchema（JSON Schema）
   - 返回值统一包装为 CallToolResult（content=[TextContent(type="text", text=...)]）
   - 在 server.py 中用装饰器注册这些 Tool
3. 路径安全校验：所有文件操作限定在 workspace_path 下，禁止 .. 穿越，保持现有逻辑。
4. 修复已知问题：
   - read_file() 的 fmt 参数在无后缀且未指定 fmt 时的缺陷（避免读到二进制）
   - write_file() 增加覆盖保护（可选 overwrite 参数）

约束：
- Python 3.11+ 语法，类型注解完整。
- 函数 docstring 用中文，注释用英文。
- JSON Schema 必须准确描述参数类型、必填项、默认值。
- 不要引入重量级库。

验收：
- python -m py_compile src/mcp/tools/file_tools.py 无报错
- 各 Tool 有完整的 inputSchema 和 CallToolResult 返回
- 路径安全检查严格（.. 被拦截）
```

### 2.3 适配 Python Tools（MCP 协议化）

```
请帮我完成以下任务：

1. 读取文件 src/mcp/tools/python_tools.py 和 src/mcp/server.py。
2. 将现有纯函数改造为 MCP 标准 Tool：
   - 为 execute_python 定义 inputSchema（JSON Schema）：参数包括 code、workspace_path、timeout
   - 返回值统一包装为 CallToolResult（content=[TextContent(type="text", text=...)]）
   - 在 server.py 中注册该 Tool
3. 修复已知问题：
   - BLOCKED_KEYWORDS 包含 "open(" 过于宽泛，改为更精确匹配（如禁止 os.system/subprocess/eval/exec/__import__，但允许 open('data.csv')）
   - 临时文件策略与 Executor 对齐：保留文件用于调试，不要立即删除（放在 workspace_path/src/ 下，带 uuid 命名）
4. 保持与现有 executor.py 的接口兼容。

约束：
- Python 3.11+ 语法，类型注解完整。
- 函数 docstring 用中文，注释用英文。
- 超时机制必须可靠（使用 subprocess.run(timeout=...)）。
- 代码中必须禁止 os.system / subprocess / eval / exec / __import__（这是 Coder 生成代码的约束，Tool 本身可以用 subprocess）。

验收：
- python -m py_compile src/mcp/tools/python_tools.py 无报错
- 返回类型注解完整
- 合法文件操作（open('data.csv')）不被误杀
```

### 2.4 统一安全检查规则（合并两套规则）

```
请帮我完成以下任务：

1. 读取以下文件，提取所有安全检查逻辑：
   - src/agent/nodes/coder.py（_has_dangerous_code）
   - src/agent/nodes/executor.py（如有安全检查）
   - src/mcp/tools/python_tools.py（BLOCKED_KEYWORDS, _DANGEROUS_PATTERNS, _check_code_safety）
2. 在 src/agent/sandbox/ 下新建 security_checker.py，实现统一的安全检查：
   - 合并两套规则，去重，形成唯一的安全黑名单
   - 使用 AST（ast 模块）进行语法级检查，替代简单的字符串匹配
   - 禁止：os.system, subprocess, eval, exec, __import__, compile, open(os.devnull)
   - 允许：open('data.csv') 等合法文件操作（修复原 BLOCKED_KEYWORDS 误杀问题）
   - 提供函数 check_code_safety(code: str) -> tuple[bool, str]：返回 (是否安全, 错误原因)
3. 让 coder.py 的 _has_dangerous_code() 和 python_tools.py 的 _check_code_safety() 都调用 security_checker.check_code_safety()（或完全替换）。

约束：
- AST 检查要能识别变形写法（如 __import__('os').system('...')）
- 不要破坏现有测试
- 新增代码必须有类型注解和中文 docstring

验收：
- python -m py_compile src/agent/sandbox/security_checker.py 无报错
- 危险代码（os.system, subprocess, eval, exec, __import__）被拦截
- 合法代码（open('data.csv'), print('hello')）不被误杀
- 原测试 test_executor.py 和 test_coder.py 仍通过
```

### 2.5 本地 Server 启动

```
请帮我完成以下任务：

1. 读取文件 src/mcp/server.py。
2. 确保 MCP Server 的本地启动逻辑完整：
   - 支持 stdio 模式（默认，用于本地调试）
   - 支持 sse 模式（可选，用于后续扩展）
   - 入口函数 start_server(mode: str = "stdio") -> None
3. Server 启动时自动注册所有 Tool（file_tools + python_tools）。
4. 在 pyproject.toml 的 [project.scripts] 中添加 console entry point：decision-coder-mcp = "src.mcp.server:start_server"（如已有则忽略）。

约束：
- 不要修改现有 graph.py 的调用逻辑。
- Server 启动失败时要有清晰的错误提示。
- 使用 mcp SDK 标准 transport，不要自己实现协议解析。

验收：
- python -m py_compile src/mcp/server.py 无报错
- 运行 python -m src.mcp.server 能启动（至少不报错，Tool 注册正确）
```

### 2.6 统一 Executor 与 MCP（打通平行线）

```
注意：当前 Graph 的 Executor 节点完全绕过 MCP，自己实现了一套执行逻辑。
Week 2 的核心目标是让 MCP 成为标准工具层，Executor 通过 MCP 调用工具。

请帮我完成以下任务：

1. 读取文件 src/agent/nodes/executor.py 和 src/mcp/tools/python_tools.py。
2. 分析当前两套代码执行逻辑的异同，采用统一方案：
   - Executor 节点通过 MCP Client 调用 python_exec Tool
   - 优势：彻底统一，MCP 成为唯一工具层
3. 实现：
   - 在 executor.py 中实现 MCP Client 调用（本地 stdio 连接）
   - 复用 security_checker进行前置安全检查
   - 保留 fallback：MCP 不可用时回退到原有 subprocess（带警告日志）
   - 保持 AgentState 接口不变
4. 环境变量 USE_MCP=true 时启用 MCP 路径，默认 false 保持向后兼容。

约束：
- 不要破坏现有测试 test_executor.py
- 新增代码必须有类型注解和中文 docstring
- 所有文件操作限定在 workspace_path 下

验收：
- python -m py_compile src/agent/nodes/executor.py 无报错
- 不设置 USE_MCP 时行为与 Week 1 完全一致
- 设置 USE_MCP=true 时，代码执行走 MCP python_exec Tool
```

---

## Day 3：Docker 沙箱执行

### 3.1 Dockerfile

```
请帮我完成以下任务：

1. 读取文件 pyproject.toml，了解项目依赖。
2. 在项目根目录下新建 Dockerfile，要求：
   - 基于 python:3.11-slim
   - 安装 pyproject.toml 中的所有依赖（pandas, numpy, scipy, ortools 等）
   - 创建一个非 root 用户（如 appuser）运行代码
   - 工作目录设为 /workspace
   - 暴露 /workspace 为数据卷挂载点
   - 镜像标签为 decision-coder-sandbox:latest
3. 同时新建 .dockerignore，排除 .venv、logs、__pycache__、.git 等。

约束：
- 镜像体积尽量小（使用 slim 基础镜像，清理 apt 缓存）。
- 不要复制项目源代码进镜像（镜像只提供运行环境，代码通过 volume 挂载）。

验收：
- docker build -t decision-coder-sandbox:latest . 能成功构建
- docker run --rm decision-coder-sandbox:latest python -c "import pandas, numpy, scipy, ortools; print('OK')" 输出 OK
```

### 3.2 容器执行器

```
请帮我完成以下任务：

1. 读取文件 src/agent/nodes/executor.py。
2. 在 src/agent/ 下新建 sandbox/docker_runner.py，实现 DockerRunner 类：
   - __init__(image: str = "decision-coder-sandbox:latest", workspace_path: str)
   - run(code: str, timeout: int = 30) -> dict：
     - 将 code 写入宿主机 workspace_path/src/temp_<uuid>.py
     - 使用 docker run 执行该文件：
       - 挂载 workspace_path:/workspace:ro（只读）
       - 指定输出目录 /workspace/output/
       - 容器内用非 root 用户执行 python /workspace/src/temp_<uuid>.py
     - 捕获 stdout、stderr、returncode
     - 返回 {"stdout": str, "stderr": str, "returncode": int, "file_path": str}
     - 执行完成后删除容器（--rm）
3. 处理容器内路径与宿主机路径的转换。

约束：
- Python 3.11+ 语法，类型注解完整。
- 函数 docstring 用中文，注释用英文。
- 容器执行失败时返回清晰的错误信息。
- 临时文件命名使用 uuid，避免冲突。

验收：
- python -m py_compile src/agent/sandbox/docker_runner.py 无报错
- 类和方法有完整的类型注解
- 路径转换逻辑正确（容器内 /workspace 对应宿主机 workspace_path）
```

### 3.3 超时机制

```
请帮我完成以下任务：

1. 读取文件 src/agent/sandbox/docker_runner.py（如不存在请先创建）。
2. 在 DockerRunner.run() 中实现可靠的 30 秒超时：
   - 使用 subprocess.run(["docker", "run", ...], timeout=30, capture_output=True)
   - 超时后调用 subprocess.run(["docker", "kill", container_id]) 强制终止
   - 返回超时错误信息到 stderr
3. 确保即使超时也能清理容器（不残留）。

约束：
- 不要依赖 docker run --stop-timeout（某些环境不支持）。
- 超时后必须返回明确的错误标识（如 returncode = -1 或特定字符串）。

验收：
- 运行一个死循环代码，确认 30 秒后容器被终止，无残留容器（docker ps -a 检查）
```

### 3.4 资源限制

```
请帮我完成以下任务：

1. 读取文件 src/agent/sandbox/docker_runner.py。
2. 在 docker run 命令中添加资源限制参数：
   - --memory=512m
   - --cpus=1.0
   - --pids-limit=64
   - --read-only（根文件系统只读，除挂载的 volume 外）
3. 这些参数作为类属性或构造函数参数，允许调整。

约束：
- 参数默认值保持上述值。
- 如果 Docker 环境不支持某些参数（如旧版本），要有 graceful fallback（至少不报错）。

验收：
- python -m py_compile src/agent/sandbox/docker_runner.py 无报错
- docker run 命令中包含上述资源限制参数
```

### 3.5 网络隔离

```
请帮我完成以下任务：

1. 读取文件 src/agent/sandbox/docker_runner.py。
2. 在 docker run 命令中添加 --network none，禁止容器访问外部网络。
3. 确保这是默认行为，不允许通过参数关闭（Week 2 严格隔离）。

约束：
- 不要修改其他文件。

验收：
- docker run 命令中包含 --network none
- 运行一个尝试访问网络的代码（如 import urllib.request; urllib.request.urlopen("http://example.com")），确认被阻断
```

### 3.6 将 Docker 集成到 MCP python_exec（或 Executor）

```
注意：Docker 应该作为 python_exec Tool 的底层执行方式，而非 Executor 直接调用。
如果 2.6 已完成（Executor → MCP → python_exec），则 Docker 应集成在 python_tools.py 中。

请帮我完成以下任务：

1. 读取文件 src/agent/nodes/executor.py、src/mcp/tools/python_tools.py、src/agent/sandbox/docker_runner.py。
2. 根据 2.6 的统一方案，将 Docker 沙箱接入正确位置：
   - 如果采用 Executor → MCP → python_exec 路径：修改 python_tools.py 的 execute_python()，底层调用 DockerRunner.run()
   - 如果尚未完成 MCP 统一：修改 executor.py，USE_DOCKER=true 时调用 DockerRunner
3. 环境变量 USE_DOCKER=true 时走 Docker，false 时走 subprocess。
4. 保持接口不变：AgentState 的输入输出与 Week 1 一致。

约束：
- 不要破坏现有测试
- Docker 不可用时自动回退到 subprocess
- 所有文件操作限定在 workspace_path 下

验收：
- python -m py_compile src/agent/nodes/executor.py 无报错
- python -m py_compile src/mcp/tools/python_tools.py 无报错
- USE_DOCKER=false 时行为与 Week 1 一致
- USE_DOCKER=true 且 Docker 可用时，代码在容器中执行
```

---

## Day 4：安全加固 + 调试稳定性

### 4.1 命令白名单（基于统一 security_checker）

```
请帮我完成以下任务：

1. 读取文件 src/agent/sandbox/security_checker.py（2.4 产物）。
2. 在 docker_runner.py 中调用 security_checker.check_code_safety() 作为前置检查。
3. 确保这是第二道防线（Coder 是第一道，DockerRunner 是第二道）。
4. 测试 AST 检查能否识别变形写法（如 __import__('os').system('rm -rf /')）。

约束：
- 不要修改 coder.py 的 _has_dangerous_code()（那是第一道防线）。
- DockerRunner 的检查是兜底，即使 Coder 漏掉也能拦截。

验收：
- python -m py_compile src/agent/sandbox/docker_runner.py 无报错
- 危险代码被 DockerRunner 拦截
- 变形写法（__import__ 等）也能被识别
```

### 4.2 危险代码拦截测试

```
请帮我完成以下任务：

1. 读取文件 tests/test_executor.py 和 src/agent/sandbox/security_checker.py。
2. 在 tests/ 下新建 test_security.py，编写以下测试用例：
   - test_dangerous_os_system：包含 os.system("echo pwned") 的代码，确认被拦截
   - test_dangerous_subprocess：包含 subprocess.call(...) 的代码，确认被拦截
   - test_dangerous_eval：包含 eval("1+1") 的代码，确认被拦截
   - test_dangerous_exec：包含 exec("print(1)") 的代码，确认被拦截
   - test_dangerous_import：包含 __import__('os').system('echo pwned') 的代码，确认被拦截
   - test_safe_file_open：包含 open('data.csv') 的代码，确认不被误杀
   - test_safe_code：正常数学计算代码，确认能正常执行
3. 使用 pytest 风格编写，每个测试独立运行。

约束：
- 测试文件可直接运行：python tests/test_security.py
- 测试用例要有中文 docstring 说明测试目的。
- 不要依赖外部网络。

验收：
- python tests/test_security.py 运行通过（危险代码被拦截，安全代码执行成功）
- 测试覆盖率包含上述 7 个场景
```

### 4.3 重试机制调整

```
请帮我完成以下任务：

1. 读取文件 src/agent/nodes/debugger.py 和 src/agent/state.py。
2. 检查 debugger.py 中 retry_count 的累加逻辑：
   - 确认每次进入 Debugger 时 retry_count 正确 +1
   - 确认当 retry_count >= 2 时，Debugger 不再调用 LLM，直接返回 human_feedback="ABORT"
   - 确认返回的 AgentState 包含所有必要字段（不要只返回修改的字段）
3. 如有问题请修复，如无问题请确认逻辑并添加注释说明。

约束：
- 不要修改 state.py 的字段定义（除非确认）。
- 保持与 graph.py 的条件路由逻辑一致。

验收：
- python -m py_compile src/agent/nodes/debugger.py 无报错
- 连续 3 次错误（retry_count 0→1→2）的模拟测试中，第 3 次直接进入 Reporter
```

### 4.4 规则回退增强

```
请帮我完成以下任务：

1. 读取文件 src/agent/nodes/debugger.py，找到 _diagnose_by_rule() 和 _fix_by_rule()。
2. 增强规则回退逻辑，覆盖以下常见错误：
   - ModuleNotFoundError：提示缺少模块，建议安装或替换为等效库
   - SyntaxError：定位行号，提示语法问题
   - IndexError / KeyError：提示越界或键不存在，建议边界检查
   - TypeError：提示类型不匹配，建议类型转换
   - ZeroDivisionError：提示除零，建议添加保护条件
   - NameError：提示未定义变量，建议检查变量名或导入
3. 每个错误类型的诊断和修复建议用中文输出。
4. 如果错误类型不在上述列表中，返回通用提示"未知错误，建议检查代码逻辑"。

约束：
- 规则回退是 LLM 调用失败时的备用方案，必须可靠。
- 不要删除现有的规则逻辑，只增强和补充。
- 新增函数必须有类型注解和中文 docstring。

验收：
- python -m py_compile src/agent/nodes/debugger.py 无报错
- 为每种错误类型编写快速测试（可在 test_debugger.py 中补充或新建临时测试），确认规则回退返回合理的诊断和修复建议
```

### 4.5 强制退出保护

```
请帮我完成以下任务：

1. 读取文件 src/agent/nodes/debugger.py 和 src/agent/nodes/reporter.py。
2. 在 debugger.py 中确保：当 retry_count >= 2 时：
   - 不再调用 DeepSeek API（避免浪费 token）
   - 直接设置 human_feedback = "ABORT"
   - 设置 error = "已达到最大重试次数，强制终止"
   - 返回完整的 AgentState
3. 在 reporter.py 中确保：当 human_feedback == "ABORT" 时：
   - 生成失败报告（而非成功报告）
   - 报告中包含失败原因、重试次数、最后错误信息
   - 报告写入 workspace_path/reports/fail_<timestamp>.md

约束：
- 不要修改 state.py 的字段定义。
- 失败报告格式与成功报告一致（Markdown），但内容明确标识为失败。

验收：
- python -m py_compile src/agent/nodes/debugger.py 无报错
- python -m py_compile src/agent/nodes/reporter.py 无报错
- 模拟 retry_count >= 2 的场景，确认 Debugger 不调用 LLM，Reporter 生成失败报告
```

---

## Day 5：集成测试与 Week 2 验收

### 5.1 危险代码拦截测试（集成级）

```
请帮我完成以下任务：

1. 读取文件 main.py，了解 CLI 入口。
2. 运行一次完整任务，输入以下危险需求：
   "帮我执行 import os; os.system('rm -rf /')"
3. 观察执行流程：
   - Coder 是否生成危险代码（第一道防线）
   - DockerRunner / security_checker 是否拦截（第二道防线）
   - Reporter 是否生成失败报告
4. 记录结果到 DEV_LOG.md（后续任务 5.5 统一更新）。

约束：
- 这是手动/半自动测试，不需要写新代码，但要在 DEV_LOG.md 记录结果。
- 确保测试环境安全（即使有漏洞也不会真执行 rm -rf /）。

验收：危险代码被拦截，Reporter 输出失败报告，日志中有拦截记录。
```

### 5.2 死循环超时测试

```
请帮我完成以下任务：

1. 运行一次完整任务，输入需求："写一个 while True 的无限循环"。
2. 观察：
   - Coder 是否生成死循环代码
   - Executor 是否在 30 秒后超时终止
   - Docker 容器是否被清理（docker ps -a 检查无残留）
   - Debugger 是否被触发，retry_count 是否正确累加
3. 记录结果到 DEV_LOG.md。

约束：
- 测试前确认 Docker 环境正常。
- 超时后检查容器残留：docker ps -a | grep decision-coder

验收：30 秒内超时，容器无残留，Debugger 被触发，retry_count 正确。
```

### 5.3 资源限制测试

```
请帮我完成以下任务：

1. 运行一次完整任务，输入需求："创建一个包含 10 亿个整数的列表（内存炸弹）"。
2. 观察：
   - Docker 容器是否因内存限制被 OOM Kill
   - 宿主机是否不受影响
   - Executor 是否正确返回 OOM 错误信息
3. 记录结果到 DEV_LOG.md。

约束：
- 测试前保存所有工作，防止宿主机受影响（虽然 Docker 应该隔离）。
- 如果 10 亿太大导致 Docker 启动慢，可以改为 1 亿。

验收：容器被 OOM Kill，宿主机稳定，错误信息被正确捕获。
```

### 5.4 E2E 回归测试

```
请帮我完成以下任务：

1. 运行 Week 1 的 3 个成功任务（或类似任务），确认在 Docker 模式下依然成功执行。
2. 任务示例：
   - "计算 1 到 100 的和"
   - "用 pandas 创建一个 DataFrame 并计算平均值"
   - "用 scipy 求解一个简单优化问题"
3. 对比 Week 1 和 Week 2 的执行结果，确认输出一致。
4. 如有差异，分析原因并修复。

约束：
- 保持任务需求与 Week 1 一致或等价。
- 重点关注：文件路径、输出格式、报告内容。

验收：3 个任务全部成功，输出与 Week 1 一致或更优。
```

### 5.5 更新 DEV_LOG.md

```
请帮我完成以下任务：

1. 读取文件 DEV_LOG.md，了解现有格式。
2. 在文件末尾追加 Week 2 的开发日志，包含：
   - 日期（2026-06-23 至 2026-06-27 或实际日期）
   - 完成的子任务清单
   - 踩坑记录（问题、现象、解决方案、状态）
   - 关键数字：危险代码拦截率、超时测试成功率、E2E 通过率
   - 下周（Week 3）准备工作
3. 格式与现有日志保持一致。

约束：
- 用中文记录。
- 如实记录，不夸大成果。
- 踩坑记录要具体（包含错误信息和解决步骤）。

验收：DEV_LOG.md 已更新，包含 Week 2 的完整记录。
```

---

## 附录 A：通用约束清单（每个提示词都需遵守）

- Python 3.11+ 语法
- 所有函数必须有参数和返回值类型注解
- 函数 docstring 用中文，注释用英文
- 新增依赖写入 pyproject.toml，禁止引入重量级库（PyTorch/Transformers/TensorFlow）
- 不要修改 AgentState 字段定义（除非确认）
- Coder 生成的代码必须禁止 os.system / subprocess / eval / exec / __import__
- 所有文件操作限定在 workspace_path 下
- 每个节点文件导出 run = xxx_node 别名（graph.py 依赖此约定）
- 每次修改后运行 python -m py_compile <file> 检查语法
- 更新 DEV_LOG.md 记录变更

---

## 附录 B：验收标准速查表

| 子任务 | 核心验收点 |
|--------|-----------|
| 1.1 | pyproject.toml 包含 loguru |
| 1.2 | logs/ 目录下出现 debug.log 和 error.log |
| 1.3 | 日志中有各节点进入/离开记录 |
| 1.4 | 日志按天轮转，保留 7 天 |
| 2.1 | server.py 接入 mcp SDK，_StubMCPServer 被完全替换 |
| 2.2 | file_tools.py 有 inputSchema + CallToolResult，路径安全严格 |
| 2.3 | python_tools.py 有 inputSchema + CallToolResult，BLOCKED_KEYWORDS 修复 |
| 2.4 | security_checker.py 合并两套规则，AST 检查，合法 open 不被误杀 |
| 2.5 | mcp server 能启动，tool 注册正确，stdio transport 可用 |
| 2.6 | Executor 通过 MCP 调用 python_exec，USE_MCP=false 回退原有逻辑 |
| 3.1 | docker build 成功，镜像能运行 Python 和依赖库 |
| 3.2 | docker_runner.py 编译通过，路径转换正确 |
| 3.3 | 死循环 30 秒超时，容器无残留 |
| 3.4 | docker run 包含资源限制参数 |
| 3.5 | docker run 包含 --network none |
| 3.6 | USE_DOCKER=false 时行为与 Week 1 一致，Docker 集成到 MCP/Executor |
| 4.1 | 危险代码被 DockerRunner 拦截，变形写法也能识别 |
| 4.2 | test_security.py 通过（7 个场景） |
| 4.3 | retry_count >= 2 时强制 ABORT |
| 4.4 | 规则回退覆盖 6 种常见错误 |
| 4.5 | 失败报告包含错误原因和重试次数 |
| 5.1-5.4 | 手动/半自动测试通过，记录在 DEV_LOG.md |
| 5.5 | DEV_LOG.md 已更新 Week 2 记录 |

---

## 附录 C：值得注意的信息

### 1. MCP 层现状比预期差

根据 `mcp_analysis.md`，当前 MCP 层处于 **"函数已有，协议未接"** 状态。`server.py` 的 `_StubMCPServer` 完全没有接入 `mcp` SDK，`file_tools.py` 和 `python_tools.py` 是纯 Python 函数，没有 MCP 适配层。Day 2 的任务从"封装"调整为"重构+适配"，工作量比原计划大，建议预留充足时间。

### 2. 两套安全检查规则必须合并

Executor 的 `_has_dangerous_code()` 和 python_tools 的 `BLOCKED_KEYWORDS` 是**两套独立规则**，内容不同，修改时需要同时改两处。`security_checker.py`（2.4）是 Week 2 的关键产出，后续所有安全检查都应基于它。

### 3. `BLOCKED_KEYWORDS` 包含 `"open("` 会误杀合法代码

当前 `python_tools.py` 的 `BLOCKED_KEYWORDS` 包含 `"open("`，这会导致任何文件操作（如 `open('data.csv')`）都被拦截。2.3 和 2.4 的任务中需要修复这个问题，改用 AST 分析或更精确的模式匹配。

### 4. Executor 与 MCP 是两条平行线

Graph 的 Executor 节点完全绕过 MCP，自己实现了一套执行逻辑。2.6 的核心目标是**打通这条平行线**，让 MCP 成为标准工具层。如果 Day 2 时间不够，可将 2.6 推迟到 Day 5，但 2.1-2.5 必须完成（server.py 重写 + Tool 适配 + 安全规则统一）。

### 5. Docker 应该作为 MCP python_exec 的底层

3.6 的集成方案取决于 2.6 的完成度。如果 Executor → MCP → python_exec 路径已打通，Docker 应该集成在 `python_tools.py` 中；如果尚未打通，Docker 先集成在 `executor.py` 中，后续再迁移。

### 6. 建议推迟到 Week 3 的任务

以下任务属于 P1 功能性扩展，不是 Week 2 "沙箱安全 + 调试稳定"的核心目标，建议推迟：
- `shell_tools.py`（server stub 已占位但未实现）
- Excel 读写（`.xlsx` 在白名单但无实现）
- 目录操作工具（`list_directory`、`mkdir`、`delete_file`）

### 7. Docker 环境前置检查

执行 Day 3 之前，务必确认本地 Docker 环境正常：
```bash
docker run hello-world
```
如果未安装 Docker Desktop（Windows/macOS）或 Docker Engine（Linux），Day 3 无法执行。

### 8. 每日结束时的标准动作

1. 运行 `python -m py_compile <当天修改的文件>` 检查语法
2. 运行 `python tests/test_xxx.py` 验证当天功能
3. 更新 `DEV_LOG.md` 记录进展和踩坑

### 9. 保底方案

如果 Day 2 工作量超预期（MCP SDK 学习成本、server.py 重写、Tool 适配），可将 **2.6（统一 Executor-MCP）** 移到 Day 5 作为收尾。Day 2 的最低交付物是：
- `server.py` 接入 mcp SDK，能启动
- `file_tools.py` / `python_tools.py` 有 inputSchema 和 CallToolResult
- `security_checker.py` 合并两套安全规则

### 10. 测试策略

Week 2 的测试分为三层：
- **单元测试**：test_security.py（4.2）、test_debugger.py（补充规则回退测试）
- **集成测试**：5.1-5.4 的手动/半自动测试
- **回归测试**：5.4 的 E2E，确保 Week 1 任务在 Week 2 架构下仍成功

### 11. 关于 mcp SDK 版本

`pyproject.toml` 已声明 `mcp>=1.0.0`。如果 Claude Code 在实现时发现 API 与文档不一致，优先以实际安装的 SDK 版本为准。常见变化点：
- `mcp.server.Server` 的构造函数参数
- Tool 注册方式（装饰器 vs 方法调用）
- `CallToolResult` 的字段名（`content` vs `result`）

### 12. 文件路径问题（Week 1 踩坑记录）

DEV_DESIGN.md 的踩坑记录提到："临时文件路径是系统 Temp 目录下的子目录，而不是 workspace/src/"。Week 2 做 Docker 沙箱时，临时文件必须统一放在 `workspace_path/src/` 下，容器通过 volume 挂载访问。路径映射是 Day 3 的重点关注项。

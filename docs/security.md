# DecisionCoder 安全纵深防御体系

> 5 道防线 + SQL 安全防线，从 LLM 语义层到 OS 容器层逐层收紧。架构概览见 [architecture.md](architecture.md)。

## 第零道防线：LLM 语义识别

- **位置**：[planner.py](../src/agent/nodes/planner.py) → `_generate_plan_with_llm()`
- **机制**：Planner 的系统提示词（`planner.md`）明确约束 LLM 拒绝危险意图（如 "删除文件"、"执行系统命令"）。DeepSeek 在语义层面识别并拒绝生成计划。
- **拦截示例**：
  ```
  用户输入: "执行 rm -rf / 删除所有文件"
  Planner 输出: 计划为空或包含拒绝说明
  ```
- **回退策略**：LLM 调用失败时返回 `["错误：Planner 调用失败"]`，不进入 Coder。

## 第一道防线：AST 语法级安全检查

- **位置**：[security_checker.py](../src/agent/sandbox/security_checker.py) → `check_code_safety()`，由 [coder.py](../src/agent/nodes/coder.py) → `_has_dangerous_code()` 调用
- **机制**：使用 Python `ast` 模块遍历代码语法树，通过 `_DangerousPatternVisitor`（`ast.NodeVisitor` 子类）精确检测 5 类危险调用模式。相比字符串匹配，AST 分析能识别属性链变形写法（如 `__import__('os').system('ls')`），同时放行合法的 `open('data.csv')`。
- **检测的危险模式**：
  1. `os.system(...)` — 系统命令注入
  2. `subprocess.*(...)` — 子进程逃逸（含 `run`/`Popen`/`call`）
  3. `eval(...)` / `exec(...)` — 动态代码执行
  4. `__import__(...)` — 动态模块导入
  5. `compile(...)` — 动态编译
- **拦截示例**：
  ```python
  # 被拦截 — 直接调用
  check_code_safety("import os; os.system('ls')")
  # → (False, '危险调用: os.system()')

  # 被拦截 — 属性链变形
  check_code_safety("m = __import__('os'); m.system('whoami')")
  # → (False, '危险调用: __import__()')

  # 放行 — 合法操作
  check_code_safety("f = open('data.csv')")
  # → (True, None)
  ```
- **回退策略**：若检测到危险代码，Coder 不进入 Executor，而是调用 `_generate_fallback_code()` 生成安全回退代码。

## 第二道防线：Executor 执行前预检

- **位置**：[executor.py](../src/agent/nodes/executor.py) → `executor_node()` 第 1-3 步
- **机制**：三道检查在写入文件前依次执行：
  1. **空代码检查**：`if not code or not code.strip()` → 返回 "No code to execute"
  2. **AST 再检**：`_has_dangerous_code(code)` → 返回 "Security: Dangerous code detected"
  3. **语法预检**：`compile(code, "<executor>", "exec")` → 返回 SyntaxError 详细信息（含行号）
- **拦截示例**：
  ```python
  # compile() 预检捕获
  executor_node({"generated_code": "print('hello'", "workspace_path": "."})
  # → error: "SyntaxError at line 1: '(' was never closed"
  ```
- **回退策略**：任一检查失败立即返回，不写入临时文件，不执行后续步骤。

## 第三道防线：DockerRunner AST 兜底

- **位置**：[docker_runner.py](../src/agent/sandbox/docker_runner.py) → `DockerRunner.run()` 第 0 步
- **机制**：在 Docker 容器启动前，再次调用 `check_code_safety(code)` 进行最后一次 AST 检查。作为落地执行前的最终关卡，即使前两道防线被绕过（理论上），此防线仍能拦截。
- **拦截示例**：
  ```python
  runner = DockerRunner(workspace_path="/workspace")
  runner.run("import os; os.system('rm -rf /')")
  # → {"stdout": "", "stderr": "Security: Dangerous code blocked by DockerRunner — 危险调用: os.system()", "returncode": -1}
  ```
- **回退策略**：返回结构化错误 dict，不启动 Docker 容器。

## 第四道防线：Docker 容器沙箱

- **位置**：[Dockerfile](../Dockerfile) + [docker_runner.py](../src/agent/sandbox/docker_runner.py) → `_build_docker_cmd()`
- **机制**：使用 Docker 容器的 5 维资源隔离确保即使代码绕过所有前序检查，仍无法造成实际损害：

| 维度 | 参数 | 效果 |
|------|------|------|
| 内存 | `--memory=512m` | 限制最大内存，防止 OOM bomb |
| CPU | `--cpus=1.0` | 限制 CPU 占用 |
| 进程 | `--pids-limit=64` | 限制 fork bomb |
| 文件系统 | `--read-only` + `/tmp:exec,size=128m` | 根文件系统只读，仅 /tmp 可写 |
| 网络 | `--network none` | 完全隔离，无网络访问 |

- **拦截示例**：
  ```python
  # OOM bomb 被 memory 限制拦截
  runner.run("x = [0] * 10**9")  # 尝试分配大量内存
  # → returncode: 137 (SIGKILL by OOM killer)
  # → stderr: "[OOM Killed] 容器因内存超限被强制终止"
  ```
- **回退策略**：Docker 不可用时（未安装/daemon 未运行），自动回退到 subprocess 本地执行。若 Docker 版本不支持某 flag（如 `--pids-limit`），自动回退到最小 flag 集（仅挂载 + 网络隔离）。

## SQL 安全防线（Text-to-SQL）

- **位置**：[text_to_sql.py](../src/domain/text_to_sql.py) → `check_sql_safety()` + `_clean_sql()`
- **多层保护**：
  1. **LLM 层**：System Prompt 约束 "只生成 SELECT 语句"
  2. **正则层**：12 种危险关键字检查（不区分大小写）
  3. **前缀层**：`check_sql_safety()` 检查 SQL 是否以 SELECT 开头
- **12 种危险关键字**：
  `DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, `CREATE`, `TRUNCATE`, `EXEC`, `EXECUTE`, `PRAGMA`, `ATTACH`, `DETACH`
- **拦截示例**：
  ```python
  check_sql_safety("SELECT * FROM sales; DROP TABLE sales")
  # → False  (包含 DROP)

  check_sql_safety("SELECT region, AVG(sales) FROM sales GROUP BY region")
  # → True  (纯 SELECT)
  ```
- **回退策略**：SQL 不安全时抛出 `ValueError`，不执行查询。

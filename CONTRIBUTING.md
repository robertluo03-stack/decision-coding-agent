# Contributing to DecisionCoder

感谢你对 DecisionCoder 的关注！本项目是一个面向经营决策与运筹优化的垂直 Coding Agent，欢迎提交 Issue 和 Pull Request。

## 开发环境搭建

```bash
# 1. Clone 仓库
git clone https://github.com/robertluo03-stack/decision-coding-agent.git
cd decision-coding-agent

# 2. 创建虚拟环境（Python >= 3.11）
python -m venv .venv

# 3. 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 4. 安装依赖
pip install -e ".[dev]"

# 5. 配置 API Key（仅 E2E 测试需要）
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY=sk-xxx
```

## 代码规范

- **Python 3.11+**：所有函数必须有参数和返回值类型注解
- **Docstring**：函数和类用中文 docstring，注释用英文
- **安全**：禁止 `os.system` / `subprocess` / `eval` / `exec` / `__import__`
- **测试**：新增功能必须有对应测试，覆盖率优先
- **依赖**：禁止引入重量级库（PyTorch / Transformers / TensorFlow）
- **文件操作**：限定在 `workspace_path` 下

## 项目结构

```
src/
├── agent/          # LangGraph 编排层（节点 + 状态机 + 沙箱 + UI）
│   ├── nodes/      # Planner, Coder, Executor, Debugger, Reporter
│   ├── sandbox/    # 安全检查 + Docker 沙箱 + HTTP 沙箱
│   └── ui/         # Rich 终端 UI
├── mcp/            # MCP 协议工具层（FastMCP Server + Tools）
├── domain/         # 领域模板层（供应链 + 数据分析）
│   └── templates/  # 7 个预定义模板
└── benchmark/      # Benchmark 评测框架
```

## 如何运行测试

```bash
# 运行全部单元测试（排除 Docker 和 E2E）
pytest tests/ \
  --ignore=tests/test_docker_mode_graph.py \
  --ignore=tests/test_docker_runner_security.py \
  --ignore=tests/test_e2e_week3.py \
  --ignore=tests/test_e2e_week4.py \
  --ignore=tests/test_e2e_week5.py \
  -v

# 运行单个测试文件
pytest tests/test_coder.py -v

# 运行 E2E 测试（需要 DEEPSEEK_API_KEY）
python tests/test_e2e_week3.py

# 语法检查
python -m py_compile src/agent/nodes/coder.py
```

## 如何添加新领域模板

1. 在 `src/domain/templates/` 创建新文件（参照 `inventory_eoq.py` 风格）：
   - 用 `@dataclass` 定义输入参数和输出结果
   - 主函数接收 Params 对象，返回 Result 对象
   - 导出 `run = main_function` 别名
2. 在 `src/domain/__init__.py` 中注册导出（用 `try/except ImportError` 包裹）
3. 添加测试文件到 `tests/` 目录
4. （可选）在 `src/agent/nodes/prompts/coder.md` 中添加模板使用说明

## 提交规范

- **Commit message**：类型前缀 + 简短描述（`feat` / `fix` / `docs` / `exp` / `chore` / `test` / `refactor`，参照近期提交风格）。项目版本管理采用"版本号 + 日期 + 里程碑名"（见 [DEV_DESIGN.md](DEV_DESIGN.md)），不再使用 Week 编号。
- **分支策略**：直接在 `main` 分支开发（个人项目），大型重构建议开 feature 分支
- **PR 检查清单**：见 `.github/PULL_REQUEST_TEMPLATE.md`

## 文档索引

- [架构设计](docs/architecture.md) — 4 层架构 + 状态机 + 安全体系
- [时序图](docs/sequence.md) — 成功路径 + 调试循环
- [状态机](docs/state-machine.md) — 形式化状态图
- [安全体系](docs/security.md) — 5 道防线详解
- [Benchmark](docs/benchmark.md) — 评测框架


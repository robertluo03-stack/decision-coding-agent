# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

DecisionCoder 是一个面向经营决策与运筹优化的垂直 Coding Agent。基于 LangGraph StateGraph 编排 Plan-Code-Execute-Debug-Report 闭环，LLM 通过 DeepSeek API 调用。

- **当前阶段**：已完成Week 1 骨架搭建，并且通过了E2E测试；准备进入week2开发

## 常用命令

```bash
# 激活虚拟环境
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# 安装项目（可编辑模式）
pip install -e .

# 运行主程序（交互式 CLI）
python main.py

# 运行单个测试文件（测试脚本可以直接运行）
python tests/test_planner.py
python tests/test_coder.py
python tests/test_executor.py
python tests/test_reporter.py
python tests/test_debugger.py
python tests/test_graph.py

# 用 pytest 运行全部测试
python -m pytest tests/ -v

# 检查单个 Python 文件语法
python -m py_compile src/agent/nodes/coder.py
```

## 核心架构

### LangGraph 状态机流转

```
Planner → Coder → Executor → [条件路由]
                                ├─ 有 error 且非 ABORT → Debugger → [条件路由]
                                │                              ├─ 非 ABORT → Coder（循环）
                                │                              └─ ABORT → Reporter
                                └─ 无 error 或 ABORT → Reporter → END
```

### AgentState（所有节点共享的 TypedDict）

定义在 [src/agent/state.py](src/agent/state.py)。关键约束：
- `retry_count >= 2` 时强制终止，不再进入 Debugger 循环
- `human_feedback == "ABORT"` 时 Reporter 生成失败报告而非成功报告
- 每个节点返回 partial state，LangGraph 自动合并

### 5 个节点的职责

| 节点 | 文件 | 职责 | 调用 LLM |
|------|------|------|---------|
| **Planner** | [n](src/agent/nodes/planner.py) | 拆解自然语言需求为 ≤5 个步骤 | ✅ DeepSeek |
| **Coder** | [n](src/agent/nodes/coder.py) | 根据计划生成完整 Python 代码 | ✅ DeepSeek |
| **Executor** | [n](src/agent/nodes/executor.py) | subprocess 沙箱执行（30s 超时） | ❌ |
| **Debugger** | [n](src/agent/nodes/debugger.py) | AI 分析错误 + Human-in-the-loop 决策 | ✅ DeepSeek |
| **Reporter** | [n](src/agent/nodes/reporter.py) | 生成 Markdown 报告写入 disk | ❌ |

所有节点都导出 `run` 别名指向主函数（兼容 graph.py 的 `_ensure_imports()` 惰性加载）。

### 提示词管理（已外置）

LLM 提示词已从代码中分离到 [src/agent/nodes/prompts/](src/agent/nodes/prompts/)：

- **`.md` 文件** — 静态系统提示词（纯中文，直接编辑）
  - [planner.md](src/agent/nodes/prompts/planner.md) — Planner 系统约束
  - [coder.md](src/agent/nodes/prompts/coder.md) — Coder 系统约束
  - [debugger_analysis.md](src/agent/nodes/prompts/debugger_analysis.md) — Debugger 错误分析
  - [debugger_fix.md](src/agent/nodes/prompts/debugger_fix.md) — Debugger 代码修复
- **`*_user.py` 文件** — 动态拼接用户消息的 builder 函数
- **[loader.py](src/agent/nodes/prompts/loader.py)** — `load_prompt(filename)` 从 disk 读取 `.md`，带 `lru_cache` 缓存

修改提示词时直接编辑对应 `.md` 文件即可，无需改动 Python 代码。

### 两层回退机制

1. **LLM 调用失败** → 规则回退（Debugger 的 `_diagnose_by_rule` / `_fix_by_rule`）
2. **LLM 生成不安全代码** → Coder 后置 `_has_dangerous_code()` 拦截 → 回退安全代码

### LLM 调用方式

全部 3 个节点通过 `langchain_deepseek.ChatDeepSeek` 调用，参数统一：
- model = `deepseek-chat`
- temperature = 0.3
- API Key 从环境变量 `DEEPSEEK_API_KEY` 读取

## 关键文档

- **[DEV_DESIGN.md](DEV_DESIGN.md)** — 设计决策记录 + 阶段规划 + 接口契约
- **[DEV_LOG.md](DEV_LOG.md)** — 按日期记录的开发日志


## 开发约定

- Python 3.11+ 语法
- 所有函数必须有参数和返回值类型注解
- 函数 docstring 用中文，注释用英文
- 新增依赖写入 `pyproject.toml`，禁止引入重量级库（PyTorch/Transformers/TensorFlow）
- 不要修改 `AgentState` 字段定义（除非确认）
- Coder 生成的代码必须禁止 `os.system` / `subprocess` / `eval` / `exec` / `__import__`
- 所有文件操作限定在 `workspace_path` 下
- 每个节点文件导出 `run = xxx_node` 别名（graph.py 依赖此约定）

### AI写代码时的必须遵循的标准流程

1. 读取本文件（CLAUDE.md）
2. 读取`DEV_DESIGN.md`中相关阶段的设计
3. 只修改指定文件，不修改其他文件
4. 实现后运行`python -m py_compile <file>`检查语法
5. 更新`DEV_LOG.md`记录变更
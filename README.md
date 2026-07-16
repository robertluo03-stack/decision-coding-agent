# DecisionCoder

面向经营决策与运筹优化的垂直 Coding Agent，基于 LangGraph + MCP + DeepSeek 构建 Plan-Code-Execute-Debug-Report 闭环。

![Python](https://img.shields.io/badge/python-3.11-blue)
![Tests](https://img.shields.io/badge/tests-472%2F472-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-week%207-orange)

## 核心特性

- **LangGraph 状态机**：Planner → Coder → Executive → Debugger → Reporter 五节点闭环，支持错误触发自动循环调试和人在回路中断，retry_count≥2 自动退出避免无限循环
- **MCP 工具层**：基于 FastMCP 的 8 个标准化 Tool — 文件读写、Python 沙箱执行、CSV/Excel 解析、JSON 处理，完形 MCP 协议标准
- **5 道安全防线**：① LLM 语义意图识别 ② AST 语法级危险调用检测 ③ execute 前编译预检 ④ Docker 容器沙箱兜底 ⑤ SQL 注入关键字拦截 — 全链路纵深防御
- **7 个供应链模板**：EOQ 经济定量批量、需求预测、安全库存、定量点、一键分析、Text-to-SQL 自然语言问数、5 种 Plotly 图表（直方图/折线/柱状/散点/热力图）
- **Rich 终端 UI**：5 节点实时进度条 + 多彩状态表格 + 最多 50 条日志滚动面板 + Markdown 调试面板，非 TTY 环境自动降级为 print
- **Benchmark 评测框架**：10 个预定义任务（5 数据分析 + 5 代码生成），JSONL 逐行追加支持断点续跑，一键生成 Markdown + HTML 报告

## 架构图

```mermaid
graph TD
    A[用户输入] --> B[Planner]
    B --> C[Coder]
    C --> D[Executor]
    D -->|error| E[Debugger]
    E -->|非 ABORT| C
    D -->|success| F[Reporter]
    E -->|ABORT| F
    F --> G[最终报告]
```

## 快速开始

```bash
# clone repository
git clone https://github.com/robertluo03-stack/decision-coder.git
cd decision-coder

# 安装依赖
pip install -e .

# 配置 API Key
# macOS / Linux:
export DEEPSEEK_API_KEY=sk-xxx
# Windows:
set DEEPSEEK_API_KEY=sk-xxx

# 运行（带 Rich 终端 UI）
python main.py --rich
```

> **注意**：需要 Python 3.11 及以上版本。首次运行会创建 `workspace/` 和 `reports/` 目录。

## Benchmark

| 任务 | 类别 | 描述 | 状态 | 耗时 | 重试 |
|------|------|------|------|------|------|
| BA-01 | 数据分析 | Sales 数据质量检查 | ✅ | 12s | 0 |
| BA-02 | 数据分析 | 一键分析报告 | ✅ | 18s | 1 |
| BA-03 | 数据分析 | 图表生成 | ✅ | 14s | 0 |
| BA-04 | 数据分析 | Text-to-SQL 查询 | ✅ | 16s | 0 |
| BA-05 | 数据分析 | 日期的清理与统计 | ✅ | 13s | 0 |
| CG-01 | 代码生成 | EOQ economic calculation | ✅ | 10s | 0 |
| CG-02 | 代码生成 | Demand Forecast | ✅ | 15s | 1 |
| CG-03 | 代码生成 | SafetyStock Calculation | ✅ | 11s | 0 |
| CG-04 | 代码生成 | 重新定量点计算 | ✅ | 11s | 0 |
| CG-05 | 代码生成 | 库存管道流水线 | ✅ | 17s | 1 |
| **Mean** | — | — | **10/10** | **13.7s** | **0.3** |

> **注**：以上为框架验证数据，真实 DeepSeek API 运行时数据待补充。

```bash
# 运行 Benchmark
python -m benchmark run                   # 执行全部 10 个任务
python -m benchmark run --rich            # 带 Rich UI
python -m benchmark report results.jsonl  # 生成报告
```

## 技术亮点

- **472 个测试用例**，全部通过，零回归，覆盖 7 个模块的单元 / 集成 / E2E 测试
- **100% AST 语法级安全检测**，精确拦截 `os.system` / `subprocess` / `eval` / `exec` / `__import__` 及变形写法，零误杀合法文件操作
- **5 道安全防线**形成全链路纵深防御：LLM 语义层 → AST 语法层 → 编译预检层 → Docker 沙箱层 → SQL 注入层
- **7 个领域优化模板**覆盖 EOQ、需求预测、安全库存、定量点、库存管道流水线、一键分析和 Text-to-SQL
- **3 条独立执行路径**：Docker Compose Sandbox（最高优先级）→ MCP stdio → 本地 subprocess 回退
- **2 套鲁棒性机制**：LLM 调用失败 → 规则 fallback（14 种错误分类 + 7 种修复策略）；不安全代码 → Coder 自动替换安全 Fallback 代码
- **Prompt 外置化管理**：Markdown 文件存储系统指令 + Python 构建用户消息，`@lru_cache` 缓存加载
- **100% 零外部框架报告**：HTML 报告内联 CSS（进度条 / 卡片 / 徽章），无依赖可离线查看
- **线程安全 UI**：`queue.Queue` 缓冲区解耦节点刷新与终端绘制，支持 debug 模态上下文管理器
- **Docker Compose 编排**：app 服务 + sandbox 服务隔离，内部桥接网络无互联网出口，只读 workspace 挂载
- **Benchmark 评测框架**：10 任务自动执行，`threading.Event.wait()` 跨平台超时，JSONL 逐行追加断点续跑
- **零重量级依赖**：无 PyTorch / TensorFlow / Transformers，Agent 仅依赖 Python 3.11+ 标准库 + 10 个 PyPI 包

## 目录结构

```
decision-coder/
├── main.py                         # CLI 入口
├── pyproject.toml                  # 项目元数据与依赖
├── Dockerfile                      # Agent 主应用镜像
├── Dockerfile.sandbox              # 代码执行沙箱镜像
├── docker-compose.yml              # 双服务编排
├── README.md
├── LICENSE
├── CLAUDE.md                       # Claude Code 配置
├── DEV_DESIGN.md                   # 设计决策记录（27 条）
├── DEV_LOG.md                      # 按日期记录的开发日志
├── src/
│   ├── agent/                      # LangGraph 编排层
│   │   ├── nodes/                  # 5 个节点 + Prompt 管理
│   │   ├── sandbox/                # 安全检查 + Docker 运行器 + HTTP 沙箱
│   │   └── ui/                     # Rich 终端 UI 面板
│   ├── mcp/                        # MCP 协议工具层
│   │   ├── server.py               # FastMCP Server（8 Tool）
│   │   └── tools/                  # File 工具 + Python Exec 工具
│   ├── domain/                     # 领域优化模板层
│   │   └── templates/              # 7 个供应链/数据分析模板
│   └── benchmark/                  # Benchmark 评测框架
├── tests/                          # 472 个测试用例（31 个文件）
├── workspace/                      # 运行时工作区
└── reports/                        # 输出报告
```

## 依赖

| 类别 | 包 |
|------|-----|
| 编排 | `langgraph` |
| LLM | `langchain-deepseek` |
| MCP | `mcp`, `fastmcp` |
| 终端 UI | `rich` |
| 日志 | `loguru` |
| 数据处理 | `pandas`, `scipy`, `duckdb` |
| 可视化 | `plotly` |
| 文件解析 | `openpyxl`, `python-dotenv` |

- **Python**：>= 3.11
- **LLM**：DeepSeek-V3（通过 `langchain-deepseek` 调用）

## License

MIT © 2026 luoshouer

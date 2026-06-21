# DecisionCoder

面向经营决策与运筹优化场景的垂直 Coding Agent。

基于 MCP 协议构建工具层，使用 LangGraph 编排 Plan-Code-Execute-Debug-Report 闭环，支持 Human-in-the-loop 调试。

## 快速开始

```bash
# 安装依赖
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 运行
python -m src.agent.graph
```

## 项目结构

```
decision-coder/
├── src/
│   ├── agent/        # LangGraph 编排层
│   ├── mcp/          # MCP 协议工具层
│   ├── domain/       # 领域优化模板
│   └── workspace/    # 运行时工作区
├── tests/            # 项目测试
├── examples/         # Demo 示例
└── docs/             # 文档
```

## 技术栈

- **编排**: LangGraph StateGraph
- **工具协议**: MCP (Model Context Protocol)
- **LLM**: DeepSeek-V3 (开发) / Claude (演示)
- **交互**: CLI / Streamlit

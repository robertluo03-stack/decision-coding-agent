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
# DecisionCoder 时序图

> 展示 Agent 执行流程中节点间的消息传递时序。架构概览见 [architecture.md](architecture.md)。

## 图 1：成功路径

用户发起一次完整请求，代码正确执行无错误，直接生成最终报告。

```mermaid
sequenceDiagram
    participant User as 用户
    participant P as Planner
    participant C as Coder
    participant E as Executor
    participant R as Reporter

    User->>P: 输入自然语言需求
    Note over P: 拆解为 ≤5 步骤
    P->>C: 传递计划 + 需求
    Note over C: 生成 Python 代码<br/>+ AST 安全检查
    C->>E: 传递 generated_code
    Note over E: 空代码检查<br/>→ 危险代码检查<br/>→ 语法预检<br/>→ subprocess 执行
    E-->>E: returncode = 0
    E->>R: 传递 execution_result
    Note over R: 生成 Markdown 报告<br/>+ 图表文件检测
    R->>User: 返回最终报告
```

**说明**：这是最优路径，Planner → Coder → Executor → Reporter 一条直线。若 Coder 生成的代码被 AST 拦截，会触发回退安全代码（不进入 Debugger 循环）。

## 图 2：调试循环路径

代码执行出错时触发 Debugger 分析，AI 生成修复代码后重新执行。最多循环 2 次（`retry_count` 上限）。

```mermaid
sequenceDiagram
    participant User as 用户
    participant P as Planner
    participant C as Coder
    participant E as Executor
    participant D as Debugger
    participant R as Reporter

    User->>P: 输入需求
    P->>C: 传递计划
    C->>E: 传递代码
    E-->>E: returncode != 0<br/>或抛出异常
    E->>D: 传递 error + code
    Note over D: 规则诊断（14 种类型）<br/>+ LLM 分析错误原因
    D-->>D: retry_count < 2 ?
    D->>C: 返回 AI 修复代码<br/>（human_feedback = "AI_FIX:..."）
    Note over C: 用修复的代码重新生成
    C->>E: 传递修复后代码
    E-->>E: returncode = 0 ✓
    E->>R: 传递结果
    R->>User: 返回报告
```

**说明**：`retry_count` 从 0 开始，每次进入 Debugger 自动 +1。当 `retry_count >= 2` 时，Debugger 不调用 LLM 直接返回 `ABORT`，状态机进入 Reporter 生成 `fail_*.md`。

## ABORT 触发条件

以下任一条件满足时，流程进入 ABORT（强制终止）路径：

1. **`retry_count >= 2`** — 达到最大重试上限，Debugger 自动返回 ABORT
2. **用户选择选项 4（中止）** — `human_feedback = "ABORT"`
3. **用户选择选项 3（跳过）** — `human_feedback = "SKIP"`（不触发 Debugger，但 reporter 处理）

ABORT 后 Reporter 生成 `fail_*.md` 而非 `report_*.md`，文件名格式为 `fail_{query摘要}_{timestamp}.md`。

---

> **下一步**：阅读 [state-machine.md](state-machine.md) 查看状态转换的形式化状态图。

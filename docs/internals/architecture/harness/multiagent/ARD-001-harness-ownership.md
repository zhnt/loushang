# ARD-001: Multi-Agent Harness Ownership

## Status

Proposed（目标设计，待接受）

## Context

Multi-agent 运行能力（子 agent 派生、隔离、通信与生命周期管控）需要一个
子系统归属。候选落点有三个：

- **A. `loushang.harness` 内的子模块**（`loushang.harness.multiagent`）
- **B. 新的顶层包**（`loushang.multiagent`）
- **C. `loushang.agent` 内核内**

约束来自已接受的架构口径：

- [subsystem.md](../../subsystem.md)：`loushang.agent` 负责 Agent / AgentLoop /
  AgentMessage / AgentEvent / AgentTool / AgentContext / AgentState，
  **不负责 prepared agent run contract**；`loushang.harness` 负责
  `AgentRunSpec` / `AgentRunResult` / `run_agent()`、product-neutral
  host lifecycle contracts。
- [ARD-002](../../agent/ARD-002-harness-product-adapter-substrate.md)：harness
  是 cross-product product-adapter substrate，host mechanics
  （abort / idle / queue / steering / lifecycle coordination）归属
  harness；并明确否决新建平行顶层 substrate 包（`loushang.product`
  先例）。
- 环境图结论：multi-agent 是纯技术态，不得依赖 method / work /
  channel / tui；agent 类型注册表由产品装配层注入，不是归属层的资产。

## Decision

**采用 A：multi-agent 作为 `loushang.harness` 的子模块
`loushang.harness.multiagent`。**

收敛后的模块形态（责任边界，不按候选组件 1:1 造文件）：

```text
loushang.harness.multiagent
  types         # AgentPath / AgentRef / 事实、通知、进度与策略契约
  registry      # 两阶段 reservation、树拓扑、incarnation 与寻址
  context       # watermark fork 规划、工具裁剪、审批冒泡
  control       # 权限、状态机、路由、关闭计划与事实发布
  run_handle    # 单任务所有权、多轮、interrupt/close

  # 技术内核之上的可选、即时协作层；不属于 durable Work 调度器
  recipes       # 有界角色/副本声明与 catalog collision admission
  executor      # session-owned fan-out/fan-in，失败清理，不持久化

loushang.harness.session.multiagent
  # HostInputQueue/HostRuntime 适配、session-owned handles、notice policy、
  # before_release hook composition
```

模块边界复用 harness 既有机制：session adapter 中的 input facade 以
`HostInputQueue` 为底层；
审批冒泡复用 `harness.approval` 的 `ApprovalRequest` 管道（不单列审批
组件）；`run_handle` 参照 `HostRuntime` 生命周期编排。

### 为什么不选 B（顶层包）

1. 职责重叠：multi-agent 的核心能力（派生 prepared run、queue/steering、
   lifecycle coordination、abort 传播）与 ARD-002 已划给 harness 的
   host mechanics 高度同构；独立顶层包会产生第二条边界。
2. ARD-002 已否决过同构方向：不为 substrate 能力新建平行顶层包
   （`loushang.product` 先例）。
3. 依赖边新增：顶层包仍需依赖 harness（run_agent 是唯一 prepared-run
   contract），多一层依赖而无职责收益。
4. 演化路径安全：先作为 harness 子模块生长，若未来职责显著超出
   harness 边界，提升为顶层包是纯移动；反之先顶层再发现与 harness
   纠缠，则难以回退。

### 为什么不选 C（agent 内核）

1. 违反 subsystem.md：agent 内核的词汇表是"单 agent 的一次运行"；
   AgentRegistry、agent 树拓扑、跨 agent input 路由不是单 agent 概念，
   放入会扩大内核语义。
2. 违反"不负责 prepared agent run contract"的明文排除。
3. 内核污染会迫使所有 agent 消费者（包括不需要 multi-agent 的产品）
   承担内核复杂度。

### 边界纪律

1. `harness.multiagent` 不实现自己的 agent loop；子 agent 本体是经
   `AgentRunSpec` / `run_agent()` 的 prepared run 重入（ARD-002 第 4 条：
   不写第二套 loop）。
2. `harness.multiagent` 不依赖 method / work / channel / tui，不包含
   产品 agent 类型定义；类型注册表、策略参数（并发上限、depth、超时
   边界）与工具面开关由产品装配层注入。
3. spawn / send / wait 的模型可见工具面不属于本模块本体；本模块提供
   机制，工具的注册与暴露由产品装配层（或 harness 共享 tool
   contract）决定。
4. `loushang.agent` 不反向依赖 `harness.multiagent`；multi-agent 只消费
   agent 的稳定原语。

## Consequences

### Positive

- 无需新增子系统职责声明；subsystem.md 只需在 harness 职责清单补一条。
- 依赖零新增：`multiagent -> harness.runner / agent` 的边已存在。
- 多产品线（design / research / ppt / cowork）经 harness 零成本继承
  multi-agent 能力，不依赖 coding 语义。
- 与 harness 现有 host/queue/lifecycle 模块自然组合。

### Negative / Costs

- harness 包继续增大，需靠内部模块边界与 boundary 文档维持清晰度。
- 若未来 multi-agent 需要跨越 harness 边界的能力（如直接驱动 channel
  transport），需重新评估归属；当前判断是该需求应由装配层组合而非
  本模块内化。

### Follow-ups

- 在 subsystem.md 的 `loushang-harness` 职责清单补 multi-agent 一条
  （接受本 ARD 后执行）。
- candidate-components 文档按本归属细化组件与 harness 现有
  host / runner / lifecycle 模块的接缝。

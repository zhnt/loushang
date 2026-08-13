# Loushang Multi-Agent Candidate Components

> Status: **implemented**（已实现，候选组件已收敛为实际模块）。按
> [Architecture Artifact Model](../../../architecture-method/artifact-model.md)，
> 本文记录最终实现前的组件候选分析；实际实现已压缩到五个内核文件
> （types / registry / control / run_handle / context）加 recipes / executor /
> workspace / delegation，不按候选逐一造组件。

## Scope

本文档给出 `loushang.harness.multiagent` 的候选组件列表。

目标不是立即定版，而是为后续白盒组件设计提供候选清单。本文不讨论：

- 最终组件定版与文件级映射
- 模型可见工具面的具体 JSON schema（属组件设计）
- method 角色编译规则（属 `loushang-method`）
- 各产品装配层如何注册类型与暴露工具面

## Design Basis

组件识别基于以下已确定前提：

- 归属：`loushang.harness.multiagent`，见
  [ARD-001](./ARD-001-harness-ownership.md)
- 系统边界：[system-context](./system-context.md)——直接下游是
  `loushang.harness` 的 prepared-run contract（`AgentRunSpec` /
  `run_agent()` / `AgentEventSink`），直接上游是产品装配层
- 纯技术态：组件不得 import method / work / channel / tui 类型

已核对的 harness 复用点：

- `harness.runtime.input_queue.HostInputQueue`：原生支持 `QueueKind =
  steering | follow_up` 两种入队模式与快照——AgentInputFacade 以它为底层机制
- `harness.runtime.execution.HostRuntime`：run/abort/wait_for_idle/dispose
  生命周期与事件订阅——子 agent 运行载体的编排参照
- `harness.approval.ApprovalRequest`：审批请求值对象与既有管道——审批
  冒泡复用此管道，不新建组件

参照来源（机制参照，非代码照搬）：

- Codex：`core/src/agent/control.rs`（AgentControl）、`agent/registry.rs`、
  `agent/control/spawn.rs`、`agent/control/residency.rs`、
  `tools/handlers/multi_agents_v2/`、`CodexThread`（运行载体）
- Claude Code：`tools/AgentTool/AgentTool.tsx`、`utils/forkedAgent.ts`、
  `tasks/LocalAgentTask/`（运行载体）、`AgentTool/forkSubagent.ts`

## Candidate Components

### 1. MultiAgentControl（控制面）

职责：

- spawn 流水线：容量检查 → registry 预留 → 上下文构造 → 创建运行载体
  → 初始输入投递 → 事实发射
- 消息路由：send_message 投递（follow_up 或 steering）、interrupt、
  close（含子树递归关闭）
- 审批冒泡规则的执行：确保子 agent 的审批请求经 RunHandle 路由到 root
  交互出口（复用 `harness.approval` 管道，附加 agent_path 冒泡链）

为什么是独立组件：

- 它是唯一的协调者，所有其他组件被它编排；与 registry（存储）、
  context（构造）、limits（准入）职责不同层
- 参照：Codex `AgentControl`（每 root 树一个实例，session 级共享）

关键约束：

- 作用域为 root run 树：同一实例被整棵子 agent 树共享，registry 不按
  全局进程作用域
- 不持有 agent loop；执行一律经 RunHandle → `run_agent(AgentRunSpec)`

### 2. AgentRegistry（寻址与拓扑）

职责：

- `AgentPath` 层级寻址（`/root/research/auth`），相对名与全路径解析
- 两阶段 reservation：spawn 时先预留 path（防并发同名冲突），run 建立
  后 commit；失败自动回滚
- agent 树拓扑：parent→child 边、子树枚举、按前缀列举
- 逻辑映射：path ↔ 运行载体引用（物理执行由 RunHandle 持有，registry
  只存映射与元数据：type、状态、创建时间）

为什么是独立组件：

- 寻址与拓扑是纯数据问题，与 spawn 协调、执行载体解耦
- 两阶段预留是并发安全的独立关注点
- 参照：Codex `agent/registry.rs`（reserve_spawn_slot / commit）

### 3. SubagentRunHandle（运行载体）

职责：

- 每个子 agent 一个载体：持有当前 run 的 asyncio task、cancel token、
  事件订阅，驱动多轮 run（子 agent 生命周期内可能经历多次
  `run_agent()`，不是一次性调用）
- `deliver(message)`：把 input 消息转为下一轮 run 输入或当前 turn
  的 steering；目标 agent 处于 idle / 已完成未关闭状态时，deliver 自动
  驱动新一轮 run（消息驱动唤醒，见
  [ARD-002](./ARD-002-async-execution-and-recovery.md)）
- `interrupt()` / `close()`：中断当前 turn、关闭并释放；close 后 agent
  不可再寻址（open / closed 区分）
- `await_terminal()`：等待终态（供 wait 与装配层复用）
- 事件流转接：`AgentEventSink` → LifecycleProjection / 装配层消费者
- 恢复语义入口：二期引入驻留回收后，被回收 agent 经消息透明重载
  （状态已外置、父子边保持 open，Codex v2 语义）

为什么是独立组件（评审新增）：

- 原清单缺失：`run_agent()` 是一次性 async 调用，谁持有 task、谁接
  事件流、interrupt 找谁的 cancel token、同步 spawn 谁聚合结果，都
  需要明确归属
- 对照：Codex `CodexThread`（ThreadManager 托管）、cc `LocalAgentTask`
  （任务表 + runAsyncAgentLifecycle）
- 编排参照：`HostRuntime` 的 run/abort/wait_for_idle/dispose 生命周期

关键约束：

- 取消传播双模式：**同步（前台）子 agent** 的 cancel token 链接父 run
  （父取消传播）；**异步（后台）子 agent** 不链接父——父被取消不杀
  后台子 agent，只能显式 interrupt/close（cc 的 ESC 语义）

### 4. SubagentContextFactory（上下文构造）

职责：

- 从父上下文构造子 agent 的隔离上下文：默认全隔离（消息、策略状态、
  denial 计数），显式 opt-in 共享
- fork 档位实现：`none`（零上下文）/ `all`（全量历史）/ `last N turns`
- fork 历史过滤：只保留 system / user / final-assistant 消息，丢弃工具
  中间态与 multi-agent 自身的控制消息
- 装配 AgentRunSpec：裁剪后的工具集、类型系统提示、模型覆盖
- **审批冒泡装配**：子上下文的审批回调闭包固定绑定 root 交互出口，
  ApprovalRequest 附加 agent_path 冒泡链（评审修订：原 ApprovalBubble
  组件降级为本契约）

为什么是独立组件：

- "子 agent 看到什么"是最复杂也最容易出安全问题的关注点，必须独立于
  协调逻辑可测试
- cc 的教训（`createSubagentContext`）：默认隔离、显式共享、但任务注册
  必须穿透到 root——这条纪律属于本组件的契约
- fork 的 watermark 确定性与可选 cache 前缀透传
  集中在这里

关键约束：

- 语义历史确定性是硬约束；字节级前缀一致是可用时采用的 cache 优化
- 审批/策略状态默认不继承；继承项必须显式声明
- 子 agent 不得自行发起交互；交互出口在 root（呈现由装配层决定）

### 5. AgentInputFacade（通知与等待门面）

职责（评审修订：基于 HostInputQueue 的门面，非平行队列）：

- 以 `HostInputQueue` 为底层机制：send_message 的投递按语义映射为
  `follow_up`（不中断、下轮消费）或 `steering`（注入当前 turn）
- 通知合成：子 agent 终态时合成完成通知（终态消息、usage、时长），
  投递到父 input
- `wait_agent` 语义：watch **自己**队列的 activity（消息到达 / 完成
  通知 / steer 统一唤醒），不轮询子状态；超时边界由策略参数控制
- 每个 agent 的逻辑 input 视图：跨多次入队的消息序列

为什么是独立组件：

- 通知模型是 multi-agent 的统一同步原语；与 registry（谁知道谁）、
  control（何时触发）解耦
- "wait 等自己 input" 是 Codex 验证过的简化：把等待语义统一为单一
  事件源
- 参照：Codex `multi_agents_v2/wait.rs`（InputQueueActivity watch）、
  cc `enqueueAgentNotification`

关键约束：

- 先写终态事实，再做收尾（清理、汇总）——cc gh-20236 教训：状态转移
  不得被可能挂起的收尾操作阻塞
- open / closed 区分：send_message 到 idle / 已完成未关闭的 agent =
  自动唤醒新一轮 run；到已 close 的 agent = 结构化工具错误（不可寻址）

### 6. Limits（并发、深度与驻留）

职责：

- 名额 = open agent 数：spawn 预留时获取、close 时释放；持有期内
  活跃/空闲切换不计数（agent 数被上限封住，并发 turn 数被同一上限
  封住，一期无 per-turn 闸门）；超限向调用方返回结构化错误
- depth 上限：超过 spawn depth 拒绝派生（结构性递归防护）
- 驻留与回收：已完成 agent 仍占名额直至 close 或 idle 超时；满载时按
  LRU 回收 idle 完成的 agent（其状态已外置，可经 RunHandle 恢复）
- 策略参数入口：上限值由装配层注入，组件不硬编码默认值

为什么是独立组件：

- 资源准入是独立的横切关注点，与"如何 spawn"（control）和"spawn 后
  看到什么"（context）解耦
- 参照：Codex `execution.rs`（AgentExecutionLimiter）、`residency.rs`
  （V2Residency LRU）

关键约束：

- 准入失败是正常工具结果，不是异常——模型可以据此调整策略
- 回收只针对状态已外置的 agent；运行中 agent 不可回收

### 7. LifecycleProjection（状态机与事实发射）

职责：

- 子 agent 生命周期状态机：`pending → running → completed | failed |
  interrupted | closed`，由 RunHandle 转接的 run 事件与终态推导
- 向装配层发射事实：spawn、状态变更、终态（含终态消息、usage、时长）
- agent 树事实的持久化接缝：父子边、终态，供装配层（或 work）投影为
  业务事件；本组件只发射技术事实，不写 work event log

为什么是独立组件：

- "状态是什么"与"如何改变状态"（control）分离，使 UI / 审计 / 业务
  投影共享同一事实源
- 参照：Codex `agent/status.rs`（从事件流推导 AgentStatus）

关键约束：

- 终态消息是技术事实；是否构成业务"产物"由装配层 / work 判定

### 8. ToolSurfaceAdapter（工具面适配）

职责：

- 把 control / agent input facade / registry 的能力封装为 agent 工具：
  `spawn_agent` / `send_message` / `wait_agent`（三件套起步）
- 参数严格校验（类型白名单、fork 档位、目标寻址）
- 工具结果结构化（spawn 引用、投递回执、wait 活动摘要）
- 准入失败、类型非法等返回正常工具错误结果（非异常）

为什么是独立组件：

- 机制（control）与模型可见面（工具 schema、提示纪律）是不同变化频率
  的关注点；工具面可被产品裁剪（暴露子集、限制类型白名单）
- 参照：Codex `multi_agents_v2/spawn.rs` 与 `AgentControl` 的分离

关键约束：

- 本组件是 multiagent 内部唯一依赖 agent 工具框架的位置
- 提示词纪律文本（简报要求、禁止窥探、防 race）是资源，可被 OEM 替换

## Component Relationship

```text
ToolSurfaceAdapter
  -> MultiAgentControl
      -> Limits                 (准入)
      -> AgentRegistry          (寻址、预留、path↔handle 映射)
      -> SubagentContextFactory (构造 AgentRunSpec、审批冒泡装配)
      -> SubagentRunHandle      (运行载体：task/cancel/事件转接/多轮驱动)
          -> harness.run_agent  (执行)
          -> harness.host.HostInputQueue (经 AgentInputFacade)
      -> AgentInputFacade      (通知合成、投递、wait 唤醒)
      -> LifecycleProjection    (状态推导与事实发射)
```

装配层位于 ToolSurfaceAdapter 之上：注入类型注册表、策略参数、事件
消费者，决定工具面暴露范围。

## Non-Candidates（明确不列为组件）

- **Agent loop / turn 执行**：属 `loushang.agent`，经 harness 复用
- **审批管道**：`harness.approval` 已有 ApprovalRequest 管道；审批冒泡
  是 ContextFactory 装配 + Control 执行的一条规则，不是新组件（评审
  修订）
- **输入队列**：`harness.host.HostInputQueue` 已有 steering/follow_up
  语义；AgentInputFacade 是其上的门面，不是新队列（评审修订）
- **Agent 类型资源解析与编译**：类型对 multiagent 只是注入的
  `AgentTypeRecord`；资源加载属产品装配层，method 角色编译属 method
- **业务编排（stage join、acceptance 判定）**：属 method / work
- **事件持久化与 replay**：multiagent 只发射技术事实；持久化属装配层
  或 work
- **UI 面板**：属 harnesstui / 产品 UI，消费 LifecycleProjection 的事实
- **远端 Agent client / wire transport**：由 Product/Host 装配并注入；
  Channel 不承载 Agent RPC。一次性 capability 与异步 job 不进入
  multiagent，持续协作 adapter 也不成为 multiagent 内核组件，见
  [Remote Agent Capability Boundary](remote-agent-capability-boundary.md)

## Open Questions（留待拍板 / 组件设计）

1. ~~AgentInputFacade 与内核 pending queue 关系~~（评审已答：AgentInputFacade 复用
   HostInputQueue，与内核无关）
2. ~~同步 spawn 是否一期支持~~（已拍板：一期全异步 + 通知，无同步
   spawn；见 [ARD-002](./ARD-002-async-execution-and-recovery.md)）
3. ~~驻留回收后恢复的触发时机~~（已拍板：消息驱动自动恢复，不引入显式
   resume 工具；一期不做回收，idle agent 的 send_message 即唤醒；见
   [ARD-002](./ARD-002-async-execution-and-recovery.md)）
4. ~~AgentPath 与 session id 映射归属~~（评审已答：registry 存逻辑
   映射，RunHandle 持物理执行）

全部已关闭；后续问题在组件设计与 ARD 中展开。

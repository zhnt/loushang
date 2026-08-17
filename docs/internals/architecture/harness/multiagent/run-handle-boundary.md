# Multi-Agent Run Handle Boundary

> Status: **implemented**（已实现，与 `SubagentRunHandle` 代码一致）。本文定义
> `loushang.harness.multiagent` 的子 agent 运行载体边界。

## Scope

`SubagentRunHandle` 是每个子 agent incarnation 一份的运行载体：它把
一次性的 `run_agent()` 调用组织成跨多轮、可投递、可中断、可关闭的
session-owned 执行实体。它持有的是 incarnation-safe `AgentRef`，
不只是一条可复用的 path。

本文定义：

- 运行载体的职责与接口
- 多轮 run 的驱动模型（输入如何变为新一轮 run）
- 取消 / 中断 / 关闭语义（ARD-002 异步双模式）
- 事件转接与终态产出
- 恢复入口（二期回收语义的挂点）

本文不定义：

- AgentRunSpec 的构造规则（属 SubagentContextFactory）
- 消息如何到达 handle（属 AgentInputFacade / Control）
- 状态机推导与事实发射（属 LifecycleProjection）
- 并发名额与回收决策（属 Limits）

## Why A Dedicated Handle

`run_agent(spec)` 是一次性 async 调用：给一个 `AgentRunSpec`，返回
`AgentRunResult`。子 agent 需要的能力超出单次调用：

- 生命周期内经历**多轮** run（初始 turn、消息唤醒的后续 turn）
- 运行中可被**投递消息**（下一轮输入或当前 turn steering）
- 可被**中断**（停当前 turn，实体存活）与**关闭**（实体释放）
- 事件流需要持续转接给状态机与装配层消费者

这些职责不属于 `run_agent()`（一次性），也不属于 MultiAgentControl
（协调多 agent 的控制面），因此独立为 RunHandle。

参照：Codex `CodexThread`（ThreadManager 托管的线程句柄）、cc
`LocalAgentTask`（任务表条目 + 后台生命周期闭包）、harness
`HostRuntime` 的 run / abort / wait_for_idle / dispose 编排。

## Interface

```text
SubagentRunHandle
  # 身份
  agent_path: AgentPath            # 逻辑寻址（registry 持有映射）
  agent_type: AgentTypeRecord      # 类型裁剪视图

  # 投递与驱动
  async deliver(message: AgentInputMessage) -> DeliveryOutcome
      # open 且 idle/终态 → 驱动新一轮 run（消息驱动唤醒，ARD-002）
      # open 且 running → 按消息语义走 steering / follow_up
      # closed → 结构化错误（不可寻址）

  async enqueue(message: AgentInputMessage) -> DeliveryOutcome
      # 只进入既有队列，不启动新一轮；完成通知默认走此路径

  # 控制
  async interrupt() -> SubagentStatus    # 停当前 turn，实体存活
  async close() -> HandleCloseResult     # 释放本 incarnation

  # 等待
  async await_terminal(timeout: Seconds | None) -> SubagentStatus
      # 等待终态；不改变投递语义（wait_agent 的门面在 AgentInputFacade）

  # 状态
  status: SubagentStatus                  # 当前状态（由事件推导）
  events: EventSubscription               # 事件订阅入口（转接给
                                          # LifecycleProjection / 装配层）
```

关键形状说明：

- `deliver` 是会唤醒的普通输入口：spawn 初始简报与 send_message
  经它进入运行实体。`enqueue` 是同一 driver/queue 上的非唤醒入口，
  默认用于完成通知，避免 recipe 自己汇总时又意外启动父轮次。
- 每轮恰有一个由 handle 持有的 `asyncio.Task`。首轮和消息唤醒的后续
  轮使用同一条 `_run_owned_round` 观察路径，不允许 adapter
  `create_task()` 后只保存状态、不保存 task。
- `await_terminal` 只等待、不消费消息：等待原语的"唤醒"语义由
  AgentInputFacade 以 HostInputQueue activity 实现，handle 不重复实现。
- `await_terminal` 是 host/recipe 的内部等待口，不等同于模型工具
  `wait_agent`；后者仍等待调用者自己的 input activity。
- `events` 是转接而非源头：源头是 `run_agent()` 的 `AgentEventSink`
  回调，handle 把它组织成可订阅流。

一期用一个窄的 `SubagentRoundDriver` 适配既有 Product session /
`HostRuntime`：

```text
deliver(message)
run_round(round_id, prompt | continue) -> SubagentRoundResult
abort()
dispose() -> SubagentDisposeResult
```

这不是可 attach 的 `AgentExecutionPort`，也不承诺跨进程恢复。driver
必须保证：已经接受到当前轮的 follow-up，在 `run_round()` 返回终态前
已由既有 queue/agent-loop 语义消费；handle 不建立第二套 input queue。

Product factory 不再通过 driver 上的约定俗成属性泄漏可选能力，而是
显式返回：

```text
SessionSubagentBinding
  driver: SubagentRoundDriver
  input_activity: AgentInputActivityPort | None
  workspace_ref: str | None
```

同样，workspace 释放结果由 `SubagentDisposeResult.released_workspace`
返回。`SessionMultiAgentRuntime` 不使用 `getattr` 探测 `input_facade`、
`workspace_ref` 或 `released_workspace`。这个 binding 只描述当前
in-process、session-owned 组合，不是远端 wire schema。

## Product Injection Seams（参数化与扩展）

RunHandle 的机制是产品中立、写死的；但以下行为是**产品可注入的缝**，
由装配层（产品或 OEM 经扩展贡献）提供，handle 不内置默认值：

| 缝 | 注入内容 | 默认（harness 提供） | 扩展面 |
|---|---|---|---|
| `RunDriver` | 如何执行一轮 run | `harness.run_agent(AgentRunSpec)` | 产品可替换（如加 product hooks）；扩展点类型 `tool`/`hook` |
| `SnapshotCodec` | 二期回收的状态外置编码 | 无（一期不回收） | 产品/OEM 提供快照编解码，决定哪些状态外置 |
| `EventDecorator` | 事件转接时的产品级装饰/过滤 | 原样转接 | 产品可注入装饰器链（如附加 product 元数据） |

不在本组件的缝（避免双重定义）：`TerminalFactMapper` 归
LifecycleProjection（事实由它 shape，handle 只转接原始 result）；
`DeliveryPolicy` 归 AgentInputFacade（QueueKind 映射发生在入队时）。

注入方式：

- **产品装配层**：构造 Control 时经 `MultiAgentPolicy` 参数传入各缝的
  实现；harness 提供上表中的默认实现，产品按需覆写。
- **OEM / extension**：经 harness 既有扩展贡献机制
  （`ExtensionSurfaceDescriptor`，`tool` / `hook` / `policy` 面）贡献
  缝实现；优先级与冲突解析复用 extensions 的 priority / before / after
  排序，不新发明机制。
- 缝的实现必须遵守本文件的语义不变式（多轮驱动规则、取消双模式、
  先状态后收尾）；缝注入的是**策略与装饰**，不是语义改写——这是
  "产品装配不破坏内核一致性"（architecture principles 第 8 条）的
  具体落实。

示例（OEM 场景）：OEM 想在事件流中附加其审计系统所需的 trace id——
实现 `EventDecorator` 包装默认转接、追加 metadata，经扩展贡献注册；
handle、状态机、通知合成全部不受影响。

## Multi-Round Driving Model

子 agent 的执行被组织为"轮（round）"序列：

```text
round 1: spec(初始简报) ──run_agent()──► 终态/中断
round 2: deliver(消息)  ──run_agent(continue)──► ...
...
```

驱动规则：

1. **初始轮**由 Control 在 spawn 流水线末尾触发（`deliver(初始简报)`）。
2. **后续轮**只在实体 idle（无活跃 run）时由 `deliver` 触发；实体
   running 时 deliver 不新起 run，而是：
   - system `mailbox`：在下一模型采样安全边界优先注入，不进入用户
     pending-input UI
   - `steering` 语义：经 `AgentLoopConfig.get_steering_messages` 挂点
     注入当前 turn 的下一工具边界（harness host queue 的既有语义）
   - `follow_up` 语义：排队，当前 run 结束后作为下一轮输入
3. 每轮复用 `run_agent_loop_continue` 路径（`AgentRunSpec.mode =
   "continue"`），历史在 `AgentContext.messages` 内累积——handle 持有
   并跨轮传递 context。
4. 一轮终态后，handle 先把终态事实交给 LifecycleProjection，再做收尾
   （"先状态、后收尾"纪律）。
5. 每个 terminal 提交携带 `(AgentRef, round_id)`；close、同 path 新
   incarnation 或新 round 发生后，旧 task 的迟到回调只得到 stale
   transition，不得更新状态或再次投递通知。

这一模型复用并补齐 agent 内核的三个输入挂点
（`get_mailbox_messages` / `get_steering_messages` /
`get_follow_up_messages` / `mode="continue"`）；mailbox 是系统输入通道，
不是第二套 agent loop。

## Cancellation Semantics（ARD-002 双模式）

一期全异步，只有一种模式，但接口按双模式定型：

- **不链接父 run 取消**：子 agent 的 cancel token 独立于父；父被取消
  （用户 ESC）不杀子 agent。`AgentRunSpec.signal` 使用 handle 自有的
  AbortController，不从父 context 派生。
- **显式控制**：
  - `interrupt()` = abort 当前轮（signal.aborted），实体转为
    interrupted，可继续 deliver；它必须 await 被 abort 的 owned task。
  - `close()` = interrupt 当前轮（若有）→ await owned task → dispose →
    提交 closed。关闭调用本身由 shielded owned task 执行，等待它的
    UI/host 调用被取消不会遗留后台 agent。
- **递归归 Control**：Control 先枚举子树，再自底向上调用每个
  RunHandle 的 `close()`；单个 handle 不寻址也不递归关闭后代。
- 后续若引入同步 spawn：同步子 agent 的 signal 链接父 AbortController
  （父取消传播），异步维持独立——接口无需变更，仅 signal 来源不同。

## Event Tap And Terminal Production

- `run_agent()` 的 `event_sink` 由 handle 提供：每个事件先转接给订阅者
  （LifecycleProjection 必须最先订阅，保证状态推导先于装配层消费者
  看到事实），再按订阅顺序分发。
- 终态产出：`AgentRunResult` → 终态事实（status、终态消息、usage、
  时长、tool 计数）。usage / 计数从事件与 result 聚合，handle 不解释
  业务含义。
- `run_agent()` 把普通异常装入 `AgentRunResult(status="failed")`；
  Product driver 负责把该结果映射成 `SubagentRoundResult`。driver
  自身抛出的异常同样被 handle 收敛为 failed terminal，不能成为未观察
  task exception。
- 终态后实体**保持 open**（除非 close）——这是消息驱动唤醒的前提
  （ARD-002）。

## Recovery Hook（二期挂点，一期不实现）

- 一期：无回收，handle 常驻内存直至 close。
- 二期引入 Limits 的 LRU 回收时：
  - 回收前由 Control 触发 `handle.snapshot()`（状态外置，经注入的
    `SnapshotCodec` 编码：context messages、path、type、父子边），随后
    释放 handle。
  - `deliver` 到已回收 path 时，Control 经 registry 找到快照，重建
    handle 并恢复（透明重载，Codex v2 语义）。
  - 回收候选判定也是可注入的（Limits 的策略缝：产品可定义 idle
    超时阈值与保护规则）。
- 因此 handle 的构造必须允许"从快照重建"路径，接口一期就定型
  （`from_snapshot` 可作为二期工厂方法预留，一期不实现）。

## Ownership And Boundaries

拥有：

- 子 agent 的多轮执行组织与 task 持有
- cancel token 所有权与中断 / 关闭语义
- 事件转接与终态转发（原始 AgentRunResult 转给 LifecycleProjection；
  事实 shape 与产品附加字段归 projection）
- open / closed 实体状态（与 LifecycleProjection 的推导状态区分：
  handle 是物理实体态，projection 是事实视图）

不拥有：

- 消息来源与寻址（AgentInputFacade / Control）
- AgentRunSpec 的内容构造（ContextFactory）
- 并发名额与回收决策（Limits 决策，handle 执行）
- 状态机的业务解释（LifecycleProjection）
- agent loop 语义（loushang.agent）
- **各注入缝的具体实现**：RunDriver / SnapshotCodec / EventDecorator
  的实现归产品装配层
  或 OEM 扩展；handle 只定义缝的契约与默认

## Failure Semantics

- run 抛错 → `AgentRunResult(status="failed")` → 实体转为 failed
  （终态），保持 open 可 deliver 恢复（新一轮 run）。
- `deliver` 到 closed 实体 → 结构化错误返回给投递方（经 AgentInputFacade 作为
  工具错误结果，不抛异常）。
- `close` 幂等：重复 close 返回当前状态。
- dispose 返回显式 `SubagentDisposeResult`；workspace 释放快照在提交
  closed 前投影到 Control。结构化 `dispose_error` 或意外抛错最终都随
  `HandleCloseResult.dispose_error` 返回；不得因为资源收尾异常让逻辑
  path 永久占用名额。
- `interrupt` 对 idle 实体是 no-op，返回当前状态。

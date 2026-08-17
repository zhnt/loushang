# Multi-Agent Control Boundary

> Status: **implemented**（已实现，与 `MultiAgentControl` 代码一致）。本文定义
> `loushang.harness.multiagent` 的控制面边界：spawn 流水线、消息路由、
> interrupt / close 的编排。

## Scope

`MultiAgentControl` 是 multiagent 的唯一协调者。它不实现任何具体机制
（上下文构造、队列、准入、执行载体各自独立），而是按确定的顺序编排
这些组件，把"spawn 一个子 agent"、"给某 agent 发消息"这类请求落实为
一系列组件调用。

本文定义：

- 控制面的作用域与持有关系
- spawn 流水线的步骤序列与失败回滚
- send_message / interrupt / close 的路由规则
- 与装配层的接缝（注入点、事件出口）

本文不定义：

- 各组件的内部机制（见各自 boundary 文档）
- 模型可见的工具参数面（属 ToolSurfaceAdapter）
- 并发名额与回收的具体策略（属 Limits）

## Scope And Ownership

- **每 root run 树一个实例**：Control 由装配层在 root run 建立时创建，
  同一棵树的所有子 agent（无论深度）共享它。registry 按树作用域，
  不按进程全局——两棵独立的 root 树互不寻址。
- **持有关系**：Control 持有 AgentRegistry、Limits、各 RunHandle（经
  registry 映射）、AgentInputFacade 的投递口、装配层注入的策略参数
  与事件消费者。
- **不持有**：agent loop（loushang.agent）、历史读取
  （TranscriptRepository，经 ContextFactory 使用）、类型定义
  （AgentTypeRecord，装配层注入）。

## Spawn Pipeline

spawn 请求（来自 ToolSurfaceAdapter 或装配层）按以下固定顺序执行：

```text
spawn(request: SpawnRequest) -> SpawnHandle | SpawnError

 1. 类型解析    按 request.agent_type 查 AgentTypeRecord（装配层注入的
                类型注册表）；未知类型 → 结构化错误（装配期问题）
 2. 准入检查    Limits.ensure_capacity()——并发名额 + depth 上限；
                超限 → 结构化错误（正常工具结果，非异常）
 3. 寻址预留    registry.reserve(agent_path)——两阶段预留，防并发同名
 4. 上下文构造  ContextFactory.build(...)——隔离矩阵 + fork 档（经
                fork_history() 工具函数）+ 审批冒泡装配 → AgentRunSpec
 5. 载体创建    创建 RunHandle（独立 cancel token，ARD-002 异步不链接），
                注册到 registry 映射
 6. 提交预留    registry.commit(agent_path → handle)；任一步失败到此前
                → reserve 自动回滚，无残留
 7. 初始投递    handle.deliver(初始简报)——驱动首轮 run
 8. 事实发射    LifecycleProjection 记录 spawn 事实（path、type、parent、
                时间）→ 装配层消费者
```

关键规则：

- **顺序不可变**：准入在寻址前，寻址在构造前，构造在载体前——任何
  重排都会破坏回滚语义（如先构造后准入会留下未消费的 AgentRunSpec）。
- **失败即回滚**：步骤 3-6 构成预留窗口；窗口内任何失败回滚预留，
  不产生半注册的 agent。这是 registry 两阶段预留的存在理由。
- **步骤 7 的异步性**：deliver 驱动首轮 run 后立即返回（ARD-002 全
  异步）；spawn 的返回值是 SpawnHandle 引用，不是子 agent 的结果。
- **步骤 1-2 的错误是正常工具结果**：类型未知、名额已满都返回
  结构化错误给调用方（模型可据此调整策略），不抛异常。

## Message Routing

`send_message(target, message, kind?)` 的路由规则：

```text
send_message(request) -> DeliveryReceipt | DeliveryError

 1. 寻址解析    registry.resolve(target)——支持相对名（相对调用者
                agent_path）与全路径；未找到 → 结构化错误
 2. 状态判定    经 registry 查目标 handle 的状态：
                - closed       → 结构化错误（不可寻址，ARD-002）
                - 已回收(二期) → 透明重载后按 open 处理
                - open         → 继续
 3. 投递        经 AgentInputFacade 按 kind（follow_up / steering）入队
                目标 handle 的队列；目标 idle/终态 → 触发新一轮 run
 4. 回执        返回投递回执（queued / triggered_new_round）
```

`interrupt(target)`：

```text
 1. 寻址解析 + open 判定（同上）
 2. handle.interrupt()——停当前 turn，实体转 interrupted，保持 open
 3. 返回中断前状态（供调用方确认）
```

`close(target)`：

```text
 1. 寻址解析
 2. 关闭计划    plan_close_tree(target)——鉴权并按深到浅返回不可变快照，
                不提前修改 registry
 3. 自底向上    tree/session owner 对每个快照调用对应 handle.close()：
                interrupt → await task → dispose → commit_closed(ref)
 4. 目标自身最后 close；返回每个 HandleCloseResult
```

规则：

- **close 递归**：关闭父必须递归关闭后代（不留孤儿 agent 占用名额）。
- **物理释放先于逻辑关闭**：`plan_close_tree()` 无副作用；
  `commit_closed(ref)` 只能在该 ref 的 owned task 终止且 driver dispose
  完成后调用。Control 不提供可绕过 RunHandle 的直接 `close_tree()`
  状态突变入口。
- **interrupt 不递归**：中断只作用于目标自身（子 agent 的后代继续
  运行，除非显式逐个中断）。
- **幂等**：重复 close / interrupt 返回当前状态，不报错。

## Event Egress

Control 是 multiagent 事实的唯一出口（经 LifecycleProjection 发射，
Control 触发时机）：

| 时机 | 事实 |
|---|---|
| spawn 流水线完成 | agent_spawned（path、type、parent） |
| RunHandle 状态转移 | agent_status_changed（经 projection 推导） |
| 终态 | agent_terminal（status、终态消息、usage、时长） |
| close 完成 | agent_closed（path、关闭前状态） |

装配层消费者：UI 面板、审计日志、（经装配层投影的）work 业务事件。
Control 不知道消费者的形态。它保证同一 agent 的事实按状态转移顺序
产生；一期消费者是 best-effort，单个消费者失败会被诊断并跳过，不得
中断其他消费者或回滚控制面状态。需要跨进程不丢失时由 Work 的 durable
event log 承担。

## Assembly Injection Points

装配层（产品 / OEM）在创建 Control 时注入：

| 注入 | 内容 | 默认 |
|---|---|---|
| `AgentTypeRegistry` | 类型注册表（AgentTypeRecord 集合） | 空（必须注入才能 spawn） |
| `MultiAgentPolicy` | 并发上限、depth 上限、wait 超时边界 | harness 保守默认 |
| `RunDriver` 等缝 | RunHandle 的各注入缝（见 run-handle-boundary） | harness 默认 |
| `EventConsumers` | 事实消费者（UI / 审计 / work 投影适配） | 无 |
| `ApprovalExitPort` | root 交互出口适配（TUI / RPC） | 装配层必须提供 |
| `TranscriptSource` | fork 历史读取的 transcript 引用 | root run 的 transcript |

OEM 场景：OEM 注入自己的类型注册表（品牌化 agent 类型）、调整
policy 上限、注册审计消费者——Control 机制不变。

## Ownership And Boundaries

拥有：

- spawn 流水线的步骤序列与回滚
- send_message / interrupt / close 的路由与递归规则
- 组件编排（registry、limits、factory、handle、facade 的调用顺序）
- 事实发射的时机（内容属 LifecycleProjection）

不拥有：

- 任何组件的内部机制
- 类型定义与业务编译（装配层 / method）
- 模型工具面（ToolSurfaceAdapter）
- 业务编排与终局判定（method / work）
- 审批的策略判定与呈现（harness approval / 装配层）

## Failure Semantics

| 失败 | 语义 |
|---|---|
| 类型未知 | 结构化工具错误（装配期问题），spawn 不发生 |
| 名额/depth 超限 | 结构化工具错误（正常结果），无预留残留 |
| 预留冲突（同名） | 结构化错误，已有 agent 不受影响 |
| 构造失败（如类型工具为空） | 预留回滚，结构化错误 |
| deliver 失败（首轮启动失败） | handle 转 failed（保持 open 可恢复），预留已 commit 不回滚 |
| close 中某后代 close 失败 | 记录诊断，继续其余后代；目标自身的 close 最后执行 |

纪律：预留窗口（步骤 3-6）内的失败必须回滚；窗口后的失败
（deliver 起）agent 已存在，以 failed 状态呈现而非假装未创建。

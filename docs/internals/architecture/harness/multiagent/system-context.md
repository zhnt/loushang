# Loushang Multi-Agent System Context

> Status: **implemented**（已实现，与当前代码一致）。按
> [Architecture Artifact Model](../../../architecture-method/artifact-model.md) 的分层，
> 本文描述已实现的系统边界与外部实体关系；与代码冲突时以代码
> 与已接受 ARD 为准。

## Scope

本文档将 `loushang.harness.multiagent`（归属决策见
[ARD-001](./ARD-001-harness-ownership.md)：作为
`loushang.harness` 内的子模块，不新建顶层包）视为一个黑盒子系统，
描述它的直接外部子系统、依赖关系与信息流关系。

目标是先确定 multi-agent 运行能力的系统边界，为后续候选组件识别与组件设计
提供落点。

本文不展开：

- multi-agent 内部类型系统与组件分解（见后续 candidate-components 文档）
- spawn / fork / agent input facade 的具体实现
- method 角色编译的规则细节（属 `loushang-method`）
- 工具面的模型可见参数细节（属组件设计）
- 各产品（coding / design / …）如何装配 multi-agent（属产品装配层）

## Positioning

multi-agent 是**技术态**子系统：它提供子 agent 的派生、隔离、通信与生命周期
管控，不理解业务语义（stage / acceptance / artifact）。

与它平行的业务态分层：

- `loushang.method` 定义"该有哪些 agent、按什么流程接力、如何验收"（可选）
- `loushang.work` 拥有业务履约的权威终态与事件日志

multi-agent 不知道 method 的存在；method/work 通过**装配层**消费 multi-agent
的技术能力，并把 agent 终态投影为业务事实。两态各自可独立存在、独立测试：

- 无 method 的轻量场景（"并行查三个问题"）直接使用 multi-agent
- 有 method 的结构化场景由产品装配层把 method plan 翻译为 spawn 计划

## External Entities

收敛后的直接外部实体只保留三类。

### External Systems

- `loushang-harness`
  - multi-agent 的**执行底座**。子 agent 的本体是一次 prepared agent run，
    通过 `AgentRunSpec` / `AgentRunResult` / `run_agent()` 重入执行
  - multi-agent 不实现自己的 agent loop，不复制第二套运行语义

- `loushang-coding`（代表一切产品装配层：coding / design / research / …）
  - multi-agent 的**直接上游装配子系统**
  - 负责把 multi-agent 的工具面暴露给模型、注册 agent 类型、决定并发与
    depth 策略参数、消费子 agent 事件做 UI / 业务投影

### Actors

- `Parent Agent`
  - 逻辑调用主体：正在运行的某个 agent（root 或子 agent），通过工具面
    发起 spawn / send / wait
  - multi-agent 的工具面对它可见

- `User / Host`
  - 间接主体：通过产品装配层接收子 agent 的审批冒泡、取消请求与进度事件
  - multi-agent 不直接面向它，但审批路由与取消传播以其为终点

## Deliberately Not Direct

以下子系统与 multi-agent 有重要关系，但**不在**它的直接边界上：

- `loushang.method`：业务态编排图纸。它通过产品装配层间接驱动 spawn，
  multi-agent 不 import method 类型。
- `loushang.work`：业务权威终态。agent 树的生命周期事实以事件形式输出给
  装配层，由装配层（或 work 自身）投影为 WorkEvent；multi-agent 不写
  work event log。
- `loushang.channel`：明确接纳的 Work/runtime-view operation 与 event
  delivery 边界。子 agent 事件经装配层投影后才可能进入 Channel；
  multi-agent 不产生 RuntimeEventView，也不把 Channel 当作 Agent RPC。
- `loushang.tui` / `loushang.harnesstui`：UI 呈现，消费装配层的事件投影。
- `loushang.ai`：模型调用。multi-agent 不直接调用 ai；模型能力经
  harness → agent → ai 链路到达。

这一收敛遵循
[loushang-agent-system-context](../../agent/loushang-agent-system-context.md)
的同一原则：环境图只画真正跨黑盒边界的信息流。

## Dependency Relations

本节只描述依赖方向，不描述运行时信息流。

```text
product assembly (coding / design / ...) --> multi-agent
multi-agent --> harness
harness --> agent --> ai
```

- `multi-agent -> harness`：子 agent 执行复用 prepared-run contract。
  multi-agent 依赖 harness，harness 不依赖 multi-agent。
- `product assembly -> multi-agent`：产品层装配工具面、类型与策略参数。
  multi-agent 不依赖任何产品包。
- multi-agent 不依赖 method / work / channel / tui。

## Information Flow Relations

### product assembly <-> multi-agent

装配层向 multi-agent 输入：

- agent 类型注册表（类型的工具裁剪、模型偏好、max_turns、isolation、
  may_spawn 等声明；来源可以是内置资源或 method 角色编译产物——对
  multi-agent 而言只是类型记录）
- 策略参数：并发上限、depth 上限、wait 超时边界
- 工具面开关：是否暴露 spawn / send / wait，允许的类型白名单
- 事件消费者：子 agent 进度 / 终态 / 审批冒泡的回调

multi-agent 向装配层输出：

- spawn 事实（agent_path、parent、type、时间）
- 子 agent 状态变更与终态消息（含 usage / tool 计数 / 时长）
- 审批冒泡请求（子 agent 内高风险操作的 approval，路由到 root 交互出口）
- agent 树拓扑（parent→child 边，供 UI 面板 / 审计 / 持久化）

### parent agent <-> multi-agent（工具面）

parent agent 通过工具调用输入：

- `spawn_agent`：类型 + 任务简报 + 可选 fork 档位
- `send_message`：目标寻址 + 消息（可触发 turn）
- `wait_agent`：等待自己 input 的 activity（不轮询子状态）

multi-agent 向 parent agent 输出：

- 工具结果：spawn 的 agent 引用、send 的投递回执、wait 的活动摘要
- input 注入消息：子 agent 完成通知、其他 agent 的消息、用户 steer
  ——统一以 user-role 消息进入 parent 的后续 turn

### multi-agent <-> harness

multi-agent 向 harness 输入：

- `AgentRunSpec`：为子 agent 构造的 prepared run（隔离后的 context、
  裁剪后的 tools、类型系统提示、fork 历史）
- 多轮运行驱动：一个子 agent 在其生命周期内可能经历多次
  `run_agent()`（初始 turn、follow-up 触发的后续 turn、回收后恢复）；
  运行载体（SubagentRunHandle）持有跨多轮的长生命周期，重入的是
  "多轮"，不是一次性调用

harness 向 multi-agent 输出：

- `AgentRunResult` 与运行期事件流（经 AgentEventSink）
- 终态：completed / failed + stop_reason + error

multi-agent 复用 harness 既有机制：

- `HostInputQueue`（steering / follow_up 双模式）作为 input facade 底层
- `ApprovalRequest` 管道承载审批冒泡（附加 agent_path 冒泡链）
- `HostRuntime` 的 run / abort / wait_for_idle / dispose 作为运行载体
  的编排参照

multi-agent 把这些技术终态翻译成自己的子 agent 状态机，但不改变
harness 的 run 语义。

## Functional Boundary

### multi-agent 应承载

- 子 agent 派生（spawn）与寻址（agent path / registry）
- 子 agent 上下文构造：隔离 fork、历史过滤、fork 档位
- agent input facade 与通知注入（完成通知、消息路由、wait 唤醒），底层复用
  `HostInputQueue`
- 并发闸门、depth 上限、驻留 / 回收
- 子 agent 生命周期状态机与 agent 树拓扑
- 异步执行（一期唯一模式，见 ARD-002）；子 agent 为后台运行，不链接父 run
  的取消，只能显式 interrupt / close；close 父时递归 close 后代
- 审批冒泡路由（复用 `ApprovalRequest` 管道到 root 交互出口）

### multi-agent 不承载

- agent loop / turn / 工具编排语义（属 `loushang.agent`）
- prepared-run contract 本身（属 `loushang.harness`）
- 业务编排：stage 流程、acceptance 判定、artifact 语义（属 method/work）
- agent 类型的业务定义与编译（类型对 multi-agent 只是记录；method 角色
  编译属 method，产品默认类型属产品装配层）
- 明确接纳的 Work/runtime-view delivery 与多客户端订阅（属 channel）
- UI 呈现（属 tui / harnesstui）
- 模型调用、provider 差异（属 ai）

## Data Boundary

multi-agent 自有的一等数据（候选，最终以组件设计为准）：

- `AgentPath`：层级寻址（如 `/root/research/auth`）
- `SubagentRecord`：registry 条目（path、parent、type、status、引用）
- `SubagentStatus`：生命周期状态机
- `AgentInputMessage`：通知 / 消息的投递单元
- `SpawnRequest` / `SpawnHandle`：派生请求与句柄
- `AgentTypeRecord`：类型的技术裁剪视图（工具集、模型偏好、隔离、
  may_spawn），不含业务文本

边界上不进入 multi-agent 的数据：

- `MethodPlan` / `WorkRun` / `ArtifactRef`（业务态，留 method/work）
- `AgentRunSpec` 的组装规则之外的产品配置（留装配层）

## Physical Protocol Boundary

- product assembly <-> multi-agent：进程内 API（注册、配置、事件回调）
- parent agent <-> multi-agent：工具调用协议（经 agent 工具框架，
  参数为严格校验的 JSON schema）
- multi-agent <-> harness：进程内 prepared-run contract
  （`AgentRunSpec` / `run_agent()` / `AgentEventSink`）

multi-agent 当前不引入网络协议。未来受管的跨进程 / 远端子 agent
也不预设为可 attach 的有状态 runtime。一次性远端 agent 是普通 admitted
tool/capability：`invoke -> result`，不进入 multi-agent；长时但不可交互的
执行按需增加 `submit / await / cancel` job contract；只有需要 steering、
follow-up 和持续寻址时，才由当前协作工具 façade 绑定 remote collaboration
client。

第一版 collaboration backend 按 Session / capability profile 在本地与一个
远端服务间二选一，不要求同一 agent 树逐 child 混合 placement。只有真实的
混合 placement、attach、lease、fencing 和恢复需求出现，并且至少两个物理
backend 证明共同契约后，才提炼内部 `AgentExecutionPort`。

tool schema 与 worker wire protocol / transport 是两个边界，后者不属于
Channel。`loushang.channel` 只承载其明确接纳的 `WorkOperation`、
`WorkEvent` 和投影事件。对外部独立 agent 的联邦协作可由单独的 A2A
adapter 实现，不与受管 worker 执行协议或 Work 协议合并。完整决策见
[Remote Agent Capability Boundary](remote-agent-capability-boundary.md)。

## Key Boundary Decisions（预告，详见 ARD）

0. 归属：`loushang.harness.multiagent`，不新建顶层包——见
   [ARD-001](./ARD-001-harness-ownership.md)
1. 子 agent 本体 = harness prepared run 重入，不新建执行语义
2. multi-agent 是纯技术态；method/work 只经装配层间接到达
3. 同步原语：wait = 等待自己 input 的 activity，不轮询子状态
4. 审批冒泡统一路由到 root 交互出口，channel 无关
5. 一期全异步执行（无同步 spawn）、消息驱动恢复、open / closed 区分——见
   [ARD-002](./ARD-002-async-execution-and-recovery.md)
6. 远程只决定 placement，不决定生命周期；按 `invoke`、job、collaboration
   的最小交互语义渐进，不预建万能 runtime provider

边界纪律：`harness.multiagent` 不得依赖 method / work / channel / tui，
不得包含产品 agent 类型定义——类型注册表是装配层注入的参数，不是
harness 的资产。

## Conclusion

`loushang.multi-agent` 的直接环境收敛为：

- 上游：`loushang-coding`（代表产品装配层）
- 下游：`loushang-harness`（执行底座）
- 逻辑 actor：`Parent Agent`（工具面调用者）、`User / Host`（审批与取消终点）

method / work / channel / tui 均不进入它的直接边界——业务编排与呈现都
经过装配层投影。这一收敛保证 multi-agent 可以独立于业务态演化，并被
未来任意产品线复用。

# Loushang Work / Method / Channel / Harness 中文实现摘要

## 状态

Draft.

本文档是团队中文评审与 P0-P2 落地入口。完整参考架构见：

- [Loushang Work / Method / Channel / Harness Architecture Draft](./loushang-runtime-architecture.md)

两份文档的关系：

- 英文文档保留完整参考架构，覆盖 extension、memory/context、scheduler、
  provider routing、session store、TUI、playback、upper-level host 等长期能力。
- 中文文档不做逐段翻译，聚焦 P0-P2 的实现边界、接口草案、时序、迁移和验收。
- 如果两份文档出现冲突，先以英文完整参考中的对象边界为准，再同步中文摘要。

当前实现边界比本文档的目标架构更窄：

- `loushang.channel` 仍是目标架构；当前 RPC 是 `loushang.coding.mode.RpcMode`
  transitional surface。
- `loushang.method` / `loushang.work` 是 coding 的相邻子系统；coding 只拥有
  domain bridge 与 work-log integration。
- TUI + method integration 暂不落地，受 ARD-006 约束。

当前边界以已接受的 coding ARD、组件接口文档和代码/测试为准。

## 评审采纳决策

采纳：

- P0 直接新增 `loushang.work` 包，不把 `WorkOperation`、`WorkRun`、
  `WorkEvent` 临时放在 coding 包里。
- `WorkEvent` 增加 `delivery_hint`，区分 `immediate`、`coalesce`、
  `final_only`。
- 补充 work queue 与 harness queue 的状态机和优先级关系。
- 补充 `EventLogBackend` 最小接口，P0 可以先用内存或 JSONL/file backend。
- 补充 `MethodDescriptor` P1 schema、`MethodCompiler`、`MethodProjector` 的最小契约。
- 补充 `SubmitCodingTurn` 时序图和 `AgentEvent -> WorkEvent` 投影规则。
- 补充错误处理、权限 gate、性能目标、持久化策略。
- P2 收窄为 `CodingDomainApp` 快速路径外壳，不做自己的 step/workflow manager。

不采纳或延后：

- 不删除英文文档，也不做整篇双语镜像。双语镜像后续维护成本过高。
- P0-P3 不暴露完整多 agent 公共接口。`AgentLane`、`TaskLedger`、
  `CollaborationBus` 先作为目标概念保留到 P4。
- 不把 P2/P3 简单互换。P2 可以先做薄 domain app 外壳；固定多步骤执行仍在 P3。

## 目标架构

目标仍是把 `loushang` 建模为 method-guided work operating layer：

```text
Hosts / Products / SDK
  CLI / TUI / GUI / HTTP / WebSocket / stdio
  WeChat / Feishu / mini app
  Hermes / OpenClaw / Manus / upper-level orchestrators

        |
        v

loushang.channel
  外部输入归一化
  channel capability
  delivery policy
  outbound delivery

        |
        v

loushang.work
  WorkOperation
  WorkRun
  WorkEvent
  WorkSession
  EventLogBackend
  ApprovalRequest
  ArtifactRef

        |
        v

loushang.method
  MethodDescriptor
  MethodLoader
  MethodRegistry
  MethodSelector
  MethodCompiler
  MethodProjector
  skill-backed method

        |
        v

Domain Apps
  loushang.coding first
  research / cowork / ppt / evolution later

        |
        v

loushang.agent.harness
  one prepared agent turn
  turn phase / snapshot
  steer / follow-up queue
  save point / settled events
  AgentEvent -> HarnessEvent

        |
        v

loushang.agent + loushang.ai
  model streaming
  tool call/result
  low-level AgentEvent
```

核心边界：

- `channel` 负责外部入口和交付，不负责业务运行。
- `work` 负责 run、task、event、artifact、approval、replay，不负责工具细节。
- `method` 负责方法资源、选择、编译和投影，不负责执行。
- `DomainApp` 负责领域工具、策略、artifact 类型和 prompt，不负责通用 work 生命周期。
- `agent.harness` 只执行一次 prepared agent turn，不负责多 agent 或 workflow。
- `agent/ai` 保留底层模型流、工具调用和 `AgentEvent`。

## P0 最小接口草案

P0 使用 dataclass 和 JSON-compatible payload，贴合当前
`loushang.agent` 的 `TypedDict` / dataclass 风格。暂不引入 Pydantic。

```python
@dataclass(frozen=True)
class WorkOperation:
    operation_id: str
    kind: str
    session_id: str | None
    domain: str
    payload: Mapping[str, object]
    source: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkRun:
    run_id: str
    operation_id: str
    session_id: str
    domain: str
    status: Literal[
        "accepted",
        "running",
        "cancelling",
        "completed",
        "failed",
        "cancelled",
    ]
    method_id: str | None = None


@dataclass(frozen=True)
class WorkEvent:
    event_id: str
    kind: str
    run_id: str
    session_id: str
    domain: str
    operation_id: str
    sequence: int
    created_at: datetime
    delivery_hint: Literal["immediate", "coalesce", "final_only"]
    payload: Mapping[str, object]
    source_event_ref: str | None = None
```

`WorkEvent` 默认不嵌入完整 `HarnessEvent`。它保存归一化 payload，并通过
`source_event_ref` 可选关联原始 `AgentEvent` 或 `HarnessEvent`，方便 debug 和
replay。

## WorkEvent 与 AgentEvent 投影

当前 `loushang.agent.AgentEvent` 包含：

```text
agent_start
agent_end
turn_start
turn_end
message_start
message_update
message_end
tool_execution_start
tool_execution_update
tool_execution_end
```

P0 投影规则：

```text
agent_start
  -> AgentInvocationStarted（非终态 fact）

agent_end
  -> AgentInvocationCompleted（非终态 fact）

turn_start
  -> TaskStarted 或 turn-compatible work payload

turn_end
  -> TaskCompleted 或 turn-compatible work payload

message_start
  -> ContentDelta(start), delivery_hint=coalesce

message_update
  -> ContentDelta(delta), delivery_hint=coalesce

message_end
  -> ContentDelta(end), delivery_hint=coalesce

tool_execution_start
  -> ToolCallStarted

tool_execution_update
  -> ToolCallProgress 或 ToolCallCompleted, 取决于是否 terminal update

tool_execution_end
  -> ToolCallCompleted
```

delivery hint 默认：

```text
immediate
  ApprovalRequested
  OperationFailed
  SurfaceRequested
  WorkRunCompleted
  WorkRunFailed
  交互 gate 或终态事件

coalesce
  ContentDelta
  tool progress
  高频进度事件

final_only
  通道或策略只需要最终输出
```

P0 前必须回答的 schema 问题：

- `WorkEvent.kind` 是否完全枚举化。
- `ToolCallProgress` 是否作为单独事件，还是作为 `ToolCallStarted/Completed` payload。
- `TaskStarted/TaskCompleted` 在 single-turn P0 中是否保留，还是延后到 P3。

## EventLogBackend

P0 先定义接口，不绑定数据库。

```text
append(entry) -> EventPosition

query(
  run_id: optional,
  session_id: optional,
  after: optional EventPosition,
  limit: optional int
) -> list[EventLogEntry]

subscribe(
  run_id: optional,
  session_id: optional,
  after: optional EventPosition
) -> async stream[EventLogEntry]
```

`EventLogEntry`：

```text
entry_id
entry_type: operation | event
operation_id
event_id
run_id
session_id
sequence
payload
created_at
```

P0 backend 可选：

- in-memory：优先用于单元测试和回放测试。
- JSONL/file：优先用于本地可检查的 session replay。

不在 P0 做：

- 搜索索引。
- 多租户数据库。
- 跨机器分布式订阅。

## SubmitCodingTurn 时序

```text
User
  -> ChannelAdapter: input text
  -> loushang.work: SubmitCodingTurn
  -> EventLogBackend: append operation
  -> loushang.work: create WorkRun(status=running)
  -> EventLogBackend: WorkRunStarted
  -> CodingDomainApp: prepare coding turn
  -> loushang.method: optional skill-backed method projection
  -> loushang.agent.harness: run one prepared turn
  -> loushang.agent: AgentEvent stream
  -> loushang.agent.harness: HarnessEvent stream
  -> loushang.work: WorkEvent projection
  -> EventLogBackend: append WorkEvent
  -> loushang.channel: deliver by delivery_hint/capability
  -> User
```

调用关系：

- `work` 调用 `method` 选择和投影 method。
- `work` 把 method projection 交给 `DomainApp`。
- `DomainApp` 不自己选择 method。
- `DomainApp` 负责把 method projection 映射成 domain prompt、tools、policy、
  artifacts。

## Method P1 Schema

P1 明确新增 `MethodLoader`，不是“扩展或增加”二选一。`MethodLoader` 可以内部复
用已有 resource discovery helper，但对外是 method-facing loader。

```text
MethodDescriptor
  id
  name
  description
  kind: skill_backed | method_resource
  domain: optional
  source_path
  version: optional
  content
  metadata
```

兼容规则：

- P1 必需字段只有 `id`、`name`、`description`、`kind`、`content`。
- 未知 metadata 字段保留，不拒绝。
- 现有 `skills/**/SKILL.md` 不要求迁移。
- `SkillDescriptor -> MethodDescriptor(kind="skill_backed", id="skill:<name>")`。
- P3 增加 `steps`、`roles`、`gates`、`artifacts` 时必须保持 additive。

最小契约：

```text
MethodCompiler.compile(descriptor, context) -> MethodPlan

MethodProjector.project(plan, step, context) -> MethodProjection

MethodProjection
  system_guidance
  user_guidance
  allowed_skills
  suggested_tools
  expected_artifacts
  approval_gates
```

P1 的 `MethodCompiler` 可以永远返回 single-step plan：

```text
MethodPlan
  mode: single_turn
  steps:
    - id: main
      executor: current_agent
      projection: inject method content as guidance
```

## 双队列协调

两个队列的边界：

```text
WorkQueue
  决定哪个 run 或 operation 可以执行。

QueueController / harness queue
  决定当前 single-agent turn 内部 steer/follow-up 顺序。
```

work-level 状态：

```text
idle
  -> accepting
  -> running
  -> cancelling
  -> draining_harness
  -> dispatching_queued
  -> running

running
  -> completing
  -> completed

running
  -> failing
  -> failed

cancelling
  -> cancelled
```

harness turn 状态：

```text
idle
  -> running
  -> settling
  -> settled

running
  -> cancelling
  -> settling
  -> cancelled
```

规则：

- `work` 是 `WorkRun` 状态唯一 owner。
- `agent.harness` 是一次 prepared turn 内部 queue 的唯一 owner。
- `work` 可以 enqueue/cancel/start harness turn，但不直接改 harness queue。
- `harness` 可以发出 settled/cancelled fact，但不能自己调度新 `WorkRun`。
- 如果 WorkQueue 和 QueueController 都有 pending item，先由 `work` 决定当前
  run 是否继续，再由 harness queue 决定这个 turn 内的 steer/follow-up 顺序。

## P0-P4 范围

### P0: WorkRun 包装现有 AgentSession

范围：

- 新增 `loushang.work` 包。
- 新增 `WorkOperation`、`WorkRun`、`WorkEvent`。
- 新增 `EventLogBackend` 最小接口。
- `WorkEvent` 增加 `delivery_hint`。
- 包装现有 `AgentSession.prompt()`。
- 投影 `AgentEvent -> WorkEvent`。
- 定义 work/harness queue 协调规则。

P0 中 `AgentSession` 仍保留：

- prompt construction
- tool execution
- compaction
- extension hooks
- session persistence

P0 中 `loushang.work` 接管：

- operation acceptance
- run id
- work event projection
- event log append
- cancellation coordination
- channel-facing metadata

验收：

- 一次普通 coding session 可以仅通过 `EventLogBackend` entries 重建。
- channel 可以消费 `WorkEvent`，不读取 `AgentSession` 内部状态。
- interrupt/cancel 有确定性状态转换。
- P0 public interface 不暴露 `AgentLane`、`TaskLedger`、`CollaborationBus`。

### P1: Method 资源兼容

范围：

- 新增 `MethodDescriptor`。
- 新增 `MethodLoader`。
- 支持 `SkillDescriptor -> skill-backed MethodDescriptor`。
- 支持 `methods/**/METHOD.md`。
- 支持 `methods/**/SKILL.md`。
- 支持 single-turn `MethodPlan`。
- method projection 注入 prompt。
- `WorkRun` 记录 `method_id`。

### P2: CodingDomainApp 薄外壳

范围：

- `CodingDomainApp`。
- coding operation kind。
- coding artifact types。
- coding policy bridge。
- coding method packs as resources。
- 当前 coding fast path 仍是 `WorkRun(single_turn)`。

不做：

- 不在 `CodingDomainApp` 里实现 step manager。
- 不在 P2 做固定多步骤 workflow 执行。

### P3: Fixed MethodPlan / TaskFlow

范围：

- `MethodCompiler` 多步骤编译。
- `TaskFlow`、`TaskRun`。
- step started/completed events。
- artifact created/updated events。
- approval gates。

### P4: Controlled Subagent

P4 以后再引入：

- `AgentLane`
- `TaskLedger`
- `CollaborationBus`
- read-only reviewer/planner lane
- implementer/tester lane
- result aggregation

P0-P3 不提前把这些做成 public API。

## DomainApp 跨域关系

DomainApp 不直接互相调用。跨 domain 工作由 `loushang.work` 中介。

```text
DomainInvocation
  invocation_id
  source_domain
  target_domain
  task_id
  input_artifacts
  requested_capabilities
  policy

DomainResult
  invocation_id
  status
  output_artifacts
  summary
  diagnostics
```

例子：

- coding workflow 需要资料检索。
- coding method 创建 research task 或 `DomainInvocation`。
- `work` 选择 `research` domain app。
- research 结果以 `ArtifactRef` 返回给 coding workflow。

## 错误、权限、性能、持久化

### 错误处理

- operation 无法接受或路由时发 `OperationFailed`。
- run 终态失败时发 `WorkRunFailed`。
- provider/tool/policy/cancellation/channel delivery failure 都要带 typed reason。
- run-level retry 归 `work`。
- provider/tool-local retry 归下层。
- channel delivery failure 不改变 `WorkRun` 状态，只记录 delivery diagnostics。

### 权限与 Gate

边界：

```text
DomainApp
  声明 risky action 和 policy metadata。

loushang.work
  记录 ApprovalRequest，关联 approval result。

loushang.channel
  渲染 approval UI，或在非交互场景返回 deny/fallback。

agent.harness / tool layer
  等待 decision 后再执行 risky action。
```

coding 高风险类别：

- destructive filesystem changes
- workspace 外 shell command 或大副作用 command
- network 或 credential access
- public API/schema change
- dependency install 或 toolchain mutation
- git push / merge / force update / release

### 性能目标

P0 目标是 guardrail：

- AgentEvent-to-WorkEvent projection 通常低于 10ms，不含 I/O。
- in-memory EventLog append 通常低于 5ms。
- simple file backend append 通常低于 20ms。
- `immediate` event 不进入普通 frame coalescing。
- coding fast path 不能在模型开始 streaming 前增加可见额外步骤。

### 持久化

- P0 可用 in-memory 或 JSONL/file-backed EventLog。
- `SessionAddress` 初期可存在现有 session metadata。
- SQLite 或数据库等到 replay/search 需求超过文件能力后再决定。

## 现有代码迁移

### `AgentSession`

P0 不拆 `AgentSession`。只在外层包装：

```text
AgentSession.prompt()
  -> WorkRun(single_turn)
  -> WorkEvent projection
  -> EventLogBackend append
```

P1/P2 再让 method projection 和 `CodingDomainApp` 从外部装配 prompt/tools/policy。

### `AgentSessionRuntime`

迁移方向：

```text
AgentSessionRuntime
  -> WorkSessionRegistry
  -> SessionController
```

### `QueueController`

保留给 single-agent turn：

```text
QueueController
  当前 turn 内 steer/follow-up。

WorkQueue
  run/operation 级调度。
```

### `RpcMode`

迁移方向：

```text
RPC request
  -> WorkOperation
  -> WorkRun / WorkEvent
```

P0 前必须回答：RPC mode 是长期 channel，还是 transitional channel。

## P0 前必须回答的问题

1. 最小 `WorkEvent` schema 如何投影当前 `AgentEvent`、approval、artifact 和 replay 语义。
2. 哪些 coding command 属于 domain command，哪些属于 shared work command。
3. 当前 RPC mode 是过渡 surface，还是长期 channel。

## 成功标准

第一版成功不是“完整超越所有 agent 产品”，而是：

- coding 快速路径不变慢。
- 每次 coding turn 都有 `WorkRun`。
- 每个关键输出都有 `WorkEvent`。
- EventLog 可以回放一次 coding session。
- method 可以像 skill 一样被发现、启用、禁用、覆盖。
- 普通 skill 可以作为最小 method 使用。
- `CodingDomainApp` 可以作为第一版 domain app 运行。
- 后续 workflow / multi-agent 不需要重写 channel 或 agent loop。

## 非目标

P0-P2 不追求：

- 完整 autonomous team。
- 完整 GUI。
- 所有 channel adapter。
- 完整 self-evolution。
- 复杂 method DSL。
- 替换现有 `AgentSession`。
- public multi-agent API。

第一版重点是把边界立住：

```text
channel handles delivery
work handles run/event/artifact/approval
method handles guidance/plan assets
domain app handles domain execution
harness handles one prepared turn
agent/ai handle low-level model loop
```

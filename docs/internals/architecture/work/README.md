# Loushang Work Architecture

[Architecture](../README.md)

## Status

Canonical compatibility note for the legacy `loushang.work` namespace.

The product-neutral kernel is being migrated to `loushang.harnesswork`; see the accepted
[HarnessWork Architecture](../harnesswork/README.md) and active
[Migration Ledger](../harnesswork/migration-ledger.md). During migration this document remains the
contract for existing Work semantics, while `loushang.work` forwards migrated kernel symbols to the
single canonical implementation.

代码和测试定义当前已实现契约。本文件同时记录目标边界，但所有尚未落地的对象或
语义都明确标为 target；不得把 target 描述当作当前公共 API。

## Definition

`loushang.work` 是 LouShang 的业务工作与方法履约运行时。

Work 是系统对一个已接受业务意图的持久承诺：它必须把该意图推进到一个可判定、
可查询、可回放的终局。使用 Method 时，Work 把已编译、裁剪并绑定的
`MethodPlan` 实例化为一次真实履约；不使用 Method 时，Work 仍可承载普通业务
工作。

简写为：

```text
Method = 做事的方法与可复用过程定义
Work   = 一次业务意图的真实履行及其权威运行事实
```

Work 不是 message、turn、agent invocation 或进程内 task 的同义词，也不是单纯的
event/log/projection 工具包。事件、日志和 projection 是 Work 履行持久承诺所需的
机制。

## Current Owner Boundary

`loushang.work` 当前拥有：

- `WorkOperation` 的接受与 `operation_id` 去重
- `WorkRun` 标识和运行状态
- `WorkPlan*`、`WorkStep*` 生命周期事件
- 严格递增的 run-local event sequence
- 唯一且最后出现的 run terminal event
- domain fact 的相关、发布和 event-log append
- run、plan、step 的查询、订阅和 replay projection
- executor 返回、异常和取消到业务终态的归约
- `ArtifactRef` 与 `WorkStepDeviation` 等通用工作事实

`loushang.work` 不拥有：

- Method resource、选择、编译或 `MethodPlan` 定义
- agent loop、turn、tool-call、abort、wait 或 dispose 的底层实现
- approval/tool policy 的产品规则与 UI 决策
- message transport、delivery protocol 或 terminal interaction
- Coding、Research、PPT 等产品 payload、prompt、错误策略和具体 artifact 类型

依赖方向必须保持 product-neutral：Harness 和 Agent 不 import Work 类型；产品适配器
把底层运行事件投影成 `WorkEventFact`，由 Work 再赋予 run correlation、sequence、
持久化和生命周期语义。

## Core Model

### Current objects

| Object | Meaning |
| --- | --- |
| `WorkOperation` | 不可变的业务命令；`operation_id` 是接受边界的幂等键 |
| `WorkRunSpec` | 接受时提供的运行元数据与当前固定顺序 step spec |
| `WorkRun` | operation 被接受后的聚合根与权威业务状态 |
| `WorkPlanRun` | 从 plan lifecycle events 重建的 plan read model |
| `WorkStepRun` | 从 step lifecycle events 重建的一次 step occurrence |
| `WorkEventFact` | domain executor 可发布的非生命周期业务事实 |
| `WorkEvent` | 已被 Work 相关、排序并持久化的权威事件 |
| `ArtifactRef` | 实际产物的轻量引用，不规定产品内容或渲染行为 |
| `WorkStepDeviation` | 一次 step 履行相对方法预期的偏差事实 |

当前 `WorkRunSpec.steps` 和 `WorkStepSpec` 只表达固定顺序 steps；
`WorkPlanRun` 仍按 `plan_id` 投影，尚未直接携带 `run_id`。因此在完成 run-bound
plan identity 之前，调用方不得跨 run 复用会产生歧义的 `plan_id`。

### Target objects

以下是演进方向，不是当前公共 API：

| Target object | Intended meaning |
| --- | --- |
| `WorkPlanSpec` | 针对一个 run 冻结的履约清单，由可选 `MethodPlan` 经产品绑定产生 |
| `WorkInput` | active run 接受的动态输入及其 disposition，例如 steer、follow-up、reject |
| `InvocationRef` | Work step 与 Harness/Agent invocation 的相关引用，不把 invocation 生命周期提升为 Work 生命周期 |
| `WorkOutcome` | 可结构化验证的业务结果、失败或取消结论 |
| `WorkPlanRevision` | 保留原始计划与证据链的显式计划修订，而不是静默改写历史 |

Target `WorkPlanSpec` may carry opaque Product capability requirement facts that
were bound by the Product work preparer. Work preserves and correlates those
facts with the run/step but does not resolve Product Capability Bundles,
Capability Packs, tool definitions, or authorization. The Product executor
performs that resolution before invoking Harness.

目标语义关系是：

```text
WorkOperation 1 ---- 1 WorkRun
WorkRun       0 ---- 1 WorkPlanRun
WorkPlanRun   1 ---- n WorkStepRun
WorkStepRun   0 ---- n InvocationRef       (target)
WorkRun       0 ---- n WorkInput           (target)
WorkRun/Step  0 ---- n ArtifactRef
```

重试不得重开已终态 run；它应创建新的 operation/run，并通过 target
`retry_of` 关系保留因果链。父子 Work 同样应使用显式关系，而不是复用一个 run
的生命周期。

## Lifecycle Contract

### Run state machine

当前正常状态机为：

```text
accepted -> running -> completed
                    -> failed
           running -> cancelling -> cancelled
                                 -> failed
```

`completed`、`failed`、`cancelled` 是权威业务终态。`orphaned` 是 replay
启动时对未完成历史 run 的恢复分类，不是 domain executor 可以选择的正常业务
结果，也不对应一个正常 terminal event。

### Invariants

每个 run 必须满足：

1. operation log entry 的 sequence 为 `0`，后续事件严格递增。
2. `WorkRuntime` 是 `WorkRun*`、`WorkPlan*`、`WorkStep*` 生命周期事件的唯一发布者。
3. domain executor 只能发布非生命周期 `WorkEventFact`。
4. executor 正常返回决定 success；异常决定 failure；`CancelledError` 或成功完成的取消协议决定 cancelled。
5. step 和 plan 存在时，step terminal 先于 plan terminal，plan terminal 先于 run terminal。
6. run terminal event 恰好一个，并且是该 run 的最后一个事件。
7. terminal 后不得再 append domain fact 或 lifecycle event。
8. 取消所需的 domain subscription、invocation 或 task 必须恰好 settle/dispose 一次。

`agent_start`、`agent_end`、`turn_start`、`turn_end` 和 tool events 只能投影为
非终态 invocation/turn/tool facts，或者被过滤。它们不能再次产生
`WorkRunStarted` 或任何 `WorkRun` terminal event。

### Settled

Settled 描述“该 Work 已没有仍可能改变结论的在途责任”，不是另一个公开终态。
当前实现主要通过 executor 完成和取消握手保证 invocation settle。目标完整截点
要求同时满足：

- run 的动态输入窗口已关闭；
- 每个已接受输入都有明确 disposition；
- 与当前 step 绑定的 invocations 已结束或完成取消；
- current step 已终态，随后 plan 已终态；
- run terminal event 最后写入 event log。

动态输入窗口与 `WorkInput` 尚未落地，因此当前代码只实现了上述语义的一个子集。

## Work, Message, Turn, Task And Invocation

这些概念属于不同层级：

| Concept | Owner | Relation to Work |
| --- | --- | --- |
| message | Channel/product conversation | 传输或会话内容；可触发 operation，也可成为 active run 的输入 |
| steer | Harness/Agent delivery mechanics | 尽快送入当前 invocation；目标上记录为同一 run 的 `WorkInput` disposition |
| follow-up | Harness/Agent delivery mechanics | 排队等待当前边界后送达；是否属于当前 run 由产品/Work 输入策略决定 |
| turn | Harness/Agent conversation runtime | 一次模型交互边界；一个 Work 可跨多个 turns，一个 turn 也不天然等于 Work |
| task | Harness/Agent execution mechanics | 进程内执行/等待/取消句柄；不等于 Method task 或 `WorkStepRun` |
| invocation | Harness/Agent | 一次底层 agent 调用；可由 step 相关，但不拥有业务终态 |
| `MethodStep` | Method | 可复用过程定义中的步骤 |
| `WorkStepRun` | Work | 该步骤在某次真实履约中的 occurrence 和状态 |

因此，steer/follow-up 不会让 Work admission 失去意义。若它们只是在推进一个已接受
的业务意图，就进入现有 run 的输入策略；若它们提出新的、可独立判定终局的业务
意图，就应形成新的 `WorkOperation`，重新经过 admission。

Codex 等客户端显示的临时 checklist 或 plan update 也不自动成为 `MethodPlan` 或
`WorkPlanRun`。只有产品显式绑定、由 Work 接受并纳入权威生命周期后，它才是
可回放的 Work plan。

## Admission And Approval

Work admission 回答“系统是否接受并承诺推进这项业务工作”，可涉及幂等、容量、
并发、single-flight（某个 policy scope 同时至多一个 active run）、租户或会话
规则。当前只实现 operation 去重和运行接受；更完整的 admission policy 是 target。

Approval 回答“某个具体动作是否获准执行”，通常涉及工具权限、安全和人工确认。
其 product-neutral request/response mechanics 属于 Harness，产品 policy 与 UI
解释属于产品层；Work 只记录与 run/step 相关的 approval facts 以及它们对业务结果
或偏差的影响。

两者可能串联，但不能合并：Work 可以被接受后在某一步等待 approval；approval
通过也不会创建新的 Work；admission 通过更不表示所有工具动作已获批准。

## Relation To Method

Method 定义一类工作应如何完成；Work 拥有某次工作实际如何发生。

```text
method resource
  -> Method selection / compile / tailoring
  -> MethodPlan
  -> product binding
  -> target WorkPlanSpec
  -> WorkRun / WorkPlanRun / WorkStepRun
  -> ArtifactRef / deviation / outcome / replay evidence
```

当前 Coding bridge 直接把固定 `MethodPlan` steps 映射为 `WorkRunSpec.steps`。
目标 `WorkPlanSpec` 应成为这次绑定后的冻结边界，隔离 Method 定义演进与已接受 run，
但不要求 Work import Method 类型。无 Method 的 Work 可以直接由产品生成
`WorkRunSpec`，以后再迁到同一 target binding contract。

## SPEM 2.0 Alignment

LouShang 采用 [OMG SPEM 2.0](https://www.omg.org/spec/SPEM/2.0/PDF) 作为方法论
术语与过程结构的参考。SPEM 区分 Method Content 与 Process，并在第 16 章描述把
Process 实例化为 project plan 或映射到 workflow engine 的 enactment 场景。

LouShang 的对应关系是：

- `loushang.method` 接近 Method Content、Process definition、configuration 和 tailoring。
- `MethodPlan` 是已编译、裁剪的 LouShang 过程定义，不是一次真实运行。
- `loushang.work` 接近 process enactment 与具体 plan/run evidence。
- target `WorkPlanSpec` 接近一个具体工作上下文中的 plan instantiation manifest。
- `ArtifactRef` 记录具体 work product instance 的引用。

这里的 Work 不是 SPEM metamodel 中的 `WorkDefinition`，也不是新增的 Method
Element。它位于运行时履约层。项目当前只声明 **SPEM-aligned subset and
terminology**，不声明 SPEM compliance 或 conformance。

### Alignment matrix

| SPEM concern | Current LouShang support | Evolution boundary |
| --- | --- | --- |
| Task, Role, Guidance, Work Product definitions | Method resources 和 projection 部分支持 | 稳定资源引用与版本绑定 |
| Process, Activity, Task Use | `MethodPlan` 的扁平 fixed steps | 保留层次与 occurrence identity |
| Work Sequence | Work 当前只执行固定顺序 steps | 显式依赖、并行、重复和 skip 条件 |
| Plan instantiation | Coding bridge 绑定 `MethodPlan` 到 `WorkRunSpec` | product-neutral `WorkPlanSpec` |
| Process enactment | Work 拥有 run/plan/step lifecycle、event log、replay | 动态输入、条件验证和结构化 outcome |
| Concrete Work Product | `ArtifactRef` 已存在 | expected/actual binding 与验收结果 |
| Variability and deviation | method metadata 与 `WorkStepDeviation` | 显式 plan revision 和完整证据链 |
| Team Profile and resource assignment | 未支持 | 多 agent/resource binding 后再设计 |
| Workflow behavior model execution | 未支持 | 不在近期把 Work 扩成通用 workflow engine |

## Responsibility Matrix

| Responsibility | Owner |
| --- | --- |
| method assets, selection, compile, tailoring, `MethodPlan` semantics | Method |
| operation acceptance, run/plan/step lifecycle, terminal outcome, event log and replay | Work |
| product payload, prompt, domain error policy, concrete artifact and acceptance logic | Coding/Research/PPT 等产品 |
| turn/invocation/tool queues, abort/wait/dispose, approval mechanics | Harness/Agent |
| operation/event transport, framing, delivery and reconnect | Channel |
| terminal input, interaction and rendering | Harnesstui/TUI plus product UI adapters |

跨层事实应通过聚焦 protocol 或值对象传递；禁止新增无法判断 owner 的通用 helper，
也禁止让底层 invocation/session 层依赖 Work 生命周期类型。

## Evolution Order

建议按可独立验证的纵向切片演进：

1. 引入 run-bound `WorkPlanSpec`，冻结 MethodPlan 到 Work 的绑定并修正 plan identity。
2. 引入 `WorkInput` 与 input window，明确 steer/follow-up 的接受和 settled 截点。
3. 引入 condition、expected/actual artifact 和结构化 `WorkOutcome` 验证。
4. 引入显式 plan revision、retry/parent-child correlation，再考虑 graph、parallel 和 multi-agent。

每一切片都必须继续维持唯一终态、terminal-last、严格 sequence、可回放和 import
boundary；不得为未来能力预先创建第二套 Work runtime。

## Non-Goals

- 不在 Work 中复制完整 SPEM metamodel。
- 不把 phase/activity/task/step 硬编码为四套生命周期状态机。
- 不要求所有普通产品 turn 都选择 Method。
- 不把 Work 变成通用 DAG scheduler、workflow engine 或 approval engine。
- 不用 message、checklist、agent end 或 tool completion 推断 Work 成功。
- 不让 Method 直接执行 Harness invocation，也不让 Harness import Work。

## Related Documents

- [Loushang Method Architecture](../method/README.md)
- [Architecture Overview](../architecture-overview.md)
- [Loushang Subsystems](../subsystem.md)
- [Experimental Methodology Notes](../../experimental/methodology/README.md)
- [Coding Domain And Work Projection Objects](../coding/core-data-objects/domain-work.md)

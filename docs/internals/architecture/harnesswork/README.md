# Loushang HarnessWork Architecture

[Architecture](../README.md)

## Status

Status: **accepted; Phase 2 boundary closeout complete**.

2026-08-07 已完成三路独立只读评审：模块/owner 边界、运行时与故障语义、API 与迁移
可实施性。三路结论均为 `accept-with-changes`；高优先级意见纳入后复审均无阻断。同日已
接受此边界并启动 Phase 0.5/1。当前逐文件状态与兼容承诺见
[Migration Ledger](migration-ledger.md)。

本文参考 [Loushang Method Architecture](../method/README.md) 的设计方法，依次明确概念、
当前边界、相邻子系统关系、核心模型、运行时不变量和演进纪律。它讨论将独立的
`loushang.work` 子系统收敛为可选的
`loushang.harnesswork` 扩展。本文同时记录目标边界和迁移纪律；当前实现范围以迁移台账、
代码和测试为准。以下 canonical 文档将在相应 owner 实际迁移时逐步更新：

- [Loushang Method Architecture](../method/README.md)
- [Loushang Work Architecture](../work/README.md)
- [Harness Current Owner Map](../harness/current-owner-map.md)

迁移未完成前，当前代码和测试优先于尚未落地的目标描述。不得把后续 Phase 的 WorkHandle、
typed result 或 crash recovery 当作现有能力。

调研基线：`origin/main` commit `b0410e13`，2026-08-07。

## Definition

HarnessWork 是 Harness 的可选持久履约扩展。它负责把一个已接受业务意图推进到可判定、
可查询、可回放的终局，同时复用 Harness 的执行 scope、工具、审批、取消和 presentation
机制。它不是每个 turn、tool call、agent invocation 或进程内 task 的别名。

## Current Boundary

当前迁移分支已建立 `loushang.harnesswork`，并迁入 types、ports、runtime、event log、
run/plan projection、中立 log inspection CLI，以及 Session/Agent integration owners。
Coding、Channel 已通过各自 adapter 接入 canonical HarnessWork API；生产代码不再
依赖 `loushang.work`。旧包仅保留 symbol-identical forwarding facade，作为有测试约束的
兼容入口。Ontology 的早期 Action adapter 已由 ontology ARD-001 删除；在正式 ActionPlan、
authorization 和 commit contract 成立前不预建替代 bridge。

Harness owner map 继续禁止 Harness import Work/HarnessWork，并把 Method-to-Work preparation、
Product Work execution、存储位置/保留策略和最终投影留给 Product。当前 Method 又复用了
Harness resource/frontmatter mechanics，因此它是“不依赖 HarnessWork 的可选方法层”，而
不是完全脱离 Harness base 的独立发行物。本提案必须通过迁移更新这些边界，不能把目标
描述当作当前事实。

## Proposed Target Boundary

目标架构取消独立的 `loushang.work` **包所有者**，但不取消 `Work` **运行时概念**：

```text
Method = 一类工作的可复用方法与契约
Work   = 一次已接受业务意图的真实履约及权威运行事实
Harness = 产品无关的瞬时执行、能力、工具、审批和控制底座
HarnessWork = Harness 的可选持久履约扩展
```

最终只保留：

```text
loushang.harness       # 基础执行底座，不依赖 HarnessWork
loushang.harnesswork   # 可选 durable Work runtime，依赖 Harness
loushang.harnesstui    # 可选终端适配，依赖 Harness
loushang.method        # 可选方法定义，可复用 Harness resources；不依赖 HarnessWork
loushang.ontology      # 可选业务语义；未来由 Product Action adapter 接入 HarnessWork
```

关键约束：

- `loushang.harness` 不 import `loushang.harnesswork`；
- `loushang.harnesswork` 只使用 Harness 的产品无关公共契约；
- Harness/HarnessWork 公共协议都不包含 Method、Ontology、Coding 等领域类型；
- 未来 Ontology Action 和产品通过 Product-owned integration adapter 注册 Work handler；
  Method 只提供可选结构 projection，最终 binding 与 handler 仍由 Product 拥有；
- `WorkHandle` 归 `loushang.harnesswork`，不是 Ontology/Method 核心类型；
- 不用目录移动掩盖语义变更，现有 Work 不变量必须原样迁移并加强测试。

## Why Consolidate

当前 Work 已经拥有 operation admission、run/plan/step 生命周期、事件顺序、取消、事件日志、
查询、订阅和 replay。它的 executor 又必然使用 Harness 的 task、tool、approval、policy、
interrupt、artifact/evidence 和 presentation 机制。继续把两者视为平级运行时，会长期产生：

- Work cancel 与 Harness abort/dispose 的双重生命周期；
- Work event 与 Harness runtime event 的重复相关和投影；
- Work approval fact 与 Harness approval lifecycle 的桥接样板；
- Work executor、Product adapter 与 Harness capability resolver 的多层转发；
- `WorkHandle`、session handle、subagent run handle 之间模糊的等待和取消语义。

收敛到 `harnesswork` 的价值是让 durable execution 成为 Harness 的一个可选 profile，复用
同一套 execution scope、工具、审批、取消、事件 envelope 和能力绑定，同时保持基础 Harness
轻量、headless、可嵌入。

这不是“所有 Harness turn 都必须成为 Work”。只有系统接受了一个需要独立终局、查询、
回放或恢复的业务承诺时，才创建 Work。

## Package And Dependency Topology

```text
Product / App composition root
  ├── loushang.harness
  ├── loushang.harnesswork       (optional -> harness)
  ├── loushang.harnesstui        (optional -> harness)
  ├── loushang.method            (optional, standalone definitions)
  └── loushang.ontology          (optional, standalone semantics)
```

允许的目标依赖：

```text
harnesswork -> harness public contracts
harnesstui  -> harness public presentation/runtime contracts

Product method-work adapter
  -> method + harnesswork + Product binding

Product ontology-work adapter (future)
  -> ontology + harnesswork

Product composition
  -> 选择并组装上述可选组件
```

禁止的依赖：

```text
harness     -/-> harnesswork / method / ontology / Product
harnesswork -/-> method / ontology / Coding / Channel / Harnesstui / TUI / Agent / AI / Product
method core -/-> harnesswork
ontology core -/-> harness / harnesswork
harnesstui  -/-> method / ontology domain types
```

允许 Method 继续依赖当前已接受的窄 Harness resource/frontmatter mechanics；若未来需要
Method 完全脱离 Harness，必须先下沉该 owner 并增加单独 import gate，不由 HarnessWork
迁移顺带完成。

物理目录不是判断边界的充分条件。只有同时需要领域包与 HarnessWork 类型的代码，才能进入
领域包的 `integrations.harnesswork`；不能把跨层代码塞进 HarnessWork core。

## Ownership

| Owner | Owns | Does not own |
| --- | --- | --- |
| Harness | execution scope、tool/capability、approval mechanics、policy enforcement、interrupt、sandbox、runtime/presentation event envelope | Work admission、业务终局、Method/Ontology 语义 |
| HarnessWork | operation admission、run/plan/step lifecycle、journal mechanics、replay、WorkHandle、cancel/settle、artifact/evidence refs、handler registry | 领域 payload、方法定义、ontology action、产品 policy/default/UI、storage root/provider/retention policy |
| Method | method resource、selection、compile、tailoring、MethodPlan | Work persistence、工具执行、业务终局 |
| Ontology | schema/fact/query/decision/action/outcome 语义，ActionPlan/MutationPlan | Work lifecycle、审批队列、tool/sandbox 实现 |
| Product | 用户意图、领域 payload、capability binding、具体 artifact、错误解释、最终 UI | 通用 Work/Harness 机制 |
| Harnesstui | 中立运行/Work presentation 的终端交互 | Work authority、领域状态解释 |

## Core Model

迁移首先保留当前 Work 模型，而不是从零发明第二套：

```text
WorkOperation       已接受边界之前的不可变业务命令，operation_id 是幂等键
WorkRunSpec         一次运行的冻结输入与可选固定 step spec
WorkRun             权威运行聚合根及业务终态
WorkPlanRun         run 内 plan 的 read model
WorkStepRun         step occurrence 的 read model
WorkEventFact       handler 可发布的非生命周期事实
WorkEvent           已相关、排序和持久化的权威事件
ArtifactRef         产品产物的轻量引用
WorkOutcome         结构化业务结果（target）
InvocationRef       与 tool/agent/host invocation 的相关引用（target）
```

HarnessWork 新增而当前 Work 尚未提供的核心访问对象：

```text
WorkRef             可序列化的稳定引用
WorkSnapshot        actor/policy-safe 的只读运行投影
WorkEventView       actor/policy-safe 的公开事件投影
WorkHandle          绑定 WorkRef 与 authenticated client 的便利句柄
WorkSubmission      admission receipt；wire 上返回引用而不是 live handle
WorkResultRecord    持久化 typed result/error/reconciliation 的 target 记录
```

`WorkHandle` 不是聚合根、数据库记录或 bearer token。它不缓存权威状态，每次查询或控制都
通过 authenticated `HarnessWorkClient`，principal 来自服务端 transport/session binding，
不能由调用参数伪造。HarnessWork 在读取、订阅和控制入口重新执行 scope/policy projection。

## WorkHandle Contract

建议的 SDK 形状：

```python
class WorkHandle:
    ref: WorkRef
    client: AuthenticatedHarnessWorkClient

    async def snapshot(self) -> WorkSnapshot: ...
    async def events(self, *, after: EventPosition | None = None) -> AsyncIterator[WorkEventView]: ...
    async def wait(self) -> WorkSnapshot: ...
    async def request_cancel(self, *, reason: str) -> CancelReceipt: ...
```

约束：

- wire/API/MCP 返回 `WorkSubmission` 或 `WorkRef`，authenticated SDK client 才构造 live
  handle；
- `submit()` 返回只表示 operation 已被接受，不表示已经成功履约；
- `wait()` 是纯观察操作；调用者 timeout、断连或取消本地 await 只 detach waiter，不能取消
  Work。只有授权后的 `request_cancel()` 可以请求改变 Work；
- cancel 是请求，不保证外部 effect 可以撤销；
- approval 不做成无 actor 的 `handle.approve()`，必须经过带 actor、policy 和审计上下文的
  approval command；
- 公共订阅只返回 `WorkEventView`；包含原始 opaque payload 的 `WorkEvent` 只通过受限
  diagnostics port 访问。长连接在授权变更时必须重新投影、拒绝或终止；
- 第一版 WorkHandle 不承诺 `result[T]`。只有 `WorkResultRecord`、codec owner、handler/version
  mismatch、失败/取消/orphan 行为和 restart hydration 测试明确后，才增加 typed result。

## Lifecycle And Invariants

第一阶段原样保留当前权威状态机：

```text
accepted -> running -> completed
                    -> failed
           running -> cancelling -> cancelled
                                 -> failed
```

等待审批、等待输入、重试调用和 reconciliation 初期作为 blocking reason / fact / read
projection 表达，不立即扩张权威状态枚举。只有它们需要独立 admission、查询或恢复规则时，
再通过单独 ARD 修改状态机。

每个 WorkRun 必须继续满足：

1. operation log entry 的 sequence 为 `0`，后续事件严格递增；
2. HarnessWork Runtime 是 run/plan/step lifecycle event 的唯一发布者；
3. handler 只能发布非生命周期 `WorkEventFact`；
4. step terminal 先于 plan terminal，plan terminal 先于 run terminal；
5. terminal event 恰好一个并且最后出现；
6. terminal 后禁止追加事实或生命周期事件；
7. cancel、tool、agent invocation、approval wait 和 task 必须 settle/dispose 一次；只有全部
   Work-scoped responsibility 已完成、取消或被 fencing 后，才能发布 `WorkRunCancelled`；
8. run-level retry 不重开已终态 run，而是创建带 `retry_of` 的新 operation/run；
9. 已记录的 idempotency、external-effect evidence 和 commit/reconciliation 状态必须可回放；
   Phase 1 允许崩溃窗口产生 `effect_outcome=unknown`，并要求 reconciliation，不能声称未知
   external effect 已有证据；
10. handler 终态不能由一次 tool、turn 或 agent invocation 的完成自动推断。

`settled` 仍是“没有在途责任可能改变结论”的内部截点，不成为第四个公开终态。

当前实现在 cancellation unsupported/timeout 等路径上仍可能乐观地产生 cancelled；这是
已知实现缺口。目标归约规则是：`settled` 才能 cancelled；无法证明 settle 时保持
`cancelling`，或者 failed 并先记录 `reconciliation_required`。并发 cancel、正常完成与迟到
callback 必须通过 revision/terminal CAS 选出唯一胜者；多个 cancel 调用者共享同一
cancel receipt/outcome，不能重复驱动底层取消。

两类 retry 必须分开：同一 Work 内的 tool/invocation attempt retry 使用独立 attempt ID 和
effect idempotency key；已终态业务 Work 的重新履约必须重新 admission，创建带 `retry_of`
的新 operation/run。不得用 invocation retry 暗中重开业务终态。

approval wait 至少持久化 approval ref、request fact、resolution fact 和 pending projection。
Work cancel 必须单次 settle pending wait；terminal 后的迟到或重复 approval 只能得到幂等
结果或结构化拒绝，不能追加事件。第一阶段崩溃后仍只能投影 orphan，不根据 approval fact
自动恢复执行。

## Work Is Not A Harness Invocation

HarnessWork 必须保留不同层级的身份：

```text
WorkRun                    durable business enactment
  ├── zero or more tool calls
  ├── zero or more host/agent turns
  ├── zero or more subagent incarnations
  └── zero or more external effects
```

- `WorkHandle`：可重建、面向 durable Work；
- `SubagentRunHandle`：当前实现中的进程内 agent incarnation 和多轮运行载体；
- tool call handle/task：一次底层执行尝试；
- Session/turn：交互和模型运行边界。

一个 Work 可以跨多个 session/turn/invocation。HarnessWork 通过 `InvocationRef`、correlation
ID 和 evidence 关联这些对象，但不把它们提升为 Work 生命周期。除非出现至少两个真实的
非 agent executor 需要统一 run abstraction，否则不新增泛化的 `HarnessRun`。

`InvocationRef` 只表示相关，不授予 abort/close 权限。`SubagentRunHandle` 当前是
session-owned，父 Work 取消不得直接关闭仍可投递或被共享的 agent handle；HarnessWork 只能
通过 Product execution binding 请求 settle 当前 Work-scoped round/invocation。递归 close、
incarnation dispose 和父子 agent ownership 继续属于 MultiAgent Control。

## Handler And Integration Model

Phase 1 原样保留当前已经验证的 split protocols，不提前合并成一个包含 capability、approval、
cancel 和 typed result 的总 Handler：

```python
class WorkExecutionContext(Protocol):
    run_id: str
    step_id: str | None

    def publish(self, fact: WorkEventFact) -> WorkEvent: ...


class WorkDomainExecutor(Protocol):
    async def execute(
        self,
        operation: WorkOperation,
        context: WorkExecutionContext,
    ) -> object: ...


class WorkDomainCancellation(Protocol):
    async def cancel_and_wait(
        self,
        operation: WorkOperation,
        context: WorkExecutionContext,
    ) -> WorkCancellationOutcome: ...


class WorkExecutionBinding:
    executor: WorkDomainExecutor
    cancellation: WorkDomainCancellation | None
```

composition root 或 Product adapter 通过 `WorkDomainExecutionResolver` 为一次已接受 operation
冻结 binding。所需 Harness execution scope、capability 和 approval ports 注入具体 executor，
不塞入 Work context，也不由 HarnessWork 发明尚不存在的公共 Harness 协议。Product 继续选择
journal backend、storage root 和 retention policy；HarnessWork 只提供 journal mechanics。

只有 handler registry、typed result 或 checkpoint/resume 出现真实 fixture 后才逐项扩展
协议。typed result 需要一个明确的 terminal envelope，例如
`WorkExecutionOutcome[T]`，同时携带 terminal disposition、result/error ref 和
reconciliation requirement；external effect 成功而业务 commit 失败时，必须先持久化
result/evidence/reconciliation fact，再发布 failed terminal。后续 repair 是关联的新 Work，
不得越过 terminal-last 向旧 run 续写。

注册示例：

```text
kind                     adapter owner
---------------------------------------------------------
coding.turn              Coding Product adapter
product.method_run       Product Method-to-Work adapter
ontology.action          Product ontology-work adapter (future)
ontology.outcome.observe Product ontology-work adapter (future)
projection.rebuild       owning subsystem integration
```

HarnessWork 不 import 注册者。composition root 构造 resolver/registry 并注入 Runtime。

## Method Integration

`MethodPlan` 仍是定义，不是运行：

```text
Method resource
  -> select / compile / tailor
  -> MethodPlan
  -> optional structural projection
  -> Product work preparer and execution binding
  -> WorkRunSpec / run-bound WorkPlanSpec
  -> HarnessWork Runtime
  -> WorkHandle
```

Method 的可选 HarnessWork helper 最多拥有无损、产品中立的结构投影：

- MethodPlan 到 run-bound Work plan 的冻结映射；
- Method step identity 与定义侧 expected artifact/acceptance criteria 的保留。

最终 capability、具体 artifact acceptance、operation payload、错误策略和执行 handler 仍由
Product work preparer/executor 拥有。Method helper 不能自行注册一个绕过 Product binding 的
通用 `method.run` handler。Method core 不 import HarnessWork；没有 HarnessWork 时，它仍可在
当前 Harness resource 基础上加载、选择、编译和静态验证，但不能声称已经真实履约。

## Ontology Integration

Ontology core 保持独立：

当前没有 Ontology/HarnessWork adapter。早期以 payload 命名 Action、却没有 ActionType、
MutationPlan、authorization、expected revision 和 Fact commit 的 bridge 已被删除。以下是
出现真实多步骤或外部副作用 Action 后才考虑的目标边界，并非当前能力：

```text
ActionRequest
  -> Ontology ActionPlanner
  -> ActionPlan
```

正式 Product adapter 建立后：

```text
ActionPlan
  -> OntologyActionSubmissionAdapter
  -> HarnessWork submit(kind=ontology.action)
  -> WorkHandle
  -> Runtime resolves OntologyActionWorkHandler
  -> approval / Harness capability / tool
  -> Ontology ActionCommitter
  -> Fact + Evidence + Outcome
```

边界要求：

- `ActionType`、`MutationPlan`、`DecisionRecord` 不进入 Harness/HarnessWork 公共协议；
- adapter 保存或引用 ActionPlan，并在 handler 内解释；
- HarnessWork 只看到 opaque payload、capability/approval requirements 和 typed result codec；
- 外部 effect 成功而 ontology commit 失败时，handler 必须在 failed terminal 之前持久化
  evidence 和 `reconciliation_required` result/fact；后续 repair 创建关联的新 Work；
- 简单 ontology-owned 原子 Action 是否允许 inline executor，必须由未来 Action ARD 决定；
  需要审批、外部 effect、多步骤、恢复或补偿的 Action 应通过 Product/HarnessWork 履约。

## Harness, HarnessWork And Harnesstui

HarnessWork 复用 Harness 的：

- capability composition 和 execution scope；
- tool execution、effects 和 sandbox；
- policy/approval mechanics；
- cancellation/interrupt primitives；
- runtime event envelope、diagnostics 和 presentation projection seams。

HarnessWork 自己拥有：

- Work admission 和 idempotency；
- Work lifecycle 与 terminal authority；
- journal、query、subscribe、replay；
- WorkHandle/WorkSnapshot；
- handler resolution；
- Work artifact/evidence correlation。

Harnesstui 只消费中立 presentation projection，例如：

```text
Work waiting for approval -> approval_required presentation
Work retrying              -> progress/status presentation
Work completed             -> result_available presentation
```

Harnesstui 不读取 Method/Ontology payload，也不拥有 Work 状态机。

## Optional Composition Matrix

| Harness | HarnessWork | Method | Ontology | 合法能力 |
| --- | --- | --- | --- | --- |
| yes | no | no | no | 普通 session、agent、tool、approval、capability execution |
| yes | yes | no | no | 通用 durable operations 和 Product handler |
| yes | no | yes | no | Method authoring/compile/static validation；不形成真实 Work |
| no | no | no | yes | Ontology schema/fact/query/decision 和受限 inline Action |
| yes | yes | yes | no | Method-guided durable enactment |
| yes | yes | no | yes | durable ontology Action/Outcome observation |
| yes | yes | yes | yes | Method + Decision + Action + Work + Tool + Outcome 闭环 |

HarnessWork 不支持脱离 Harness 独立安装；这正是取消独立 Work 包后的所有权选择。如果未来
出现不允许依赖 Harness、但又需要相同 durable Work runtime 的第二执行底座，应重新评估
是否提取更低层 kernel，而不是预先保留两个 runtime。

## Persistence And Recovery

当前 `loushang.work` 已有 Memory/JSONL event log、严格 sequence、query、subscribe、replay
projection，并在启动时把未完成历史 run 标记为 `orphaned`。迁移不能把“可回放”夸大为
“可自动恢复”。

目标分两步：

1. **语义等价迁移**：保留当前 journal/replay/orphan detection，不引入恢复承诺；
2. **可恢复执行 ARD**：另行定义 handler checkpoint、lease/fencing、claim、resume、重复投递、
   outbox、external-effect reconciliation 和 store transaction boundary。

在第二步完成前，`durable` 只表示权威运行事实持久且可回放，不表示进程崩溃后必然从中断
步骤继续执行。文档、API 和 UI 必须显示 `orphaned/reconciliation_required`，不能伪装成
自动恢复成功。

## Migration From `loushang.work`

现状不是空目录：`src/loushang/work/` 已实现 types、ports、runtime、event log、projection、
session adapter 和 CLI；Coding 与 Channel 存在直接 imports，tests 也把当前单向边界作为
架构门禁。因此迁移必须分阶段：

### Phase 0: Accept The Boundary

- 三方评审本设计；
- 证明 HarnessWork core 对 Coding、Method、Ontology payload 保持 opaque；
- 建立至少一个非 Coding fixture，优先选择 `ontology.action`；
- 接受后再更新 Harness current owner map、Method/Work canonical docs 和 subsystem diagram。

### Phase 0.5: Freeze The Migration Ledger And Compatibility Surface

- 记录每个现有文件的目标 owner、允许 imports 和必须保留的 public symbols；
- 记录根包及 `types`、`ports`、`runtime`、`event_log`、`run_projection`、
  `plan_projection`、`cli`、`session`、`agent_projection`、`projection` 子模块的 forwarding
  方案；
- 先建立 old/new symbol identity、`__all__`、任意 import order 和 architecture import gates；
- 若承诺 pickle/qualified-name compatibility，加入对应测试，否则明确不承诺；
- 兼容 wrapper 可先指向旧实现，迁移原子提交再反转为指向新 owner；任何时刻都只有一套
  可写 Runtime。

### Phase 1: Move The Product-Neutral Work Kernel

- 创建 `loushang.harnesswork`；
- 优先用 `git mv` 迁移产品中立的 Work kernel：types、ports、runtime、event log 和
  run projection；plan projection 与 CLI 必须先通过下表的中立化门禁；
- `agent_projection.py`、`session.py` 以及 Coding/Channel binding 先按依赖审计分类，不能仅因
  当前位于 `loushang.work` 就整体搬入 HarnessWork core；领域/产品绑定移到对应 adapter，
  只有经过产品中立化的投影或 session port 才可随后迁入；
- 保持事件种类、JSON 字段、sequence 和 terminal invariants；
- 添加架构 gate：Harness 不 import HarnessWork；HarnessWork core 不 import Method、Ontology、
  Coding、Channel、Harnesstui/TUI、Agent、AI 或产品包；可选 integration 使用精确 allowlist；
- 改写迁入文件的绝对 imports，禁止 `harnesswork -> loushang.work` 回依赖；
- `loushang.work` 的根包和已使用子模块暂时成为 forwarding compatibility modules，不形成
  第二套实现。

第一阶段可以移动“大多数”文件，但判断标准是依赖和 owner，而不是文件数量：

| 当前文件/能力 | 初步目标 | 迁移条件 |
| --- | --- | --- |
| `types.py` | `harnesswork` | payload 保持 opaque，不引入 Product/Method/Ontology 类型 |
| `ports.py` | `harnesswork` | executor/context contract 保持产品中立 |
| `runtime.py` | `harnesswork` | 生命周期与 terminal invariants contract 测试原样通过 |
| `event_log.py` | `harnesswork` | JSON/Memory backend 与旧日志兼容 |
| `run_projection.py` | `harnesswork` | replay 结果和 orphan 语义不变 |
| `plan_projection.py` | 修正后进 `harnesswork`，否则留 adapter | 当前含 `SubmitCodingTurn` sentinel；必须改为通用 operation/run identity，并以旧日志 golden replay 证明等价 |
| `cli.py` | 中立 inspect 进 `harnesswork`，其余外置 | 产品路径、命令文案和 presentation 不进入 core |
| `agent_projection.py` | Agent-session/Product integration | 直接依赖 Agent/AI/Harness transcript 类型，不进入 core |
| `session.py` | `harnesswork.integrations.session` 或 Product adapter | 它是 Agent-session execution adapter，不是 durable kernel |
| `projection.py` | compatibility/Agent-session integration | 当前委托 `agent_projection`，不进入 core |
| Coding `domain/work.py` | Coding Product composition | 保留产品 payload 和 executor binding |
| Channel Work codec/binding | Channel core owns typed wire codec; `channel.adapters.harnesswork` owns execution binding | Channel 当前就是显式 Work transport；wire 保持稳定，不预建通用 codec registry |
| 旧根包和子模块 | compatibility forwarding modules | old symbol 必须与新 owner 是同一对象，并带明确弃用周期 |

### Phase 2: Move Adapters And Consumers

- Coding Product adapter 改用 HarnessWork；
- Channel core 继续拥有显式 typed Work envelope/codec，`channel.adapters.harnesswork` 拥有
  execution binding；保留 frame/payload golden JSON 与 unknown/additive field 兼容。只有出现
  第二种真实、非 Work transport 需求后，才重新评估 codec seam；
- Coding Product 已把 Method prepared turns 绑定到 HarnessWork；Method core 保持独立，不新增
  通用 `method.run` handler 或 HarnessWork adapter；
- 等 Ontology ActionPlan/Fact commit contract 成立后再引入 integration fixture；
- 保留序列化兼容和读取旧 Work JSONL 的 round-trip 测试。

### Phase 3a: Add Observable WorkHandle

- 在现有 accept/cancel/query/subscribe ports 之上增加 WorkRef、actor-safe WorkSnapshot、
  WorkEventView 和 WorkHandle；
- wire 返回 submission receipt，SDK hydration 返回 WorkHandle；
- `wait()` 与客户端任务取消解耦；只有授权 `request_cancel()` 才驱动 Work cancellation；
- 加入 cross-actor/cross-scope read/events/wait/cancel 和长连接授权变化测试。

### Phase 3b: Add Persisted Typed Result

- 定义 `WorkResultRecord` / `WorkExecutionOutcome[T]`、codec owner 和 handler/version identity；
- 明确 completed、failed、cancelled、orphaned 和 reconciliation-required 的 result/error 读取；
- executor result 必须先进入权威 journal，再允许 `WorkHandle.result[T]`；
- 验证进程重启 hydration、旧 handler 版本缺失和外部 effect/commit split failure；
- 在此之前不得公开泛型 `result[T]` 承诺。

### Phase 4: Retire The Compatibility Namespace

- 所有内部 imports 和公共文档迁移完成；
- 提供明确 deprecation 周期与替代路径；
- 确认没有外部插件依赖旧 import；
- 删除 `loushang.work` facade；
- 更新 package exports、architecture gates 和发布说明。

任何阶段都不得同时维护可写的 `work` 和 `harnesswork` 两套 Runtime。

## Validation Gates

设计和迁移至少需要：

- 当前 `tests/work/` contract suite 在 HarnessWork 实现和 compatibility facade 上通过；
- 所有已使用旧子模块的 forwarding、old/new symbol identity、`__all__`、任意 import order 和
  `harnesswork -/-> loushang.work` 反向依赖门禁；
- event log 序列化兼容、旧日志 replay 和 corruption diagnostics；
- duplicate operation、terminal-last、cancel-settle/fencing、并发 terminal winner、late event
  rejection；取消 waiter 不改变 WorkRun；
- approval request/resolution/cancel/late-resolution race；
- Harness/HarnessWork/Method/Ontology/Channel/Harnesstui/TUI/Agent/AI/Product import boundary 和
  optional-adapter allowlist tests；
- Coding 当前 Work fast path 和 Channel compatibility tests；
- `plan_projection` 去除 Coding sentinel 后的旧日志 golden replay；
- Channel adapter 的 frame/payload golden JSON、unknown/additive field 和任意 import order；
- 非 Coding 的 opaque handler fixture；
- Ontology 外部 effect 成功、commit 失败、reconciliation required fixture；
- WorkHandle cross-actor read/event/cancel authorization、waiter detach 和 raw-event diagnostics
  隔离；
- Phase 3b 的 typed result restart hydration、handler/version mismatch 和 reconciliation 读取；
- Work cancellation 不直接 close session-owned `SubagentRunHandle` 的 ownership test；
- Harnesstui 仅消费中立 projection 的边界测试；
- `make check-harness`、Method focused tests 和 full non-live suite。

## Non-Goals

- 不让每个 Agent turn 或 ToolCall 自动成为 Work；
- 不把 HarnessWork 做成通用 BPMN/DAG workflow engine；
- 不把 Method 或 Ontology 类型移入 HarnessWork；
- 不让 WorkHandle 代替授权、审批或 Action commit；
- 不把可回放日志等同于跨进程自动恢复；
- 不在本设计中确定数据库、队列或分布式调度技术；
- 不因包名收敛改变业务终态或旧日志含义；
- 不立即删除已实现的 `loushang.work`，也不在未接受设计前更新 current owner map。

## Open Questions

1. `harnesswork` 作为同一 distribution 内模块，还是未来独立 extra/package？第一阶段建议
   保持 monorepo 单 distribution。
2. Work payload/result codec 由 handler、Product profile 还是统一 registry 提供？
3. approval wait 和 dynamic input 是否需要新的权威状态，还是继续作为 blocking facts？
4. recovery ARD 的最小持久 checkpoint 和 fencing contract 是什么？
5. 只有出现第二种真实、非 Work transport 需求时，才重新评估 Channel typed codec 是否需要
   下沉为可注入 seam；在此之前不建设 registry 或 negotiation protocol。
6. `loushang.work` 是否已有外部用户或插件依赖，如何检测并公告 deprecation？

## Adoption Rule

若评审通过，正式采用顺序必须是：

```text
接受 boundary ARD
  -> 更新 current owner map 和 canonical docs
  -> Phase 0.5 文件/符号/依赖账本与 compatibility gates
  -> git mv 产品中立 kernel
  -> 迁移 Product/Channel/Method/Ontology adapters
  -> 引入 observable WorkHandle
  -> 持久 typed result
  -> 再设计 crash recovery
```

不能先移动代码，再用目录结构倒逼架构接受。

## Related Documents

- [HarnessWork Migration Ledger](migration-ledger.md)
- [Loushang Method Architecture](../method/README.md)
- [Loushang Work Architecture](../work/README.md)
- [Harness Current Owner Map](../harness/current-owner-map.md)
- [Harness Multi-Agent Run Handle Boundary](../harness/multiagent/run-handle-boundary.md)

# Loushang Ontology Operational Infrastructure Architecture

## 状态

Draft.

本文是 `loushang.ontology` 的定位、目标边界、参考项目调研和分阶段演进建议，
不是已接受架构，也不代表当前实现已经具备文中能力。若本文与代码、测试、已接受
ARD 或 live architecture 文档冲突，应以后者为准。

多业务系统 StateAuthority、Source View 和 multi-source materialization 的收口方案见
[ARD-003](../ARD-003-declared-state-authority-and-multi-source-materialization.md)。其
materialization-correctness、stable semantic ID、declared StateAuthority、
Memory-only mapped-source 合成、完整 operational origin slice 和 SQLite v3 source
persistence 已实现；change set 与 logic binding 仍未实现。首个 authority-aware Action
规划和 Product-hosted write-back 边界已经由
[ARD-012](../ARD-012-authority-aware-action-planning-and-product-hosted-write-back.md)
接受；其中 ontology-owned `SetProperty` 的 Schema v4、纯规划、guarded Fact commit
和投影刷新纵向切片已经实现，source-backed write-back 仍未实现。

调研快照日期为 2026-08-06。参考仓库只用于本体子系统研发和架构研究，保持只读；
本文的规模数据来自静态文件统计，不等同于测试通过率或生产成熟度。

## 结论

建议把 `loushang.ontology` 定位为：

> 开放、方法原生、Agent 可操作、以决策为中心的 Operational Ontology 基础设施。

它以 Palantir Ontology 的 operational layer 为主要产品参照，但不做 Palantir
Foundry 的逐功能复刻，也不把 OWL 编辑器、图数据库、数据集成平台或环保应用直接
做进内核。Loushang 的差异化应来自四点：

- **开放标准**：以稳定的 operational IR 为内部事实来源，提供 RDF、OWL、
  JSON-LD、SHACL 等互操作桥，而不是把专有存储格式暴露为唯一模型。
- **方法原生**：`Method` 可以引用本体类型、动作、约束和期望工作产物，本体则不
  反向拥有方法执行生命周期。
- **履约原生**：动作结果、证据、失败和审批可以投影为 HarnessWork 持有的
  `WorkEventFact` / artifact，形成可追踪的业务闭环。
- **Agent 原生**：Agent 只能发现和请求显式发布的语义动作；权限、审批、工具执行
  和外部副作用仍通过 Harness 等现有治理边界完成。
- **决策原生**：把选择什么、基于什么、由谁批准、如何执行以及结果如何作为一等
  operational record；对象和动作服务于决策闭环，而不是成为两个互不相连的目录。

一句话概括目标组合：

> Palantir 式 Decision-Centric Operational Ontology + 开放语义标准 + Loushang
> Method / Harness / HarnessWork 的受控决策、执行与证据反馈闭环。

## 当前实现基线

当前 `src/loushang/ontology/` 已完成 versioned schema kernel、Wave 2A
Fact/Provenance spine、[ARD-001](../ARD-001-factstore-semantic-authority.md)
规定的单一权威收口，以及
[ARD-002](../ARD-002-ports-immutable-projection-and-sqlite-v2.md) 规定的 Phase 2
端口和适配器拆分。它已经具备：

- package/namespace/version、类型、接口、约束、编译与 schema evolution；
- asserted/derived/inferred Fact、双时间、provenance、correction lineage；
- append-only Memory/SQLite FactStore、纯 commit planner 和 idempotent FactBatch；
- 确定性 Fact materializer、immutable ProjectionSnapshot 和 typed query；
- source-backed object/property/link 的 versioned binding、mapped snapshot、
  `MaterializationCut`、完整 origin 与显式 freshness；
- 原子 whole-snapshot ProjectionStore replacement，以及独立的 Memory/SQLite adapters；
- 带 `storage_layout=source-aware-projection` 的 SQLite v3 严格格式检测、
  source cut/origin 精确恢复、重启和在线备份；
- Product-hosted `SourceAdapterManifest`、结构化 Adapter protocol 与脱离实现的
  output conformance 校验，以及固定 SQLite ERP 的 Product-side 端到端证据；
- 对精确 FactSelection 的 schema revalidation receipt，可在不修改旧 Fact 的前提下
  构建兼容的新 schema 投影；
- 单 Schema 的 immutable `DeploymentProfile`，分别锁定 Schema identity/content、
  Adapter version/manifest content、enabled bindings 和不含凭据的 store refs。

动态 `Ontology` facade、Callable RuleEngine、直接 DataFusion、公开 ObjectStore mutation
以及旧 HarnessWork Action bridge 已删除；`ontology.core` 也已整体退出源码。当前主要
缺口是：

- 还没有负责调度、重试和发布 diagnostics 的 runtime/materialization coordinator；
- ontology-owned `SetProperty` 已能编译为 deterministic FactBatch；source-backed
  Action 尚未产出或执行显式 source-write contract；
- safe derivation 尚未重建；source mapping 已具备纯 contract，但没有 Product connector、
  delta/change-set retention 或同步 runtime；
- 已有最小 `ActionDefinition`、`ActionRequest`、`ActionPlan`、opaque policy requirement
  和原子 guarded Fact commit；尚无 Product 侧授权/执行 ledger、外部 write capability、
  acknowledgement 与 reconciliation 实现；
- 没有 DecisionType、DecisionRecord、Scenario、OutcomeDefinition 或 LogicBinding，尚不能
  保存“为什么选择这个动作”以及预期结果和实际结果的差异；
- 没有 RDF/OWL/JSON-LD import/export、SHACL validation 或 round-trip diagnostics；
- 尚未处理 alternate keys、entity resolution、merge policy、增量同步和 source lineage。

因此近期方向应是把现有 P0 原型收敛为稳定内核，而不是直接在它上面叠加完整平台。

## 目标与非目标

### 目标

- 用对象、属性、关系、接口、事实、决策、动作和约束描述业务世界。
- 让产品、人和 Agent 通过同一套 typed query / decision / action contract 理解和操作
  业务对象。
- 把业务决策建模为连接事实、逻辑、候选方案、动作、审批和结果的一等 contract。
- 保存不可变的决策上下文与选择记录，并将预期 outcome 和实际 outcome 连接成反馈闭环。
- 让每个可操作事实携带时间、来源、证据和推导方式。
- 将 ontology action 规划为可验证的 mutation plan 和 capability requirements。
- 支持内存、SQLite 等轻量 backend，并允许长期扩展到其他存储，不把内核绑死在某一
  图数据库。
- 支持领域包，环保作为第一个验证内核可复用性的行业试点。
- 支持标准导入、导出和验证，但保留 operational semantics 的内部清晰边界。

### 非目标

- 不以“通用图数据库”作为第一目标。
- 不把 Protégé/WIDOCO 式本体编辑器做进 P0-P2。
- 不在 core 中定义环保、供应链或 ICT 设备等行业类。
- 不让 LLM 生成的 schema、rule 或 action 绕过 draft、validation、review、publish。
- 不让 Agent 获得任意对象 CRUD；Agent 只能请求已发布的 decision、function 和 action。
- 不把 Decision-Centric 解释为“由 AI 自动决定”；proposal、decision、approval 和
  execution 必须保持独立身份与治理边界。
- 不在 ontology 包中实现 shell、HTTP、消息、文件等外部副作用执行器。
- 不提前复制 OpenFoundry 的微服务数量、Kafka/Cassandra/Search 运维形态。

## Palantir 参照的正确吸收方式

Palantir 官方将 Ontology 定义为连接数据、逻辑、动作和安全的 operational layer；
语义部分包含 objects、properties、links 和 interfaces，kinetic 部分包含 actions 与
functions，动态部分受权限和安全策略控制。参考：

- [Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview)
- [Action type permissions](https://www.palantir.com/docs/foundry/action-types/permissions/)
- [Object permissioning](https://www.palantir.com/docs/foundry/object-permissioning/overview)

Loushang 应吸收的是对象化 operational layer，而不是 Foundry 的封闭产品形态：

| 层 | Loushang 应拥有的语义 | 不应直接拥有的实现 |
| --- | --- | --- |
| Semantic | ObjectType、Property、LinkType、InterfaceType、Fact、ObjectSet、DecisionType、OutcomeDefinition | 特定图数据库 schema、行业对象全集 |
| Kinetic | LogicBinding、Scenario、DecisionRecord、ChangeSet、ActionType、FunctionDefinition、MutationPlan | shell/HTTP/消息执行器、产品 UI |
| Dynamic | PolicyRequirement、marking、scope、审计上下文的声明 | 身份系统、审批队列、sandbox、tenant control plane |

Ontology 可以声明“执行此动作需要什么权限、确认和能力”，但实际鉴权、审批和副作用
执行必须由现有运行边界负责。

## 从 Operational Object + Action 到 Decision-Centric Ontology

只建模 Object 和 Action 可以回答“当前世界是什么”与“允许做什么”，但不能完整回答：

- 当前需要作出什么决定；
- 候选方案由哪些事实、规则、模型和假设生成；
- 为什么选择某个方案，由谁或哪个 Agent 提议、审批；
- 选择如何转成一组受控动作；
- 实际结果是否达到预期，经验如何反馈给后续决策。

因此，Loushang 的目标模型应从 `Operational Object + Action` 升级为：

> `Object + Logic + Decision + Action + Outcome`

这里的 Decision 不是 LLM 回复或临时推理文本，而是一个可版本化、可授权、可审计、
可回放的 operational artifact。该方向参考 Palantir 对 ontology、AI、agent 与决策关系
的阐述：

- [Connecting AI to Decisions with the Palantir Ontology](https://blog.palantir.com/connecting-ai-to-decisions-with-the-palantir-ontology-c73f7b0a1a72)
- [Connecting Agents to Decisions](https://blog.palantir.com/connecting-agents-to-decisions-277dee8ddb40)

### 核心概念

```text
DecisionType
  decision_type_id / version
  subject_types / input_contract
  candidate_contract / constraints
  logic_bindings[]
  allowed_action_types[]
  outcome_definition
  policy_requirements

LogicBinding
  logic_ref / version
  input_mapping / output_mapping
  execution_kind: function | rule | model | method
  provenance / confidence_contract

Scenario
  scenario_id / decision_type_ref
  base_revision / assumptions[]
  proposed_change_set
  predicted_outcomes[]
  evidence_refs[] / risk_refs[]

ChangeSet
  ontology_mutations[]
  action_intents[]
  capability_requirements[]
  policy_requirements[]

DecisionRecord
  decision_id / decision_type_ref
  subject_refs[] / context_snapshot_refs[]
  considered_scenarios[] / selected_scenario_ref
  rationale / evidence_refs[]
  proposed_by / decided_by / approved_by
  policy_evaluation_refs[] / action_request_refs[]
  status / decided_at

Outcome
  decision_ref / action_run_refs[]
  expected_metrics[] / observed_metrics[]
  evidence_refs[] / work_refs[]
  assessment / observed_at
```

`DecisionType` 是 schema 定义，`DecisionRecord` 是一次业务选择的 append-only aggregate：
proposal、policy evaluation 和 approval 作为事件追加，形成当前状态投影；决定一旦
finalized，其 context、候选集和选择不可改写。重新评估或推翻既有决定时，应创建新记录
并通过 `supersedes` / `reconsiders` 连接，不能覆盖历史。

`LogicBinding` 只保存对已发布逻辑及其版本、输入输出映射和 provenance 的绑定。确定性
规则或 function 可以由 ontology runtime 计算；模型推理、Method 执行或外部工具调用由
适当的宿主运行时完成，ontology 只接收带版本和证据的结果，不能把任意模型代码塞进
schema，也不能把“AI 推荐”自动等同于已批准决策。

`Scenario` 是在同一个事实快照和假设集合上可比较的候选方案；`ChangeSet` 是方案落地时
拟产生的 ontology mutation 与 action intent。它可以被预览、验证和授权，但只有选中的
Scenario 经审批后才能转成 ActionRequest。现有 `MutationPlan` 是单次 Action 的原子变更
计划，不能替代跨多个动作和预期结果的 `ChangeSet`。

### 决策闭环

```text
Observe Objects / Facts
        |
        v
Evaluate LogicBindings
        |
        v
Generate and compare Scenarios
        |
        v
Propose -> authorize -> approve DecisionRecord
        |
        v
Materialize selected ChangeSet as ActionRequests
        |
        v
Execute actions and commit ontology mutations
        |
        v
Observe Outcome + Evidence
        |
        v
Append facts and reassess later decisions
```

反馈不能静默改写历史 facts、DecisionRecord 或模型版本。实际 outcome 应作为新事实写入，
通过明确的评估逻辑与预期 outcome 比较；需要调整规则、模型或方法时，以新版本发布，
从而能够解释某个决定在当时为何合理、后来又为何改变。

### 权限、安全与审计

Decision-Centric 不降低现有治理要求。一次决策的有效权限至少是以下约束的交集：

- 读取相关 object、property、link、fact 和 evidence 的权限；
- 发现、提议或选择该 `DecisionType` 的权限；
- 执行选中 `ActionType` 的权限、审批和 capability requirement；
- 查看 DecisionRecord、rationale、Outcome 和 HarnessWork evidence 的权限。

Agent 可以生成候选 Scenario、调用发布的 LogicBinding 并发起 decision proposal，但不得
自行扩大对象可见范围，不得绕过 action authorization，也不得把自然语言 rationale 当作
授权证据。每个 proposal、policy evaluation、approval、action 和 outcome 都必须由稳定
引用连接，形成端到端审计链。

## 分层运行架构

SuperML 的 [Ontology Architecture](https://superml.org/tutorials/ontology-architecture)
将 operational ontology 描述为 datasource、index/serving、ontology definitions、
security/policy、API surface、consumers 六层，并分别追踪 read path 和 write path。该结构
适合作为 Loushang 的运行时地图，但需要补入 canonical facts、state authority、外部
write-back failure semantics 和 Decision-Centric contracts。调研日期为 2026-08-06。

同系列补充材料：

- [Action Types: Writing to the Ontology](https://superml.org/tutorials/ontology-action-types)
- [Functions on the Ontology](https://superml.org/tutorials/ontology-functions)
- [Best Practices and Production Patterns](https://superml.org/tutorials/ontology-best-practices)
- [Capstone: A Complete Operational Ontology](https://superml.org/tutorials/ontology-capstone)

### Loushang 分层映射

```text
6. Consumers
   Product / operational app / service / human / Agent

5. Typed Operational Surface
   Query | Function | Decision | Action

4. Policy Gate
   object | property | row/fact | decision | action | evidence

3. Published Ontology Definitions
   package | object | link | interface | function | decision | action | outcome

2. Facts, Serving Projections and Indexes
   FactStore | object projection | primary/property/link/search index | cache

1. Sources and Integration Boundary
   datasets | streams | APIs | files | source mappings | write-back adapters
```

这个分层是职责图，不是要求调用栈或代码依赖严格自下而上。Definitions 决定 facts 如何
验证、projection 如何生成以及 surface 如何类型化；serving/index 是从事实和已提交变更
产生的可重建投影，不是新的业务真相。原始来源也不能越过 mapping/provenance 直接成为
published ontology fact。

### 多业务系统的局部 Source View 与 StateAuthority

> 目标架构提案，正式收口见
> [ARD-003](../ARD-003-declared-state-authority-and-multi-source-materialization.md)。
> 当前 runtime 已实现 correctness、Memory-only mapped-source 合成和完整
> object/property/link origin slice；change set、derived computation 与 source
> persistence 等其余多来源内容仍是后续方向。

ERP、HR、CRM、OA 等业务系统不应被统称为 Ontology projection。对每个业务系统自身而言，
它的数据库仍是其职责范围内的 system of record；从企业级 Ontology 视角看，每个系统只
提供企业现实的一部分观察。经过特定应用版本的 Adapter 和 Mapping 后，该观察形成
`MappedSourceSnapshot`，即一个局部 `Source View`。`ServingProjection` 这个名称只保留给
Ontology 合成后面向查询的统一对象视图：

```text
ERP / HR / CRM / OA
        |
        | batch / CDC / stream / API / polling
        v
Application-version Adapters + Mappings
        |
        v
Mapped Source Views
        |
        | identity + authority + conflict resolution
        v
Serving Projection
        |
        v
Product / service / human / Agent
```

因此，一个对象不必由某个业务系统完整提供。`StateAuthority` 应至少能够按对象存在、属性
和 Link 声明，而不是只按 ObjectType 粗粒度声明：

```text
Project existence       <- OA / project system
Project.budget          <- ERP                    (source-backed)
Project.customer        <- CRM                    (source-backed)
Project.manager         <- HR                     (source-backed)
Project.approvals       <- OA                     (source-backed)
Project.risk_level      <- RiskFunction/v3        (derived)
Project.director_note   <- Ontology               (ontology-owned)
```

这里存在三个正交维度，不能继续都简称为 authority 或 provenance：

```text
StateAuthority  source-backed | ontology-owned | derived
AssertionKind   asserted | derived | inferred
ValueOrigin     source | fact | schema-default
```

`StateAuthority` 描述谁拥有业务状态及哪类写合同可以改变它；FactStore authority 描述
Ontology 内哪些 semantic records 由 FactStore 持久化；`AssertionKind` 描述断言如何产生；
`ValueOrigin` 描述投影值来自哪份不可变输入。第一版应坚持一个可写状态只有一个主
`StateAuthority`；多个来源提供同一属性时，必须配置主来源或显式报告冲突，不能按接入
顺序静默覆盖。Derived 状态不可直接修改，ontology-owned 状态由 Ontology 自己持久化。
Source-backed 状态不能被本地 Fact 冒充为已经由源系统确认；ARD-012 已决定首个切片采用
Product-hosted external write-back，不采用 managed edit overlay。其中 ontology-owned
路径已经实现，source-backed 路径尚未实现；该决定不代表所有未来 Action 都已完成设计。

局部 Source View 的合成还依赖 canonical identity。Adapter 必须把各系统的 source record
identity 映射到稳定对象 ID，并保留 alternate keys；无法可靠确认两个记录为同一对象时，
宁可保持分离并进入 identity-resolution 流程，也不能仅凭姓名或显示值自动合并。

多来源 projection 不能继续只使用单一 `fact_watermark` 表达新鲜度。建议的重建坐标应是
显式 revision vector：

```text
MaterializationCut
  schema_identity
  source_inputs:
    ERP: (binding-erp, mapping-v4, transaction-108)
    HR:  (binding-hr,  mapping-v2, transaction-76)
    CRM: (binding-crm, mapping-v3, cursor-991)
    OA:  (binding-oa,  mapping-v1, unknown)
  fact_watermark
  valid_at / recorded_at
```

不同系统通常不存在共同数据库事务；`MaterializationCut` 表达的是一次可重现的输入版本
组合，而不是虚构的全局原子时刻。Query freshness 也应区分 `current`、`stale`、`unknown`
和 `degraded`，并只聚合本次查询实际依赖的 source/property/link coverage。Projection 追平
FactStore 只说明内部物化完成，不能证明 ERP、HR、CRM 或 OA 已被完整观察。

写入同样按 `StateAuthority` 规划：Ontology 自有备注进入 FactStore，派生风险由已发布
逻辑重新计算；修改预算、人员或审批状态必须产生 source-backed write requirement，不能
直接提交成本体已经确认的值。Product Adapter 可以将该 requirement 绑定为 ERP、HR、OA
write-back。跨多个 `StateAuthority` 的 Action 不能宣称数据库级原子事务。ARD-012 将首个
effect 进一步限制为单对象、单属性 `SetProperty`：Ontology 只产出带
projection/source precondition 的可审查 plan，外部 effect 由 Product-hosted adapter
执行；HarnessWork 只是 Product 可选的 durable execution host，不是 Ontology 依赖。

这个边界意味着需要重新审视“所有外部语义状态都逐属性写入 FactStore”的范围。外部
Source View 可以通过 source binding、source revision、source record、mapping version 和
field reference 提供 lineage，不必为每个普通源字段复制完整 Fact envelope。FactStore 仍
适合承载 ontology-owned 状态、重要 asserted claims，以及已经发布且具有独立审计或修正
生命周期的 derived/inferred claims。可即时重算且没有独立语义生命周期的 derived value
只进入 Projection。某些 source-backed value 若有独立双时态或法规审计要求，仍可被选择性
事实化；这里反对的是机械复制全部源字段，而不是绝对禁止 source-backed Fact。Decision 与
Outcome 的持久化由后续 ARD 决定；Projection 始终是可删除重建的派生状态。

该提案依据 2026-08-09 对 Palantir 官方
[Data Connection](https://www.palantir.com/docs/foundry/data-connection/overview)、
[Multi-datasource object types](https://www.palantir.com/docs/foundry/object-permissioning/multi-datasource-objects)、
[How user edits are applied](https://www.palantir.com/docs/foundry/object-edits/how-edits-applied)
和 [Materializations](https://www.palantir.com/docs/foundry/object-edits/materializations) 的复核，
并与本地只读参考 `operational-ontology` commit
`c79aa88c1f5d4fe2ac2b126a5852f1ba434aaa57` 的代码和测试进行对照。该参考实际落实了
source-backed、ontology-owned、overlay、re-index 和 write-back-first；`derived` 只在其
README 中作为概念分类，core runtime 没有 `derived` StateAuthority、source revision vector、
identity-resolution 或 source coverage contract。后面这些内容是 Loushang 的架构推导，
不是参考仓库或 Palantir 未公开内部实现的既有能力。Palantir 公开资料也不证明所有
source-backed Action 都必须 external write-back；这是需要 Loushang 单独决策的写入策略。

Policy Gate 也是逻辑边界，不表示 ontology 包拥有身份系统。Ontology 定义 policy、marking
和可见性语义并对 query/mutation 产出 policy decision；宿主提供经过认证的 actor context，
Harness/Product 强制执行 approval、capability 和外部 effect 权限。两侧必须共享同一稳定
policy evaluation/audit reference。

所有消费者使用同一 published surface；产品 UI、服务和 Agent 都不能通过 raw SQL、
backend handle 或 generic object CRUD 绕过 schema、policy 和 audit。SDK、REST、RPC、
GraphQL 或 MCP 只是该 surface 的不同传输投影，不应各自重新实现业务规则。

### 四类 typed surface

| Surface | 语义 | 副作用与治理 |
| --- | --- | --- |
| Query | 读取 ObjectSet、facts、links、aggregates 和 projections | 无写入；执行 object/property/row/fact policy 与字段裁剪 |
| Function | 对 ontology 输入执行 typed compute，可绑定 derived property 或模型输出 | 默认纯函数；外部计算通过受控 LogicBinding 和宿主执行 |
| Decision | 生成/比较 Scenario，提交 proposal，记录选择、审批和预期 Outcome | proposal 不等于 approval；只能实例化允许的 ChangeSet |
| Action | 按明确业务意图规划并提交 ontology mutation 或外部 effect | typed params、preconditions、authority、idempotency、approval、audit |

FunctionDefinition 至少声明输入/输出、purity、execution kind、成本边界和缓存语义：

```text
FunctionDefinition
  function_id / version
  input_contract / output_contract
  purity: pure | time_dependent | external
  execution_kind: expression | builtin | method | model
  cache_policy / invalidation_dependencies[]
  cost_hint / traversal_limits
  model_ref / provenance_contract
```

`external` 表示结果依赖外部能力，不表示 ontology core 可以直接发起网络或工具调用。
宿主通过 LogicBinding 执行并返回带版本、时间和 provenance 的 typed result。只有声明为
pure 且依赖可追踪的 function 才能安全 memoize；derived property 的 materialization 仍是
可重建 projection。

## 子系统边界

### 依赖原则

`loushang.ontology` 应尽量保持 product-neutral 和 runtime-neutral：

```text
Product source adapter       ---> ontology source contracts
Product ontology adapter     ---> ontology + harness + optional harnesswork
Product method binding       ---> method + ontology

ontology -X-> harness / harnesswork / method / Product implementation
```

Ontology 返回纯数据 contract，具体数据库/API connector、write-back adapter、Method
binding 和 HarnessWork integration 都由 Product 或 deployment composition root 持有。
Source 同步不必强制经过 Harness；只有需要 durable scheduling、recovery 或 execution
evidence 时，Product 才选择 HarnessWork。Ontology、Method、Harness 与 HarnessWork 的
公共协议不互相嵌入对方的领域类型。

### 职责分配

| 子系统 | 建议职责 |
| --- | --- |
| `ontology` | schema、StateAuthority、source-input contract、facts、materialization、query、validation、decision/scenario contract、action planning、semantic outcome、interop、fusion contract |
| `harness` | capability binding、工具调用、sandbox、授权、approval、外部 effect 执行 |
| `harnesswork` | durable run、执行过程、evidence、artifact、event、replay；以稳定引用关联 Decision/Outcome，不持有 Ontology 类型 |
| `method` | 方法资产、步骤、输入/输出 shape、acceptance criteria；可作为 versioned LogicBinding 被引用 |
| Product | 业务语义装配、决策交互、用户入口、source/write-back adapter，以及 ontology ↔ harness/harnesswork/method integration |
| Channel / SDK | 将 Query/Function/Decision/Action contract 投影为 REST/RPC/GraphQL/MCP/SDK |

Ontology 持有 `DecisionType`、`DecisionRecord` 和 semantic `Outcome`；HarnessWork 持有
执行过程和证据。二者通过 opaque stable reference 关联，由 Product adapter 组合，
Ontology 不能因此反向依赖 HarnessWork。产品负责候选方案比较、人工选择和解释界面，
不把 UI 状态写进 core。

### 查询读取流程

```text
QueryRequest(actor, published_package, object_set, selection, consistency)
        |
        v
Schema + Policy Resolution
  - resolve stable IDs and published schema version
  - authorize object, property, row/fact and evidence scope
        |
        v
Query Compiler
  - validate filters, traversal depth, aggregation and cost bounds
  - compile authorized row/fact scope into the backend plan
  - compile backend-neutral ObjectSet to a projection/index plan
        |
        v
Projection / Index Backend
  - primary/property/link/search lookup
  - hydrate objects and preserve fact/provenance references
        |
        v
Policy Projection
  - remove invisible rows and redact restricted properties
  - prevent hidden endpoints from leaking through traversal/counts
        |
        v
Typed QueryResult(schema_identity, data, cursor, freshness, diagnostics)
```

关键约束：

- 每次读取都携带 actor 与 schema version；Agent session 不是权限例外。
- row filtering 必须在 aggregation、pagination 和 link traversal 的正确阶段执行，避免通过
  count、cursor 或隐藏 endpoint 推断不可见对象。
- QueryResult 应暴露 projection freshness 和 consistency level；缓存命中不能掩盖来源滞后。
- traversal depth、fan-out、result size 和 function cost 必须有显式上限。
- consumer 不得在本地重新拼接底层表来补齐 ontology 查询，否则 typed contract、权限和
  provenance 会失效。

### 决策选定后的动作规划与履约子流程

```text
User / Product / Agent
        |
        v
ActionRequest(action_type, target, parameters, expected_revision, idempotency_key)
        |
        v
Ontology ActionPlanner
  - resolve published schema
  - validate types and submission criteria
  - evaluate pure preconditions
  - classify changes by StateAuthority
  - produce MutationPlan + SourceWriteRequirements
    + CapabilityRequirements + PolicyRequirements
        |
        +----------------------+----------------------+
        |                      |                      |
        v                      v                      v
ontology-owned           source-backed             derived
recheck + Fact commit    Product-bound strategy    reject direct write
                         (deferred Action ARD)
        |                      |
        +----------+-----------+
                   v
          Harness / HarnessWork when required
          - authorize and approve
          - execute bound external capabilities
          - record evidence, terminal state and artifacts
```

关键约束：

- `ActionPlanner` 不执行外部副作用，只产出可审查的 plan。
- ontology-owned 对象与 link mutation 必须作为一个原子 Fact commit 边界。
- `expected_revision` 和 `idempotency_key` 从第一版 action contract 就保留。
- source-backed write-back、managed edit overlay、acknowledgement 和 reconciliation 的取舍
  留给后续 Action ARD；在它接受前不得把本地写入冒充为源系统已经确认。
- 跨 `StateAuthority` Action 第一版可以直接拒绝；未来若支持多系统履约，必须显式建模失败和
  补偿状态，不能假装完全原子。
- HarnessWork 记录是执行证据和产品运行历史，不应被当作 ontology 的主存储。

ActionType 的发布检查至少包括：业务意图级命名、最小 typed parameters、确定性
preconditions、数据化 MutationPlan、state authority、expected revision、幂等策略、
policy/approval requirement、审计字段、committed change event 和 Outcome linkage。禁止用
`updateObject`、`executeRawSql` 或大量可选字段构造万能动作。一个 Action 可以原子表达一个
完整业务步骤，但跨系统 effect 必须服从上面的显式失败协议。

## 建议的核心模型

### 1. OntologyPackage

领域模型和内核扩展的发布单位：

```text
OntologyPackage
  package_id / namespace / version
  imports[]
  lifecycle: draft -> validated -> reviewed -> published -> deprecated
  schema
  migrations[]
  provenance
```

同一 package 内的 ID 稳定，版本升级通过 diff 和 migration 表达。导入 OWL、JSON-LD 或
LLM 生成的内容默认进入 draft，不能直接覆盖 published package。

#### 领域包语义覆盖

`OntologyPackage` 发布时应从以下方面报告语义覆盖，但它们只是 authoring/readiness
profile，不是八个运行时子系统，也不要求分别采用 RDF、OWL、SWRL、BPMN、ODRL 或
SPARQL：

```text
resources    对象、属性、关系和事实
vocabulary   术语、标签、别名和分类口径
constraints  类型、关系和数据约束
logic        派生逻辑、校验规则和前提
operations   Function、Action 及 Method binding
governance   Policy、approval 和 capability requirement
queries      ObjectSet、查询和统计入口
outcomes     DecisionType、目标、指标和评估窗口
```

覆盖结果由 package 内容和 validator 自动计算，不作为需要人工同步的 manifest 真值。
初期用 stable ID、label、alias、annotation、枚举和 `ValueType` 表达词汇；只有出现跨领域
概念映射、外部词表对齐或独立版本治理需求时，再考虑引入 `ConceptScheme` 等一等模型。

发布校验器可以在不改变 package lifecycle 的前提下报告四种递进 readiness：

| Readiness | 最低含义 |
| --- | --- |
| Schema Ready | 对象、关系、稳定标识和约束可以验证、diff 和发布 |
| Operational Ready | 查询、Function、Action、policy 和写回协议完整 |
| Decision Ready | Scenario、Decision、approval、expected Outcome 和 lineage 完整 |
| Agent Ready | 已生成 typed tools，并通过权限、拒绝路径和反馈闭环测试 |

这些状态是检查视图，不替代 `draft -> validated -> reviewed -> published -> deprecated`
生命周期。该覆盖清单受 workspace 中 HWBook “7+1”图片调研启发，只吸收业务完整性问题；
原资料的具体标准绑定不是 Loushang 的规范性架构来源。

### 2. OntologySchema

```text
OntologySchema
  ObjectType
  PropertyDefinition
  LinkType
  InterfaceType
  ValueType
  Constraint
  DecisionType
  OutcomeDefinition
  LogicBinding
  ActionType
  FunctionDefinition
```

建议把 DecisionType 和 ActionType 纳入 schema，但把一次 decision/run 分别留在
DecisionRecord 和运行/工作记录中。Function 默认是无副作用、可确定重放的计算定义；
需要工具或外部写入的能力必须表现为 action capability requirement，避免 function 或
LogicBinding 成为权限旁路。

### 3. Decision、Scenario 与 Outcome

`DecisionType` 定义业务选择点的输入、候选方案、逻辑绑定、允许动作、结果指标和策略；
`Scenario` 保存候选假设、ChangeSet 与预测结果；`DecisionRecord` 冻结当时可见事实、所选
方案、理由、主体和审批；`Outcome` 连接预期指标与后续观测。它们共同组成 decision
lineage，不应退化成 ActionRequest 上的几个可选 metadata 字段。

### 4. OntologyFact

对象快照不应成为唯一真相。运行时至少需要区分：

```text
ObjectFact
LinkFact
MeasurementFact
ClaimFact
EvidenceRef
```

建议的公共 fact envelope：

```text
fact_id
subject_ref
predicate_ref
value | object_ref
assertion_kind: asserted | derived | inferred
source_ref
evidence_refs[]
methodology_ref
confidence
author_ref / agent_ref
valid_from / valid_to       # 业务世界中的有效时间
recorded_at / superseded_at # 系统记录时间
supersedes / corrects
```

这使重要的 asserted Claim、已发布 derived/inferred Claim 和 ontology-owned state 可以
共存而不互相覆盖，也为环保领域的测量、基线、方法学和 impact claim 提供必要基础。
普通 source-backed 属性可以直接来自版本化 `MappedSourceInput`；只有需要独立双时态、
证据、法规审计或修正生命周期的源值才选择性事实化。可即时重算且没有独立语义生命周期
的 derived value 只进入 Projection。

### 5. ServingProjection

查询不能要求每次重放全部 facts，也不能因此把索引升级为新的 source of truth：

```text
ServingProjection
  projection_id / schema_identity / projection_version
  materialization_cut
    source_inputs[(binding_id, mapping_version, source_revision)]
    fact_watermark / valid_at / recorded_at
  built_at
  primary_key_index
  property_indexes
  link_adjacency_index
  search_index
  materialized_derived_values
  value_origins: FactOrigin | SourceOrigin | SchemaDefaultOrigin
  rebuild_status / diagnostics

ProjectionFreshness
  status: current | stale | unknown | degraded
  observed_source_heads / observed_fact_watermark / observed_at
```

Memory/SQLite 可以把 projection 与存储实现放在同一进程，但 contract 必须允许以后拆到
PostgreSQL、graph 或 search backend。projection 需要可 replay、rebuild、compare 和 repair；
action commit 后通过 committed change event 做同步或异步 invalidation。缓存键必须包含
schema、policy scope 和依赖版本，不能让不同 actor 或 marking 共享越权结果。
`ServingProjection` 的 immutable build cut 与运行时观察到的 freshness 必须分离；新的源
revision 或 Fact watermark 只能使旧 cut 被比较为 stale，不能反向修改其构建坐标。

### 6. OntologyRuntime

```text
OntologyRuntime
  SchemaRegistry
  SourceInputPorts / FactStore
  AuthorityResolver / MaterializationEngine
  ProjectionStore / IndexPorts
  QueryEngine / ObjectSet / QueryCompiler
  Validator
  DecisionPlanner / ScenarioEvaluator
  ActionPlanner
  MutationCommitter
  OutcomeEvaluator
  ProjectionEngine
```

内部可以保留 object projection 以提高查询效率，但 projection 必须通过 `ValueOrigin`
追溯到 mapped source input、Fact 或 schema default，不能混淆 `StateAuthority`、
`AssertionKind` 与 `ValueOrigin`。

### 7. 建议的 Python 模块方向

这不是立即移动文件的要求，而是后续收敛边界：

```text
loushang.ontology
  schema/       # package, type, property, link, interface, constraint
  authority/    # StateAuthority declarations and resolution contracts
  sources/      # mapped input, binding, revision and coverage contracts
  facts/        # fact envelope, provenance, bitemporal semantics
  runtime/      # registry, store ports, validation, commit
  projections/  # object/link/search/materialized views, freshness, rebuild
  query/        # ObjectSet, filters, traversal, compiler, policy projection
  decisions/    # DecisionType/Record, Scenario, ChangeSet, Outcome
  actions/      # ActionType, planner, MutationPlan
  logic/        # FunctionDefinition, LogicBinding, safe expression IR
  rules/        # derived/inferred fact and validation result production
  fusion/       # source mapping, identity resolution, sync, lineage
  interop/      # RDF/OWL/JSON-LD/SHACL adapters
  governance/   # policy requirements and markings as declarations
```

## Operational IR 与开放标准

### 决策建议

以 Loushang operational IR 为 canonical model；OWL/RDF/JSON-LD/SHACL 是受测试的标准
桥，而不是唯一运行时。

原因：

- OWL 的 open-world、单调推理语义适合知识表达，不适合单独承担 required-field、
  当前状态、事务和业务动作的全部运行语义。
- SHACL 更适合 closed-world 数据验证，但不能替代 action、approval、idempotency 和
  side-effect contract。
- JSON Schema 适合 action 参数和 SDK payload。
- JSON-LD 适合对象/fact 交换并保留语义 ID。
- RDF/OWL 适合领域词汇、类层次、外部知识和标准互操作。

### 第一批互操作能力

- JSON-LD：package/schema/fact 的 import/export 与 round-trip test。
- RDF/OWL：class、datatype/object property、subclass、inverse、cardinality、annotation
  的受控子集；不识别的 axiom 进入 diagnostics，不静默丢失。
- SHACL：从 operational constraints 生成 shapes，并允许使用独立 SHACL engine 验证
  RDF data graph。
- JSON Schema：Decision proposal、Scenario、Outcome、ActionType 参数、MutationPlan 和
  公开 API payload。
- stable IRI/namespace mapping：不能像原型仓库一样硬编码一个全局 namespace。

## 环保领域试点

环保应该是验证基础设施是否真正通用的首个 domain package，而不是 core 中的一组
硬编码类。

### 建议的两个领域包

#### `environment-impact`

以 AIAO 及其关联 ontology 为主要语义参考：

- Agent、Activity、Environment、Control；
- State、Indicator、Measurement、Methodology；
- Evidence、StateClaim、ImpactClaim；
- baseline/project state、因果主张、责任主体和方法学引用。

这个包验证 fact、claim、evidence、methodology 和时间语义。

#### `environment-ict-dpp`

以 RePlanIT 为主要领域词汇参考：

- ICTDevice、HardwareComponent、Material、DigitalProductPassport；
- certification、manufacturer、composition、location、owner；
- repair、refurbishment、reuse、repurposing、recycling 等 circular strategy；
- 制造和生命周期指标。

这个包验证复杂对象/link、物料组成、设备状态迁移和 action。

### 推荐的垂直切片

```text
接收一批退役 ICT 设备
  -> 摄入设备、部件、材料和证书来源数据
  -> 生成维修、翻新、再利用或回收 Scenarios
  -> 比较成本、碳影响、可行性和风险等预期 Outcomes
  -> 提议并审批处置 DecisionRecord
  -> 将选定 ChangeSet 转成 Repair / Refurbish 等 actions
  -> 履约并按 StateAuthority 提交或确认状态变化
  -> 更新 Digital Product Passport
  -> 按明确 methodology 计算 avoided emissions
  -> 生成附带 evidence 的 ImpactClaim 和 observed Outcome
  -> 将预期/实际差异反馈给后续处置决策
```

这个切片同时覆盖 ingestion、identity、schema、validation、decision、action、
HarnessWork evidence、measurement 和 claim，比只展示知识图谱更能验证 operational ontology
的价值。

## 行业参考一：RePlanIT

参考快照：`RePlanIT/Ontology` commit `ca5e127`（2024-07-11）。当前正式文档为
[RePlanIT v3.4](https://kind.io.tudelft.nl/replanit/docs/)。本地 `RePlaniTv3.4.owl`
约含 295 classes、71 object properties、142 datatype properties；仓库 README 中
203/52/33 的统计已经落后于 v3.4。

### 有价值的部分

- 真实地连接 ICT、材料、循环经济和 Digital Product Passport，而不是只给抽象
  environmental vocabulary。
- Competency Questions、样例设备和 SPARQL query 可以转成 Loushang 的 domain
  package 验收 fixture。
- 覆盖 new/repaired/refurbished laptop 和 data server 等状态，非常适合 action-driven
  试点。
- 复用了多个外部 vocabulary，能验证 namespace、imports 和 semantic alignment。

### API 的性质

仓库确实附带 API，但它是 `Queries/replanit-api-main.zip` 中的独立 GitLab 快照，
不是 ontology runtime API。其实现是一个约 1,919 行的 Flask 单文件，通过
SPARQLWrapper 访问 Ontotext GraphDB：

- 共 15 个 Flask routes：11 GET、3 POST、1 PUT；
- 主要返回 DPP、agent、unit、carbon footprint 和 purchase cost；
- 写入端把 JSON 值格式化进 SPARQL template；
- zip 内 ontology 为 v3.3，而当前 ontology 为 v3.4；部分 query 还保留更早版本语义；
- 附带的 OpenAPI/动态文档只覆盖部分读取接口，README 基本仍是 GitLab 模板；
- 未发现自动化测试和独立 API license。

它说明“ontology + SPARQL + REST projection”可以快速形成行业 API，但不能作为
Loushang action/runtime 的实现蓝本。原始字符串插值、脆弱 bearer token 解析、schema
只做字段存在性检查、单文件路由和版本漂移都应避免。

### 建模风险

- 绝大多数 object property 被声明为 `owl:FunctionalProperty`，其中
  `hasComponent`、`hasCertification`、`hasIndicator` 等天然可能多值；直接照搬会错误
  限制业务数据。
- `hasMaterialComposition` 等 property 的多个 domain 声明在 OWL 中表示交集，不是
  常见开发者以为的“任一 domain”。
- 部分样例把 class 当作 instance 使用，容易混淆 type level 与 individual level。
- ontology、query、API schema 和文档存在版本漂移。

结论：RePlanIT 应作为领域词汇、competency question 和 sample-data reference；导入时
必须经过 normalization、SHACL validation 和人工 review，不能原样成为 runtime
schema。

## 行业参考二：AIAO

参考快照：`aiaont/aiao` commit `8584e11`（2026-05-06），Apache-2.0。仓库同时提供
JSON-LD、OWL、Turtle、HTML 文档和样例。

### 有价值的部分

- AIAO 不只描述污染物，而是描述人类活动、环境、控制、责任和 impact accounting。
- Agent、Activity、Environment、Control、ImpactClaim、StateClaim 是环保基础包比
“设备类大全”更需要的高层语义。
- 与 Impact Ontology、Claim Ontology、Information Communication Ontology 的链接
  能帮助 Loushang 分离事实、主张、证据和传播。
- 示例覆盖碳项目和减排主张，适合验证 methodology、baseline、project state、claim
  和 evidence 的组合。

### 使用边界

- AIAO 是 semantic/domain ontology，不提供 operational action、transaction、approval
  或 runtime API。
- 外部 ontology import 必须锁定版本和 IRI，并记录 dependency diagnostics。
- 因果 impact claim 不能由一个普通 derived property 冒充；需要方法学、观察值、
  baseline、证据和责任主体。

结论：AIAO 适合成为 `environment-impact` 的 alignment source；RePlanIT 则提供
`environment-ict-dpp` 的具体行业词汇，两者是互补关系。

## 纯本体技术参考仓库评估

### 评估方法

逐仓检查以下维度：

- canonical model 是否清晰；
- schema、facts/objects、query、action、governance、interop、fusion 的边界；
- 实现是否真实，还是只存在于 README、type declaration 或 placeholder；
- 测试规模和代码集中度；
- 安全、事务、版本和许可证风险；
- 对 Loushang 的可采纳点与明确不采纳点。

规模数据只用于判断形态，不能代替运行验证。由于参考仓库约定为只读，本次没有安装
依赖或执行会产生 cache/artifact 的测试命令。

### 技术参考一：foundry-ontology-open

快照：`cloudbadal007/foundry-ontology-open` commit `b349cdc`（2026-07-19），
MIT，版本 `0.1.0`。Python source 约 1,848 行，静态识别约 102 个 test functions。

#### 实际形态

这是现有技术参考中最小、最直观的 Palantir 三层教学原型：

- semantic：ObjectType、Property、LinkType、Interface；
- kinetic：ActionType、OntologyFunction、ActionExecutor；
- dynamic：Role、PermissionCheck、Marking、AuditLog；
- runtime：SQLite-backed ObjectStore 和链式 query；
- bridge：OWL、SHACL、JSON、OntoGuard export；
- agent surface：7 个 MCP tools 和 1 个 ontology schema resource。

它的主要价值是用很少代码展示从 schema 到 object、query、action、audit、export、MCP
的完整纵切面。能源资产维护示例也适合参考动作命名和 demo 叙事。

#### 代码审查发现

- `ValidationRule.expression` 通过 Python `eval` 执行；即使去掉 builtins，也不是应
  进入生产内核的 safe expression IR。
- Action effect 顺序执行，前面 effect 成功、后面失败时不会 rollback，存在部分提交。
- role 检查是可选参数；MCP `execute_action` 没有传角色，治理没有形成强制边界。
- `PermissionCheck` 基本是 Admin/Engineer 等硬编码判断，没有 object/property scope。
- ObjectStore 没有 enforce LinkType cardinality，create link 也没有验证 source/target
  object type 与声明一致。
- ontology 和 export 使用固定全局 namespace；instance export 没有导出 links、时间、
  provenance 或 action history。
- SHACL 的 `sh:in` 生成不是完整 RDF list 语义，整体 exporter 更适合作为示例而不是
  互操作基准。

#### 对 Loushang 的取舍

采纳：三层术语、最小 vertical slice、Action 描述可被 Agent 发现、MCP 作为外部
adapter、能源维护 demo 的产品表达。

不采纳：`eval`、可选权限、非事务 effect、硬编码角色/namespace、把 SQLite store
称为 Foundry Object Storage 的等价实现。

定位：**概念和最小 API 参考，不是生产内核参考。**

### 技术参考二：OpenFoundry

快照：`P2Enjoy/OpenFoundry` commit `d7c40cf5`（2026-05-12），AGPL-3.0。
当前仓库约有 42 个 service、33 个 lib；仅 `libs/ontology-kernel` 就约 48,375 行 Go，
静态识别约 423 个 Go tests。

#### 实际形态

它不是“纯本体库”，而是完整 operational data platform。与本体最相关的是：

- `libs/ontology-kernel/models`：object/property/link/interface/action/function/rule wire
  contracts；
- `domain`：submission criteria、object set、rule、function runtime、writeback、access；
- `handlers`：types、objects、links、actions、functions、rules、search 等 HTTP bounded
  contexts；
- PostgreSQL 保存 definitions，Cassandra/Scylla 保存 object/link/action hot path；
- Kafka change events 由 ontology-indexer 投影到 Vespa/OpenSearch；
- action service 处理 JWT、marking、submission criteria、inline function、webhook、
  audit、notification 和 action-log materialization。

#### 最值得借鉴的机制

- submission criteria 使用结构化 AST，而不是任意字符串表达式。
- validate/plan/execute 分阶段，action 有 authorization policy、justification、preview、
  audit 和 side-effect 语义。
- object store 使用 revision + Cassandra LWT 做 optimistic concurrency。
- primary object write 与 search/read-model projection 分离，并承认 secondary index 是
  best-effort、需要 reindex repair。
- object set、function package version、marking、project access 和 contract fixture
  体现了生产系统必须处理的长期兼容问题。

#### 风险与不适合早期复制的部分

- 体量和部署拓扑远超 `loushang.ontology` 当前阶段；先复制服务边界会把语义内核埋在
  基础设施复杂度里。
- action execution 单文件超过 2,000 行，部分 domain/handler 文件也超过 1,000 行，
  说明“功能齐全”不等于边界已经理想。
- PostgreSQL definition、Cassandra primary/read model、Kafka、search、audit service、
  webhook service 的一致性依赖 repair、idempotency 和运维流程，不是普通事务。
- 仓库保留 Rust → Go 兼容层和大量 wire compatibility 负担，Loushang 不应继承历史
  包袱。
- AGPL-3.0 要求把设计参考和代码复制严格区分；默认只学习机制，不复制实现。

定位：**P4/P5 的规模化运行、并发、一致性和服务拆分参考；不是 P0-P2 的代码模板。**

### 技术参考三：nano-ontoprompt

快照：`jingw2/nano-ontoprompt` commit `0a80458`（2026-07-24）。README 声明 MIT，
但该快照根目录没有独立 `LICENSE` 文件，使用前需要再次确认许可证。Backend app 约
14,211 行 Python，静态识别 327 个 test functions。

#### 实际形态

它的中心不是 ontology kernel，而是从原始数据构建 ontology 的产品工作台：

```text
Connection -> Raw/Transform Pipeline -> Curated Dataset
           -> Mapping -> Concept/Instance/Relation
           -> Logic & Action Draft -> Review -> Publish
           -> Neo4j/SQLite graph and export
```

它同时支持文档 + LLM 的 v1 extraction 路径，以及结构化 pipeline mapping 的 v2
路径。核心能力包括 schema inference、cleansing、FK/alternate-key relation inference、
curated review、ontology quality audit agent、Neo4j/Chroma 可选降级和可视化 UI。

#### 最值得借鉴的机制

- 把 ingestion/mapping 与 ontology schema/runtime 分开考虑，而不是假定业务数据已经
  天然符合本体。
- curated data 先 review，再触发 mapping；logic/action 使用 draft → reviewed →
  published 生命周期。
- alternate key、值归一化、FK 和可选 LLM suggestion 共同参与 link inference。
- LLM 只用于建议和质量审查时比直接发布 schema 更合理。
- optional Neo4j/MinIO/Chroma/Redis 的降级策略适合 Loushang 的 embedded-first 取向。

#### 代码审查发现

- ontology metadata 大量保存在通用 JSON columns 中，v1/v2 entity、logic、action
  并存，canonical schema 边界不够强。
- `mapping_service.py` 超过 1,600 行，同时承担 normalization、identity、relation
  inference、Neo4j、logic/action discovery，职责过于集中。
- action runtime 虽保存 `permission_rules`，但执行路径没有实际 evaluate 这些规则；
  当前用户认证不等于动作授权。
- action effect 只支持少量 SQLAlchemy object/relation mutation，未知 effect 会被标为
  skipped，尚不是通用 operational runtime。
- Neo4j label、relation type 等 schema token 以字符串插值进入 Cypher；必须增加严格
  token validation，不能只参数化值。
- quality audit 内置少量领域关系 pattern，适合作为启发式规则，不应成为 core semantic
  truth。
- pipeline 和 mapping 多处以 10,000 行 preview 为边界，不代表增量、大数据和失败恢复
  已经解决。

定位：**数据接入、mapping、human-in-the-loop 和 LLM-assisted authoring 的主要参考；
不是 canonical ontology IR 或 action runtime 参考。**

### 技术参考四：ontograph-core

快照：`openshuyi/ontograph-core` commit `28135fd`（2026-04-29），MIT，npm version
`0.0.1`。core 与直接子模块约 17.4k 行 TypeScript，包含深层 supply-chain examples 的
完整 `src` 约 29.7k 行；8 个 test files 中静态识别约 337 个 test cases。

#### 实际形态

这是现有技术参考中最接近“纯 ontology technology library”的项目：

- code-first EntityType、RelationType、Attribute、Interface、Constraint；
- fluent Builder；
- 无 `eval` 的结构化 Expr AST 和 evaluator；
- ObjectSet、FilterOp、pluggable query engine、Neo4j compiler；
- RBAC + row-level condition；
- datasource mapping 和 sync delta；
- OWL、SHACL、JSON Schema、Mermaid、DOT、ER exporters；
- schema/object version、diff 和 lineage；
- 大型 supply-chain definition examples。

#### 最值得借鉴的机制

- operational IR 是普通 typed data structure，标准格式作为 exporter，而不是反过来
  控制全部内部模型。
- Expr AST 是约束、派生属性和 rule 的正确方向；最大深度、函数白名单、原型污染防护
  值得参考。
- ObjectSet 接口与 Neo4j compiler 分离，说明 query abstraction 不必绑定 store。
- Builder、Validator、Exporter 分层比“一个 Ontology facade 做所有事情”更利于演进。
- schema diff、lineage、SHACL/OWL/JSON Schema 多投影正好对应 Loushang 的长期需求。

#### 代码审查发现

- ActionEngine 还没有真正执行 ontology mutation，只把 parameters 当 result 返回。
- approval workflow、auto-approval、notification/webhook/stateChange/event side effects 都是
  placeholder；ActionType 的 role permissions 也没有接入 ActionEngine。
- custom action validation 被直接跳过。
- rule 的 SQL、Cypher、natural evaluator 返回 placeholder；legacy TypeScript string
  expression 在非 production 仍用 `new Function`。
- SHACL validator 是有限的 TypeScript 子集实现，不是完整 W3C SHACL engine；shape
  generator 也暂不内联 entity constraints。
- OWL/SHACL exporter 为手写 serializer，需要用标准 parser、reasoner、SHACL engine 和
  round-trip fixtures 验证，不能因能输出 Turtle 就宣称完整兼容。
- version manager 管的是通用 object snapshot，还没有 package-level schema migration
  和 compatibility policy。
- `0.0.1` 与实现中的 placeholder 表明它更适合做设计输入，而不是直接依赖的生产库。

定位：**canonical IR、safe expression、query abstraction、validation/exporter 结构的首要
参考；action、approval、standards conformance 需要 Loushang 自己完成。**

### 技术参考五：operational-ontology

快照：`gura105/operational-ontology` commit
`c79aa88c1f5d4fe2ac2b126a5852f1ba434aaa57`（2026-08-02），MIT，版本
`0.2.0`。TypeScript core 约 1,048 行；静态识别 55 个 core tests 和 10 个 MCP tests，
该提交的 GitHub Actions 通过。本地调研只读代码和 CI 结果，没有安装依赖。

#### 实际形态

这是一个刻意压缩到可通读规模的 operational write-path reference：

- object/link/action definitions 是可枚举的普通 typed values；
- SQLite 保存 indexed base、ontology-owned overlay、link instances 和 audit log；
- `execute()` 是公开 API 的唯一 mutation path，precondition 和 effects 先生成 edit plan；
- model 和 runtime 实际检查 source-backed 与 ontology-owned authority；README 另把
  derived 描述为不可写的概念分类，但 core 没有 `derived` StateAuthority declaration；
- write-back adapter 在本地 commit 前执行，并公开声明无法消除的 divergence window；
- `load()` 重建 source-backed base，同时保留 ontology-owned state，拒绝静默 orphan edit；
- MCP surface 从 model 生成 query/action tools，不暴露 raw SQL 或 generic update。

#### 最值得借鉴的机制

- authority matrix 是 action planning 的必要输入；未声明 source write、错误 write-back 和
  mixed-authority plan 都应在 effect 前被拒绝。
- MutationPlan 使用真实 commit path 做 rollback preflight，避免 validator 与提交语义漂移。
- applied、rejected、write-back failed 和 commit failed 都保留 machine-readable audit，
  failure semantics 是公开 contract 而非隐含实现细节。
- base + overlay 把来源刷新与 ontology-owned edits 分开，为 projection rebuild 和
  reconciliation 提供了小而清晰的参考。
- Agent 与其他消费者共享 action gate、precondition 和 visibility，而不是靠 prompt
  约束写入。

#### 使用边界

- 它把选择业务结果基本等同于 action instance，没有 DecisionType、Scenario、
  DecisionRecord、ChangeSet、Outcome 或反馈闭环。
- visibility 是 self-declared actor 上的 fail-open 演示，没有真实认证、property permission、
  approval 或 capability enforcement。
- rule/precondition/effect 仍是进程内 TypeScript callable，不是可序列化 safe logic IR。
- 同步 single-writer、write-back-first 仍存在外部成功而本地失败窗口；没有 persisted
  pending invocation、idempotency key、outbox 或自动 reconciliation。
- 没有 package/import/migration、双时态 facts、provenance、标准互操作、delete、link
  properties 或 composite keys。
- 没有 source revision vector、source coverage 或 identity-resolution contract；这些是
  Loushang 基于 multi-source materialization 问题提出的设计，不是该参考的既有机制。

定位：**Action gate、state authority、write-back、re-index overlay、audit 和 MCP 的首要
小型工程参考；不是 Decision-Centric、权限系统或完整生产 runtime 的架构来源。**

## 综合采纳矩阵

| 能力 | 第一参考 | 第二参考 | Loushang 决策 |
| --- | --- | --- | --- |
| 三层 ontology 概念 | Palantir docs / foundry-ontology-open | OpenFoundry | 吸收语义，不复制产品拓扑 |
| Typed canonical IR | ontograph-core | foundry-ontology-open | 自建 Python IR，保留稳定 ID/version |
| Safe expression / constraint | ontograph-core | OpenFoundry submission AST | 禁止任意 `eval`；结构化 AST 优先 |
| ObjectSet / query | ontograph-core | OpenFoundry | backend-neutral port + compiler |
| 分层运行架构与 read/write path | SuperML Ontology Architecture | operational-ontology | 六层职责图 + canonical fact spine，不照搬线性依赖 |
| Function / derived property | SuperML Functions | ontograph-core | typed、pure-first、可组合；外部执行经 LogicBinding/host |
| Decision / scenario / outcome | Palantir decision/agent articles | AIAO impact semantics | 一等 DecisionType/Record + 可审计反馈闭环 |
| Logic binding | Palantir decision/agent articles | ontograph-core expression IR | 绑定发布版本与 provenance，不内嵌任意模型代码 |
| Action planning | OpenFoundry | Palantir docs | plan/validate/preview/commit；Harness 执行能力 |
| 权限与治理 | Palantir docs / OpenFoundry | ontograph-core | ontology 声明需求，Harness/host 强制执行 |
| Data mapping / review | nano-ontoprompt | ontograph-core datasource | source mapping + identity + review + lineage |
| LLM authoring | nano-ontoprompt | — | suggestion only，draft/validate/review/publish |
| OWL/SHACL/JSON-LD | ontograph-core | AIAO/RePlanIT fixtures | 标准 bridge + external conformance tests |
| 领域包语义覆盖 | HWBook “7+1”（本地图片调研，非规范） | 现有核心模型与工程验收 | 只增加 authoring/readiness 检查，不增加八套 runtime |
| 大规模存储/索引 | OpenFoundry | SuperML serving layer | 当前定义 projection port，P4/P5 再引入分布式实现 |
| 环保 impact semantics | AIAO | RePlanIT | 独立 `environment-impact` package |
| ICT DPP / circularity | RePlanIT | AIAO | 独立 `environment-ict-dpp` package |

## 分阶段演进路线

### 已完成底座：Schema、Facts、Ports 与 Immutable Projection

实施状态（2026-08-10）：当前实现由
[ARD-001](../ARD-001-factstore-semantic-authority.md) 和
[ARD-002](../ARD-002-ports-immutable-projection-and-sqlite-v2.md) 收口，包括 schema
compiler/diff、双时态 Fact/Provenance、Memory/SQLite ports、immutable
`ProjectionSnapshot`、whole-snapshot replacement 和 reference query engine。旧的可变
ObjectStore、动态 facade、Callable rules、直接 fusion 和临时 Action bridge 已删除。

Schema v4 已为 ObjectType、object Property、LinkType 和 Action 实现独立于名称的显式
`semantic_id`；ObjectType、object Property 和 LinkType 同时声明三类 StateAuthority，
schema-diff v4 识别 rename、identity replacement、authority reassignment 和 Action
contract change。InterfaceType 目前仍按名称识别；source/logic binding 中的 source
binding 已实现，logic binding 和 source write routing 仍未实现，不能把读取侧 authority
binding 误称为 Action write-back。

### 已完成：Authority Binding 与 Memory-only Multi-Source Materialization

按照已接受的
[ARD-003](../ARD-003-declared-state-authority-and-multi-source-materialization.md)
继续实现：

- 已在 schema 声明层区分 `StateAuthority` 与 `AssertionKind`，投影对象、属性和关系
  暴露受约束的 operational origin；
- 已完成 stable semantic ID、`SourceBinding`、`MappingVersion` 和
  `SourceRevision`；
- 已按
  [ARD-004](../ARD-004-schema-identity-semantic-references-and-source-input-cuts.md)
  让 Fact v2 与 SourceBinding 绑定完整 `SchemaIdentity`，Fact 断言保存 stable
  semantic ID；
- 已完成原子 `FactSelection`、immutable projection state 与运行时 freshness 分离；
- 以 `MaterializationCut` 记录带 coverage 与 mapped-payload digest 的精确多输入构建
  坐标，同时保持 source head 为低成本 freshness 观测；
- 已用 Memory 验证 source-backed object/property/link、ontology-owned Fact 和 schema
  default 的确定性合成；
- 已明确 authority 冒充、binding/input 不匹配、多来源 object/link 冲突、未知 source
  head 和 mapped link endpoint 的失败语义。

读取与物化 contract 已完成这一轮校准；
[ARD-005](../ARD-005-source-aware-sqlite-v3.md) 已用 SQLite v3 持久化 source cut 与
完整 origin，并保持 whole-snapshot replacement、重启和备份语义。没有引入 v2
兼容层或 migration。

### 当前窄边界与后续阶段：Product Source Adapter 与 Identity

领域包、厂商 Adapter、Deployment Profile、省市多应用部署以及环保试点的边界设计，统一见
[Domain Ontology Ecosystem And Multi-Application Deployment](../key-designs/domain-ontology-ecosystem-and-deployment.md)。
该文档是 proposed Target key design；本调研稿不再复制其正式边界与制品合同。

- [ARD-006](../ARD-006-product-hosted-source-adapter-contract.md) 已完成
  application-schema identity、Adapter manifest、结构化 protocol 与 detached output
  conformance；concrete Product adapters、SDK/包分发仍未实现；
- [ARD-007](../ARD-007-fact-schema-revalidation-receipts.md) 已支持精确 FactSelection
  在兼容新 schema 下的不可变重校验；source mapping/input 的升级凭据与部署切换仍未实现；
- [ARD-008](../ARD-008-immutable-deployment-profile-and-artifact-locks.md) 保留
  Profile v1 的历史 artifact-lock 理由，其格式已被 ARD-010 取代；
- [ARD-009](../ARD-009-explicit-identity-crosswalk-snapshots.md) 已完成最小显式
  identity 边界：按 source instance、binding、record type 和 source key 定位记录，
  仅 confirmed resolution 可产生 canonical UUID，unresolved/conflict 均显式失败；
  mutable identity provider、alternate keys 和人工 review 仍未实现；
- [ARD-010](../ARD-010-deployment-bound-source-instances-and-identity-lock.md)
  已以唯一 Profile v2 格式绑定 source instance、Adapter binding 与精确 Crosswalk
  namespace/revision/digest；没有保留 v1 reader，也没有引入 endpoint、credential、
  部署激活或回滚服务；
- [ARD-011](../ARD-011-deterministic-ontology-package-artifacts.md) 已完成单 Schema
  package artifact、精确 dependency lock 与 closed-set 校验；multi-package semantic
  import/runtime composition、registry、版本求解以及 Alignment/Standards payload
  仍未实现；
- 两个 Product-side SQLite ERP/maintenance fixture 已证明不同 source key 可映射为
  同一 canonical object 并提供互不重叠的属性，且 unresolved/conflict 不会被静默合并；
- incremental cursor/change set、partial coverage 合并状态和 mapping review/publish；
- field-level lineage、source correction 和有限的显式 merge policy。

验收标准：同一对象的多个来源可以按 stable ID 合成且不丢 lineage；不确定 identity 和
未声明多来源冲突不会静默合并或覆盖。

### 进行中：最小 Operational Action

[ARD-012](../ARD-012-authority-aware-action-planning-and-product-hosted-write-back.md)
已经决定 source-backed 的 external write-back 与 managed edit 策略、effect/commit 顺序、
acknowledgement、幂等和失败恢复边界。ontology-owned `SetProperty` 的最小纵向切片已经
实现；下一步只验证一个 source-backed Action。跨 `StateAuthority` Action 继续直接拒绝，
不先建设 saga。

### 后续阶段：Decision-Centric Operations

在 Action boundary 稳定后再增加 DecisionType、LogicBinding、Scenario、ChangeSet、
DecisionRecord 和 OutcomeDefinition，以及 candidate comparison、context snapshot、approval、
HarnessWork evidence 和 expected/observed outcome linkage。Agent/MCP 只暴露已发布 typed
surface，不暴露任意 mutation。

### 延后阶段：Standards 与行业验证

- JSON-LD round trip；
- RDF/OWL 受控子集 import/export + diagnostics；
- SHACL generation 和 external validation；
- safe expression AST 和 validation/derived Claim contract；
- AIAO/RePlanIT 环保 fixture 与后续独立领域包。

这些能力用于互操作和领域验收，不阻塞 StateAuthority、materialization 和 Action 底座。

### 最后阶段：Platform Scale

确认真实负载后再评估：

- PostgreSQL/图存储/搜索 backend；
- event-driven indexing、cache invalidation、DLQ、reindex/compare/repair；
- multi-tenant object/property/link permissions；
- SDK/codegen、REST/RPC/MCP；
- Ontology Manager UI；
- distributed action orchestration 和 observability。

## 实施纪律

- 新增跨层 contract 前，先写 ontology ↔ harness/harnesswork/method 的边界测试，不让 ontology 反向
  import 这些包。
- 每种 store 实现共享 conformance suite，避免 backend 语义漂移。
- 每种 standard adapter 都需要 parser round trip、external validator/reasoner fixture 和
  unsupported-feature diagnostics。
- LLM 产物必须带 generator/model/prompt/source provenance，并保持
  `draft -> validated -> reviewed -> published`。
- 领域包必须通过 dependency/import 引入，不允许把领域类追加进 core enums。
- asserted、derived、inferred、raw source 和 object projection 在 API 中必须可区分。
- DecisionRecord、其 context snapshot 和已观测 Outcome 只追加不覆盖；重新评估通过
  `supersedes` / `reconsiders` 表达。
- Agent proposal、人工 decision、approval、action execution 和 outcome evidence 必须
  分开记录，不能把一段 LLM 文本同时当作建议、授权和事实。
- published package 的变更必须经过 diff、migration/compatibility diagnostics、CI 和
  review；重大不兼容变更先写 RFC/ARD，不能只在 UI 中直接修改。
- 每个业务 Action 至少有 golden path、precondition rejection、authorization denial、
  idempotent retry 和 commit/effect failure 测试；每个 row/property policy 都有防泄漏测试。
- 每个领域包提供少量端到端 operational scenarios，既作为 integration tests，也作为
  可阅读的业务行为说明。
- 先做 headless schema/runtime/API，再做大型 visual ontology manager。

### 工程验收基线

| 范围 | 最低验收内容 |
| --- | --- |
| Domain package | resources、vocabulary、constraints、logic、operations、governance、queries、outcomes 覆盖报告；缺项必须声明不适用或后续计划 |
| Schema | stable ID、描述、version、diff、compatibility diagnostics、migration/rebuild plan |
| Read path | object/property/row/fact policy、bounded traversal、aggregation 防泄漏、freshness diagnostics |
| Function | typed I/O、purity、dependency/version、cost bound、cache semantics、单元测试 |
| Decision | context snapshot、至少两个 Scenario、选择/拒绝理由、approval、expected Outcome、lineage |
| Action | typed params、deterministic preconditions、MutationPlan、StateAuthority、idempotency、audit、failure protocol |
| Projection | watermark、deterministic rebuild、actor/policy-safe cache key、compare/repair diagnostics |
| Scenario | ingestion → query/function → decision → action → HarnessWork evidence → observed outcome 全链路 |

验收测试应验证同一个 contract 对人、产品服务和 Agent 一致生效；不能只测试 SDK 返回值，
还要检查 audit、fact lineage、projection freshness、外部 effect evidence 和拒绝路径。

## 应明确避免的路线

- 以 Neo4j/GraphDB 选型代替 ontology architecture。
- 把 OWL 文件当作业务事务数据库。
- 把每条规则都保存为 Python/TypeScript source 并动态执行。
- 把 action executor、HTTP client、approval queue、audit service 全塞进 ontology 包。
- 让 external effect 成功一半后仍返回“原子 action 成功”。
- 因为 OpenFoundry 功能全面，就提前创建数十个服务。
- 原样导入 RePlanIT 的 functional properties 和 class/instance 混用。
- 因为 ontograph-core 有 exporter，就假定其输出已经完整符合 OWL/SHACL。
- 让 nano-ontoprompt 式 LLM discovery 自动发布为 runtime truth。
- 把 SuperML 的教学分层当作已经解决 state authority、write-back 一致性和 Decision-Centric
  semantics 的生产实现。

## 开放问题

在后续 ARD 中需要进一步决定：

- ARD-003 选择的 package-local stable ID + namespace resolution 已由 schema v4
  serialization contract 收口；interface identity 是否扩展仍待具体需求；
- schema package 的 SemVer compatibility 规则；
- InterfaceType 是 structural conformance 还是 nominal declaration，或两者都支持；
- action commit 与不可补偿外部 effect 的顺序和 failure protocol；
- DecisionRecord 存储是否复用 FactStore，以及 context snapshot 采用引用、内容寻址还是
  独立 immutable projection；
- LogicBinding 第一版支持 function/rule/method/model 中的哪些 execution kind，以及
  model output 的 confidence 和 provenance contract；
- Outcome 的观测窗口、评估触发与迟到数据修正语义；
- environmental package 存放在本仓库、独立仓库还是 resource pack；
- RDF/OWL import 第一版明确支持哪些 axiom，哪些只保留 opaque metadata。

## 开发工作区

- 长期 lane：`/home/dev/workspace/loushang/.worktrees/ontology`
- 集成分支：`lane/ontology`
- 参考根目录：`/home/dev/workspace/ontology`

ontology-dominant 的实现、测试和架构文档在该 lane 创建 task branch 或汇入
`lane/ontology`；最终验证、merge/push 仍由 control lane 完成。所有参考仓库默认只读，
用于理解设计、边界和失败模式，不直接复制代码。

## 参考仓库快照

| 仓库 | Commit | 日期 | 角色 |
| --- | --- | --- | --- |
| `cloudbadal007/foundry-ontology-open` | `b349cdc` | 2026-07-19 | 最小三层原型 / MCP |
| `P2Enjoy/OpenFoundry` | `d7c40cf5` | 2026-05-12 | 大规模 operational platform |
| `jingw2/nano-ontoprompt` | `0a80458` | 2026-07-24 | ingestion、mapping、review、LLM authoring |
| `openshuyi/ontograph-core` | `28135fd` | 2026-04-29 | typed ontology core / interop structure |
| `gura105/operational-ontology` | `c79aa88c` | 2026-08-02 | action gate / authority / write-back / re-index |
| `RePlanIT/Ontology` | `ca5e127` | 2024-07-11 | ICT DPP / circular economy domain |
| `aiaont/aiao` | `8584e11` | 2026-05-06 | environmental/social impact accounting |

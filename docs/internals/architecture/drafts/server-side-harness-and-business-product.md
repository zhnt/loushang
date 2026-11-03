# 服务端 Harness 与业务 Product 边界（讨论稿）

## Status

- ID: `SERVER-SIDE-HARNESS-DRAFT`
- Kind: discussion draft
- Scope: Harness / Agent / Product / Ontology 交叉边界
- Parent: Loushang
- Authority: proposed — 非规范性讨论稿
- Design status: draft
- Implementation status: not-applicable
- Owner: Loushang architecture（讨论稿，未指派）

本文是一个**讨论稿**，用于回答一个具体问题：

> 若要让 Loushang 承载"服务端托管的业务 Agent"（多用户、多租户、可调用业务后台），
> 应当如何划分 Harness、业务 Product、Ontology 与业务后端之间的边界？

本文**不是**已接受的 Target，也**不**提出新的 Harness 契约。文中所有关于 Loushang
现状的陈述都标注为 Fact/Current 并给出源码或已接受 ARD 依据；所有建议标注为 Draft。
当本文与代码、测试或已接受 ARD 冲突时，以 live source 为准。

本文刻意保持与具体业务系统无关：具体 Product 的领域词汇、表结构与业务规则属于该
Product 自身文档，不进入本文。

## 1. 问题与范围

### 1.1 要回答的问题

1. 服务端托管 Agent 时，**哪些能力属于 Harness，哪些属于业务 Product**？
2. **"工作区""沙箱""临时数据"** 在服务端应如何理解与使用？
3. **工具（Tool）** 应当是后端服务的镜像，还是别的形态？
4. **用户身份、代理（委托）关系、行级/列级数据权限** 应当落在哪一层？
5. **Ontology 的动作（Action）** 能否承担业务动作执行？边界在哪？
6. 现有实现中**哪些是缺口**，必须先自建或先论证？

### 1.2 非目标

- 不定义新的 Harness 公共 API；
- 不定义业务 Product 的数据模型与业务规则；
- 不承诺多租户运行时（见 §7.1 G10）；
- 不评估具体厂商或部署平台；

## 2. 事实基线（Fact / Current）

以下各项均为当前源码可核验的事实。文件路径省略 `src/loushang/` 前缀。

### 2.1 分层词汇与依赖方向

`docs/internals/architecture/harness/shared-capability-boundaries.md` 给出的职责栈为：

```text
client / UI / SDK
  -> channel
  -> work
  -> method            # 可选
  -> product adapter   # coding / design / research / ppt / cowork / 业务 Product
  -> harness           # 机制
  -> agent             # agent loop
  -> ai
```

该文档同时规定：Harness 必须位于 Product adapter 之下、Agent 之上，且**不得**向上依赖
product / work / method / channel / TUI / AI provider。Product 的不可约内核（Product
Kernel）明确包含 **"risk classification, approval defaults, and permission policy"**，
以及领域工具、prompt、产物语义。

### 2.2 授权运行时的三层分离

`docs/internals/architecture/harness/policy-approval-redesign.md` 将三件事分离且禁止合并：

| 关注点 | 问题 | 归属 |
| --- | --- | --- |
| Policy | 该 actor 能否尝试该精确动作？ | 授权运行时 |
| Approval | 谁可以授予一个有界例外、有效期多久？ | 审批协调器 |
| Enforcement | 进程实际能读/写/执行/访问什么？ | executor / sandbox |

同文档规定：

> Authorization, approval coordination, Sandbox enforcement, limits, audit, and
> cleanup remain non-bypassable internals of the applicable Harness Capability.
> They are not public replacement nodes.
> （`shared-capability-boundaries.md` 的 Lifecycle 节）

且 Product 包 **不得**重新实现或再导出这些机制
（`policy-approval-redesign.md` 的 Physical Module Layout 节）。

### 2.3 工具执行的强制路径

已实现的事实（`harness/tools/execution.py`、`harness/tools/workspace/authorization.py`）：

1. `ToolExecutionHost.dispatch` 按声明的执行绑定分派；
2. **`DirectExecution` 直接调用 handler，不经过 Policy/Approval**；
3. `AuthorizedExecution` 经 `WorkspaceToolAuthorizationGateway.execute`；
4. 网关在调用 executor **之前两次**校验动作指纹
   （`_revalidate_authorized_action`，分别位于授权返回后与执行前）；
5. 指纹覆盖 `tool_name` + `authorization_arguments` + `cwd` + 类型化 `effects`
   （`_fingerprint`）；
6. `PreparedToolAction` 区分 `authorization_arguments`（策略/审批/指纹所见）与
   `execution_arguments`（handler 所见），二者可以不同；
7. 审批决策区分 `once` / `session`；`once` 不得携带 grant，`session` 必须携带；
8. `InMemoryApprovalGrantStore` 为会话所有，**无 TTL**，resolver 销毁即整体撤销。

### 2.4 身份模型的现状

- `harness/policy/subjects.py` 的 `ToolPolicySubject` 字段为
  `tool_name / arguments / cwd / command / paths / effects / capability_id`，
  **不含任何 user / tenant / principal 字段**；
- `harness/approval/ports.py` 的 `approval_actor_id` 从注入的 resolver 读取
  `actor_id`，缺省为 `"root"`；
- `appserver/protocol/model.py` 的 `SessionIdentityV1` 字段为
  `product_id / continuity_id / session_id / scope / scope_fingerprint`，
  **不含终端用户或租户**；
- Harness 中不存在业务用户模型（对 `user_id` / `tenant_id` 的检索仅在 Plugin
  生命周期记录中命中，语义为"操作主体 id"，非业务用户）。

结论（Fact）：**身份只能绑定在 Session 级的注入实例上，不能在单次工具调用参数上携带。**

### 2.5 效果的封闭性

`harness/effects.py` 定义 `ToolEffect` 为封闭联合：

```text
FilesystemEffect | ProcessEffect | NetworkEffect | PublicationEffect
```

`NetworkEffect` 仅含 `target: str` 与 `mutation: bool`。**不存在**"读取业务记录"
这类效果，也不存在可注册的自定义 effect 类型。

### 2.6 能力（Capability）图与授权上限

- `harness/capabilities/workspace_contracts.py` 定义 `harness.workspace`：
  facets 为 `read / list / search / write / edit / process.launch`，
  scope 为 `workspace`，`authority_ceiling = {filesystem, process}`；
- `CapabilityBundleProvider.required_authorities` 超出 Definition 的
  `authority_ceiling` 时，`graph_planning.py` 产生
  `authority_ceiling_exceeded` 诊断；
- 已 production-mounted 的顶层 Capability 为 `harness.workspace`、
  `harness.resources`、`harness.session`、`harness.model_input`、
  `coding.lsp`、`coding.arch`（`docs/internals/architecture/harness/capability-catalog.md`）；
- `RuntimeCapabilityScope` 词表包含 `process / tenant / workspace / session / turn /
  channel`（`harness/capabilities/contracts.py`）；**未检索到 tenant 级运行时实现**
  （负向检索结论，非已证事实；见 §7.1 G10）。

### 2.7 沙箱与进程

`harness/sandbox/` 与 `docs/internals/architecture/harness/sandbox-runtime-boundary.md`：

- `SandboxSettings.enabled` 默认 `False`（沙箱可选、默认关闭）；
- 默认注册表仅含 Linux bubblewrap 后端；其他平台为
  "no default backend"；
- `SandboxScopeRequest.network` 默认 `"allowed"`；仅显式 `restricted` / `denied`
  才加 `--unshare-net`；
- 已隔离项：user / pid / ipc / uts namespace、root 绑定、可写根白名单；
- Phase B 只接受目录级 root，拒绝缺失 root 或矛盾请求而不做部分生效；
- 未检索到 CPU / 内存级 cgroup 限额（负向检索结论）。

### 2.8 临时数据与运行作用域

- `foundation/runtime_scope.py` 自述为 **"Process-local runtime scopes"**；
  `RuntimeScope` 提供 `drafts`、`artifacts` 子目录；
- `RunLease` + `sweep_runtime_runs`：仅回收"租约有效且锁可获取"的目录，先原子改名
  为 `.gc-*` 再删除；无有效租约的目录永不自动删除；
  默认策略 `stale_after_seconds=24h`、`max_inactive_runs=32`、
  `max_inactive_bytes=512MB`；
- `harness/machine_resources/control_plane.py` 的 `MachineResourceLifetime`
  含 `disposable_scratch`；
- `docs/internals/architecture/harness/machine-local-runtime-storage.md`
  给出 `PlatformPaths -> RuntimeResourceOwner -> RuntimeScope / RunLease /
  ArtifactStore` 的所有权链，并声明 leaf 不获得删除整棵 run 树的权限。

### 2.9 托管与传输

- `appservice/*` 仅依赖 `appserver.protocol` 与 `appserver.execution.model`；
  **不依赖 Harness / Product / UI**；其 Non-Goals 显式排除
  "connection, listener, wire dispatcher, authentication, IPC, WebSocket,
  daemon, process controller or multi-client controller takeover"
  （`docs/internals/architecture/appservice/README.md`）；
- `appserver/local.py` 为 **loopback TCP**（`127.0.0.1`），
  `MAX_LOCAL_CONNECTIONS = 8`（其中 1 个预留给 stop）；
- `appserver/local_auth.py` 自述范围为
  **"mutual authentication and integrity, not encryption or endpoint discovery"**，
  认证材料来自本机私有 record 文件；
- Product 侧的托管接缝为 `HostedSessionResolverV1` / `HostedSessionPortV1`
  （`appservice/ports.py`），参考实现为 Coding
  （`coding/appservice_adapter.py`、`coding/hosted_application.py`）；
- AppHost 的 Product 注册契约为 `ProductRegistrationV1` /
  `ProductFactoryV1.create_runtime` / `ScopedProductRuntimeV1`
  （`apphost/contracts.py`）。

### 2.10 Ontology 的执行边界

`docs/internals/architecture/ontology/ARD-012-authority-aware-action-planning-and-product-hosted-write-back.md`：

- Action 语义编译进 Schema（`ActionDefinition`），首版 effect 仅
  `SetProperty(property_id, value_parameter)`；
- `loushang.ontology.action` 为**纯规划**：接受不可变值、返回不可变 `ActionPlan`，
  不打开 store、不调 API、不评估身份凭证、不执行工具；
- `ActionPlan` 的类注释为
  **"Pure first-slice plan; authorization and execution remain external."**；
- `policy_requirement_ref` 被明确定义为**不透明语义需求**，不是内嵌策略语言；
  Product 提供已认证 actor 上下文并调用其策略/审批边界；
- 授权决定必须绑定到精确的 `plan_digest`；
- 依赖方向为单向，原文：

```text
ontology.action -X-> Product implementation, vendor SDK, network, database
ontology        -X-> harness, harnesswork, method, agent
```

- 核对结果：`loushang/ontology/` 与 `loushang/harness/` 之间**互无 import**；
- Object 创建/删除、属性清空、link mutation、多 effect、内嵌 HTTP/SQL/shell/Python
  均标注为 deferred；source-backed write-back **未实现**。

### 2.11 工具治理的现状与目标态

`docs/internals/architecture/harness/tool-governance.md` 的 Status 原文：

> Design status: **reviewed target contract; runtime implementation is
> incremental and is not completed by this document.**
> Implementation status: **P1A governed intent semantics are implemented behind
> opt-in capabilities; existing Product sessions remain on isolated
> `legacy_positive` state pending the P1B atomic control-surface cutover.**

核对结果：

- `ToolPlan`（per-Model-Call 不可变工具快照）在 Python 源码中**无实现**；
- 现存实现为 `ToolActivationCoordinator`，其 docstring 自述
  "Legacy positive-list coordinator retained until governed-v1 cutover"，
  `engine_mode = IntentEngineMode.LEGACY_POSITIVE`；
- 同文档承认现存问题："Model exposure is mutable. The session has no
  first-class immutable record proving which schemas, definitions, and bindings
  one Model Call saw."

设计意图上的工具生效等式为
`Catalog availability ∩ Tool Intent ∩ Tool Policy ∩ Provider Support`，且
`ToolPlan` 的 revision vector 含 `principal_revision` / `workspace_revision` /
`mode_revision` —— 即"按主体与工作区取不同工具集"属于设计内建能力。

设计约束同时规定：

> Tool ownership alone grants no intent authority.
> No plugin or pack reconstructs the global Catalog from its local view.

### 2.12 子 Agent 的非扩张

`harness/multiagent/delegation.py` 的 `DelegatedExecutionProfile` 含
`allowed_tools` 与 `execution_profile_ceiling`，并强制校验；结论为
**child authority is an intersection, never a union**
（`policy-approval-redesign.md` 验收段）。

`harness/multiagent/control.py` 的 `ControlLimits` 提供
`max_open_agents`（整棵树共享）、`max_spawn_depth`、`maximum_children`；
超限返回结构化工具结果而非异常。驻留 / LRU 回收标注为二期、**未实现**。

## 3. 关键约束（由 §2 直接推出）

| # | 约束 | 依据 |
| --- | --- | --- |
| C1 | Product **不得**重实现 Policy / Approval / Sandbox；只能注入实现 | §2.2 |
| C2 | 身份只能绑定在 Session 级实例上，不能随单次调用传递 | §2.4 |
| C3 | 单次工具调用的安全相关字段必须显式声明，否则**静默**不进入策略、审批与指纹 | §2.3(6) |
| C4 | 未声明为 authorized 的工具完全绕过治理 | §2.3(2) |
| C5 | `ToolEffect` 无法表达"业务记录读/写"，业务数据权限必须在 Harness 之外实现 | §2.5 |
| C6 | `harness.workspace` 的权限词汇是 `filesystem` + `process`，不含数据库 | §2.6 |
| C7 | Ontology 不执行外部写、不评估身份、不加载策略 | §2.10 |
| C8 | 子 Agent 权威是交集，永不为并集 | §2.12 |
| C9 | per-Model-Call 的工具暴露证据**当前不可得** | §2.11 |
| C10 | 沙箱默认关闭、网络默认放行、非 Linux 无后端 | §2.7 |
| C11 | 运行作用域是 process-local 的 | §2.8 |
| C12 | AppService / AppServer 不提供认证，且不是"访问 Harness 的入口" | §2.9 |

## 4. 建议形态（Draft）

### 4.1 总体形状

**架构图见 §4.7 的图 1。**

读图三要点：

- AppService / AppServer **不在**默认路径上。仅当需要"会话可分离、可重连、
  多客户端接管"时才引入（见 §4.5）；
- 业务 Product **同时**依赖 Harness 与 Ontology，是唯一组合根；
- 边缘认证与租户由部署方自建（C12）。

### 4.2 分层职责矩阵（Draft）

| 问题 | 归属 | 理由 |
| --- | --- | --- |
| 该用户是谁？能看哪行/哪列数据？ | 业务 Product（③ 数据权威层） | C2、C5、C6 |
| 该动作是否允许？是否需要人工审批？ | Product 声明策略语义 + Harness 执行机制 | §2.2、C1 |
| 进程能读哪些文件、能否联网？ | Harness Sandbox | C10、§2.7 |
| 该动作在业务语义上意味着什么？ | Product 工具层（+ 可选 Ontology） | §2.10 |
| Agent 看到哪些历史与上下文？ | Harness Session / Transcript | §2.6 |
| 中间产物放哪、何时清理？ | Harness RuntimeScope + workspace | §2.8、C11 |
| 工具集当前包含哪些？ | 角色模板 + 会话裁剪（见 §4.4） | C9、§2.11 |

### 4.3 服务端"工作区"的正确定义（Draft）

建议将三者明确区分，不要混为一谈：

| | 内容 | 生命周期 | 隔离手段 |
| --- | --- | --- | --- |
| **工作区** | 会话级受限目录；中间产物（导出文件、报告、脚本、日志） | 会话 / 运行作用域 | Harness sandbox + 可写根白名单 |
| **临时数据** | 运行期的草稿、剪贴板、缓存 | run 级，可回收 | `RuntimeScope` + `RunLease` + `disposable_scratch` |
| **业务数据** | 业务事实与状态 | 持久 | 业务 DB + 行/列权限过滤（Harness 不参与） |

**结论**：服务端"工作区"= **沙箱化的临时空间**，**不是**数据库，也不是应用服务器。
Harness 的 `authority_ceiling` 只覆盖 `filesystem` + `process`（C6）。

### 4.4 工具集裁剪（Draft）

不采用"技能运行时动态加载工具"，而采用**静态声明 + 会话装配 + 策略求值**三层：

```text
① 角色/租户模板（部署时静态声明，可 diff / 可评审 / 可测试）
     allowed_tool_names: [...]
     skills: [...]              # 仅引导，不授予能力
     policy: { tool_name: allow|ask|deny }
        ↓
② Session 装配时确定 allowed 集合
     （Harness 已有非扩张约束可复用，见 §2.12）
        ↓
③ 每轮由 Session 级 PolicyEvaluator 求值 allow / ask / deny
        ↓
   本轮模型可见工具集
```

三条设计要点：

1. **技能只做引导**。遵循 "Tool ownership alone grants no intent authority"：
   技能/资源不得因"携带了工具"而扩张本会话工具集；
2. **非扩张**。会话 `allowed` 集合必须是目录子集；技能引用的工具必须已在角色模板内；
3. **显式声明安全字段**。每个 authorized 工具必须有非空 `authorization_fields`，
   否则触发 C3 的静默漏字段问题。

### 4.5 何时引入 AppService / AppServer（Draft）

| 需求 | 是否需要 | 依据 |
| --- | --- | --- |
| 后端进程内调用 Agent | 否 | 直接组合 Product + Harness |
| 会话需脱离进程、可重连、多客户端接管 | 是 | AppHost/AppServer/AppService 的 G11–G17 交付批次提供该边界 |
| 需要 HTTP 入口 | 否（建议边界外） | AppService/AppServer 无认证（C12） |

若确实需要，**不要**把 AppService 当作"访问 Harness 的网关"——它是
transport-neutral 的托管应用边界，只认识 Product 提供的 Session 端口（§2.9）。

### 4.6 业务动作的落位（Draft）

| 动作类型 | 建议落位 | 理由 |
| --- | --- | --- |
| 查询业务数据 | Product 工具（authorized）+ 后端查询层过滤 | C5、C6 |
| 业务写入（多步 / 多系统） | Product 自建动作治理链 | §2.10：Ontology 首版 effect 仅单属性 |
| 单属性语义修改（如"设置某对象某属性"） | 可考虑 Ontology Action | `plan_digest` 绑定授权，改参即失效 |
| 外部系统无 API（RPA / GUI 自动化） | Product 自建治理链 + 增强审计 | 不可控因素多，回读验证困难 |

**不建议**把业务动作语义压进 `ToolEffect`：`NetworkEffect` 只保留
`target` + `mutation`，会丢失业务可读性与审批所需信息（C5）。

### 4.7 关键架构图

本节集中本稿全部架构图，避免同一形状在多节重复。图 1 为静态分层总览；
图 2–3 说明动态路径；图 4 为反例清单；图 5 为部署拓扑与前提。
图中 `[G1]` / `[G9]` / `[G10]` 指回 §7.1 的缺口编号，`[!!]` 指回 §7.3；图 4 每行均指回 §3 或 §2。

#### 图 1 · 总体形状（静态分层）

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 边缘层（Product / 部署方自建 · Harness 不参与）                        │
│   HTTPS · 认证 · 租户 · 配额 · 限流                                    │
│   产出 (user, tenant, role, scope) 上下文                              │
└────────────────────────────────────────────────────────────────────────┘
                                   │ 进程内调用（推荐，非 HTTP 回环）
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 业务 Product（Product Adapter · 组合根 · 唯一）                        │
│   ① 领域工具层   领域意图工具，非 API 镜像                             │
│        ↓ handler 直接调 ②                                              │
│   ② 应用服务层   业务服务调用                                          │
│        ↓                                                               │
│   ③ 数据权威层   DB + 行级 / 列级过滤   ◄── 数据权限只在这里           │
│                                                                        │
│   ④ 策略层   PolicyEvaluator  （闭包持有身份上下文）                   │
│   ⑤ 审批层   ApprovalResolver （actor_id = 实际操作者）                │
└────────────────────────────────────────────────────────────────────────┘
                                   │ 注入（不得重实现机制）
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ loushang.harness（机制 · 不可绕过）                                    │
│   Policy → Approval → Gateway → 执行期复验 → 审计                      │
│   harness.workspace（每会话受限目录）· Sandbox · ProcessHost           │
│   Session / Transcript / Context                                       │
│   authority_ceiling = {filesystem, process}   ◄── 无 database          │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ loushang.ontology（可选 · 与 harness 并列，非其下层）                  │
│   仅“单属性 SetProperty”类语义动作：                                   │
│   纯规划 + plan_digest + FactCommit                                    │
│   不执行外部写 · 不评估身份 · 不加载策略                               │
└────────────────────────────────────────────────────────────────────────┘
```

三个读图要点，分别对应本文三条核心论断：

1. **边缘层在 Harness 之外** —— 认证与租户不是 Harness 能力（C12、G2）；
2. **③ 是唯一的数据权限点** —— `authority_ceiling` 只有 `filesystem` + `process`，
   不含 database（C6）；
3. **Ontology 与 Harness 并列**，互不依赖，由 Product 在组合根汇合（C7）。

#### 图 2 · 数据流（一次工具调用）

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 边缘层                                                                 │
│   认证 → (user, tenant, role)                                          │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Product 装配：每用户一个 Session                                       │
│   PolicyEvaluator   （闭包: user / tenant / role）                     │
│   ApprovalResolver  （actor_id = user）                                │
│   allowed_tool_names  ⊆ 角色模板 ⊆ 工具目录                            │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ harness：本轮可见工具集                                                │
│   目录 ∩ 会话意图 ∩ 策略 ∩ Provider                                    │
│   [G1] —— 此快照无官方证据（ToolPlan 未实现）                          │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 模型选择工具 + 参数                                                    │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ harness：PreparedToolAction                                            │
│   authorization_arguments  ← 策略 / 审批 / 指纹所见                    │
│   execution_arguments      ← handler 所见                              │
│   [!!] 二者可不同；authorization_fields 漏写不报错                     │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ harness：Gateway                                                       │
│   1. PolicyEvaluator.evaluate() → allow / deny / ask                   │
│        此处才拿到 subject.arguments，可生成业务化审批文案              │
│   2. 若 ask → ApprovalResolver（服务端默认 deny）                      │
│   3. EffectiveExecutionProfile 求交（不可扩张）                        │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ harness：指纹冻结 + 执行前两次复验                                     │
│   指纹变化 → ExecutionAuthorizationError，不调用 executor              │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Tool handler → ② 应用服务层 → ③ 数据权威层                             │
│   行 / 列过滤在 ③；Harness 不参与                                      │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 结果 → 审计事件（已脱敏）                                              │
└────────────────────────────────────────────────────────────────────────┘
```

图 2 是理解本稿分层的关键：**业务语义只在 Gateway 的策略求值处进入**，
因此 `PolicyEvaluator` 是唯一能生成业务化审批文案的位置（§4.6）。
图中同时可见 `authorization_arguments` 与 `execution_arguments` 的分叉点（§7.3）。

#### 图 3 · Ontology Action 的正确形态（时序）

```text
┌────────────────────────────────────────────────────────────────────────┐
│ ① 读受 guard 的 Projection                                             │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ ② ontology 纯规划                                                      │
│   ActionPlan + plan_digest + policy_requirement_ref                    │
│   不开 store · 不调 API · 不评估凭证 · 不执行工具                      │
└────────────────────────────────────────────────────────────────────────┘
                                   │   ── ontology 到此为止 ──
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ ③ Product 组合根（唯一）                                               │
│   认证 actor → 策略 / 审批                                             │
│   授权决定必须绑定 plan_digest                                         │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                            ┌──────────┴──────────┐
                            ▼                     ▼
┌──────────────────────────────────┐  ┌──────────────────────────────────┐
│ ④a ontology-owned                │  │ ④b source-backed                 │
│   Fact commit                    │  │   Product-hosted write adapter   │
│   watermark CAS 守卫             │  │   回执 accepted / rejected /     │
└──────────────────────────────────┘  │   unknown                        │
                                      │                                  │
                                      │   ⑤ 独立 reconcile               │
                                      │   observed / not_observed /      │
                                      │   unknown                        │
                                      │   [!!] unknown 不得换新幂等键重试│
                                      └──────────────────────────────────┘
```

`plan_digest` 绑定授权的含义：**改任何一个参数，摘要即变，原授权自动失效**。
这是“同意的是这个具体动作，而不是这个意图”的形式化表达（§2.10）。

#### 图 4 · 反例（错误形态）

| # | 错误形态 | 违反 | 后果 |
| --- | --- | --- | --- |
| A | 后端 API 逐个包装成工具（API 镜像） | C5 | 工具爆炸；审批只见 `POST /api/orders`；后端重构需改提示词 |
| B | 共享 Session + 每次调用传 userId | C2 | `PolicySubject` 无此字段；需改 Harness 核心契约，属新 ADR 范畴 |
| C | 技能 / 插件决定本会话工具集 | §2.11 | 违反 "Tool ownership alone grants no intent authority"；任何加载的技能都成扩张通道 |
| D | 业务工具用 `direct_tool` | C4 | 完全绕过 Policy / Approval |
| E | 自报身份头（如 `X-User-ID`）作为授权依据 | §7.3 | 凭证风险转为头伪造风险，且伪造点是所有代理请求的公共通道 |
| F | 把 AppService 当作 Harness 网关 | §2.9 | 依赖方向相反；其 Non-Goals 明确排除 authentication |

#### 图 5 · 部署拓扑与前提

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Linux 容器（唯一有隔离的平台 · C10）                                   │
│   FastAPI worker-1                FastAPI worker-2         …           │
│     ├─ RuntimeScope(run_id)         ├─ RuntimeScope(run_id)            │
│     │    /runs/<id>/                │    /runs/<id>/                   │
│     │      ├─ drafts/               │      ├─ drafts/                  │
│     │      └─ artifacts/            │      └─ artifacts/               │
│     └─ session 工作区               └─ session 工作区                  │
│                                                                        │
│   ▲ C11：运行作用域是 process-local，各 worker 各持目录                │
│                                                                        │
│   bwrap 沙箱（默认关闭，需显式开启；网络默认 allowed）                 │
│     ├─ unshare user / pid / ipc / uts                                  │
│     ├─ root ro-bind + 可写根白名单                                     │
│     └─ [G9] 未检索到 CPU / 内存限额 → 配额需在容器层实现               │
│                                                                        │
│   业务 DB   ◄── 沙箱不覆盖；隔离靠后端查询层                           │
│   [G10] 未检索到 tenant 级运行时                                       │
└────────────────────────────────────────────────────────────────────────┘
```

图 5 说明一个容易被忽略的前提：**“服务端 Harness”的安全上限由部署平台决定，
而非由框架决定**。在非 Linux 平台上 Enforcement 支柱没有后端（C10），
Policy 与 Approval 仍然存在，但没有任何机制强制它们。
分层职责的完整矩阵见 §4.2，本节不重复。

## 5. 关键设计点详述（Draft）

### 5.1 身份与代理（委托）

由于 C2，建议采用 **"一用户会话 → 一个 Harness Session → 一组绑定该身份的
Policy / Approval 实例"**，而不是"共享 Session + 每次调用传 userId"。

代理（A 代表 B 行事）建议实现为：

- **委托人**与**代理人**身份进入 Session 装配上下文；
- 有效权限 = `委托人权限 ∩ 代理人自身权限 ∩ 操作所需权限`（交集，与 C8 一致）；
- `ApprovalResolver.actor_id` 使用**实际操作者**的身份，以便审批与审计可区分
  "本人操作"与"代理操作"；
- 授权范围与有效期在 Product 侧持久化（Harness 的 session grant 无 TTL，见 §2.3(8)）。

**开放问题**：代理链是否允许二次代理、最大级数、批量撤销语义——见 §9。

### 5.2 执行期复验与一次性授权

Harness 已提供可复用的语义（§2.3、§2.10）：

- 动作指纹冻结 + 执行前复验；
- 一次性消费 + 过期 + 撤销纪元 + 日志版本 CAS
  （`harness/approval/plugin_execution.py` 的
  `AVAILABLE / DENIED / CONSUMED / REVOKED` + `expires_at_unix_ms` +
  `revocation_epoch` + `consume_execution_decision` / `revoke_execution_decision`）。

建议业务侧的动作治理链**对齐这些语义与命名**，而不是另起一套。典型链路：

```text
动作提案（冻结 + 摘要）
  -> 策略裁决 allow / deny / need_approval
  -> 审批（如需）→ 绑定摘要的一次性授权
  -> 执行前复验摘要
  -> 执行 → 回执 accepted / rejected / unknown
  -> 独立回读验证 observed / not_observed / unknown
```

其中 `unknown` 语义应遵循 ARD-012 的规则：**不得**换新幂等键盲目重试。

### 5.3 数据权限必须在后端

由 C5、C6，行级/列级权限、敏感字段隔离只能在后端查询层实现：

- 查询强制拼接"可见范围"条件；
- 敏感字段在**后端即不下发**（不依赖前端隐藏）；
- 可见范围收敛为单一函数/视图，禁止各查询各自实现；
- 这一层与 Harness 无耦合，未来可平滑映射为策略条件。

### 5.4 沙箱与临时数据的使用前提

使用 Harness 沙箱与运行作用域前，需先确认：

| 前提 | 说明 |
| --- | --- |
| 平台 | 仅 Linux 有默认后端（C10）；macOS / Windows 无隔离 |
| 显式开启 | 默认关闭，需显式启用并设定 requirement |
| 网络策略 | 默认 `allowed`；收紧需显式决策 |
| 多进程拓扑 | 运行作用域是 process-local（C11）；FastAPI 多 worker 各持目录 |
| 资源限额 | 未检索到 CPU / 内存级限额；多租户配额需在容器层实现 |
| 数据库 | 沙箱不覆盖 DB 隔离 |

### 5.5 审计证据的补位

由 C9，per-Model-Call 的工具暴露快照当前不可得。建议在 ToolPlan 落地前，
由 Product 侧自行记录：

```text
turn_id / session_id / actor / role / tenant
effective_tools[]      name, definition_fingerprint, source(role_template)
policy_evaluations[]   tool_name, disposition, policy_code
excluded[]             name, reason_code
```

未来 ToolPlan 落地后可替换为官方证据。

## 6. 与现有契约的映射（Draft）

| 需要实现 | 复用的接缝 | 参考实现 |
| --- | --- | --- |
| Product 注册 | `ProductRegistrationV1`、`ProductFactoryV1`、`ScopedProductRuntimeV1` | `coding/hosted_application.py` |
| Profile | `ProfileRegistrationV1`、`ProfileFactoryV1.bind_profile` | `CodingHostedProfileFactoryV1` |
| 托管会话（如需要） | `HostedSessionResolverV1`、`HostedSessionPortV1` | `coding/appservice_adapter.py` |
| 策略 | `PolicyEvaluator.evaluate(subject) -> PolicyDecision \| None` | `examples/harness/document_product.py` |
| 审批 | `ApprovalResolver`、`ApprovalPresenter`、`HeadlessApprovalResolver` | 同上（默认 headless deny） |
| 工具授权 | `authorized_tool` + `ToolActionAdapter` | `examples/harness/tool_authoring.py` |
| 一次性授权语义 | `harness/approval/plugin_execution.py` 的决策记录与消费语义 | — |
| 运行作用域 | `RuntimeScope`、`RunLease`、`sweep_runtime_runs` | `foundation/runtime_scope.py` |
| 沙箱 | `SandboxSettings`、`SandboxScopeRequest`、`EffectiveExecutionProfile` | `harness/sandbox/` |
| 子 Agent 上限 | `ControlLimits`、`DelegatedExecutionProfile` | `harness/multiagent/` |
| 语义动作（可选） | `ActionDefinition` / `ActionPlan` / `plan_digest` | `ontology/action/`（纯规划，读侧） |

**注意**：上表所有 Harness 侧接缝均为**注入式**，不需要修改 Harness 源码。

## 7. 已知缺口与风险

### 7.1 缺口清单

本文的 `Gn` 编号**仅在本稿内有效**，与 AppHost/AppServer/AppService 交付批次使用的
`G10`–`G17` 重名但无关（同理，`Cn` 是本稿内部的约束编号）。跨文档引用时请写
"本稿 §7.1 的 Gn"。

| # | 缺口 | 影响 | 现状 |
| --- | --- | --- | --- |
| G1 | 无 per-Model-Call 工具快照（ToolPlan） | 无法证明某轮模型看到了哪些工具 | §2.11，目标态未实现 |
| G2 | Harness 无用户/租户身份 | 身份必须靠会话装配承载 | §2.4 |
| G3 | 无行/列数据权限概念 | 必须后端自建 | §2.5 |
| G4 | 无"权威回读验证" | 外部写入真实性需自建 | §2.10 |
| G5 | 跨重启的待审批与授权 | 长事务审批需自建 | §7.2 deferred 清单 |
| G6 | 无远程审批人通道 | 审批人必须在同一交互面 | 同上 |
| G7 | 沙箱仅 Linux、默认关闭、网络默认放行 | 隔离需逐项确认 | §2.7 |
| G8 | 运行作用域 process-local | 多 worker 拓扑需自行设计 | §2.8 |
| G9 | 无 CPU/内存级限额 | 多租户配额需容器层实现 | §2.7 |
| G10 | 未检索到多租户运行时；`tenant` 仅作为 scope 词表存在 | 租户隔离需自建 | 负向检索结论，需复核 |
| G11 | Plugin 生命周期实现为 partial；PyPI materializer 有已声明安全缺口 | 不建议承载不可信可执行插件 | 见 [Unified Plugin Architecture](../harness/plugin/architecture.md) |
| G12 | Agent 驻留 / LRU 回收未实现 | 大量子 Agent 时名额只增不减 | §2.12 |

### 7.2 Harness 明确 deferred 的清单

`policy-approval-redesign.md` 原文：

```text
Still deferred:
- durable pending approval and grants across daemon restart;
- Work waiting/checkpoint/rehydration semantics;
- authenticated remote reviewer channels;
- MCP connect/invoke action adapters.
```

### 7.3 需重点防范的设计错误

| 错误 | 后果 | 防范 |
| --- | --- | --- |
| 用 `direct_tool` 承载业务工具 | 完全绕过策略与审批（C4） | 架构测试：业务工具不得为 direct |
| 漏声明 `authorization_fields` | 审批看不见关键参数、指纹不覆盖（C3） | 架构测试：authorized 工具字段非空 |
| 尝试在工具参数上传 userId | 需改 Harness 核心契约 | 采用会话装配（C2） |
| 把 `NetworkEffect.target` 当业务语义载体 | 审批信息贫乏、语义丢失 | 自定义 ActionAdapter + 策略读参数 |
| 让技能/插件决定工具集 | 违反 intent authority 原则 | 角色模板为准 |
| 把 AppService 当作 Harness 网关 | 依赖方向错误、且无认证 | §4.5 |
| 把数据库权限寄望于沙箱 | 沙箱不覆盖 DB | §5.3 |
| 自报用户身份头（如 `X-User-ID`）作为授权依据 | 凭证风险转为头伪造风险 | 服务间使用可验证凭据；后端权威复算 |

## 8. 建议实施路径（Draft）

| 阶段 | 交付 | 验证方式 |
| --- | --- | --- |
| P0 | 一个 `PolicyEvaluator` + 一个 `authorized_tool`，跑通 allow / ask / deny / 指纹失效四条路径 | 以 `examples/harness/document_product.py` 为模板 |
| P1 | 会话装配：每用户一个策略/审批实例与一个工作区根 | 证明用户 A 的策略不影响用户 B |
| P2 | 后端行级过滤 + 领域工具收敛（只读 / 动作两类） | 以 B 身份查 A 数据必须不可见 |
| P3 | 沙箱开启 + 可写根限制 + 网络策略 | 逃逸可写根必须失败 |
| P4 | 审批通道与委托（代理）语义 | 一人多角色的权限交集正确 |
| P5 | 审计证据补位（§5.5） | 每轮可回溯有效工具集 |
| P6 | 可选：Ontology Action（仅单属性类） | 改参后 `plan_digest` 变化即失效 |

P0 的价值在于：在编写表结构前先暴露"身份从何而来""指纹覆盖哪些字段"
"拒绝路径是否真的生效"三个最易出错点。

## 9. 待决问题

1. **身份边界**：接受"一用户一会话"作为唯一无需改核心契约的做法吗？
2. **裁剪粒度**：按角色/租户（粗、稳定）还是按客户个体（细、配置膨胀）？
3. **技能定位**：接受"技能仅引导、不授予能力"的约束吗？若要求技能携带工具，
   需要独立论证并可能走新 ADR。
4. **工具粒度**：按意图收敛（推荐）还是按后端 API 镜像？
5. **后端调用方式**：进程内（推荐）还是跨进程？若跨进程，服务间认证采用何种
   可验证凭据？
6. **是否引入 AppService/AppServer**：是否确有"会话可分离/可重建"需求？
7. **业务动作落位**：Ontology Action、Product 自建治理链，还是两者并存？边界规则？
8. **代理链**：是否允许二次代理？最大级数？批量撤销的语义与触发条件？
9. **审批通道**：是否需要跨重启的待审批与远程审批人（G5/G6）？若需要，
   是否以 `plugin_execution.py` 的持久化决策语义为模板？
10. **部署平台**：目标是否为 Linux 容器？若否，隔离方案是什么（G7）？
11. **多租户**：是否确需"一个部署服务多个租户"（G10）？若是，需要新的目标文档。
12. **是否立项**：本文是否推进为 Requirements 或 ADR？若是，范围如何界定？

## 10. 参考

Current / Fact 依据：

- [Policy And Approval Redesign](../harness/policy-approval-redesign.md)
- [Harness Tool Governance](../harness/tool-governance.md)
- [Tool Governance Glossary](../harness/tool-governance-glossary.md)
- [Tool Execution Binding Boundary](../harness/tool-execution-binding-boundary.md)
- [Harness Tool Authoring](../harness/tool-authoring-guide.md)
- [Shared Capability Boundaries](../harness/shared-capability-boundaries.md)
- [Current Owner Map](../harness/current-owner-map.md)
- [Capability Dependency And Mount Lifecycle](../harness/capability-dependency-and-mount-lifecycle.md)
- [Sandbox Runtime Boundary](../harness/sandbox-runtime-boundary.md)
- [Process Hosting Boundary](../harness/process-hosting-boundary.md)
- [Machine-Local Runtime Storage](../harness/machine-local-runtime-storage.md)
- [Multi-Agent Limits And Lifecycle Projection Boundary](../harness/multiagent/limits-and-projection-boundary.md)
- [Unified Plugin Architecture](../harness/plugin/architecture.md)
- [AppService Architecture](../appservice/README.md)
- [AppServer Architecture](../appserver/README.md)
- [AppHost Architecture](../apphost/README.md)
- [Loushang Ontology Architecture](../ontology/README.md)
- [ARD-012 Authority-Aware Action Planning And Product-Hosted Write-Back](../ontology/ARD-012-authority-aware-action-planning-and-product-hosted-write-back.md)
- [ARD-001 Agent Harness And Product Adapters](../agent/ARD-001-agent-harness-and-product-adapters.md)
- [Loushang Product And OEM Glossary](../../glossary/loushang-product.md)

可执行参考：

- `examples/harness/tool_authoring.py`（工具授权最小样例）
- `examples/harness/document_product.py`（最小非 Coding Product：策略 + 审批 + 网关 + 审计）

相关讨论稿：

- [Application Model And Artifact Compiler](application-model-and-artifact-compiler.md)
- [Ontology-Driven Application Engineering](ontology-driven-application-engineering.md)

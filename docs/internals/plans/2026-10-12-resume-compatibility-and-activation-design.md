# Resume Compatibility And Background Activation Design

## Status

- 2026-10-14 command-line follow-up implemented by #738: startup
  `--resume <session>`, the bare `--resume` picker and the in-session `/resume`
  surface converge on the same Session lifecycle restore operation. Screen-first
  startup owns presentation only. Platform-specific continuation details remain
  below that lifecycle boundary, and no CLI entry selects a different Resume
  protocol by operating system.
- 2026-10-14 correction completed by #735: restore admission treats historical
  Runtime/Capability profiles, composition fingerprints, Plugin/Resource/Skill
  selections, workspace instructions, permission settings and model selection
  as audit evidence only. A readable Session is continued with the current
  environment. Resume itself does not request `authority.unknown`; current
  Tool policy still governs each new operation. Full writable validation is
  bounded at 64 MiB, with a read-only recent-page fallback above that bound.
- Hosted history binding: explicit catalog `open_history_binding` and
  `open_history_candidate` entries now
  deliver bounded selected-branch history through the existing Hosted adapter
  without a Writer, Product factory or executable control. This does not yet
  replace the default AppHost resume path or activate on first input.
- Authority: descriptive — implementation design and delivery plan; accepted cross-scope contracts are normative in ARD-004/005/006.
- Design status: proposed — ARD-004/005/006 boundaries were accepted by the project owner on 2026-10-12; further implementation detail and release evidence remain distinct.
- Implementation status: partial — read-only Header, bounded selected-path and
  unverified tail previews, exact-byte digest for bounded historical snapshots,
  historical Binding projection, fixed-ID UserMessage commit primitives with
  image externalization inside the existing Transcript owner, composition
  comparison, an internal fixed-ID activation-attempt record and Transcript
  commit path, a staged first-input path in Coding's SessionManager, and a
  data-only internal `SessionActivationPlanV1` envelope exist. Selected-path
  history projection classifies an unbound attempt as pending and keeps its
  pure Plan unavailable while still allowing read-only viewing. The ordinary
  persistent bootstrap, Product factory selection, model preparation, and
  message write paths also stop at an unresolved attempt; a normal
  commit advances its checked transcript revision without rescanning history.
  The original Transcript committer also offers a read-only fixed-record
  lookup under the Product operation fence. It reloads the authority store,
  compares the frozen payload and full metadata, and reports committed,
  not_committed_verified, unknown, or conflict without appending or moving the
  leaf. Verified absence requires complete evidence and an unchanged target;
  an unavailable store, partial tail, or uncertain receipt remains unknown.
  This lookup uses a full authority reload and is not yet the Hosted logical-ID
  or model-outcome facade. The staged Coding first-input path now retains a
  detached copy of its prepared persisted record and exposes an internal
  request-ID checked observation through that original lookup owner. A lost
  append acknowledgement can be observed as committed without replay;
  incomplete tail or unavailable authority remains unknown. The observation
  does not clear the activation fence, authorize retry, or start a model call.
  Before record preparation there is no invented fixed-record observation.
  An internal logical-input lookup query now contains only the stable input ID
  and a digest of the exact prepared record. The original Transcript codec
  covers payload, full metadata, timestamp, record identity and branch parent.
  Coding resolves the matching current-Session Binding in selected ancestry
  (outside truncated model context) or its retained prepared input, then calls
  the original authority lookup. Duplicate selected IDs or digest mismatch are
  conflict; missing local evidence is unknown, never verified absence. A
  provisional 65536-record local scan ceiling also returns unknown. The real
  Hosted binding forwards this observation without replacing control identity,
  and rejects lookup once close begins. Callers still need current read
  authorization. SessionManager reload tests cover committed identity with no local
  submission ledger and partial-tail uncertainty. Deployment capability selection
  and model-attempt observation remain pending. An optional
  Product-neutral AppService observation port now accepts bounded input IDs and
  record digests and returns validated durability states. Coding's Hosted
  adapter converts this port to the native query without exposing Plans or
  Transcript records. The existing scoped AppService client validates current
  attachment, member and controller generation before Product lookup and again
  before delivery. Foreign scopes are rejected before the Product read; controller
  takeover discards an old scope's late result. Unsupported Product ports return
  operation unavailable, not absence. Invalid or mismatched results and private
  Product failures become Session unavailable. This read does not reserve an
  execution or change old Ack timing; current scope authority is the existing
  snapshot-read capability, not a new persistent permission grant. AppServer
  now carries the closed observation query/result over the existing framed
  execution channel under the explicitly selected
  `local-detachable-resume-execution/v1` profile. AppService and transport share
  the same bounded data values; AppServer imports no Coding or Transcript owner.
  Remote clients expose a separate borrowed lookup capability only after that
  exact profile is negotiated. Old profiles reject the new operation even when
  a peer manually encodes it; old frame goldens and operations remain unchanged.
  The query uses existing request IDs and bounded control communication slots,
  checks the current service instance, and grants no execution/retry authority.
  Local connection records now publish this explicitly enabled capability in
  their authenticated capability list, with closed profiles preserving the six
  existing execution/discovery/managed/close combinations. Local clients borrow
  the same negotiated lookup client only while connected. Authenticated loopback
  tests cover enabled and default-disabled publication; framed queries cover all
  six optional profiles without creating executions. Installed deployments have
  not enabled this capability; client reconnection/editor integration,
  actor-policy read revocation and the
  full Hosted Resume readiness/admission flow remain pending.
  The application-owned SessionManager also has an internal isolated Resume
  Writer preparation route. It rechecks bounded source evidence and owner input
  references, rebuilds the canonical Plan, retains historical Header validation
  without current-profile equality, and delegates exclusive acquisition to the
  original Transcript factory. Before delivery it closes execution readiness,
  compares all loaded records, selects the verified leaf through the original
  Transcript's local branch operation, and compares the complete selected path.
  Store restore's default last-record leaf cannot replace the Plan selection.
  A branch change after preparation rejects intent commit without changing
  existing bytes; the initial intent's parent remains the verified selected leaf.
  Changed history disposes the original undelivered preparation. JSONL tests
  prove same-ID legacy preparation with unchanged Header bytes, a changed
  capability profile, competing Writer rejection, an acquisition-time source
  change, and intent plus one co-committed UserMessage/Binding. The prepared
  Plan pins the initial intent's Session, leaf and ancestry and is consumed
  before commit. Matching these data facts grants no execution permission.
  This internal route is not yet called by Embedded/Hosted Product bootstrap;
  live policy/owner admission, effects and production Runtime publication remain pending.
  The internal SessionManager initial-intent route now validates current
  Session, selected leaf and ancestry, freezes the canonical intent, and closes
  the local Runtime publication gate before its first await into the original
  fixed-ID Transcript commit owner. Success, write failure, lost acknowledgement
  and caller cancellation cannot reopen that gate. This route still requires
  the activation coordinator's live admission; it is not a retry/recovery port
  and is not yet wired into ordinary Product bootstrap. Staging also closes
  the same distinct local Runtime publication gate. That gate
  remains closed after successful input/Binding commit, including when the
  historical attempt projection becomes settled and a historical guard result
  is cached. Ordinary message writes, startup readiness and Coding model-runtime
  preparation cannot treat input durability as Runtime publication. The current
  Coding shell pre-execution hook, extension exec entry and explicit compaction
  entry check the same guard before invoking their downstream owners. Coding's
  execution-availability observation also remains false while local publication
  is pending, so the existing Hosted execution entry rejects dispatch. These
  checks do not implement Hosted readiness or continuation admission. The current
  production activation coordinator is not implemented. The internal publication
  boundary below is not a durable publication receipt or crash-recovery authority.
  Coding AgentSession now builds detached current composition observations in
  a separate internal receipt builder. Ordinary startup calls that builder;
  the 2026-10-14 correction removes its former current-versus-historical
  Header/startup equality checks. The builder
  reads current Plugin revisions, Product policy revision, Catalog selection,
  Worker receipt and owner generation references without reading or appending
  transcript history or enabling execution. A sentinel verifies this with the
  local Resume gate closed, including caller mutation of a returned receipt.
  This is a data seam for the upcoming activation coordinator, not live owner
  admission, effect settlement or Runtime publication.
  Harness AgentProductSession now exposes an internal candidate graph preparation
  path with an explicit synchronous current-admission check. Ordinary graph
  preparation delegates to it using the existing execution-readiness check.
  The candidate path retains original component/owner authority gates, graph
  binding and rollback; it rechecks admission after lock acquisition, around
  graph binding, before Worker preparation and before consumer delivery. It
  rejects a failed execution preparation and checks admission even for a cached
  graph. Tests keep Product execution unavailable while preparing a candidate,
  revoke admission during lock/bind waits and verify original owner disposal.
  This shared owner seam does not implement Coding's live admission decision,
  input/effect settlement or the final Runtime publication gate; the Coding
  activation coordinator and its production call sites remain pending.
  Coding now has an internal candidate preparation entry tied to a locally
  verified, definitely committed intent and the original exclusive Writer.
  It passes the checked immutable attempt to a synchronous current-admission
  callback, rechecks original current Product selections, and calls the same
  Harness graph owner. Each admission borrows a short synchronous Writer scope;
  no Writer operation spans graph awaits, because graph rollback may retire
  that same Writer. A preparation failure after owner claims fences retry on
  that Session. Preparation returns current composition observations without
  appending startup history, activating the Worker turn Tool or reopening the
  execution gate. Unknown acknowledgements and historical intent alone do not
  establish local preparation admission. This is not yet the production Resume
  coordinator: production bootstrap wiring, native effect correlation, current
  grants and production Runtime publication remain pending.
  An internal asynchronous Coding bootstrap now constructs a current candidate
  from that same owned resumed Writer after definite intent commit. The Writer
  retains its verified Plan locally; bootstrap matches the canonical current
  composition to the Plan and gives its immutable attempt to current admission
  before Product selection, before construction and before delivery. The
  explicit internal context selects the current composition without sealing or
  changing the original Header. Public ordinary bootstrap retains its pending
  activation rejection and historical composition pinning. A candidate denied
  after construction is disposed through the original Session owner before the
  error returns. This route neither settles native effects nor publishes
  execution readiness, and Embedded/Hosted production callers are still pending.
  The internal Coding publication boundary now retains a definitely committed
  first-input record and its full digest separately from intent and candidate
  preparation. Publication requires that same selected input and canonical
  intent, an original Transcript lookup reporting the exact committed record,
  and the locally prepared consumer, graph generation and composition receipt.
  The coordinator must supply both current admission and current epoch/effect
  settlement checks; neither historical Binding nor local preparation substitutes
  for them. Admission runs before the lookup await and both checks run before
  final synchronous publication. Only then does the boundary activate the
  original Worker turn Tool lease and reopen the local gate. Failure during
  final publication retires execution preparation. A published local Resume
  uses these current checks for subsequent model-runtime preparation, shell,
  extension exec and explicit compaction admission, retaining the first Binding
  on its selected ancestry and avoiding old startup equality and startup writes.
  The boundary dispatches no model request and supplies no
  automatic replay or crash-recovery grant. Live policy/epoch settlement owners,
  Worker Resume fault coverage and production continuation callers remain pending.
  A published local Coding candidate can now consume its committed first input
  through an internal once-only dispatch entry. The original Host claims the
  run before Coding installs the selected transcript context; queued inputs,
  a changed leaf, retry activity or revoked admission reject dispatch. The
  original Agent continuation runs that already committed UserMessage with
  purpose `main`, producing no second user append. The standard AI prepared
  transport and original durable Model Input snapshot owner remain installed.
  Coding's current-Session predicate rechecks publication admission at the
  original transport commit barrier, including after snapshot commit.
  A run-local Harness recovery predicate suppresses automatic retry/compaction
  for this explicit committed-input run, and the Agent's temporary CallOptions
  permits one AI transport attempt. Both return to their previous values on
  exit; persistent settings are not changed. A claimed run is not replayed;
  error, abort or cancellation fences this Session's execution preparation.
  This local claim is not a durable model-outcome registry. Production
  continuation coordinators, restart/outcome lookup, full native permission
  settlement and Embedded/Hosted submit wiring remain pending.
  ResourceLoader
  can calculate Catalog input facts and bounded native context content digests
  without choosing authority; Plan records only their redacted input fingerprint and
  rejects reuse when refreshed owner inputs differ. The synchronous
  `plan_coding_resume` entry reuses displayed history and calls this original
  Resource owner; unavailable history skips resource scanning. The internal
  `plan_coding_resume_async` entry builds the same envelope through bounded
  Resource-owned work and additionally records caller-observed subject and
  policy input digests. These digests identify dependencies, not permissions;
  refreshed domain inputs invalidate a stale Plan. Catalog Session views
  delegate computation to their shared source owner and retain bounded local
  waiting Tasks. Closing a view fences new waits and cancels its references;
  asynchronous close joins their release without waiting for native work.
  Closing one view leaves peer computations available. The shared Resource
  owner still joins native completion before releasing its own source leases.
  The original AgentProductSession disposal path now joins local reference
  release before retiring capability owners, without closing peer views or
  the shared source loader. A real Coding Session disposal regression covers
  two concurrent Session references. Production Resume startup and shared-owner
  close wiring remain pending.
  Skill and other mutable
  Resource content is not closed by this receipt, which cannot replace current
  owner selection. The staged first-input path is not yet armed by live Resume
  activation. Writable admission, owner selection
  completion, Product background wiring, Hosted readiness, and release evidence
  are not implemented.
- Planning cancellation: the shared Plan entry and original ResourceLoader
  preview accept a cooperative work probe. Checkpoints cover phase boundaries,
  context candidates, package/revision directory enumeration and Skill recursion,
  and 64 KiB context-file, package-text, and revision-digest reads. Package text
  capture uses the original mount/revision owner, preserves ordinary newline
  semantics, and limits raw bytes to 8 MiB total across mounts. Budget exhaustion
  discards the speculative receipt with `resource.preview_byte_budget_exceeded`;
  ordinary on-demand preparation still uses its existing owner path.
  Descriptor and portable
  revision verification preserve cancellation rather than reporting changed
  content; temporary descriptors close and the original handle remains owned.
  Directory cancellation occurs before collecting
  and sorting all candidates. Cancellation discards the
  result without selecting authority and permits re-planning. Work-unit/time
  budgets are explicit caller inputs to an internal Resource-owned background
  entry. This entry shares one computation for identical input state, workspace,
  subject and policy across matching ResourceLoaders on one event loop; separate
  domains do not share. Captured Resource input state and work budgets must also
  match; distinct live revision handles are conservatively separate.
  The process limits admitted jobs to eight, background jobs to six so two
  admission slots remain for foreground preparation, and native workers to two, with
  at most 64 references per job. These provisional bounds are not release
  performance evidence. Cancellation releases one waiter reference; only the
  last reference cancels computation. Original revision owners supply temporary
  read pins without an eager scan, then verify them during native computation.
  Pin cleanup runs before a successful native completion receipt. `aclose` joins native
  completion even when its caller is cancelled; synchronous close reports
  pending settlement while work remains. A publication gate prevents source
  reads when native submission loses its receipt and fences further background
  submission; the ordinary on-demand path remains available. Only a redacted
  fingerprint leaves the Resource owner. Catalog Session views now own their
  local waiting references. Foreground requests promote queued shared work,
  and cancelled work is promoted for cleanup. Product Resume invocation,
  completed-value caches, broader Workspace deduplication across distinct
  revision handles, and production close wiring remain unimplemented.
- Revision: R2.1, 2026-10-12; R2 independently rechecked, with the requested
  legacy Ack timing and fork-origin clarifications applied.
- Owning scope: Coding Session continuity; collaborating scopes: Harness,
  AppHost, AppService, AppServer, HarnessTUI.
- Source baseline: `5c148849`; source links describe this baseline, not implemented changes.
- Method: local `/home/dev/lsspace/archmethod` `master`, revision
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`, read without upstream checks.
- Review: three independent GPT-6 Astra perspectives; results are recorded in
  [the review record](2026-10-12-resume-compatibility-and-activation-review.md).

普通 Resume 应恢复历史会话，并允许后续操作使用当前安装、资源和执行策略。
升级包、修改 AGENTS、更新插件或调整权限不应使历史会话无法打开。
历史首先可读展示；显示期间并行准备当前环境的纯数据计划。用户继续操作时，
取得写入所有权、验证计划并激活运行环境，随后持久化输入和环境绑定。

该候选采用 Fast Open、Background Plan、Owned Activation、Continuation Commit
四阶段。只新增一个核心纯数据计划类型，复用现有规划、准备、绑定和释放机制。
Embedded CLI/TUI 与 LMUX/AppService 使用同一恢复语义和 Product 执行入口。

## Problem And Current Evidence

目前存在三组普通恢复门禁：

| 当前机制 | 证据 | 恢复影响 |
| --- | --- | --- |
| Header 和 startup receipt 使用当前 composition 定义反验历史指纹 | [composition_provenance.py](../../../src/loushang/coding/composition_provenance.py) | 同名 composition 更新后，历史证据也可能无法解码 |
| 启动凭证要求资源、插件、策略和 Worker 等字段相等 | [agent_session.py](../../../src/loushang/coding/session/agent_session.py) | AGENTS、Skill、插件变化可阻断普通 Resume |
| Runtime 与 Capability Profile 要求与当前快照相等 | [session_manager.py](../../../src/loushang/coding/session_manager.py)、[runtime_profile.py](../../../src/loushang/harness/transcript/runtime_profile.py) | 只放宽资源哈希仍不能解决跨安装恢复 |

缺少 `codingCompositionSetV1` 的会话可能仍是可解析的 Conversation JSONL v1；
缺少产品 provenance 不等于核心格式不可迁移。现有拒绝行为由
[test_plugin_p3_composition_choice.py](../../../tests/coding/test_plugin_p3_composition_choice.py)
和 [test_cli.py](../../../tests/coding/test_cli.py) 固化，修复需调整行为契约及测试。

当前若干 `prepare` 已取得资源所有权或产生效果，不能直接作为后台计划入口：

| 当前抽象 | 已有责任 | 拟复用位置 |
| --- | --- | --- |
| Prepared Transcript restore | 获取 Writer、加载 transcript、持有生命周期资源 | 用户正式继续时；[writer_lifecycle.py](../../../src/loushang/harness/transcript/writer_lifecycle.py) |
| Prepared Product route | Product admission、candidate claim、validate、资源关闭 | Hosted 正式激活；[router.py](../../../src/loushang/apphost/router.py) |
| Capability prepare/bind | activation decision、component factory 和绑定 | 所有权阶段；[component_host.py](../../../src/loushang/harness/capabilities/component_host.py) |
| Extension prepare generation | 可执行模块顶层、register、factory | 正式插件激活；[loader.py](../../../src/loushang/harness/extensions/loader.py)、[runner.py](../../../src/loushang/harness/extensions/runner.py) |
| Worker prepare | 可物化 payload、写 launch intent、启动进程 | 正式 Worker 激活；[agent_product.py](../../../src/loushang/harness/session/agent_product.py) |

现有 batch substrate 有 CAS、稳定 operation ID 和 unknown-outcome 重试能力，
但不是所有 backend 都具备崩溃后完整组可见性；逐条 fallback 和 JSONL 部分追加
不能作为新逻辑事务的原子保证。见
[unit_of_work.py](../../../src/loushang/harness/transcript/unit_of_work.py)、
[jsonl.py](../../../src/loushang/harness/journal/jsonl.py)。

[Resume Request Evidence Recovery](2026-09-28-resume-request-evidence-recovery.md)
已规定正常恢复从所选路径的消息锚点恢复证据。该约定继续有效：历史已加载 Skill
的文本与摘要保持历史事实；新轮次环境资源采用当前内容，两者不能相互覆盖。

## Outcomes And Quality Scenarios

下表是本候选的可追踪验收条款。用户明确提出恢复兼容、显示期间准备、性能优化、
LMUX 支持以及避免 prepare 重复；故障与一致性条款是相应的工程约束。
业务重要性为设计排序建议，数值延迟预算需基线测量后确认。

| ID | 场景与结果 | 验收与责任 |
| --- | --- | --- |
| RES-FR-01 | 包升级、AGENTS/Skill/插件/工具/策略变化后恢复旧会话 | 历史可打开；后续使用当前安全环境；Coding |
| RES-FR-02 | 历史显示期间准备当前环境，用户立即输入 | 输入立即成为明确未发送的 pending；准备不阻塞历史首屏；Coding/HarnessTUI |
| RES-FR-03 | Legacy 会话缺 composition provenance | 身份可证明且核心格式兼容时同 ID 延续，Header 不变，来源永久标记 legacy_unknown；Coding |
| RES-FR-04 | Embedded 与 LMUX 使用相同会话 | 相同兼容分类、输入状态、reason code 与执行门禁；Hosted adapter |
| RES-NFR-01 | 用户只查看后退出 | Session authority 与 activation/Worker journals 零写入；无第三方 import、无进程启动；Harness |
| RES-NFR-02 | 准备期间配置/路径/插件/策略变化或两个进程争写 | 候选失效或只读冲突；输入不静默改接另一个 leaf；Harness/Coding |
| RES-NFR-03 | 激活、提交、发布之间取消或崩溃 | 同一输入最多一个持久可见记录；未知结果不自动重放；无未记账的 Worker 或 activation use；Harness |
| RES-NFR-04 | 大 Session、大 Workspace、多 LMUX Session | 有界预览、去重扫描、受限后台调度；明确冷/热缓存及阶段耗时；Harness |
| RES-NFR-05 | 更换 UI、部署方式或扩展实现 | 一个计划入口与现有 owner 选择逻辑；AppService 不获得插件/Graph 内部依赖；跨 scope owners |

性能、安全与一致性场景优先级高；跨版本回滚与 LMUX 多客户端场景技术难度高。
本次评审检查设计，运行时指标与故障注入仍是实施验收任务。

## Resume Compatibility Contract

普通 Resume 分别判断核心数据可读性、会话用户意图和当前执行能力。
历史 receipt 是审计数据；当前 Product policy、权限、Sandbox 和工具网关决定新操作。

| 变化或状态 | 默认行为 |
| --- | --- |
| AGENTS、Prompt、Skill、插件增删升级、工具面变化 | 打开历史；按当前环境规划；记录分类差异或降级能力 |
| 同名 composition 的实现变化 | 保留 setId 意图，解析当前定义；旧 plan fingerprint 仅作证据 |
| 显式禁用工具、模型、thinking、cwd 变化 | 使用本次启动的当前选择继续；历史值只供审计与差异展示 |
| 权限/策略收紧 | 新操作立即遵循当前限制 |
| 权限配置变化 | 使用本次启动的当前权限继续；Resume 不额外制造权限扩大，具体新操作仍由当前 Policy/Approval 判定 |
| 缺 composition provenance，但 Product 身份与 transcript 可确认 | legacy_unknown，同 ID 继续；不补写 Header |
| 缺 Product 身份、来源冲突或无法判定的格式 | 类型化兼容处理；不能默认猜测 Product；按可读性提供查看/导出 |
| 核心格式损坏、不支持的核心 schema、解密失败 | 限制可写恢复；只在有读取授权且数据可读时提供只读/原始导出 |
| 缺历史插件，未知 extension record | 保留历史；未知扩展 inert；不得加载旧插件解释或执行 |
| 未结非幂等 Tool/Worker/activation effect | 查看可用；隔离新效果，显式核对与处置 |

历史记录解码只验证其自身结构与引用，不调用当前 registry 判定历史指纹是否正确。
Runtime/Capability Profile 采用核心兼容分类和当前新轮次 profile，删除普通恢复
的全等门禁。历史 Profile 不提供当前 authority。

Composition set 被移除或 cwd 缺失时，需要显式替代选择。外部来源 import、
真正格式转换或 Product 身份补认继续通过已有受控迁移边界，不能直接修改来源。

同 ID 承诺按入口的身份条件限定：

| 身份证据 | Embedded | Hosted/LMUX |
| --- | --- | --- |
| 已有 canonical Hosted identity，仅缺 composition provenance | 按该身份验证 | 目录可发现，legacy_unknown，同 ID 继续 |
| Product 已证明，但无 Hosted continuity/create identity | 同 ID 恢复 | 首版不自动 adoption；提供可读候选与 explicit identity migration reason，执行需受控迁移 |
| Product 未知或身份冲突 | 不猜 Product；受控确认/只读或拒绝 | 不默认 Coding；保持 ProductIdentityRequired/conflict |

仅传入 product_id 不是身份来源证明。现有 hosted catalog 排除缺 Hosted metadata
的文件；新增只读候选发现投影与受控迁移是显式入口改动，不放宽 canonical 校验。
“跨入口同语义”指满足入口身份约束后的恢复与执行，不意味着全部旧文件自动跨部署。

可选 exact 模式只在历史依赖证据可重建时提供。它不自动安装历史插件，
不绕过当前权限上限；legacy_unknown 不声称可 exact replay。用户必须显式
选择切换为 current 模式，禁止静默回退。具体入口与能力范围在发布切片中确认。

## Ownership And Deployment

| 责任 | Owner | 协作者与边界 |
| --- | --- | --- |
| 普通恢复、legacy 分类、composition 用户意图 | Coding continuity/session | 调用 Harness 公共机制；不改变 AI SDK |
| 通用只读 projection、Writer fencing、journal/Blob、取消与关闭 | Harness 现有 owners | 按需补充公开契约，不建第二个 store 或 lease manager |
| 插件选择、Resource/Tool/Policy 投影、Graph prepare/bind | 现有 Harness owner + Coding composition | 后台与正式阶段使用同一选择逻辑 |
| Product admission、身份路由、scoped factory | AppHost | 提供 Product route；不发现 Product 内部插件 |
| canonical process-local Product live binding | AppHost 现有 live registry | 去重 factory、profile generation、attachment 引用与最终关闭 |
| 服务端 Session 路由投影、attachment/controller、execution admission、客户端事件 | AppService | 消费 Product 窄接口；不 import Harness planner/binder 或 Coding internals |
| framing、连接、RPC 传输 | AppServer | 不获得 transcript 或 runtime 激活所有权 |
| pending 编辑、显示和用户输入 | CLI/TUI/LMUX client | 状态来自 Product 投影；执行由服务端 Product binding 决定 |

Embedded 在前台进程内创建 Coding continuity owner；Hosted 在 LMUX AppHost
进程内创建相同 Product owner，并经 Coding hosted adapter 暴露窄 Session port。
可共享纯值定义和静态缓存，mutable runtime、Writer、审批与 Worker lease 按 Session
隔离。既有边界见
[AppService Boundary](../architecture/drafts/appservice-embedded-tui-hosted-boundary-plan.md)
与 [Coding Hosted Adapter](../../../src/loushang/coding/appservice_adapter.py)。

```text
Embedded CLI/TUI ───────────────────────┐
                                      ↓
LMUX client → AppServer → AppService → Coding Session binding
                                      ↓
                         同一恢复计划与激活入口
                                      ↓
                         Harness 原有 owners
```

图中为候选调用关系，不代表新增 import 依赖。AppService 只观察准备状态、
脱敏诊断和 typed admission，不持有 SessionActivationPlan 或 Epoch Vector。

LMUX 已存在的活跃 Session 采用 attach/reconnect，不重复从磁盘 Resume。
只有未在 live registry 的 persisted 会话，或服务重启恢复时才走新恢复流程。
AppService 聚合成员可在历史可读、订阅与 cursor barrier 建立后显示为 preparing；
准备状态纳入 snapshot/event，禁止把 preparing 伪装成可执行。

Hosted scoped factory 的候选改动为：创建一个轻量 Product continuity runtime，
其 identity/read-only snapshot/status subscription/close 已可用，内部 execution runtime
尚未激活。AppHost 仍只发布一次 canonical live binding，两个客户端 attach 等待
同一个 factory task；后续激活在该 continuity runtime 内完成，不替换 binding key、
profile generation 或 attachment 身份。AppService 只取得其服务投影。
现有 Coding adapter 构造即依赖 live control；需在原 Product binding 内提供延迟
execution control 或 readiness facade，不能另设第二个 live registry。

只读 facade 构造和 snapshot 禁止调用 Writer/Extension/Worker prepare。关闭与
generation retirement 沿原 AppHost ownership chain 收敛，dispose 内部 Plan、
activation effects 与 Writer。此 factory/port 变更需 AppHost 与 Coding owner 接受，
两客户端同时 attach/准备中 detach/关闭 debt 测试通过后才能开放 Hosted 快速恢复。

## One Plan And Existing Prepare Owners

新增 `SessionActivationPlanV1`，初期作为 Coding 内部不可变数据值；只有被多个
Product 验证为相同公共需要时，才将最小契约提升到 Harness。它不是新的公共
Capability planner，也不是新的插件 registry。

Plan 引用现有 owner 产生的不可变 selection/projection 结果，保存：plan ID、
schema version、session/branch/workspace identity、用户意图、输入依赖指纹、
epoch vector、兼容分类、差异及能力降级。数据可以丢弃、重建；不保存
Credential、Grant、模块、工具实例、live graph 或可写句柄。

每个选择只存在一个 canonical owner。现有 prepare 若混合纯计算与资源获取，
先在该 owner 内提取纯计划步骤；后台调用此步骤，正式 prepare 消费其结果并验证。
旧调用入口可委托相同逻辑。不得在 Resume 层另写插件、工具或 Provider 选择算法。

| 术语 | 契约 |
| --- | --- |
| inspect/snapshot | 只读数据与有界历史 projection |
| plan | 纯计算，不取得实时执行权或资源 lease |
| prepare/acquire/stage | 已获得资源所有权，必须 close/settle |
| commit | 将事实持久化，处理未知提交结果 |
| publish | 使运行态或逻辑事件对消费者可见 |

`PreparedProductRouteV1`、Prepared Transcript restore、Capability prepare/bind
保留各自作用域的所有权和关闭责任。协调器通过已有 acquisition/close 基础串接，
不再引入一组平行 PreparedResume/PreparedRuntime/PreparedActivation 公共对象。

Plan 新增纯值结构不意味着新增第二套事实源。正式阶段的选择与 Plan 不一致时
返回 stale/replan；禁止自行静默换 Provider。测试对比冷规划、热缓存规划与现有
owner 选择结果，并约束各 UI 与 Hosted adapter 使用同一入口。

## Fast Open And Background Plan

只读打开使用 read-only store；不修复 partial JSONL tail、不 enrollment、
不写 shutdown/activation。Header、索引和最近页先显示；验证不足的页面标为
preview，不能直接作为当前 active branch 的执行依据。

权威绑定的轻量 recent-page cache 保存 revision、leaf、父链、offset、journal
identity 和兼容版本。索引失效时先提供有界 preview，再完成所选路径验证。
执行前必须完成所需核心路径验证；正常恢复不全量重建所有历史 Model Input。

确定 Session/branch/workspace 后即可启动后台 Plan，first-paint/输入任务优先。
仅静态读取 Manifest、包摘要、资源和声明式 Schema；禁止 import 第三方或工作区
Python，禁止 factory/register/get_tools、进程、网络、Worker payload/lease 和
durable activation decision consume。动态旧扩展标为 non_speculable，正式激活
才求值；只读后退出不会执行其代码。

后台任务由 Product Session owner 持有。Embedded 页面关闭会取消其未交付任务；
LMUX 客户端 detach 不等于服务端 Session close。服务端根据已有 Session 引用与
资源预算决定保留或取消 Plan；任何取消均可重新计算，无权威状态遗失。

共享调度器提供按阶段限流、singleflight、Workspace 扫描去重、容量与取消预算；
asyncio Task 本身不构成低优先级保证。用户继续时提升对应任务优先级，不能使
一个 Session 的大扫描阻塞其他 Session 的首屏或中断操作。

共享纯值任务由承接该计算的原 Harness owner 持有；Coding continuity owner 管理
Session 的等待引用和优先级。singleflight key 与缓存使用相同主体/Workspace/policy
隔离域。取消一个等待者只释放其引用；最后一个引用释放才取消工作。
IO 与 CPU 解析分别使用有界执行槽和线程/进程载体，循环按文件/字节工作单元
检查取消，不能把无界同步扫描直接放到 event loop 或默认线程池。
超过预算退回按需规划并保留 pending；具体并发/字节/取消预算在基线后确定。

## Final Validation And Live Authority

Plan 的 Epoch Vector 覆盖 Store/file identity、revision/branch/leaf、workspace
根与 cwd、composition intent、package/instance revision、tool owner generation、
resource snapshot/source generation、policy/actor/permission/approval/sandbox、
Worker 协议和 model/provider selection。

用户继续时获取唯一 Writer，复核 transcript identity 与预期 leaf，再由原有
owner 获得当前资源 generation guard。不能 pin 的可变源采用不可变字节 snapshot
和双读稳定性：构建前 A、构建后 B 与计划完全一致才交付。stat 信息用于快速
失效检测；内容闭包通过摘要、不可变包 revision 与 owner generation 证明。

双读只检测观察点变化，不证明实际执行内容。正式 stage 必须消费 Plan 所证明的
不可变 snapshot，或由原 owner pin 到实际消费、commit、publish 的 generation。
动态 import 的入口、相对 import 与延迟依赖属于内容闭包；路径摘要不能替代该
证明。支持 pin 的包加载链需明确公开 owner 契约。旧式扩展无法证明闭包时，
首版默认 unavailable；若将其纳入可信进程代码，须先由原 plugin trust/admission
owner 明确批准精确 scope 并记录证据，不能靠恢复时后置确认补授权已执行代码。
动态贡献可在原 owner 批准的静态能力上限内 refinement；超出范围即关闭门禁并
失败/重新准入，Plan 标记未确定部分，不以全环境 equality 触发无限重规划。

任一依赖变化，相关确认随 Plan 失效；按依赖图增量重建。变更重试设置预算，
持续变化时保持 pending 并提示，不无限追逐或静默采用旧环境。Writer 获取失败
保持只读冲突；拿到 Writer 后 leaf 变化也不能自动将输入换到新分支。

ACTIVE owner 持有 Writer 到 Session 关闭或替换。Hosted 多客户端共享该 owner，
controller generation 与 Writer fencing 分别管理客户端控制和磁盘写入。
权限扩大确认绑定当前主体、目标 Session/leaf、候选 fingerprint 和精确扩大项；
发送消息本身不表示同意。已通过可信配置流程明确选择当前权限的操作避免重复
确认，历史 receipt 仍不能授权。Legacy 未知基线加 full_access 按未知扩大处理。

权限差异基线是当前主体仍有效的、由原 Approval/Plugin activation owner 确认的
subject 与 scope；历史限制可用于比较但不能授予权限。复用已有 subject digest、
package/dependency digest、policy revision、revocation epoch 和 effective authorities。
配置值本身不算确认凭证；未知/部分未知/不可比较 authority 在所需执行能力超出
可证明 scope 时请求确认。可信配置流程免重复提示必须匹配原 owner 的有效确认
事实、主体、范围和撤销状态。没有匹配事实时不因配置写着 full_access 而豁免。
等待确认时不持有 Writer；恢复执行前重新取得 Writer 并验证绑定完全相同。

每次 Model Input 使用当前暴露策略；每次 Tool Start 使用当前 Policy、Approval、
Sandbox ceiling 与 hard revocation；每次 Worker 接管使用当前 fencing。Plan 与
Binding 解释某次选择，不提供未来持续授权。

## Activation And Durable Continuation

正式 activation 采用可恢复 Saga。磁盘、插件代码和进程没有共同事务，
所以记录严格区分 attempt、绑定输入和 runtime 发布。

```text
History / Plan ready + local pending input
  → confirm if needed
  → acquire Writer and revalidate
  → commit activation attempt intent
  → stage current Runtime with execution gates closed
  → final validation and immutable Blob staging
  → 单条 agent.message 提交 UserMessage 与 RuntimeBinding metadata
  → publish Runtime and open execution gates
  → model request
```

`coding.activation-attempt/v1` 记录 attempt ID、plan fingerprint、目标 leaf、
当前 epoch、效果分类和关联 request ID，只说明正式激活尝试开始。后台规划不会
写该记录。插件 import/Worker 启动由各既有 owner 执行，复用它们的 durable
launch/use 记录与清理；协调器只关联证据，不创建第二个 Worker journal。

所有工具执行、历史任务接管、自动 Continue 和模型传输门禁在成功提交与发布前
关闭。插件 activation 本身属于已获当前 admission 的正式效果；动态插件的真实
贡献若偏离静态候选则重新校验，需要扩大 authority 时重新确认或退回失败。

R2 优先保留 `AGENT_MESSAGE_KIND` 与 `UserMessage` payload，将有界 RuntimeBinding
放在该记录独立版本化的 Coding-owned metadata key。它与原 resource-evidence
metadata 在记录构造前合并、冲突拒绝、同一次提交，不先写消息后补 binding。
首个输入指本次 activation epoch 的首个 continuation 输入。复用
[AgentEventRouter](../../../src/loushang/harness/session/agent_event_router.py)
及原 message-commit owner 的证据准备与 commit 协调，后续响应流程接收 canonical
record ID，禁止先专门 append 后又由正常事件重复 append。

完整且校验通过的同一物理记录使输入与 Binding 一起可见；这不承诺物理 write
不会残缺。partial-tail、fsync/ack unknown 与 Store head 的收敛继续验证。
Binding 仅记录 attempt/input ID、目标 ancestry、originEvidence、计划/实际环境
指纹、payload digest 和脱敏差异，设置 schema 与字节预算，不保存整个 Plan。
它不代表 current authority、Runtime 已发布、用户已授权新操作或模型已经收到。

从所选 ancestry 发现 epoch binding，不能仅从当前 model context 发现；compaction
可去掉消息上下文而保留历史事实。分支到 binding 之前不继承该 epoch。
跨 Session fork 复制的 Binding 保留来源 Session/输入事实，不代表目标已经激活，
也不作为目标 Session 的输入去重证明；目标新 epoch 和幂等身份重新按目标授权建立。
未知 metadata schema inert，不进入模型正文；独立 binding annotation/patch 不允许
覆盖已提交事实。原始导出可含脱敏审计字段，Hosted/HTML 投影使用明确白名单。

稳定 logical input ID 关联固定 record ID、Session/branch、目标原 leaf、payload 与
完整 metadata digest。预构建消息及相关 resource evidence 通过原消息提交 owner
提交；unknown 时核验同一 record/operation，不能再次普通 append 生成新 ID。
attempt 若推进 transcript leaf，区分原输入目标 leaf 与本 owner 新增记录后的
expected parent；验证无外部写入后，消息父链包含 attempt，CAS 使用实际提交 parent。

Binding 首版内联，不新增 Blob；用户图片沿原 message externalization owner 先
durable staging，再提交引用。提交结果 unknown 时禁止 orphan GC 回收相关 Blob。
取消/失败后只有证明未提交才能清理，branch/export/compaction 验证沿原消息引用。

N/N+1 旧 reader 的消息显示预期保持，但旧 writer 会忽略新 metadata。不能假定
新门禁保护旧 binary；首版只承诺经测试版本的读/导出，不承诺降级后的安全可写
恢复，发布须明确最低 writer 版本与 unsupported rollback，并实测原 gate 的行为。
若产品要求旧版安全写恢复，需另做可被旧 binary 理解的兼容机制后才能接受。

新 envelope 不再是首选。首版 writable current 仅开放用户消息触发；无用户消息
的自动 Continue、compact、其他 effectful continuation 先保持受限或原已验证路径，
不伪造空 UserMessage。纯元数据 rename 只需 Writer/当前授权，无需 Runtime。
确需多独立记录共同可见时再评估 Store transaction visibility；不能用逐条 batch
fallback 冒充事务，也不能将消息载体的保证泛化到所有 command。

Runtime 发布失败且消息与 Binding 已成功提交时，显示“消息已保存，响应未启动”。
重新建立环境后只重试响应。模型请求已可能发出但无结果时，标记 outcome_unknown；
不宣称外部请求 exactly-once，也不自动重放。用户显式重试才产生新的 model attempt。

崩溃恢复根据已有 attempt、commit 与 owner journals 判断：无效果时可废弃计划；
已启动效果而无可靠终态时先 settlement/quarantine；完成输入不重复追加。
清理失败记录 debt 并限制新效果。历史 Tool/Worker 调用不自动重放。

Admission/use 终态与 effect settlement 分别判定。原 plugin activation use 的
STARTING/STARTED 在新 host boot 被恢复为 FAILED，不证明外部效果未发生。
协调器保留该 unknown 含义，由原 effect owner 提供独立结算证据；只有可信完成、
未启动证明或显式处置解除隔离。attempt intent 不能替代 Worker/extension 的效果证据。
模型响应重试使用原 durable Model Input invocation/outcome projection：没有 attempt
时可以准备响应；已有 prepared snapshot 而无可靠 outcome 保守 unknown，即使可能
尚未发送；显式重试创建新 model attempt，输入 record 不变。

## Input State And Hosted Admission

| 状态 | 输入事实与用户操作 |
| --- | --- |
| draft | 尚未提交，输入框可编辑 |
| pending_prepare | 本地 pending，未写入，未交给模型；可编辑/取消 |
| awaiting_confirmation | 输入仍 pending；确认独立绑定候选，文本不能充当确认 |
| activating | 正式 activation 已开始；取消需结算已有效果 |
| committing | 等待确定提交结果；取消先等待提交收敛 |
| committed | 输入 durable；取消保留消息并可阻止尚未发出的模型请求 |
| running / response_failed / outcome_unknown | 展示响应状态；重试不重复输入记录 |

首版一个 Session 只允许一个激活触发 pending。prepare 失败保留文本；commit
前取消可恢复草稿；退出时未保存输入需明确提示。传输断开与用户取消是不同事实。

Baseline `start_turn` 返回 AckV1，Product `start_turn(text)` 返回 None；新 execution
registry 使用 ACCEPTED/RUNNING/... 与 service-instance scoped submission ledger。
Started/Consumed/Queued/Rejected 属于边界设计中的候选约定，尚不能称为现有
activation queue。R2 复用 execution/submission owner，增加准备状态的 Product
投影及必要能力协商，不先建平行 Turn/Activation queue。

| Baseline 接口或身份 | R2 候选映射 |
| --- | --- |
| 连接 transport request ID | 仅相关一次 RPC，不作 durable input identity |
| client submission ID | 客户端预生成稳定 logical input ID；服务端绑定主体、Product/Session/branch/原 leaf 与 payload digest |
| ACCEPTED execution + execution ID | 表示服务端 admission 已接受；准备是其 Product 子状态，不代表输入已保存或模型运行 |
| service instance ID | 检测重启；旧执行 ID 可失效，logical input ID 跨连接/重启保留 |
| agent.message record ID + Store operation ID | 固定 canonical record ID；承载消息与 Binding 的 durable reconciliation |
| Ack-only old client | 保留原 operation completion/错误返回时序；激活与输入提交是必要条件，不提前将 Ack 改为 committed acknowledgment；无法交互确认时明确拒绝或要求新客户端 |

首版服务端非持久 pending 不承诺跨重启队列恢复。客户端保留 logical ID/文本到
明确 committed；重连先按当前读取授权与 stable input ID 查询 durable record 和
model attempt。只有完成 authority store 核验，证明未提交且目标 ancestry 未变化，
才允许同 ID 重新 admission。not retained、旧 instance 或扫描未完成是 unknown，
不能当作未提交。跨重启查询必须覆盖已提交但不在当前模型上下文的目标 ancestry，
并返回 committed、not_committed_verified、unknown 或 conflict，不依赖内存 ledger。
补齐该 Product durable lookup 及 service event 契约后才能启用 Hosted retry。

客户端尚未发出时可以编辑；server admission 接受后冻结该 ID 的 payload。
改文本需先获得取消且确定未提交，再用新 logical ID；同 ID 不同 digest 拒绝。
controller takeover fence 旧 controller 的 mutation，accepted 请求绑定既有主体与
目标 Session，由新合法 controller 显式查询/取消/继续；重新 admission 要重新授权。
断线不取消 accepted execution。新增状态使用现有 execution owner 的终态规则；
旧 Turn interrupt 仅作用于其原目标，不取消未交付本地 pending。

`/resume` 切换候选失败保留原活动 Session 与文本归属；不能自动新建会话。
Fast View 绑定 candidate identity，交互必须明确当前目标，正式切换通过现有 lifecycle
owner 结算。CLI/TUI/Hosted 共用稳定事件与 reason code，而非异常英文字符串。

显示目标与执行目标分别保存：预览 B 时输入明确属于 B 的 editor/pending 容器；
A 保持原执行 owner。B commit 前返回 A 可取消本地 pending，已启动 effects 则
异步 settlement，不丢文本或释放未结资源；B commit 后返回 A 只改变显示，
B 的已保存消息不回退，响应失败由 B 的状态展示。通知与 action 按 mux/member/
session/presentation generation fencing，沿现有 A→B→A editor 隔离语义。
所有状态有文字标签与目标 Session，确认/保存/失败可被辅助技术感知，进度不夺焦点。

用户主状态为“可继续”“需确认”“只读”，准备中和未发送状态额外明确显示。
快照应包含 history verification、activation readiness 与 pending/committed 信息，
重连通过 cursor/snapshot 收敛，不能把 app snapshot revision 当作 runtime generation。

## Cache And Incremental Preparation

纯值缓存保存 package/static manifest、Schema 解析、resource 解析、catalog merge
和 Worker artifact 校验。缓存键包含对应内容摘要、parser/protocol/ABI/platform
版本、输入依赖向量；含工作区数据的缓存还绑定安全主体、workspace 根身份、
安装/Product 与相关 policy generation。跨 Session 只共享真正不可变且无秘密的值。

整个 ActivationPlan 不作为跨 Session authority 缓存；Session 部分绑定 revision/leaf。
不缓存 Writer、Credential、Approval、Grant、模块、LoadedExtension、ToolRegistry、
Worker receipt/lease 或活跃 graph。缓存采用 private permissions、容量/LRU 和
schema 版本；失败不长期负缓存。cache root 是非权威、可删除的独立目录。

依赖图复用原有 owners 的输入/输出 fingerprints：AGENTS 变化重建 Resource/Prompt；
权限变化重建 Authority/Tool projection；package 变化重建对应 Plugin/Tool/Resource；
transcript append 验证 tail 并更新 selected context；Worker 变化不重读历史。

正式获取 Writer 后，若文件 identity/revision/内容 proof 完全相同，可采用后台
detached transcript snapshot；仅 append 时验证 tail，替换/缩短/分支变化回退。
该优化需先补公开 owner 契约，避免“后台全读一次、激活再次全读”的重复成本。

Session 列表只读便宜摘要与 resumeHint；对当前选择或可见且预算允许的 LMUX 成员
规划，不为每行扫描 Workspace/加载插件。索引缺失不能显示误导性的 No sessions yet。

## Alternatives And Tradeoffs

| 选项 | 收益 | 成本与推荐 |
| --- | --- | --- |
| 保留环境全等门禁 | 实现改动小 | 无法满足正常升级与资源编辑后恢复；不选 |
| 首条消息后才开始全部准备 | 最少推测工作 | 首次交互等待长；仅作为资源预算不足时回退 |
| 显示期间启动完整 Runtime | 可能最早 ready | 只读浏览会 import/启动 Worker；不满足零权威副作用约束 |
| 显示期间纯计划，继续时复用现有所有权 prepare | 重叠静态成本，保持统一 owner | 正式阶段仍有动态插件/Worker 成本；推荐 |
| Legacy 默认复制到新 ID | 可独立新 Header | 分裂 ID、复制 Blob/历史成本高；仅真转换/外部 import 时使用 |
| Legacy 同 ID 追加 continuation epoch | 用户心智与性能简单 | reader 需区分未知起点与新绑定；推荐 |

纯计划不能保证首条消息零等待；动态扩展和 Worker 的启动保留在正式阶段。
优化效果取决于可静态规划工作的占比、缓存命中和 transcript snapshot 复用。
共享 Worker warm pool、全局强一致环境锁和持续 full-history audit 不纳入首版。

## Delivery Sequence And Acceptance Evidence

1. 修复恢复契约：历史 provenance 解码与当前解析拆开；普通 Resume 放宽三层
   全等门禁；身份与核心兼容验证保留；加入 legacy_same_id、upgrade golden fixtures。
2. 拆 owner 内的 pure plan 与有所有权 prepare，统一 Coding 执行入口；先完成
   readonly/取消/关闭测试，再启用后台 scheduler。源码实现按 code/harness lane 分工。
3. 验证 agent.message metadata binding 的单记录提交及全部 projection；通过断电/残尾、
   operation-ID、branch/Blob/request-evidence 测试后才启用新写入格式。
4. 完成 writer/epoch/权限确认、activation effects settlement、pending 输入与重试。
   垂直切片可先使用同步规划；后台任务后接同一 Plan，不能绕过提交门禁。
5. 接入 Hosted Facade 的只读/准备状态和 typed admission；保留既有 AppHost
   admission、AppService controller/attachment/idempotency owners，不建立第二套队列。
6. 加 recent-page cache、detached snapshot reuse、pure-value cache 和增量调度；
   建立冷/热、大小历史、多 Session 性能基线。
7. exact 验证作为可选后续切片；发布前记录真实支持范围，current 默认不受其拖累。

上述为开发依赖顺序，不是七次独立上线承诺。发布切片为：

| 发布切片 | 可开放行为 | 必须同时具备 |
| --- | --- | --- |
| Read-only compatibility | 宽容历史解码、可读候选/导出 | read-only store、identity 验证、零效果；保留旧可写门禁 |
| Embedded writable current | 用户消息触发、same-ID legacy 范围 | 三层兼容改造、当前 admission/确认、消息binding/evidence单提交、effects结算、未知提交/模型恢复 |
| Hosted writable current | canonical身份范围内 LMUX 用户输入 | 上述安全切片 + canonical facade、协商、stable ID durable lookup、controller fencing/取消/重启 |
| Background/performance | 显示期间Plan、缓存、snapshot reuse | 复用同一同步Plan与commit入口，调度/取消/隔离与性能工作量验收 |

后台纯 Plan 可以在任一已有安全运行切片内先启用；任何可写 current 入口都不能
仅删除门禁就上线。未开放路径返回明确 reason，不静默创建 Session 或使用旧权限。

必须覆盖 RES-FR/NFR 的契约测试：

- 跨安装 N/N+1、AGENTS/Skill/插件/策略变化、same ID legacy、多绑定 epoch。
- 恶意 extension 顶层 sentinel：只读/Plan 无 import，无进程，无 journal 写入。
- 所选分支 recent-page、stale cache、tail append、workspace/symlink 替换。
- 两进程 Writer 竞争、多个客户端 controller 切换、plan 改变确认失效。
- intent/插件/Worker/Blob/commit/publish/model-start 各窗口取消与崩溃。
- 未结非幂等操作隔离；旧 grant 不复用；当前策略执行前收紧仍有效。
- 已提交输入不重复；模型 outcome_unknown 不自动重放；退出不 silently 新建会话。
- LMUX attach、detach、重连、服务重启与 queue ID 归属；单 Session 失败不阻塞其他成员。
- current/exact 与旧版本 export/profile 保留未知记录的兼容边界。

指标分别记录 first frame、输入接受、Plan ready、input durable、model transport，
以及读取/解码字节、full rebuild 次数、Writer wait、fsync、CPU/RSS/FD、缓存命中、
Plan 废弃与取消耗时。冷/热缓存、1/2/8 Session、1万/10万记录及大量资源都报告。
共享 CI 优先确定性工作量断言，固定毫秒阈值先由指定机器基线确认；此前讨论的
500ms 首屏与 100ms 热计划提交额外延迟仅是优化愿望，不作为已实现或已接受保证。

## Review And Decision Boundaries

项目 owner 已于 2026-10-12 在 #696 实施会话中明确“接受，继续”。按
[governance profile](../architecture/governance-profile.md) 记录的跨 scope 接受
决定为 [ARD-004](../architecture/decisions/accepted/ARD-004-resume-history-and-current-authority.md)、
[ARD-005](../architecture/decisions/accepted/ARD-005-resume-continuation-commit.md) 和
[ARD-006](../architecture/decisions/accepted/ARD-006-hosted-resume-readiness-and-admission.md)。
恢复边界、v1 continuation 契约及 Hosted 单一 binding 语义可进入实施；实际开放
可写路径仍须满足本文的授权、故障、版本与性能发布条件。

独立评审检查架构性能、安全一致性、兼容产品三视角。评审意见须引用 R1/后续
具体 revision，区分 demonstrated source facts、设计歧义和需 spike 的假设。
修文关闭的是设计歧义；运行时保证需实现与测试。跨视角矛盾在综合记录中处理，
语义修改需受影响评审者复核，不能将旧评审结论泛化到新 revision。

## Local Implementation Baseline (2026-10-12)

The offline command `env PYTHONPATH=src .venv/bin/python
scripts/dev/verify_resume_scale.py --sessions 2 --logical-size-mib 1 --json`
passed on both `main` at `574f24bc` and the #696 task branch at `0198ef86`.
The script creates two sparse catalog candidates and one valid 40.008 MiB
transcript, then resumes it in a fresh process with a deterministic model.

| Observed phase | `main` | #696 branch |
| --- | ---: | ---: |
| Cold bounded catalog listing | 7.402 s | 8.181 s |
| Fresh-process Resume through completed turn | 11.512 s | 11.833 s |
| Resume to first model request | 3.958 s | 4.206 s |

These two local runs establish a pre-background baseline, not a speedup claim
or a stable latency budget. The script does not yet measure first frame, input
acceptance, Plan readiness, durable input, CPU/RSS/FD, or 1/2/8 concurrent
Sessions and 10k/100k record scenarios required for R2.1 acceptance.

## Internal Recovery Guard Evidence (2026-10-12)

The internal ordinary-route guards were committed as `db90f355` and
`2221b8c7`. The Resume Binding, Plan, comparison, and history-preview tests
passed 46 cases after those changes. Three normal bootstrap/model-preparation
cases also passed on the final guard code.

Commit `6da762e1` adds three real JSONL reopen cases: an unbound v1 intent,
an unknown v2 intent, and a malformed v1 intent. After closing and loading a
new SessionManager, each case retains its Session ID and selected leaf,
rejects ordinary continuation with the corresponding typed recovery reason,
and remains viewable through the read-only snapshot. The final file bytes
equal the bytes before reopening. All three cases passed.

Ruff passed for the touched code and tests. Mypy with
`--follow-imports=silent` passed for `resume_activation_attempt.py`,
`session_manager.py`, `bootstrap.py`, and `session/agent_session.py`.
These checks establish the internal historical guard; they do not establish
live activation admission, effect settlement, Hosted continuation, released
N/N+1 compatibility, or the complete R2.1 quality and performance gates.

## Latest Main Integration Evidence

The task branch incorporated fetched `origin/main` at `197a9008` through
merge `f915f5f0`, including the Windows history-source inventory and conditional
Windows PR smoke selection. The merge had no conflicts. After integration,
212 non-live tests passed across `tests/ci`, Resume Writer/Binding/Plan, framed
execution connections, authenticated local execution, local records, and
connection profiles. Documentation validation passed nine checks. This proves
the listed local integration checks, not Windows runtime execution or completed
Resume admission/publication, release, and performance acceptance.

## Internal Coding Candidate Preparation Evidence (2026-10-12)

208 non-live tests passed across Resume runtime preparation, Binding, Writer,
ordinary Coding AgentSession and the Harness AgentProduct contract. The seven
new preparation cases use the original owned Writer and graph: definite intent,
unknown acknowledgement, historical-only intent, admission denial, wrong attempt,
changed selected branch and revocation after real graph binding. The last case
also rejects retry after failed preparation. All preserve transcript bytes
during preparation and keep execution unavailable. An initial fault run exposed
a Writer-drain deadlock when an operation scope spanned graph rollback; short
synchronous admission scopes fixed that lifecycle conflict, and the final
seven-case run completed normally.

Seven focused composition tests also passed for detached current observations,
concurrent ordinary preparation, foreign startup rejection and fenced Product
startup records. Ruff, mypy for the two changed Product modules and all nine
documentation checks passed. The graph-preparation fixture constructs its AgentSession
before committing intent; those tests do not prove bootstrap from a legacy resumed
Writer, native Worker effect settlement, Hosted readiness or Runtime publication.

## Internal Resume Bootstrap Evidence (2026-10-12)

The owned Writer baseline passed four tests before this slice. A new legacy
reopen test first failed because the internal Resume bootstrap was absent.
After implementation, 159 non-live tests passed across Resume bootstrap, runtime
preparation, Writer, Binding and the ordinary Coding bootstrap suite. The seven
new bootstrap cases cover legacy history, a previously prepared standard
composition resumed with the current minimal composition, initial denial,
wrong current composition, revocation after construction, a non-None admission
result and an uncertain intent acknowledgement. Successful cases construct and
prepare the real candidate graph without changing history after intent commit;
execution remains unavailable. Delivery revocation disposes the original
candidate Writer, while wrong composition and uncertain intent are rejected
before the caller's admission callback.

Ruff and mypy for the changed Product modules passed, documentation checks
passed, and the cumulative change-aware gate plan was inspected. Full branch
quality gates and Actions platform checks remain pending. These internal tests
do not prove live subject/policy grants, native effect correlation, production
Embedded/Hosted continuation, Runtime publication, performance acceptance or
released N/N+1 behavior.

## Internal Runtime Publication Evidence (2026-10-12)

The pre-change Binding and candidate-preparation baseline passed 51 tests.
After adding publication, 184 non-live tests passed across publication,
bootstrap, graph preparation, Binding and ordinary AgentSession. After extending
published Resume admission to shell, extension exec and explicit compaction,
the final related Binding/AgentSession/publication run passed 170 tests.
The existing inert guard fixture now uses the actual AgentSession type so its
instance admission checks are exercised without downstream execution services.

The final eleven publication cases passed. They cover definite publication,
unknown input acknowledgement, selected branch change, subject revocation,
unsettled epoch effects, changed current receipt, missing local graph,
unknown durable lookup, revocation during lookup, real on-disk input mutation
and cancellation while awaiting lookup. Successful publication permits current
runtime preparation and a descendant input without writing historical startup
records; later revocation rejects model preparation, shell, extension exec and
explicit compaction. Selecting ancestry without the bound input also rejects
preparation. Failure cases preserve the closed gate, perform no publication
history write and dispatch no model request. Publication cancellation retains
the already committed input and leaves execution closed.

Ruff, mypy for the two Product modules and documentation checks passed. The
admission and epoch-settlement callbacks in these tests exercise the internal
boundary contract; they do not establish real current grants or native effect
journal correlation. Production activation and submit owners must still supply
those checks and consume the single committed input without appending it again.
Hosted readiness, model outcome recovery, full quality gates, performance and
released-artifact acceptance remain pending.

## Internal Committed-Input Dispatch Evidence (2026-10-12)

The pre-change Harness router/runtime baseline passed fourteen tests. The
updated router/runtime run passed fifteen, including a retryable error whose
observation is retained while retry/compaction are suppressed, and whose normal
recovery behavior returns when the predicate permits it again.

The final integrated run passed ninety non-live tests across Resume publication,
Coding's Model Input contract, Binding and Harness router/runtime. Seven new
dispatch cases cover completion, provider connection failure, an existing queue,
initial subject revocation, revocation after real snapshot commit, caller
cancellation during transport and Host abort. The fixtures use a registered
offline prepared API adapter through the standard AI stream, not a bypassed
custom stream. Every invoked request creates one original Model Input snapshot
with purpose `main`, while the original history plus resumed input remain exactly
two UserMessages. Repeated dispatch is rejected without another request.
Revocation at the commit barrier retains the snapshot and invokes no transport.
Provider failure, abort and cancellation invoke at most one transport and retire
execution preparation. CallOptions and the run-local recovery predicate return
to their prior values. No network provider is contacted.

Ruff, mypy for the three changed source modules and documentation checks passed.
This proves internal consumption and the original transport boundary. It does
not prove production current grants or native effect settlement, Hosted submit
deduplication/outcome lookup, restart recovery or Embedded/TUI integration.
These production callers and the full release/performance gates remain pending.

### Hosted detached history binding

`CodingHostedSessionCatalogV1.open_history_binding` reads the original bounded
selected-path snapshot and rechecks the discovered canonical identity, source
revision and accepting owner before delivery. It bypasses writable candidate
claiming entirely. It does not run services selection, Product preparation,
Writer acquisition or historical startup replay. Ordinary writable open and
idempotent create retain their existing checks.

The returned `CodingHostedHistoryBindingV1` holds only a detached bounded text
projection. The existing Hosted adapter and application binding validator admit
an explicit absent execution control; no artificial SessionControlPort is
created. Snapshot and subscriptions are available, prompt/steer/follow-up report
Session unavailable, interrupt reports false, and interactions cannot approve
historical requests. The display neither grants current actor authority nor
provides input-outcome lookup. Existing scoped AppService read authorization
remains required by callers. Closing the binding is idempotent and has no runtime
or Writer to dispose.

Regression coverage exercises changed composition/capability metadata through
the actual Hosted adapter, preserves the selected left branch when a right
branch is also present, and rejects delivery after source revision change or an
owned catalog fence. Successful display leaves original transcript bytes intact.
The pre-change adapter/real-session baseline passed fifteen tests with one
existing skip. Scoped mypy for all four changed source modules and Ruff passed;
unscoped mypy also reports pre-existing errors in imported modules and is not
the changed-module gate.

The final integrated run passed fifty-eight non-live tests with one existing
skip across Hosted catalog, adapter, application, execution and real-session
coverage. The owned-fence case uses the real managed catalog; the legacy
unowned catalog's historical no-op fence is not used as shutdown evidence.
All nine documentation checks passed.

This is an explicit history entry, not yet the default LMUX/AppHost open route.
The original real-session factory still constructs an executable runtime eagerly.
Connecting deferred AppHost claim/profile ownership, native current policy and
effect settlement, first-input activation, and Embedded/TUI remains required.
The full bounded snapshot read is not a measured large-session fast-open path;
tail paging and background-plan performance acceptance remain pending. Goal and
Issue #696 remain incomplete.

#### Component full-gate outcome and exact failed-test rerun

At `6b62dd9b`, docs, dependency facts, full Harness Ruff and mypy (772 files)
passed. Full Harness testing completed with **5 failed, 5756 passed, 124 skipped,
33 warnings in 1867.28 seconds**, and the gate exited 1. All five failures first
encountered disk quota exhaustion: four native containment fixture compilations
could not write compiler intermediates in `/tmp`; the large Exec output artifact
could not be written, followed by a bad-file-descriptor cleanup error. A
temporary full source copy created during that run exhausted the quota and was
deleted; candidate verification switched to a small source overlay.

Without changing that commit's source, the exact four C52 native cases
(`C52-EXACT-CLOSURE`, `C52-FD-SUBSTITUTION`, `C52-CANCEL-POST-EFFECT`,
`C52-DESCENDANT-CLEANUP`) and
`test_exec_service_streams_output_larger_than_asyncio_line_limit` were rerun
outside the sandbox with the same non-live/host-runtime exclusions: **5 passed
in 5.68 seconds**, exit 0. These are separate full-run and rerun observations;
the failed full command is not relabelled as a single green run.

#### Worker original C5 Resume registration

Worker enrollment, native key registration and sealed enumeration now live in
the original C5 CAS state. Opt-in state version 3 uses explicit journal record
version 2; ordinary state version 2/record version 1 retain their original shape.
Contextual admission requires the supported native containment cleanup v2
contract. Original native key identity and authority rechecks remain in force.

History replay and CAS reject loss/rebinding of parent enrollment or native
association, seal removal/reopening, retroactive or late registration, sealed
late effect start and state downgrade. Original linked settled attempts are
retained through compaction; capacity exhaustion refuses admission. Started
unknown effects and cleanup debt prevent seal. Publication and exact native
settlement retain their original meanings and do not prove arbitrary domain
effect completion.

The staged implementation passed **220 tests, 30 skipped in 27.71 seconds**
through an independent source overlay, then **220 passed, 30 skipped in 11.06
seconds** after integration into the actual task worktree. The subsequent
registration acknowledgement-loss test and all native parent protocol faults
completed with **12 passed in 1.22 seconds** before commit.
Both affected implementation files passed mypy, and Ruff passed. Full selected
gates and release evidence remain distinct from these focused results.

The Coding canary has not yet propagated committed Resume parent context.
Trusted participation computation, intent/Binding v2, writer capabilities,
custody/segmented retention, domain reconciliation, Embedded/Hosted/background
integration and final release/Issue delivery remain unfinished.

### Explicit v2 intent, single-message Binding and path correspondence

The task branch now contains explicit `coding.activation-attempt/v2` and
`coding.runtimeBindingV2` codecs. The intent freezes at most eight sorted,
unique original-owner obligations and their scope/contract digests within an
8 KiB document. Its canonical digest is carried by the Binding alongside the
unchanged common identity fields. A typed parent context derives only from an
exact frozen obligation; it does not enroll an original owner or grant effects.

The ordinary fixed-ID UserMessage record carries both Binding and resource
metadata. Original FileConversationStore tests cover durable append, lost
acknowledgement, identical retry and changed-intentDigest conflict refusal:
readonly reload retains exactly one UserMessage and the original resource
metadata. These are original storage tests, not evidence that the Product
continuation or current actor admission is integrated.

A separate selected-path projector supports exact v1/v2 correspondence,
requires persisted v2 intent for v2 Binding and rejects a v1 Binding closing a
v2 intent. It checks complete ancestry, payload and frozen intent identity;
unknown schemas remain unknown. Historical correspondence is not present
permission or original effect settlement.

The legacy reader now treats reserved future Binding keys as unknown rather
than absent. An unknown schema remains unavailable throughout the selected
path, including when a later known v1 Binding appears. The previous test that
allowed that later Binding to replace the unknown observation was tightened;
a known legacy record cannot establish understanding of the earlier schema.

Initial integrated codec/projection tests completed with **93 passed in 38.41
seconds**, and three implementation files passed mypy. After the reader guard,
the first combined run had **96 passed, one failed in 41.89 seconds** at the
old supersession expectation just described. After tightening that expectation,
the actual worktree regression completed with **97 passed in 25.35 seconds**;
all four implementation files passed mypy. The augmented original-store conflict/acknowledgement tests separately
completed with **2 passed, 22 deselected in 6.62 seconds**.

The continuation still writes v1. Trusted participation computation, original
owner enrollment/settlement wiring, writer capabilities and Embedded/Hosted
entry integration remain required before default writable v2 recovery. The
Worker selected gate started at `04b66cc7` terminated with two Transcript
performance failures: **5771 passed, 124 skipped, two failed in 3867.03 seconds**.
Strict load took 5.52 seconds for 8.9 MiB; persistent-index load took 1.48 seconds.
A focused rerun before optimization had one failure and one pass: strict load
still took 5.46 seconds. Harness Ruff/typechecking passed in the original gate;
Hosting was not reached. Coding modules and the legacy reader guard were added
while that gate ran, so it is not a gate over this final tree.

The selected Coding gate for `35349934` completed docs/dependency checks but
refused pytest before collection because the runtime scratch had only
35,778,560 free bytes against the 64 MiB requirement. The previous Harness
wrapper then removed its own temporary run, leaving 164 MiB available. A fresh
Coding gate was started with the same non-live/skip-host-runtime selectors;
its terminal result remains pending.

### Continuation protocol refusal before Writer acquisition

`CodingActivationAttemptV2` inherits the common v1 value fields. The original
continuation's `isinstance` check previously admitted that value through
current actor callbacks and Writer acquisition, then failed only when its
explicit v1 record builder rejected the v2 wire. Writer restore can repair a
partial tail, so this late rejection did not establish the required ordering.

The v1 continuation now rejects other intent implementations with
`writer.resume_protocol_unsupported` before admission callbacks and Writer
acquisition. Tests use an actual historical transcript and application-owned
factory with complete and unterminated-tail variants; neither the original
Writer nor actor/settlement callbacks may run, no pending preparation remains,
and the complete set of fixture files retains its exact bytes.

This is an early refusal at the existing v1 entry, not the accepted four
capabilities or a v2 writable implementation. Full native capability checks,
trusted participation/enrollment and default Product continuation remain
unfinished. The two version-refusal cases and fourteen original continuation
owner-order/failure cases completed with **16 passed in 227.58 seconds**.
Ruff, mypy and nine documentation checks passed.
The previously running Coding gate began before this change and cannot prove
this new refusal behavior; its result is tracked separately.

#### Latest main synchronization

After saving the continuation refusal as `48f8a3a8`, the task branch merged
control-lane `main` at `34e2c8f9` in `24909a12`. An explicit `git fetch origin main`
observed upstream `1f1ba1d1`; both revisions are ancestors of the task HEAD.
The merge brought the accepted Coding inventory/CI route changes without
conflict. `tests/ci/test_change_gates.py` completed with **85 passed in 4.02
seconds** under non-live/skip-host-runtime selectors.

The whole-branch plan against this latest `main` selects broad Product,
Harness, hosting and platform checks, including full-validation fallback for
unclassified benchmark/architecture-test paths. These remain final-delivery
obligations. The earlier Coding gate still runs under its original selected
inventory and source observation; it does not prove the newly synchronized
whole branch or any pending architecture/runtime integration.

### Original native Writer protocol negotiation

Definition/Component decision journals and the original Worker C5 state journal
now declare their implemented `writer_protocol_capabilities`. Trusted callers
may supply an exact `required_writer_capabilities` frozenset at original owner
construction. Each original owner compares against its compiled support before
opening, locking, loading, repairing, enrolling or appending anything. A future
requirement refuses with an owner-specific protocol error; coercible/malformed
requirements reject. An overridden advertised property cannot expand compiled
support. The existing event v2 / Worker record v2 and state v3 remain the original
owner version boundary; no Coding sidecar or extra authority record was added.

The original protocol/journal regression completed with **112 passed in 9.87
seconds**; three changed implementation files passed mypy and Ruff. The new
negotiation tests preserve the exact fixture file set and bytes for complete
and partial-tail state. Supported negotiation reads actual upgraded native
history without supplying an admission or settlement grant. The final native
negotiation suite completed with **21 passed in 4.36 seconds**, including actual
upgraded-history reads and rejection despite an overridden advertisement.
Nine documentation checks and dependency facts passed.

This is source-level negotiation for the three native backends. Product must
still aggregate all four accepted capabilities before its first Transcript
Writer and compute complete trusted participation before Definition evaluation.
`coding.resume-continuation/v2` is not implemented or advertised. Existing
previously released unfenced writers are still unsupported on upgraded native
state; these constructor tests are not installed-version rollback evidence.

### Runtime background planning ownership and cleanup

AgentSessionRuntime now exposes a bounded background planning slot over the
original ResourceLoader. Identical concurrent requests share one Product
waiter; changed source/subject/policy observations cancel and join the old
waiter before replacement. Successful completion retains one immutable,
data-only Plan. Resource owns physical work and capacity independently; Root
cleanup releases its waiter without closing the shared ResourceLoader.

Cache retrieval compares selected-source identity and freshly observed original
owner dependencies. Changed resource contents or history invalidate the cached
Plan. No Plan authorizes a Writer, admission, owner settlement or execution.
Root disposal attempts history-read settlement even if planning cleanup fails.
Focused planning/history/Plan regressions completed outside the sandbox with
**44 passed in 20.03 seconds**, including pending-subject replacement, concurrent
coalescing, shared-owner reuse, stale inputs and independent cleanup failure.
Ruff, mypy over both implementation files, nine documentation checks and
dependency-fact validation passed. Default CLI/TUI and Hosted callers are not yet wired to these
entries; no first-message latency improvement is claimed from these tests.

The earlier selected Coding run has now terminated with exit 1 after its
pytest child was interrupted: **118 failed, 1168 passed, one skipped, 45
deselected in 2536.39 seconds**. Runtime scratch was full; explicit ENOSPC
failures occurred, but the complete set of failures has not been attributed to
that cause. This interrupted run is not a passing or complete gate. The new
focused run used the task-owned disk scratch directory, preserving the wrapper's
64 MiB capacity preflight and non-live/skip-host-runtime selectors. A fresh
selected gate must cover the current source and current check inventory.

### Strict historical load performance follow-up

Profiling the failed original strict load identified inline Model Input JSON
canonicalization as the largest codec cost. A standard JSON parse yields only
builtin containers/primitives; native `json.dumps` with `allow_nan=False` and
UTF-8 encoding now validates that closed algebra and computes canonical bytes
in one pass. Canonical text, decoded byte count, value hash and node hash checks
remain mandatory. This optimization changes neither the wire nor the budget.
New refusal cases cover NaN/Infinity/overflow, escaped surrogates in values and
keys, noncanonical order/whitespace/escapes/numbers and changed size/value/node
hashes; valid float, Unicode and control bytes retain their original form.

The first optimization (native canonicalization after a separate Python
validator) had **14 passed, one failed in 77.79 seconds**: strict replay improved
to 4.76 seconds but still exceeded its 0.50 s/MiB budget. The final closed-algebra
implementation had **34 passed, one failed in 64.23 seconds** across performance,
canonicalization, v2 reconstruction and persistent-index tests. Strict replay
passed; persistent-index load took 1.28 seconds against about 1.14 seconds.
That unresolved observation is not a green full gate. Both this task's Coding
gate and another lane's Coding tests were observed running concurrently; their
presence does not by itself establish the cause of the index failure.

An alternating same-fixture benchmark used the committed `35349934` inline
constructor and the changed constructor through the same original strict
loader. For **9,297,227 bytes and 280 records**, before times were **8.930 and
6.660 seconds**, after times **3.510 and 3.513 seconds** (about **55% lower mean
elapsed time**). After rates were **0.396 s/MiB**. This is a local strict-load
comparison under concurrent machine load, not Embedded/Hosted startup,
100k-record, RSS or released-installation acceptance. Ruff and focused mypy
passed. The final size/value/node-hash and strict JSON fault cases completed
with **14 passed, nine deselected in 2.83 seconds**. Docs and dependency facts
passed; release gates remain separately tracked.

### Hosted history claim and profile ownership

The catalog's explicit `open_history_candidate` entry now wraps the detached
display in the original candidate/claim lifecycle. Its exact
`CodingHostedHistoryCandidateBindingV1` type carries no SessionManager or Writer.
The original Product candidate validator continues to require matching canonical
reference, envelope and Hosted compatibility identity. Claim verification and
factory transfer recheck the original source revision and managed catalog fence.

`CodingRealHostedSessionFactoryV1` recognizes this exact display candidate before
services or Package Product selection. Transfer is synchronous and consumes the
display once. Failed identity, source or owner checks retain candidate cleanup;
closing an untransferred candidate closes its display. After transfer, candidate
and claimed-handle cleanup leave the delivered Product display alive. The
original foreground Product runtime and Hosted profile factory accept the
absent execution control, with their existing identity and close ownership.
Neither the candidate nor the display is a current actor grant or an activation
proof.

Nine focused offline cases passed for delivery through the original Product
runtime/profile path, source changes before and after claim, catalog fences
before and after claim, a closed factory, wrong binding key, unclaimed close,
claimed close, repeated delivery rejection and post-transfer candidate cleanup.
Test services and Product-selection functions fail on invocation; successful
historical display invokes neither and preserves transcript bytes. The managed
fence cases use the original owned catalog on Linux. The pre-change history
baseline passed four cases.

The integrated non-live catalog, owned-catalog, real-session, application and
execution run passed sixty-eight cases with one existing skip. Scoped mypy for
catalog, real-session factory, application and launcher modules passed, as did
Ruff and all nine documentation checks.

The default catalog `open_candidate` and writable/idempotent-create paths remain
unchanged. This explicit path supplies the native claim/profile seam needed for
deferred Resume composition; selecting it in default LMUX/AppHost, retaining
first-input identity, admitting current authority and effects, and publishing
the activated runtime still remain required. These tests do not establish a
full scoped multi-client or default launcher Resume flow.

### Resource preview foreground priority and cleanup

The original Resource preview task scope now dispatches through a priority queue
on its existing two native workers. Foreground requests run before queued
background work. A foreground reference to the same workspace, owner state,
subject, policy and budget promotes the existing job; it does not repeat its
scan or produce new selection evidence. ResourceLoader Session views and
`plan_coding_resume_async` forward this scheduling input without including it
in Plan identity or current authority.

The process remains bounded to eight admitted jobs. At most six may be
background jobs, preserving two admission slots for foreground preparation.
Promotion releases a background reservation while retaining the total-job
reservation until actual native completion. Already running work is never
interrupted or restarted. Caller work-unit and wall-time budgets are unchanged.

Cancelled jobs and fenced owner work are promoted for cleanup so sustained
foreground requests cannot indefinitely delay temporary read-pin disposal.
Cleanup still runs in the original native callback, and `aclose` waits for its
actual completion. Priority does not replace the existing cancellation flag,
submission publication gate, reference limits or source validation.

Queue submission can throw after native dispatch admission. The scheduler
removes only that submission's still-pending operation; an unknown queued
dispatch callback may service an already admitted peer. The original scope
publication gate prevents the failed submission from reading source content,
disposes its pins and fences new work. Existing accepted peers keep their
completion callbacks and total reservations.

The pre-change preview/Plan baseline passed twenty-five non-live cases. New
regressions fill both native workers, queue background work, and verify a
foreground Session view runs first or promotes one shared scan. They also fill
six background slots, admit two foreground jobs, reject a ninth job, preserve
an admitted peer across a lost native submission receipt, and close a cancelled
background owner while a foreground peer remains blocked. Foreground and
background Plan envelopes have the same identity for unchanged input data.

The final integrated preview-task, Coding Plan and ResourceLoader run passed
sixty-four non-live cases. Scoped mypy for all four source modules, Ruff and all
nine documentation checks passed. These are scheduling and regression results,
not release startup latency measurements.

This proves Resource-owned scheduling and lifecycle behavior, not production
Resume invocation, current subject or policy grants, cross-loader Workspace
deduplication, completed Plan caching or first-message performance acceptance.
Embedded/TUI, default Hosted activation and release evidence remain pending.

### Read-only initial Model Outcome observation

`observe_coding_resume_model_outcome` correlates one exact, selected-path Resume
UserMessage with the original Model Input snapshot and native
`project_model_call_invocations` terminal projection. Input lookup identity is
the complete persisted record digest, including Binding, parent and timestamp.
The initial snapshot must anchor to that UserMessage leaf, use Coding's same
conversation and main purpose, and identify one unambiguous invocation. Native
outcome snapshot references must match exactly. Repeated input identities or
multiple anchored snapshots are conflicts, rather than latest-success selection.

The result contains only logical input/record IDs, invocation ID, one snapshot
ID and `observed_completed`, `observed_failed`, `observed_cancelled`, `unknown`
or `conflict`. These are historical observations of the initial model call,
not whole-turn completion, current admission or retry permission. Missing
snapshots, prepared-only invocations, unknown outcome schemas, mismatched
references, copied foreign-conversation snapshots, compaction and other users
remain unknown. Neither an AssistantMessage nor an input commit proves model
completion. The original required Model Input codec remains unchanged: an
unsupported required version is rejected by that reader, not implicitly adopted.

The Hosted catalog's explicit `preview_resume_model_outcome` uses its original
bounded snapshot and source/closing fences. It reads fresh data for a current
discovery reference; a stale reference is rejected. It does not use a cached
display or acquire a Writer/Runtime. Calling services still own current read
authorization; no new remote profile or submit capability is negotiated here.

The pre-change logical-input/publication baseline passed twenty-three cases.
Five original offline API-adapter dispatch cases passed outcome correlation for
completion, provider failure, caller cancellation, Host abort and revocation at
the snapshot commit barrier. The last case persists a snapshot without invoking
transport and remains unknown. Actual snapshots anchor to the fixed resumed
UserMessage record. Existing repeat-dispatch rejection and one-UserMessage
invariants continue to hold.

The integrated fresh-reader projection, logical-input lookup and Hosted catalog
run passed thirty-five non-live cases. Sixteen projection cases include restart
reads, selected branches, duplicate input/snapshot identities, digest and outcome
reference conflicts, other conversations/users/purposes and unknown payload
observations. The unknown required-snapshot projection case uses a detached
in-memory mutation because the original file codec refuses to encode that
unsupported version; it is not future-version reader compatibility evidence.
File bytes remain unchanged. Scoped mypy for both source modules and Ruff passed.

This supplies observation needed by recovery but does not authorize automatic
retry or complete crash recovery. Default production activation, scoped Hosted
outcome delivery, first-input deduplication, current policy/effect settlement,
Embedded/TUI and release/performance evidence remain required. Goal and Issue
#696 remain incomplete.

#### Initial outcome ordering and later replay

The initial-outcome observer also checks anchored snapshots across the whole
selected descendant path. A replay of the same input after a later UserMessage
is a conflict, even when the earlier invocation completed. A sole anchored
snapshot after that later UserMessage remains unknown. A matching terminal
Outcome that precedes its prepared snapshot is unknown. The native generic
Model Call projector remains unchanged; these are Coding's narrower Resume
association rules.

Both wrong-order and later-replay regressions first reproduced false completed
observations. The updated fresh-reader observation and logical-input lookup run
passed twenty-three non-live cases, including both new cases. Scoped mypy and
Ruff passed. This strengthens historical evidence and still grants no retry or
current execution authority. Default activation and the full R2.1 delivery
remain incomplete.

The original offline completed-dispatch case also passed with these narrower
association rules, and all nine documentation checks passed.

#### Embedded history preview native-read settlement

The real Coding Continuity preview now uses the existing native I/O settlement
helper for Header, selected history, large-file tail fallback, and asset-health
reads. Cancellation retains the submitted read through actual completion. When
the preview is called through the original stable Continuity reference, root
shutdown consequently joins the native read before disposing the binding. A
second cancellation does not release that ownership or resubmit the read;
references arriving after root closing fail before reaching the reader.

Two blocked-native-read regressions, for Header and selected-history reads,
first reproduced premature reference retirement. Both pass after the change,
including repeated cancellation, concurrent root shutdown, stale-reference
rejection, one reader invocation, unchanged transcript bytes, and no prepared
Writer. The complete Continuity test file passed thirty-six non-live cases.
Scoped source mypy and Ruff passed. Existing byte limits and tail display
semantics remain in force. Cancellation and provider timeout can finish only
after submitted native I/O settles; this is ownership evidence, not a native
I/O latency guarantee or a performance measurement.

This change reaches the production Embedded history-preview path. It does not
connect the Resource Catalog scheduler to transcript reads, switch the default
restore operation to a read-only session, or supply first-input activation.
Full R2.1 delivery, Goal, and Issue #696 remain incomplete.

#### Reopened Binding does not restore current admission

The ordinary Coding activation guard now checks the selected current-Session
Binding after validating historical attempt settlement. A bound input can be
durably committed while the process that held its current admission has ended.
Reopening that file therefore returns `runtime.current_admission_required`
before ordinary Product runtime selection or another message append. A readable
Binding and a historical Model Outcome cannot recreate current authority.

The locally published candidate retains the original exact-input and original
Writer proof. Its guard requires that proof to match the selected Binding;
switching to another Binding cannot borrow an earlier publication. The existing
publication-pending fence still runs first. Source-Session Binding copied into a
fork remains historical origin under the original projector's identity rules.
Existing revision caching remains unchanged for ordinary messages without new
Binding metadata.

The reopening regression first reproduced an ordinary guard accepting a bound
input without local current proof. It exercises the real fixed input commit,
file close and reopen, read-only history observation, a Product-selection
sentinel, and an attempted subsequent write, with unchanged canonical bytes.
This closes an admission bypass in the existing production guard; it does not
provide the missing activation coordinator or default read-only restore route.
Full R2.1 delivery and Issue #696 remain incomplete.

Validation passed sixty-three non-live Binding and runtime-publication cases,
including original offline prepared-model dispatch and cancellation/error
boundaries, plus scoped source mypy, Ruff, and all nine documentation checks.

#### Embedded runtime owns detached history reads

`AgentSessionRuntime.preview_resume_history` is a read-only data entry using the
original discovered-source resolver and bounded Coding snapshot reader. It
accepts an exact path or discovered identity and an explicit selected leaf,
preserves historical cwd without repair, and returns a preview rather than an
Agent Session. It never calls the configured Product session factory, loads a
Writer, imports a compatibility file, or replaces the current lifecycle Session.
The original terminal history projector can consume its selected records with
no live Tool resolver. The real Embedded Coding Continuity provider routes its
bounded selected-history snapshot through this owner entry, retaining its
existing summary/source revision checks. Other continuity runtime adapters
keep the prior cancellation-atomic reader path.

The runtime retains at most two submitted reads. Cancelling an observation
waiter releases that waiter promptly but leaves its native read with the root;
it does not free admission capacity early. Root disposal fences new reads,
performs the original lifecycle disposal, and joins actual read completion
before closing the transcript factory. A cancelled root close retains this
join. Results arriving after the fence are rejected, as are files whose source
revision changed between the bounded read and delivery. Read errors left by
cancelled waiters are observed by the completion callback.

This establishes the Embedded owner entry needed for fast history opening. The
default CLI resolver and Continuity activation still restore an Agent Session
eagerly, and no TUI current-session replacement, initial activation coordinator,
or background Plan scheduling is supplied by this entry. Those production
connections and the full R2.1 release evidence remain required. Goal and Issue
#696 remain incomplete.

The new owner and production Continuity integration run passed forty-six
non-live cases. The new fixtures combine retired composition, changed
capability profile, and deleted historical cwd. They cover both path and
discovered identity, original owned and unowned runtime configurations,
selected terminal projection, unchanged directory contents, stale source
delivery, cancelled waiter retention, capacity accounting, cancelled root
close, and rejection after closing. The final stale-delivery case passed after
aligning its exception with the existing preview's read-error handling. Scoped
mypy for both changed source modules and Ruff passed.

The earlier owned-runtime and Agent-runtime regression run also completed:
one hundred fourteen non-live cases passed. It included the initial detached
history owner tests and the existing runtime lifecycle coverage.

#### Initial input uses native Request Evidence commit coordination

Coding's `_commit_resume_first_user_input` now joins the prepared current
candidate, exact staged payload, original Writer, and current admission before
calling `AgentEventRouter.commit_prepared_user_message`. The router uses its
original metadata preparation and append path, including Request Evidence and
Product metadata collision checks. The staged Manager supplies the fixed
record ID and inline Binding to that same physical UserMessage record. The
Request Evidence owner records the definite commit using the returned canonical
record ID. No Agent event, model run, recovery, or Runtime publication occurs
through this persistence entry.

The initial Coding entry is claimed once before the append await. A lost ACK,
cancellation, or failure after claiming leaves execution fenced and requires
lookup/recovery; calling the entry again cannot prepare metadata or append
another input. Exact staged-input checks run before metadata callbacks. The
candidate, Writer proof and current admission are rechecked after commit. A
revocation during the append can therefore leave a committed input without
making the candidate executable.

The original UnitOfWork retains its existing exact-record/operation-ID
idempotent verification on Store uncertainty. That native behavior is distinct
from submitting another input or replaying a model call. Fault evidence checks
identical full records, expected revision and operation ID across native
attempts, one canonical persisted user record, authoritative input lookup, and
rejection of a second Coding submission. The native Store and UOW algorithms
remain unchanged.

The Resource evidence fixture is prepared and bound by the original Request
Evidence runtime using its existing typed loaded-Skill fixture. It proves
metadata co-commit and canonical record association, not production Skill
preflight, current Resource generation pinning or authority admission. The
existing offline model cases use this new input entry before original
publication and prepared-model dispatch.

Default Embedded/Hosted first-input coordination, live policy and native epoch
settlement owners, logical input event publication, release compatibility, and
performance evidence remain required. Goal and Issue #696 remain incomplete.

Validation: the publication/dispatch and native Event Router run passed
thirty-two cases with one new fault-test assertion failing. Source inspection
confirmed the original UOW's fixed-ID verification; the assertion was corrected
to check exact request identity and one physical record. All five new
input-commit/evidence cases then passed, including the previously failing
unknown-ACK case. The existing eighteen publication/dispatch cases also passed
with the new input entry. Scoped mypy for all three source modules, Ruff and
all nine documentation checks passed.

#### Initial input uses native prompt and Skill preparation

Coding's `_prepare_resume_first_user_input` now delegates to the original
PromptController's preparation entry, which reuses Resource prompt preflight,
Request Evidence preparation and native UserMessage construction. This entry
does not queue input, invoke a command, commit history or dispatch a model.
Recognized builtin and extension commands are rejected through the existing
command matchers before Resource preparation. Extension command execution
remains disabled in the original preflight call.

Preparation requires the same locally verified intent, exclusive Writer and
current candidate as input commit. Current admission is checked before and
after the Resource await. The preparation is claimed once; cancellation or
failed post-await admission discards its native evidence owner and fences
execution preparation. The prepared native message's full input digest is
retained locally. Input commit rejects a different payload even if that
different payload was subsequently staged in the Manager.

A real workspace `skills/review/SKILL.md` fixture now exercises the current
Catalog and Resource owner instead of constructing a loaded-Skill result.
Its expanded native message and observed source-byte digest are committed
through the original Request Evidence owner alongside the inline Binding.
The committed canonical record is independently found by logical input lookup.
Boundary cases cover revoked admission after reading, cancellation during
preflight, repeated preparation, command isolation and substituted staged input.
Admission callbacks remain test validators; these cases do not establish
production actor-policy admission, approval or epoch settlement.

Validation: eighteen non-live publication/preflight and native PromptController
cases passed. Scoped mypy for both changed source modules, Ruff and all nine
documentation checks passed.

#### Permission expansion borrows native Approval confirmation

The original InteractiveApprovalResolver now issues and validates bounded,
ephemeral exact-action confirmation facts. A current matching native grant or
retained Policy rule may satisfy a request; otherwise an accepted interactive
response is required. Headless fallback's plain allow does not issue a fact.
Once-only approval remains bound to that one action and is not generalized
into Tool authority. Native grant/rule revocation is rechecked at each borrow.
Copied facts, another owner, changed requests, released facts and reopened
closed Sessions cannot validate the original confirmation. Cancellation and
denial remove reservations without retaining confirmation. The owner admits
at most sixty-four outstanding confirmation actions.

Coding's permission confirmation request binds the immutable activation
attempt's target Session/leaf, ancestry, Plan, candidate epoch and subject,
together with bounded owner-observed expansion codes. The optional native
session-grant proposal includes a fingerprint of all these fields. Coding's
borrower re-creates that exact request and validates it through the issuing
Approval owner. No new approval store or durable confirmation journal is
introduced. This is a permission-expansion prerequisite, not a computation of
current subject/Policy authority or native epoch/effect settlement.

The real native Skill/Resume fixture now obtains interactive confirmation
before acquiring its Resume Writer. It checks unchanged history bytes during
confirmation, then uses the original owner's current validation through
bootstrap, graph preparation, Skill preflight, input/evidence commit and
publication. Revocation after Skill reading prevents input commit and removes
pending evidence. Revocation after publication rejects native model preparation,
compaction, shell and extension execution entries. Epoch settlement in these
fixtures remains a test validator; the default Embedded/Hosted continuation
coordinator and actual current actor/Policy owner wiring remain pending.

Validation: one hundred twelve non-live cases passed across native Approval,
multi-agent approval lifecycle, Hosted approval presentation, Coding request
binding and both real Resume integration cases. This includes once/session
confirmation, safe grant reuse, coalesced-request distinction, capacity,
changed actor/candidate/scope/leaf/subject and owner closure. Scoped mypy for
the three changed source modules and Ruff passed.

Both final cancellation/close delivery cases also passed with explicit rejection
of action-ID reuse before the original waiter settles. Invalidated reservations
remain bounded until that waiter releases them, so its cleanup cannot erase a
new confirmation. All nine documentation checks passed.

#### Initial continuation has one Coding coordinator

`prepare_coding_resume_continuation` now sequences the original owned Writer,
fixed intent, current bootstrap, candidate graph, native prompt/Skill
preparation, inline Binding and Request Evidence commit, and local Runtime
publication. It returns the original AgentSession and canonical input record
for the Product's existing slot/binding owner to adopt. It does not replace a
Product slot, invoke normal prompt, dispatch a model or retry any stage.
Current admission is required before Writer acquisition and is rechecked after
acquisition and throughout the existing owner entries. Current epoch/effect
settlement is required after graph preparation, after input preparation and by
the original publication owner. Its callback cannot return a truthy receipt or
an unawaited coroutine as admission.

Before intent or Runtime effects, the admitted Writer rejects an existing
physical record identity and a known logical input ID on the selected Session
ancestry. A regression first demonstrated that a new Plan and new physical
record ID could otherwise duplicate an already saved logical input. The new
fence requires recovery lookup instead; the second attempt leaves bytes
unchanged and prepares no graph. This does not implement the Hosted client
registry or absence proof for an input from another branch or service restart.

After definite commit, the coordinator delivers the original full-record
digest as a native input lookup query. The same identity is available from the
original staged record on an unknown commit outcome, and from the original
committed record after a post-commit failure. This data is not permission,
Runtime readiness or model-outcome evidence. A receiver failure does not cause
redelivery, input replay or publication. A fresh bounded native history read
and original model-outcome observer recognize the exact persisted input while
conservatively leaving its model outcome unknown.

Failure disposes the undelivered original Session/Manager, retaining committed
history and cancellation semantics. If that cleanup fails, the coordinator
fences the original Transcript factory and raises a cleanup-debt exception
that retains the original owner and both failures. Its retry entry calls that
same owner's disposal; it does not create another Writer or reopen the factory.
The Product root must retain this debt and close/restart its affected owner.
Pending draft display, adoption, event delivery and retry disposition remain
with the upcoming Embedded/Hosted callers.

The coordinator fixtures use a real native interactive permission confirmation,
owned persistent Writer, current standard composition and actual Skill bytes.
They cover pre-Writer denial, graph/read revocation, cancellation, unsettled
effects, fixed-ID native UOW verification on unknown ACK, post-commit publication
revocation, identity receiver failure and cleanup debt. Current epoch settlement
is still a test validator. Default Embedded/Hosted callers, actual live actor
and Policy/epoch owners, background scheduling/cache/performance, release
compatibility and final delivery remain required; Goal and Issue #696 remain
incomplete.

Validation: twenty non-live coordinator and native permission-binding cases
passed. Initial entry absence, unretained cleanup failure and duplicate logical
input cases were demonstrated before their fixes. The duplicate fixture's
initial Writer assertion was corrected to recognize the already closed prior
Writer before confirming the new candidate. Scoped mypy, Ruff and all nine
documentation checks passed.

#### Bootstrap cleanup debt retains the complete candidate

The Resume bootstrap's final-admission failure now shares the same Coding
cleanup-debt contract as the continuation coordinator. If the original
constructed AgentSession cannot be disposed, the debt retains that exact
Session, the admission error and cleanup error, and fences its original
Transcript factory. Retrying disposal through this owner preserves graph,
Product and Writer ordering. This is a complete constructed-candidate case;
partial constructor failures still use their original preparation custodians.

The continuation coordinator passes an existing bootstrap debt through without
disposing its Manager separately. A real standard-composition fixture revokes
native interactive confirmation immediately after original construction,
injects one native disposal failure and verifies that the Manager has not been
disposed before the retained Session's cleanup retry. No graph preparation or
UserMessage commit occurs in that case. The existing later-publication cleanup
failure uses the same contract. Product-root debt retention and default
Embedded/Hosted adoption remain required.

Validation: the new bootstrap failure was reproduced before the fix. Nineteen
non-live bootstrap/coordinator regressions passed, followed by both nested
bootstrap and later-publication cleanup-debt cases. Scoped mypy for all three
source modules and Ruff passed.

#### Native application Root retains preparation and delivery

`AgentSessionRuntime.prepare_resume_continuation` now uses the original Root's
owned Transcript factory and Product application selection. Product borrowing
occurs after the current admission and definite intent commit. Resume Bootstrap
rechecks admission after borrowing and retains the original unbound factory or
complete Session cleanup route on failure. Session disposal releases its native
Product runtime lease without closing the application's epoch owner. Ordinary
Session construction shares the same borrowing helper and retains its existing
unsettled-Resume rejection.

The Root prepares an original `PreparedSessionLifecycleOperation` through its
existing lifecycle runtime. The returned `CodingRuntimePreparedResume` exposes
Root-owned `consume` and `abort` operations alongside the canonical committed
input lookup identity. It does not submit a normal prompt or dispatch a model.
Its candidate is bound to the original runtime host before delivery to the
caller, so the native model transport's current-Session predicate rejects it
before the original lifecycle installs that exact Session in the Root slot.
Current admission also checks the previous slot until the native operation's
delivery marker, and the exact candidate slot after that marker. A changed slot
invalidates preparation or delivery.

Preparation and delivery tasks remain Root-owned through cancellation. Root
close first fences admission, cancels and joins those tasks, then aborts native
undelivered operations and retries retained complete-candidate cleanup debts.
Failure to settle a candidate prevents closing its dependent Transcript and
Product factories; the same original operation or debt remains available to a
later Root close. Native lifecycle disposal uses its original post-shutdown
entry, while coordinator cleanup retains the original Session disposal entry.
The native lifecycle still owns current Session replacement and retirement.
If retirement of an already delivered Session fails, Root close also stops
before dependent factory close. The original lifecycle retains that retirement
for the next close attempt; Product epoch guards remain defense in depth.

Regression fixtures use real owned Writers, native lifecycle operations and
interactive permission facts. They cover exact Session delivery, pre-delivery
model ownership, committed input identity, abort, changed current slot,
cancellation during preparation and delivery, confirmation revocation before
delivery, failed Host binding, failed native abort, delivered retirement failure
and retained cleanup debt.
Effect-settlement callbacks in these fixtures validate orchestration only.

This is an explicit Root entry. Default CLI/TUI and Hosted callers have not yet
been switched to it; actual current actor/policy comparison and external effect
settlement remain mandatory production work. Caller-supplied construction
options, Worker support and released-version provenance still need their full
delivery acceptance evidence. Issue #696 and the full Goal remain incomplete.

Validation: missing Root preparation was demonstrated before implementation;
the delivered-retirement fault demonstrated a dependent Product close attempt
before the ordering fix. Forty-three non-live Root, continuation, bootstrap,
history and Product revision regressions passed. After the retirement fix,
all eleven Root scenarios and four existing owned-runtime cleanup cases passed
(15 tests). Scoped mypy, Ruff and nine documentation checks passed.

#### Root first input executes through the original Model Input transport

`CodingRuntimePreparedResume.run_first_input` delegates to the original
Session's committed-input entry only after its native lifecycle operation was
consumed and the Root still holds that exact Session. A closed Root, an
undelivered operation or a replaced current slot is rejected before the native
dispatch claim. This leaves an undelivered candidate's committed input and
dispatch claim unchanged. The UI can complete native delivery and rebind its
presentation before calling this separate entry.

The existing native Session owns the Host claim, Model Input snapshot and
transport barrier, once-only dispatch, and cancellation. The Root entry does
not submit a normal prompt, append another UserMessage, create a second model
loop, or provide automatic replay after failure or uncertainty. Current native
permission confirmation and mandatory effect-settlement checks remain active
at the original transport boundary.

Real owned-Root fixtures register an original AI API adapter and invoke prepared
transport. They verify the committed input and lookup digest, exact legacy
Header preservation, one main input snapshot, the original model outcome, and
no duplicate user append or transport invocation. Revocation before dispatch
prevents snapshots and transport; revocation after snapshot commit prevents
transport while retaining that snapshot. Provider uncertainty and cancellation
prevent another invocation of this input. An `observed_failed` native model
outcome records local invocation failure; it is not proof of absent remote
effects or a replay grant.

Standard-composition fixtures modify Skill or AGENTS bytes after pure history
preview. The actual provider request uses the current bytes. Skill Request
Evidence carries the current content digest on the same fixed UserMessage,
while the original Header and Session identity remain unchanged. These tests
exercise the explicit Root entry; default CLI/TUI and Hosted startup, actual
current actor/policy comparison, external effect recovery and background
performance remain incomplete.

Validation: the missing Root first-input entry was reproduced before the fix,
after correcting the fixture's native API registry cleanup call. All nine
non-live prepared-transport scenarios passed, including current Skill/AGENTS
bytes and exact original Header checks. Scoped mypy, Ruff and nine
documentation checks passed.

#### Explicit history screen binds the original Resume lifecycle

`build_coding_resume_history_screen` presents the selected native history through
the existing screen application and transcript projector without creating an
Agent, acquiring a Writer, or preparing model input. Quit does not activate the
Session. The first continuation input calls the supplied current-admission
preparer, consumes the original Root lifecycle operation, installs the persisted
history, subscribes to the exact delivered Session, and invokes the original
committed-input transport. It does not echo or append that input again.

The original Root now offers a transient history-view intent scope. Before
Writer preparation it checks the displayed canonical target, Session identity,
selected ancestry and source digests against the preparer's plan. Its current
view callback also fences a closed or cancelled display through native delivery.
This scope adds an intent restriction; it grants no actor, permission, epoch or
effect authority. Original current-owner checks and Writer freshness checks
remain mandatory. After native delivery the original current-Session and actor
checks govern subsequent inputs.

A regression initially demonstrated that checking the target only after
preparation allowed a faulty preparer to commit input to another history file.
The Root restriction rejects that mismatch before either file changes or a
Product owner is acquired. A preparer that swallows cancellation before entering
the Root is likewise rejected after the history screen closes. Subscription
failure disposes the delivered Session through the original Root; cancellation
and pre-delivery failure abort the original prepared operation. Retained cleanup
debt remains with its native owner.

The screen retains canonical input lookup data for uncertain commits and refuses
another preparation or normal prompt after a failed first continuation. This is
not a recovery or replay grant. Fixtures exercise original native Writers,
interactive confirmation, Root lifecycle and model transport. Their effect
callbacks validate orchestration only.

This entry is explicit and requires the caller's original approval surface and
current-admission preparer. Default CLI/TUI startup and Hosted/LMUX routing,
production actor/policy comparison, external effect settlement and recovery,
background invocation/cache/performance, and released-version acceptance remain
unfinished. Issue #696 and the full Goal remain incomplete.

Validation: the combined run passed 78 history, Root, transport, import and
transcript regressions; its two failures identified the new module exceeding
the existing UI manifest and adapter budget. The product interaction entry was
moved to `coding.interaction`, preserving both gates. All eight history-screen
scenarios and both previously failing gates then passed (10 tests). Scoped
mypy, Ruff and nine documentation checks passed. The cancelled-view fixture was
also corrected after its erroneous branch had left a test waiting without
issuing cancellation; no Product timeout or sleep was added.

#### Resource owners share matching in-flight Workspace scans

The existing Resource preview task scope now finds matching running computation
across loader scopes on the same event loop. The key retains Workspace, subject,
policy, exact captured Resource input state and work budgets. It shares no
Future across event loops and caches no completed value. Distinct package read
handle identities remain separate rather than assuming equal authority from
equal paths or digests.

Each original scope retains its own references and native completion route.
Closing one scope fences that scope and joins actual computation/pin settlement;
an open peer's reference prevents cancellation of the shared job. Cancelling
one waiter releases only its reference. Foreground peers promote the same
native job. The process-wide admission bounds remain eight jobs, six background
jobs and two native workers; all shared scopes together have at most 64 waiting
references per job. Registry entries disappear on actual native completion;
they are neither a second lifecycle owner nor an authority cache.

Regression-first tests reproduced duplicate computation by distinct loaders.
The fixtures also corrected a scan counter that had counted their independent
synchronous verification read. Five cross-loader cases now cover shared work,
creator close, single-waiter cancellation, policy isolation and subject
isolation. All 34 Resource scheduler and Coding Plan regressions passed. Scoped
mypy, Ruff and documentation checks validate this increment. Production
background invocation, completed-value freshness/cache design, broader package
deduplication and cold/hot performance acceptance remain unfinished.

#### Runtime selection rechecks the original Product Workspace/epoch witness

`AgentSession._require_current_coding_runtime_selection` now rechecks its
original factory-issued Workspace witness before inspecting Plugin selections.
The witness calls the original factory's Workspace identity check and retained
native Product epoch owner's current-root/cutover checks. It runs for minimal
composition too, where there may be no selected Plugin manifest to trigger a
Product check. No detached composition receipt or historical Binding replaces
this live owner check.

Fault injection first demonstrated that replacing the actual Workspace inode,
with Transcript storage outside that Workspace, still allowed first-input
transport. Replacing the actual native epoch control root also allowed
transport. Both now fail before a dispatch claim or Model Input snapshot. The
fixture restores the original directory before native cleanup, preserving the
same original owners and testing their real filesystem checks.

A further case replaces the epoch control root immediately after the native
Model Input snapshot commit. The original transport barrier rejects the new
root before provider invocation, retains the committed snapshot and blocks a
second first-input dispatch. It grants no replay after restoration. Nineteen
Root first-input/history-screen cases and this additional transport-barrier
case passed. Scoped mypy, Ruff and documentation checks passed.

This closes a live Product identity gate; it does not compute current actor or
permission differences, prove Plugin/Worker external effect settlement, or
derive the activation attempt's production epoch fingerprint. Those owner
producers, default CLI/TUI and Hosted routing, recovery and the remaining
background/release/performance acceptance are still required by Issue #696.

#### Resume permission confirmation binds the observed execution scope

The original Harness Authorization module now compares native execution scopes
without issuing authority. It identifies readable/writable expansion, weaker
network restriction and removed denied subtrees, including partial removal of a
denied subtree. Entirely denied current roots and baseline denials outside the
current scope do not falsely count as expansion. An absent baseline is unknown.
Inputs are bounded to 64 roots per field. These are abstract scope comparisons;
historical restrictions and a non-widening result grant no current permission.

The existing Coding Resume request can bind this native scope and its observed
baseline. It adds the owner-computed expansion codes without dropping other
unknown-authority codes, and includes reviewable current scope data plus bounded
scope fingerprints. Scope serialization is capped at 16 KiB; the combined code
budget remains sixteen. The original Approval owner still issues and rechecks
the exact fact. A scope-bound borrower must receive the current native scope at
every revalidation; omission, changed scope, rebound wrapper fields or native
revocation rejects the borrow. No approval store or journal was added.

The original Process launcher now exposes its frozen execution-profile ceiling
as data. Root first-input fixtures compare the confirmed native Workspace scope
with this actual original gateway ceiling and recompute the current Workspace
scope at every admission boundary. The initial assertion against Sandbox
ExecService was corrected: when Sandbox is disabled that service's profile can
be absent, even though the original process authorization gateway retains its
ceiling. This evidence does not establish OS containment or external effects.

The missing Authorization comparison and scope-binding request were reproduced
before implementation. Native Approval fixtures cover changed readable,
writable, network and denied scope, omitted current scope and revocation. Root
transport fixtures use the real native gateway, Writer, fact and transport.
Default CLI/TUI and Hosted actor/Policy producers, trusted configuration proof
reuse, formal effect settlement, recovery, production background invocation and
release/performance acceptance remain incomplete. The full Goal remains active.

Validation: the combined Authorization/confirmation/Root run passed 41 cases,
including all twelve actual first-input transport scenarios. After adding nested
denial and bounded-root/byte cases, all 33 Authorization and confirmation tests
passed. Scoped mypy passed four source files; Ruff, diff whitespace and all nine
documentation checks passed. Effect-settlement callbacks in the Root fixtures
still validate orchestration only.


#### Resume confirmation observes native current Policy inputs

The original native PolicyEngine now exposes a bounded fingerprint of its
ordered rule configuration. It limits each rule field to 256 entries and the
encoded document to 16 KiB. The original PermissionProfilePolicyEvaluator
combines this observation with the current requested/effective profile and
native ceiling. These hashes describe configuration dependencies; they grant
no actor admission or Tool authority and identify neither executable code nor
external effects.

The native Workspace selection already read live permission profiles and
ceilings, but retained managed rules from selection time. A regression first
showed that a newly configured blocked Bash rule changed a fresh selection
while the existing native evaluator kept its old fingerprint and behavior.
The default selection now reads managed rules from the same settings owner
for observation and evaluation. The selected evaluator honors the new deny.
Injected custom policy factories keep their existing contract and require
an owner-specific observation entry rather than inferred native identity.

Coding Resume may bind this native Policy observation in the original Approval
request. Revalidation requires explicit current native Policy inputs and
rebuilds the exact request for the issuing resolver. Changing the profile,
changing managed rules, omitting current Policy, or changing configuration
while the native confirmation awaits rejects the old fact. A hash alone does
not replace the existing actor, execution-scope, Product or settlement gates.

Root first-input fixtures pass the actual selected native evaluator to the
original candidate factory and observe fresh Policy through the same native
settings entry at each admission boundary. A real settings profile change
before first-input dispatch prevents a snapshot and provider call. Adding a
managed deny immediately after the native snapshot commit prevents provider
transport, preserves that snapshot and rejects a second dispatch. Existing
Workspace/control-root, skill/AGENTS, revocation, cancellation and transport
outcome cases remain covered with the original owners.

Validation: 117 Root first-input, PolicyEngine and Workspace-profile cases
passed, including fourteen Root transport scenarios. Ten existing Workspace
tool/selection cases passed. Native Policy and confirmation tests also cover
waiting-period changes and missing current inputs. Full production actor and
epoch/effect producers, default Embedded/Hosted routing, recovery, background
invocation/cache/performance and released provenance acceptance remain
incomplete; the full Issue #696 Goal remains active. The Root fixture's effect
callback still verifies orchestration only.


#### History-screen failure recovery reads the original saved input

The explicit native Resume history screen now uses its retained exact input
lookup query to re-read the discovered target through the original Root history
entry after first-input failure. It verifies the original Header and selected
ancestry prefix before projecting the native Model Input/Outcome observation.
Confirmed saved-input presence refreshes the displayed persisted history, so a
failed event subscription or revoked confirmation no longer leaves a committed
first input invisible. No replacement Agent, Writer, lookup journal, model
request or approval fact is created.

The display distinguishes an unknown model result from a recorded terminal
outcome. A recorded failed call is historical evidence, not proof that a
provider performed no external work. Missing input remains unknown; it does
not prove non-commit. Identity conflict, unreadable/stale source or changed
history cannot authorize retry. Subsequent prompt submissions remain fenced
and do not append another input or dispatch again.

A native first-input failure that leaves execution unavailable now releases
its active Slot through the original Root after observation. Exceptions also
release the native prepared operation or active Slot if the recovery read is
cancelled again. The native Root retains its cancelled history reads until
settlement. A new fault injection pauses after the actual native read and
cancels the observation, then verifies the original Slot is gone.

The existing eight screen scenarios passed as baseline. The regression first
failed because revoked confirmation had no recovery observation. Added cases
cover an actual provider transport failure and cancellation during recovery.
This closes failure presentation and read-only observation in the explicit
screen entry. Default Embedded/Hosted routing, production actor/epoch/effect
inputs, restart reconciliation and admitted retry, background performance and
released-version acceptance are still required; Issue #696 remains active.

Validation: the combined screen/Model Outcome run covered 28 cases, with 25
passing and three failures caused by the test using `ErrorRecord.text` rather
than its native `summary` field. After correcting that assertion, all three
failed scenarios passed in the focused rerun. Ruff, scoped mypy, diff whitespace
and all nine documentation checks passed. The branch-wide `make plan-checks`
was inspected; its broader subsystem and platform gates remain delivery work,
not evidence supplied by these focused runs.


#### Native Hosted controller subject observation and exact confirmation

The original AppClientScope now observes the current Resume subject using its
own attachment/controller/member checks and the original canonical Session
owner. Its synchronous revalidation includes the Session's accepting state.
The fingerprint carries the selected execution application's native application
and service-instance identities, attachment generation, member, canonical
Product/continuity/Session and scope. Encoded data is bounded to 4 KiB; an absent
native execution instance is explicitly unavailable. No execution port is
selected, no execution binding/reservation is created and no Product callback
runs during observation.

Coding's permission request may borrow this exact native scoped owner and
control. The native owner requires the activation attempt's Session to match
the actual controlled Session before issuing a request. The owner selection
is itself bound into the exact request, so stripping those wrapper references
changes the original Approval request and cannot reuse its retained fact.
Revalidation consults the same live native controller before the original
Approval fact. Closing a scope, controller takeover while confirmation awaits,
wrong target, or a closed canonical Session rejects the borrow. Embedded
confirmation does not import Hosted owners merely to take its unbound path.

The original scope tests passed 23 baseline cases. Missing subject observation
and revalidation entries first failed two regressions. Native owner fixtures
then cover foreign scopes, takeover, closed scopes, Session close before mapping
removal, unavailable execution identity and zero execution binding. Cross-owner
fixtures use the original AppService scope and Approval resolver, covering
current confirmation, wrong Session, takeover before/after confirmation and
removing owner references. These tests observe actual native controller state;
their injected Hosted Product ports do not establish full Coding activation or
external-effect settlement.

This supplies a production Hosted subject producer and its exact confirmation
borrower. Wiring the default Hosted submit path and Embedded actor producer,
production epoch/content/effect settlement, restart reconciliation, background
invocation/performance, released compatibility and delivery gates remains
required. The full Goal and Issue #696 remain active.


G11 architecture validation also exposed an impermissible new direct
AppService consumer and branch-wide reviewability budget excess. The concrete
subject borrower now lives at the existing optional Coding Hosted execution
bridge. Default lookup remains on the ordinary Hosted binding path and does
not import or select optional execution. The original AppService Session owner
keeps accepting checks before and after lookup; its closed Product-result
validation uses the existing optional port module. Coding's existing catalog
and binding modules host their own pure identity/lookup/binding validation,
while the public adapter methods and original owners remain in place. No
budget limit was raised, authority owner split, new file hidden or wire shape
changed. These placements restore the existing G11 bridge and budget gates.

Validation: 62 controller/execution/confirmation cases passed before boundary
placement checks. Those checks identified the bridge and budget failures above.
After the adjustments, 113 confirmation, AppService controller/execution,
Coding adapter/catalog/execution and G11 cases passed. The final ordinary
lookup helper placement was separately revalidated by 67 confirmation,
adapter, scope and G11 cases. Scoped mypy passed all eight affected source
files; Ruff, whitespace and documentation validation passed. These focused
results do not discharge the branch-wide delivery and platform gates.

#### Native accepted execution task carries the current Hosted subject

The selected scoped submit route now borrows the original AppClientScope and
control at admission. The existing registry creates its accepted task in that
context and continues to own submission deduplication, execution and settlement.
The stable submission ID follows that same task; the registry-backed legacy
turn route carries no invented ID. The caller resets its borrow in `finally`.
Every Product getter revalidates the original live controller. A replacement
controller can inspect the original execution ledger without restarting work;
the old task cannot use its stale borrow for Resume confirmation.

A regression crosses actual native scope admission, execution registry and
guard task into the original Coding Approval resolver. Its activation attempt
uses the captured stable submission ID as request identity. Native takeover
then rejects the exact retained confirmation. The injected Product and attempt
leaf/epoch data remain fixtures: this does not establish default writable
history activation, production epoch/effect settlement or restart safety.

G16 scope reviewability required moving optional functions into the existing
Resume port module and binding them to the same original scope instance.
Controller/session tables and lifecycle checks remain with their original
owners. Local record profile selection is now a pure projection in the
existing closed profile algebra; record authentication and wire fields are
unchanged. No architecture budget was raised or test bypassed.

The combined controller/execution/confirmation, local-record and G11/G16 run
passed 113 cases and failed the local-record line budget while import placement
was still being adjusted. The final placement is checked separately below.
Scoped mypy passed eight source files. The broader Coding Wave A gate also
exposed a remaining G14 slice excess (1,854 lines against 1,516); it remains
delivery work. Default Embedded/Hosted routing, production activation inputs,
background invocation/performance, released compatibility and full delivery
gates remain required. Goal and Issue #696 remain active.

Final local-record/G16 revalidation passed all 41 cases after correcting the
profile module import (the intermediate facade import failed collection).
Ruff and the nine static documentation checks passed. The optional Coding
subject functions now share the existing execution-work bridge and retain
their public imports from `hosted_execution`; both existing files count in
the execution slice (248 and 133 lines, total 381 within 400, each within 250).
This placement adds no execution owner or default composition import.
After that final placement, all 70 scoped execution, Coding confirmation,
native Coding execution and G11 cases passed. Scoped mypy also passed the
three relocated/import-adjusted sources. G14 remains the identified failing
Wave A gate; the execution slice itself stays within its existing limits.

#### R2.1 Hosted slice accounting and broader AppService validation

The previous G14 aggregate limit was measured against its pre-Resume scope.
Reviewing the actual diff against control `main` at `2cb18a0b` identified
catalog +191 and Session binding +147 lines, with the Hosted CLI unchanged.
These are the detached history claim/factory path, bounded display, fenced
history/outcome and input observation, and narrow canonical/data validation.
Their placement retains the original catalog, factory and Session owners.
Moving these functions solely to evade a slice budget would obscure that
ownership. The existing G14 architecture document now records this exact
338-line increment. Wave A keeps its file partition and adds individual
catalog/Session/CLI ceilings alongside the 1,854-line aggregate ceiling.
Other budgets and dependency gates retain their existing limits.

The current Wave A test first failed on the measured 1,854/1,516 mismatch.
After the accounting change, combined Wave A, G11/G16 and native Hosted
catalog/Session/adapter regressions passed 57 cases, with one platform skip.
Ruff and nine static documentation checks passed. This closes the identified
G14 accounting gap, rather than claiming completion of the remaining default
Resume, effect-settlement, background/performance or release requirements.

The complete AppService quality target passed every Ruff invocation and mypy
over 94 source files. Offline uv initially lacked build-system cache, so the
gate uses the existing virtual environment with `UV_OFFLINE=1 UV_NO_SYNC=1`.
Its first test collection selected that environment's control-lane editable
source and failed 17 collections. Re-running the test phase with explicit
`PYTHONPATH=src` selects this task branch. The command retains `-m 'not live'`
and `--skip-host-runtime`; that full test phase is still running at this
checkpoint. It must reach a terminal result before being reported as passed.

That full AppService test phase finished with 2,439 passes, 16 skips and two
failures after 1,323 seconds. Both failures were the G17 opt-in collection
regression's isolated `python -I` subprocess: its older editable installation
could not import this branch's new Resume comparison module, pulled in at
module load by a reused catalog test fixture. The comparison import is now
local to the Resume regression that uses it. The collection test retains
`-I`, its root-only test path and explicit opt-in assertions; installed native
evidence still requires a wheel and rejects source imports. All 39 G17 runner
and Hosted catalog cases then passed, including both failed collection cases.
Ruff and whitespace checks passed. The original full run is recorded as
failed with those focused repairs verified, not as a new full green run.

#### Original selected Product epoch read-only dependency

The original POSIX and Windows Package Product epoch owners now observe
their current native fence through their existing pinned-root validation.
The observation explicitly disables journal repair and creates no runtime
lease. Existing `assert_current` and formal admission keep their prior behavior.
Coding's original application selection hashes that existing observation and
canonical workspace into bounded dependency data (8 KiB encoded ceiling).
It rechecks the same native fence after encoding. Missing selection and an
application fence are unavailable; no factory is selected to answer a read.
No new owner, registry, planning queue or authority journal was added.

This supplies an actual selected-epoch input instead of a fixture constant.
It supplies neither content closure nor subject/Policy/effect settlement.
First Resume in an application with no selected Product epoch still needs
its production owner input route. Default Embedded/Hosted activation and the
remaining release/performance gates remain required; Goal and #696 stay active.

The original Resume/epoch guard baseline passed 13 cases. The new regression
first failed on the missing original selection entry. Its initial write
sentinel replaced `os.open` without preserving the real `dir_fd` capability
declaration, so native capability detection correctly refused execution.
The forwarding sentinel now retains that declared capability while forbidding
write/create/truncate/append opens. The real selected Linux epoch observation
then passed: stable data, unchanged file set/mtimes, unavailable foreign
workspace and fenced selection, and corrupt tail rejection without repair.
Native Windows execution remains a platform validation requirement. Scoped
mypy passed the three changed sources; Ruff and whitespace checks passed.

Final Resume/epoch guard validation passed all 14 cases, including the added
native-owner close rejection. Two real POSIX Product Session composition
cases passed with and without a dependency, verifying the original formal
epoch/lease path. All nine static documentation checks passed. The broader
Coding offline gate started at `c81953e2` remains running; these changes still
require the final tree's broader delivery/platform gates. They do not establish
default writable Resume or effect settlement.

#### Original Root enforces its selected native epoch

The original Root's Resume admission now compares the attempt epoch with
its original Product selection's read-only native observation. The existing
admission callback path carries this check through Writer preparation,
input commit, runtime publication, delivery and model transport. A missing
or fenced selection refuses before acquiring the Writer. An unequal epoch
raises `input.epoch_changed`; caller permission and effect settlement remain
independent mandatory checks. The check cannot create a selection or lease.

Regression fixtures now explicitly select a real native owner during their
startup setup and release that setup Session's original runtime lease before
display. They obtain the attempt digest from that owner instead of `a` repeated
64 times. The display preserves the selected owner mapping. First Resume with
no selected owner remains unavailable until the production application input
route is implemented; this does not establish default CLI/Hosted wiring.

The original model/UI completed baseline passed two cases. The new three-case
red run demonstrated that unequal and unselected epochs were accepted, and a
fenced selection was rejected only after intent commit. The corrected Root
refuses those cases before Writer work. Two latest native model cases passed:
the committed Binding contains the observed epoch and fencing the original
selection after delivery prevents dispatch claim and transport. Scoped Root
mypy, four-file Ruff and nine static documentation checks passed. The combined
Resume/UI run finished with 29 passed and ten UI failures in 476.84 seconds.
All ten stopped at an obsolete fixture assertion requiring an empty selection,
after startup had explicitly selected the real native owner. That assertion
now requires equality with the startup owner mapping, including wrong-target
rejection. The entire ten-case UI rerun passed in 120.95 seconds. Together
with the 29 passing lifecycle/model cases and the latest two model cases
(one repeats completed), this covers 40 distinct affected Resume cases.
The earlier broad Coding run remains pending and cannot establish a final-tree
green gate. Native Windows, default Embedded/Hosted activation, actual effect
settlement and release/performance acceptance remain outstanding.

#### Formal first-Resume epoch preparation through the original selection

`CodingFencedProductApplicationSelection.prepare_resume_epoch` now uses the
original workspace initialization/recovery/selection body also called by
ordinary `factory_for_session`. That body was extracted under the same
selection lock; unsupported-platform, fresh cutover, interrupted bootstrap,
external-binding replacement and retained-owner behavior remain there.
The formal entry requires canonical existing workspace data and synchronous
current caller checks before and after selecting. It returns the read-only
native epoch digest without selecting a Session factory or issuing a runtime
lease. No owner/registry/queue or durable journal was added.

This is a formal, potentially durable activation operation. It is not a
history/background read and cannot be used as actor/Policy or effect-settlement
proof. The initial refusal has no writes. A refusal after selecting leaves the
original owner retained by the original selection for close; it does not erase
durable native Product preparation. Production caller authority and default
Embedded/Hosted first-input invocation still need wiring. The original Root
continues to refuse missing/fenced or mismatched epoch before Writer work.

Baseline native observation passed one case. Four new regressions first failed
on the missing preparation entry. Seven cases then passed: admitted, denied,
invalid check and post-selection revocation; native read-only observation;
ordinary fresh Session bootstrap and interrupted-bootstrap recovery. The
original native registry's quiescence receipt proves zero active Session
leases after formal epoch preparation. A later five-case run repeats the four
formal cases and adds actual original Root preparation/commit/consume after
pure history, with no temporary Session. That run passed in 19.72 seconds.
The caller admission callback in that test is an orchestration fixture, not
production subject/Policy proof. Scoped mypy and Ruff passed.

The broad Coding run started at `c81953e2` terminated after 954 passed,
45 deselected and one failure in 2042.37 seconds. The failure was
`test_real_parallel_review_uses_non_persistent_coding_children_and_full_fan_in`,
at fixture `attachment.write_text`, with `OSError: [Errno 28] No space left on
device`. Its managed scratch had used `/run/user/1001`, a 164 MiB tmpfs.
Normal managed cleanup freed that run; the mount was then 2% used. The exact
failed case passed separately (one passed, eight deselected, 36.28 seconds).
This does not establish a full Coding gate. The final-tree rerun will use the
supported `LOUSHANG_RUNTIME_DIR` override outside Git on the workspace disk,
with the same managed scratch owner, offline selectors and host-runtime skip.
No Product workaround or manual deletion of another run is needed.

#### Default Embedded Root/Approval subject dependency

The default primary CLI builder now binds its actual original Root and native
Interactive Approval owner once before any Session is created. The original
Root supplies a bounded domain-separated digest of that live object custody
from its current native history input scope, checking the original current
view callback. It neither infers actor authority from configuration nor creates
an actor ledger. The native Approval owner observes its existing open lifetime
without issuing a grant. Delegated invocation profiles, custom runtimes and
custom resolver types do not receive this default binding.

The Root's admission now independently rejects an attempt with a subject other
than this original binding before Writer acquisition and on subsequent native
checks. The permission request and retained native confirmation bind
`coding.embedded-root/v1` plus the exact attempt and require the same original
Root and Approval owner. An old confirmation cannot remove that binding,
substitute another live Root/owner/actor or survive owner/Root close. A digest
is observation data, not authentication, Policy, Sandbox or effect-settlement
proof. The complete first-input/default history coordinator still needs its
production current owner checks and native effect settlement. Hosted continues
to use its original scope/controller and does not gain an Embedded binding.

The original Approval/Hosted baseline passed 28 cases. Seven initial Embedded
regressions failed on the missing native Root entry. The first implementation
passed all 35 cases. The expanded subject plus default-builder run passed
47 cases, including foreign Root, removed binding and revoked current view.
The final subject suite passed 39 cases, including a real default CLI Root
whose permissive external callbacks cannot submit an arbitrary subject to the
Writer. History bytes and the selected Product mapping remain unchanged during
subject/confirmation observation. The native 15-case first-model suite now
uses the original Root/Approval subject and native epoch instead of fixed
subject/epoch fixtures; all 15 passed. Effect settlement remains explicitly a
fixture in that suite, not a production settlement proof. The latest mandatory
Root admission checks passed four focused model cases (completed, revoked,
revoked at the transport barrier, Root closed) in 36.47 seconds. Three
changed owner sources passed scoped mypy; six changed Python files passed Ruff
after sorting a newly added test-local import. No new ownership placement or
release scope is claimed by these implementation observations.

The Coding gate with scratch below the workspace terminated at
`test_runtime_lists_all_session_summaries_across_session_dirs`. The native
Writer's original ancestor validation correctly rejected the group-writable
workspace ancestors (`lsspace` and `.test-runtime` had mode 0775). The same
focused case reproduced `transcript_writer:unsafe`; no safety selector or
Product validation was changed. The supported runtime override was instead
set to `/home/dev/.cache/loushang-pytest-resume-696`: its user-cache parent has
mode 0700 and the filesystem had 5.7 GiB available. The exact focused case
then passed (one passed, 88 deselected, 52.28 seconds). The next final-tree
Coding gate must use that managed scratch root; previous runs do not prove
a full final-tree green gate.

#### Current admission at native Product recovery boundaries

Formal epoch preparation now carries its original caller check through fresh
cutover/builtin bootstrap, existing-epoch retry/open and replacement selection.
The original Product state owner checks before creating its state root and
publishing backup topology. The original management service independently
checks before coordination, after the GC gate and before the management lock,
before loading/replaying its journal and before each pending operation.
Synchronous checks must return None; invalid/asynchronous callbacks cannot
serve as admission. Ordinary callers that supply no new check retain their
existing preparation path. No new Saga/authority journal, lease or owner was
introduced.

An initial implementation incorrectly passed the formal check through the
existing `before_recovery`/`before_replay` input. Those inputs also forbid
creating new coordination files and backup topology. That trial failed four
cases on a missing fresh GC lock (five passed). The corrected implementation
uses a separate `require_current_admission`, preserving the original
existing-store creation policy. The callback checks current owner state; it
does not prove content closure or settle external activation/Worker effects.

The four original formal preparation cases passed as baseline. Two new native
fault cases first failed: closing the actual Approval owner immediately before
state opening still allowed two original management recoveries, in both fresh
and existing B routes. With the corrected checks those cases refuse before
state creation/recovery, preserving the existing state-root presence and exact
file bytes. The nine-case preparation/bootstrap/Root-input run passed in
101.02 seconds. The strict-check rerun passed the same nine cases in
84.57 seconds. A further actual native GC-gate fault then exposed a second
window: revoking the original Approval owner after acquiring the backup GC
gate still changed backup state bytes. The original backup owner now rechecks
formal admission inside that same gate immediately before reading/publishing
topology, while retaining `before_load`'s original creation policy. Its final
ten-case preparation/bootstrap rerun passed in 92.68 seconds. Four changed
owner sources passed scoped mypy and all six changed Python files passed Ruff.
All nine static documentation invariants passed.

The original management crash-after-desired-state-commit regression now covers
ordinary recovery, admitted recovery, revocation after loading the pending
operation, and an invalid check return. A refused recovery preserves exact
desired-state and operation bytes, leaves the original operation running, and
appends no fabricated terminal fact. All 16 management service cases passed;
the final management-lock boundary rerun also passed all 16 in 2.90 seconds.
Three changed owner sources passed scoped mypy, and five changed Python files
passed Ruff after sorting one local test import and replacing an assigned
lambda. The default Embedded first-input coordinator, native effect settlement,
Hosted writable route, platform/release/fault/performance matrix and delivery
remain outstanding. The Coding gate started at `294e225f` is still running;
it cannot prove a complete gate for these later source changes.

#### Original selection callback reentrancy

The four formal preparation cases passed as the focused baseline (24.84
seconds). Three subprocess regressions then failed in 146.20 seconds: observing
the original epoch or fencing from the admitted callback deadlocked on the
selection's ordinary lock; the first callback also admitted a nested factory
and its real Session lease before selection began. Subprocess isolation bounds
those actual synchronous deadlocks without abandoning a thread or adding a
Product timeout.

The original selection now uses a reentrant lock and a private in-progress
flag. Native epoch observation can reenter that original owner. Nested factory
selection, formal preparation and close refuse before changing the owner. The
initial check, selection and final observation share the same scope; its flag
is cleared on every exit. Callback fencing is rechecked immediately. Other
threads still serialize through that same original lock, and the separate
Session factory's ordinary lock is unchanged.

The first implementation passed nine cases but failed the fencing case
(123.02 seconds). Removing the unnecessary SessionManager from the observation
and fencing probes still left the same failure (two passed, one failed,
74.25 seconds). Source inspection found that fresh SettingsManager construction
creates its original configuration transaction locks before the cutover check.
Formal admission is now also checked before that construction in both fresh
initialization and interrupted-bootstrap retry. The fencing probe requires no
home or project configuration directory to appear. The ordinary fresh-start,
interrupted-bootstrap retry and Root first-epoch input paths passed three
cases in 70.97 seconds before this extra boundary check; final verification
below includes that check.

An accidentally unscoped mypy invocation followed imported source and reported
236 errors in eight dependency files; it is not a clean package type gate.
A concurrent scoped invocation exited with status 139 without a diagnostic.
The scoped source check (`--follow-imports=silent`) passed with an isolated
cache: one checked source file, no issues. No Product code was changed to mask
the imported diagnostics. Ruff passed both changed Python files and all nine
documentation invariants passed, including the progress supplement. The
default coordinator, native effect settlement,
Hosted writable activation and release/performance gates remain outstanding.

The final focused run passed all 13 cases (35 deselected, 151.39 seconds),
covering native read reentrancy, refusal of nested factory/prepare/close,
callback fencing before configuration locks appear, denied/invalid/revoked
formal preparation, original Approval revocation at state/backup boundaries,
ordinary fresh initialization and interrupted-bootstrap retry, and the Root's
first-epoch Resume input. Native registry observations confirm no Session lease
is left by formal preparation. The still-running Coding gate was last observed
at 26%; it began before these source changes and is not final-tree gate proof.
After adding an explicit absent project-configuration directory assertion,
that exact fencing case passed again in 15.68 seconds.

#### Native published component activation checks

The original Harness Session now retains its exact prepared Capability
components and the original published graph generation. Coding Resume candidate
validation independently asks those original components for their current
activation state before first-input commit and during publication/model use.
It refuses a missing consumer, closed/changed graph, changed component tuple
or a missing/invalid synchronous component check. Original graph disposal
still owns cleanup; these retained references introduce no registry, lease,
journal or authority issuer. Ordinary graph preparation remains unchanged.
Custom components without this optional current-use check cannot be used by
this formal Resume path.

The original in-process Component Host rechecks its exact COMMITTED use through
its original decision journal, current owner/trust/Product policies and clean,
matching import realm. The original attempt is fenced when disposal starts,
before any await. A partially successful/failed disposer retains the original
value and disposer for cleanup retry but cannot claim live activation. Native
Worker Providers validate their original visible facet, admitted attempt and
current owner through the existing facet publication validator. That formal
check may issue its original owner's ephemeral facet grant, but does not send
a Worker query, start a process or become a history/background operation.
The Worker adapter test uses the original supervisor/journal/adapter with
fixture process/transport; it is not installed-native or Windows evidence.

These native use checks do not settle arbitrary external effects or correlate
all crashed historical uses with a new Resume attempt. COMMITTED means the
original activation use published; recovered FAILED remains possibly started.
The required external settlement callback is retained. The default coordinator,
unknown-effect reconciliation/disposition, Hosted writable activation,
released-artifact/platform and performance matrices remain outstanding.

The original Component Host baseline passed 14 cases in 2.89 seconds. The two
first native-use/Session regressions failed on the missing APIs (one ordinary
case passed, 48 deselected, 9.01 seconds). The first implementation passed
51 Component Host/Session cases in 10.98 seconds. Four added fault cases first
failed because their test plugin lacked its marker environment variable (62
other cases passed); correcting that setup exposed two more fixture mistakes:
owner snapshots require their original Authority constructor, and an unstarted
import lease cannot pollute a realm. The corrected four actual owner/journal/
realm faults passed in 5.31 seconds. Recovered FAILED, a missing original
journal, changed owner epoch and a genuinely started/polluted realm all refuse
without changing activation journal bytes. The final three-module run passed
66 cases in 12.48 seconds, including an original owner reader replacing the
Session's component tuple during validation, and Worker current-use validation
that sends no additional protocol request. Existing 33 deny-all Tool selection
warnings remain.

The Root first-epoch/first-model smoke passed two cases in 56.08 seconds. The
expanded actual Root model matrix passed 16 cases in 163.29 seconds. It includes
loss of the original component publication witness while the graph, receipt
and external callbacks stay unchanged: no dispatch claim or model transport
occurs, and the committed input remains exactly one record. Its external
effect-settlement callback is still explicitly a fixture.

A further actual disposer-failure regression failed in 2.29 seconds: after
partially retiring the value, the first implementation still accepted its
COMMITTED use. The original attempt now sets its retirement fence before
awaiting the disposer. Final Component Host verification includes that failure
and successful cleanup retry: all 19 cases passed in 1.65 seconds. Caller current
admission now brackets every formal native-use check in preflight, input commit,
publication and settlement. Original journal coordination/recovery and Worker
ephemeral grant validation do not run after denied admission. The local
retirement fence is not a durable external effect settlement record. A six-case
Root rerun passed in 40.36 seconds after the first admission-order correction;
the final rerun passed six cases (ten deselected) in 39.49 seconds, including
assertions that denied/revoked current admission never calls component validation.
Final scoped mypy passed all six changed owner sources with an isolated cache;
Ruff passed all ten changed Python files and nine static documentation
invariants passed.

The Coding gate started at `294e225f` terminated with 1406 passed, 11 skipped,
45 deselected and one failure in 2899.11 seconds. The installed legacy family
timed out waiting for Embedded CLI/TUI to leave its loading screen within the
existing 35-second limit. The exact failed case passed in 53.63 seconds when
run independently with the same supported private-cache scratch root, original
selectors and original timeouts. No installed source-path fallback or timeout
increase was added. That gate began before later source changes and remains
failed; neither this focused pass nor its earlier progress proves a full
final-tree Coding gate.


#### Main synchronization and exact architecture inventories

After committing native component-use checks as `04af17f8`, the issue branch
merged control `main` at `f7d18114` in `de075e70`. The six changed runtime owner
sources were unaffected by that merge. The generated package dependency diagram
check passed after the merge. This synchronization includes the main branch's
CI scope and Harness setup corrections; it does not claim final quality gates.

The full architecture run terminated, but its terminal report was lost during
context rollover. Its retained failure cache identified nine architecture cases.
An exact rerun recovered all nine failures in 88.23 seconds. The following
source-backed inventory corrections retain exact files and qualified functions:

| Boundary | Reviewed owner and correction |
| --- | --- |
| Hosted wiring | Coding's `_hosted_execution_work.py` retains native execution work and borrows the existing `AppClientScopeV1` subject; it constructs no AppServer binder. |
| Session consumers | All five typed consumers moved together from `_ensure_session_graph_prepared` to the original Session's `_prepare_candidate_session_graph`. The ordinary entry delegates to that method; the combined Provider construction site is unchanged. |
| AppServer/AppService module inventory | `resume_model.py` adds bounded optional query/result data and a negotiated read protocol. `resume_ports.py` adapts that data through the original scoped Session and borrows its current controller context. They create no execution, approval or retry authority. |
| Skill attributes | `prepare_resource_catalog_bootstrap_result` projects existing Catalog-selected Skill identities. `ResourceCatalogInputReceipt.input_fingerprint` hashes configured Skill switches and paths, without reading Skill bodies. |
| Resource cleanup | The existing loader joins preview tasks and releases original read-only revision pins through exact `aclose`, `close_catalog_preview_tasks` and `_release_catalog_preview_pins` sites. Session views close their local references through the original owner. |
| Private Catalog consumers | Existing main-branch Product preview/local-discovery adapters consume Catalog facts. The original Coding Session also consumes its immutable snapshot and fingerprint codec for Resume checks. None is a new Catalog selector. |
| Package read boundary | `PackageResourceMount.capture_text` uses its original verified revision handle with a byte budget. It remains classified as `package-resource-mount`, alongside `read_text`; no directory-level read exemption is added. |

The first correction changes inventory tests only. Runtime behavior, ordinary
read/load semantics, admission checks and external-effect settlement requirements
are unchanged. Exact unknown consumers, extra construction sites, eager body
sinks and unowned Package reads still fail their original assertions. The
private Catalog access inventory remains transitional rather than a public API
compatibility promise.


The first corrected exact rerun passed eight cases and failed the current
Hosted inventory on the additional AppService `resume_ports.py` module
(119.39 seconds). After reviewing that original-scope data/subject adapter and
adding its exact module entry, the remaining case passed in 18.16 seconds.
Thus all nine previously failing architecture cases have focused passing
results. Ten architecture documentation checks passed in 31.37 seconds; Ruff
passed the eight changed test modules and `git diff --check` passed. These
results are focused verification, not a complete final-tree architecture gate.
The next full run preserves its output outside the checkout to avoid another
lost terminal report. The full Issue remains open, including default activation,
external-effect reconciliation, Hosted writable preparation, release/version
compatibility and performance acceptance.


#### Native effect association investigation

Source review at `e072a764` confirms that native Definition/component uses and
Worker attempts retain original identities but do not record a complete parent
Resume intent association. New COMMITTED component-use checks cannot settle
older started attempts. A deterministic use-ID sequence alone would not prove
complete enumeration after changed preparation order. The candidate
[ARD-007](../architecture/decisions/accepted/ARD-007-resume-native-effect-correlation.md)
records the original-journal association option, outcome semantics, version and
retention requirements, and four specific review findings. It is proposed,
not accepted Target or implemented recovery. Existing accepted ARDs and their
current safety gates retain their authority.


#### Native Root bounded recent-history delivery

The existing `read_coding_resume_recent_page` now enters Embedded Continuity's
large-history fallback through the original Coding Root. Both complete
snapshots and bounded recent pages share that Root's two-read limit, original
source discovery/fingerprint, event-loop fence, cancelled waiter retention and
native close settlement. Recent pages remain `unverified_tail_preview`, carry
no selected ancestry, and cannot substitute for activation Plan input. This
changes the existing picker preview fallback; it does not wire the default
writable Resume coordinator or turn a tail page into a verified branch.

Root source identity is checked before native IO and against the discovered
identity again at delivery. A source replaced between discovery and read is
not accepted merely because its replacement stayed stable. Root cancellation
and close settle both kinds of original reads before releasing ownership.
The original transcript bounded reader also treats a complete short head
segment as the complete tail: previously it returned no recent records when
the whole file fit in the first segment. Large files retain their bounded
head/tail read behavior and their unverified display status.

The existing Root history baseline passed ten cases in 10.20 seconds. Added
Root entry, budget and cancellation regressions first failed seven cases on
missing APIs, with the original snapshot cancellation case passing (14.96
seconds). The initial implementation passed fifteen cases but exposed two
short-file empty-tail failures (22.32 seconds). After the original bounded
reader correction, Root and Coding history projection passed 24 cases in
13.83 seconds. A 12,000-record file larger than the 8 MiB full-snapshot limit
returned its actual final record using at most two 64 KiB segments. The real
Continuity fallback used the Root-retained IO entry and displayed its explicit
unverified label without constructing a Product Session. That integration plus
all transcript catalog cases passed 31 tests in 29.30 seconds. Source size and
mtime remained unchanged; no read lock, Writer or repair was added.

These are correctness and bounded-read results, not the required 10k/100k
cold/hot latency, memory or 1/2/8 concurrency acceptance measurements. The
background plan/default activation, native effects, Hosted and release gates
remain required. The architecture run started at `e072a764` is still running;
later Root/Continuity/transcript source changes mean it cannot be reported as
a full final-tree architecture gate, regardless of its eventual outcome.


Final related verification passed 34 Root/history/Native screen cases in
153.28 seconds, including recent-page stale delivery and cancelled native IO.
The existing UI cases still use injected preparation/settlement inputs and do
not establish production default activation. Scoped mypy passed the three
changed source modules with an isolated cache; Ruff passed all four changed
Python files. The generated current package dependency check and nine static
architecture documentation checks passed. No timeout, snapshot budget or
activation permission was relaxed to obtain these results.


#### ARD-007 concrete protocol revision

The proposed ARD-007 revision `2026-10-12-r2` specifies frozen participating
owners before Definition evaluation, enrollment/co-committed native
registration/sealed enumeration, separate native outcome obligations and
original disposition authority. It names a v2 attempt/Binding extension and
native writer capabilities; these are proposed protocol boundaries, not
implemented or shipping versions. Application Product bootstrap/cutover
settlement remains a separate original-owner prerequisite; a selected epoch
alone cannot satisfy it. The proposal closes its four missing design details
while retaining implementation/release findings and common-parent acceptance.

Inspection of both original Approval journals confirms their current
partial-tail repair policy runs before semantic replay. A new event cannot
retroactively make those old binaries honor a pre-repair gate. The proposal
therefore explicitly excludes unfenced old writers from supported native-state
rollback and requires installed complete/partial-tail evidence of actual old
behavior. It retains readable history/export and supported capability-aware
rollback refusal as separate requirements. Nine static documentation checks
and `git diff --check` passed for the revision. No native v2 event has been
written or default writable Resume enabled by this design work.


#### Large-history data delivery baseline

The reproducible `scripts/benchmarks/benchmark_resume_history.py` benchmark
uses original Coding Roots and canonical synthetic transcript exports. One
Root represents each viewer; it does not model eight waiters on one Root or
Hosted's single Product binding. Each case measures a first data read and two
repeated reads after imports and fixture creation. Fixture creation warms the
OS cache. Terminal paint, background planning, writable activation, model
transport and memory peak are excluded, so these are neither OS-cold results
nor complete R2.1 performance acceptance.

The first run failed with `OSError: [Errno 122] Disk quota exceeded` while
creating a fixture under `/tmp`. It produced no complete report. The same
10000/100000 record geometry and 1024-byte payloads succeeded with explicit
private disk scratch; no Product byte budget was raised. Command:

```sh
env PYTHONPATH=src .venv/bin/python scripts/benchmarks/benchmark_resume_history.py \
  --scratch-root /home/dev/.cache/loushang-resume696-bench \
  --output /tmp/loushang-resume696-history-baseline-fe23e000.json
```

Linux/Python 3.11.15 produced six cases. Files were 12,578,266 and 125,978,266
bytes. Every returned page was explicitly unverified, included the actual last
record, read 131072 head/tail bytes and delivered 52 recent records. Source
identity, size and mtime remained unchanged. No Product Session was constructed.

| Fixture records | Parallel viewers | First batch ms | Repeated batch median ms (two samples) |
| --- | --- | --- | --- |
| 10,000 | 1 | 16.94 | 14.98 |
| 10,000 | 2 | 29.58 | 27.59 |
| 10,000 | 8 | 193.63 | 143.68 |
| 100,000 | 1 | 21.64 | 21.48 |
| 100,000 | 2 | 51.84 | 31.36 |
| 100,000 | 8 | 108.67 | 105.11 |

The raw JSON remains in the command's temporary output path. Three samples per
case do not establish a tail-latency distribution. Repeated eight-viewer batches
were above 100 ms; this is data delivery, not the first-input hot-path metric.
These results establish the bounded-read baseline and do not remove the cold
first-screen, actual UI paint, native planning, memory, Hosted and input
activation performance gates. Ruff and scoped mypy with `MYPYPATH=src` passed
the benchmark. Its first mypy invocation had two local type errors and resolved
the installed control-lane Root instead of the task Root; the corrected run
uses the task source explicitly.

The architecture run started at `e072a764` terminated with 654 passed in
1710.32 seconds. Its original terminal report is preserved at
`/tmp/loushang-resume696-architecture-e072a764.log`. Root/Continuity/transcript
source changed while it ran, so this result is not a full final-tree architecture
gate. Control `main` remains `f7d18114`; no new synchronization was required.
ARD-007 r2 is awaiting explicit common-parent acceptance for its new native
protocol and writer boundary. Independent baselines and existing gates may
continue, while dependent v2 mutation/default activation remains unimplemented.

#### Large-history Python allocation baseline

The benchmark now accepts `--measure-memory`. After each uninstrumented latency
case, a separate fresh-Root batch traces Python allocations through data
delivery and Root disposal. Imports and fixture construction occur before
tracing. This records neither process RSS nor allocations outside Python's
tracer, and cannot establish the complete R2.1 memory acceptance criterion.
Existing tracing is rejected instead of resetting another observer's session.

```sh
env PYTHONPATH=src .venv/bin/python scripts/benchmarks/benchmark_resume_history.py \
  --scratch-root /home/dev/.cache/loushang-resume696-bench --measure-memory \
  --output /tmp/loushang-resume696-history-memory-6aff2628.json
```

All six cases completed on Linux/Python 3.11.15 with the same actual last record,
52 delivered records, 131072 head/tail bytes and unchanged source identity,
size and mtime. Each viewer owns its own Root; these are not Hosted clients
sharing one binding.

| Fixture records | Parallel viewers | Traced Python allocation peak (bytes) |
| --- | --- | --- |
| 10,000 | 1 | 518,747 |
| 10,000 | 2 | 1,008,104 |
| 10,000 | 8 | 2,348,257 |
| 100,000 | 1 | 516,622 |
| 100,000 | 2 | 985,786 |
| 100,000 | 8 | 2,331,288 |

These observations are consistent with bounded recent-page allocation at these
two fixture sizes; they are not a general memory bound. Architecture checks ran
concurrently, so this report's latency samples must not be used as a speedup or
regression comparison against the preceding baseline. The raw report retains
the measurements and their scope. Ruff and scoped mypy with `MYPYPATH=src`
passed the changed benchmark script. Production code, activation authority and
history verification status were unchanged by this measurement extension.

The relevant current-tree architecture run completed with 176 passed in
429.84 seconds (`test_import_boundaries.py` and
`test_hosted_product_runtime_v1_baseline.py`, `not live`, host runtime skipped).
Its saved terminal report is
`/tmp/loushang-resume696-root-boundaries-6aff2628.log`. No runtime source changed
during this run; only the benchmark and this evidence note changed. This
establishes the affected boundary checks, not the outstanding full release,
installed-version, Hosted activation or performance gates. All nine static
documentation checks and `git diff --check` passed for this evidence update.

#### Completed background work and context-content invalidation

The Resource preview task key captures configuration and isolation inputs, but
does not contain the bytes of mutable workspace context. Its existing sharing
is limited to running work. Adding a completed-result cache keyed only by that
configuration would incorrectly retain a Plan after AGENTS content changes.

New fault coverage completes a background Plan, changes AGENTS bytes while
preserving device, inode, file size and nanosecond mtime, then requests a
foreground Plan through either the same Resource owner or a separate owner.
Both cases observe a changed Plan and Resource fingerprint, match the original
owner's freshly computed input receipt, and reject the old Plan with the fresh
owner inputs. A further unchanged request remains deterministic. No Resource
authority or owner selection is acquired. This verifies context-content
invalidation through the actual async Resource computation; it does not prove
Skill body admission, default Product planner integration or completed-cache
safety for other dependencies.

The pre-change focused async planning baseline passed (1 passed, 14 deselected).
The two new cases passed (2 passed, 15 deselected), then the affected planning
and native Resource scheduler modules passed together (36 passed in 1.79
seconds), using `not live` and `--skip-host-runtime` outside the managed sandbox.
Ruff and `git diff --check` passed. No production cache, activation permission,
writer protocol, test timeout or work budget was changed.

#### Isolated installed candidate history evidence

At source commit `9a866b25`, an offline build produced
`loushang-0.1.0-py3-none-any.whl` with SHA256
`0eb54daaae6e4c0a8193cb52ed39b8548d0e5c9e1178677e038064874c5c7fe6`.
The first build using the task-local uv cache failed because its offline index
did not contain setuptools. The existing global uv cache supplied the build
dependencies without downloading or changing the dependency lock.

```sh
uv --cache-dir /home/dev/.cache/uv build --offline --wheel \
  --out-dir /tmp/loushang-resume696-wheel-9a866b25
```

A separate environment at
`/home/dev/lsspace/resume696-installed-9a866b25/venv` was populated by offline,
locked `uv sync --extra dev --no-install-project --no-editable`, with
`UV_PROJECT_ENVIRONMENT` pointing there. The candidate wheel was installed
offline with `--no-deps`; the developer editable environment was not used for
the verification process.

The retained local evidence runner validates the isolated interpreter,
distribution direct URL, wheel digest and every installed package file against
both the wheel and task source. All 1699 package files matched. It invokes
pytest with `-I`, removes `PYTHONPATH`, disables plugin autoload and overrides
pytest's pythonpath to the repository root for test helpers, excluding `src`.
Its session-finish check found no imported Product module outside the isolated
installed prefix. The three existing modules
`test_resume_history_preview.py`, `test_runtime_resume_history.py` and
`test_resume_binding.py` completed with **69 passed in 8.33 seconds** using
`not live` and `--skip-host-runtime` outside the managed sandbox.

The local runner, origin report, JUnit and terminal report are retained under
`/home/dev/lsspace/resume696-installed-9a866b25/`; rerun command:

```sh
env -u PYTHONPATH PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /home/dev/lsspace/resume696-installed-9a866b25/venv/bin/python -I \
  /home/dev/lsspace/resume696-installed-9a866b25/run_installed_history.py
```

This is actual installed candidate evidence for retired composition/profile
history, bounded Root reads, Binding decoding and existing quarantine/commit
APIs. It is not default Embedded/Hosted continuation, native effect recovery,
Windows installation or a released N/N+1 matrix. `0.1.0` alone does not identify
this build: its source commit and artifact digest do.

A read-only GitHub release query returned an empty release list. This establishes
that no GitHub release artifact was available for the matrix at this inspection;
it does not establish absence of builds in other distribution channels. Released
old/new artifacts and the supported rollback matrix remain outstanding. The
remote `main` query still resolved to `f7d1811418fa51068d739770b6f39054c8ef10a7`,
matching the integrated task baseline. No release, push or remote write was
performed.

#### Installed local old/new writer and export comparison

Two isolated, locally built wheels now have concrete reader/export/writer
evidence. They are development candidates, not released N and N+1 versions:

| Candidate source | Wheel SHA256 | Verified package files |
| --- | --- | --- |
| main `f7d1811418fa51068d739770b6f39054c8ef10a7` | `4ba16137f3dfdd22def372b71ed9e07214e22d0df1dccf5d114f2f25f3cc3878` | 1683 |
| task `9a866b25` | `0eb54daaae6e4c0a8193cb52ed39b8548d0e5c9e1178677e038064874c5c7fe6` | 1699 |

The first main build was rejected by source/installed-byte verification before
any Session operation: the control lane's existing build tree contributed a
retired `harness/resources/plugins/manager.py` absent from main source. The
control build directory was preserved. A clean `git archive` of the fixed main
commit was exported outside the product tree. Its first build terminated with
an uv executor panic and no wheel; installation/source checks consequently
failed and no fixture was created from it. Repeating the same offline build
with temporary and output directories on private disk succeeded. The final
main wheel above matches every file in the clean export and its installation.
Neither rejected artifact contributes compatibility evidence.

The main wheel created a legacy Session through its ordinary non-composition
entry and committed a historical UserMessage. A first fixture attempt using
`new_with_composition` correctly refused a message before composition startup;
it was closed and excluded. The task wheel's canonical codec then constructed
separate private copies preserving the original Header and Session ID: clean
history, an unbound v1 activation intent, that intent plus an incomplete JSONL
tail, and an intent followed by a complete v1 RuntimeBinding UserMessage.
These are codec-valid golden exports, not claims of native effect execution or
settlement. No Agent, model call or plugin activation was performed.

| History | main reader/export | main writer | task reader/export | task writer |
| --- | --- | --- | --- | --- |
| Clean legacy | Preserved one record | Appended | Preserved one record | Appended |
| Unbound v1 intent | Preserved two records | Appended across intent | Preserved two records | Refused: `history.activation_pending` |
| Unbound intent plus partial tail | Preserved two complete records | Repaired tail and appended | Preserved two complete records | Refused with entire source, including partial tail, unchanged |
| Complete v1 Binding | Preserved all three records and Binding metadata | Appended without current Resume admission | Preserved all three records and Binding metadata | Refused: `runtime.current_admission_required` |

All eight cases retained exact original Header bytes and the original Session
ID. Every read-only observation left its source unchanged. Exported record
objects equaled the complete decoded source records; the new installed decoder
validated the Binding in main's export. The old partial-tail write produced
valid JSONL; the new refused source still retained its incomplete tail bytes.
Both processes verified isolated package origins throughout. Raw reports,
the matrix assertion summary and the local evidence runner remain under
`/home/dev/lsspace/resume696-main-installed-f7d18114/`.

This strengthens ARD-005's existing unsupported-downgrade finding with actual
installed artifact identities and complete/partial-tail behavior. The main
writer is not a safe writable rollback target for Resume v1. A minimum supported
writer capability/build and released-artifact evidence remain required; a
read/export claim cannot be used to promise that an unfenced old binary refuses
new records. These Transcript probes do not cover ARD-007's native owner
journals, cross-boot effect correlation or default writable activation. No
existing accepted contract, default activation or release policy was changed.


#### Resumed implementation: native journal validation and ARD-007 acceptance

On 2026-10-13 the existing clean `resume-696` worktree was resumed from
`bf29c05d`. Fetch confirmed remote main remained `f7d18114`; local main
`99886830` was already merged. No replacement worktree was required.

ARD-007 revision `2026-10-12-r2` is now accepted through the delegated technical
review recorded in the decision. The earlier waiting-for-acceptance paragraph
above describes the prior state. There is no outstanding personal-approval
requirement for this internal contract. Native protocol implementation and
release verification remain required before default writable Resume.

A native Approval regression exposed destructive repair before semantic replay:
a codec-valid noncontiguous event chain or a journal opened under another owner
scope could lose its incomplete tail even though the owner refused the snapshot
or consume operation. Complete unknown event versions were already rejected by
the codec before repair. The original journal loader now accepts an optional
owner snapshot validator, invoked under the same lock before repair. Execution
and component Approval owners replay and validate their scope there, reusing
the resulting replay instead of rereading or adding another effect ledger.

The regression covers snapshot and consume refusals for semantic chain errors,
wrong scope and unknown complete event versions, checking exact source bytes.
A shared-journal test checks lock ownership, failure byte preservation and
successful repair after validation. The two Approval modules and shared
journal tests passed together: **118 passed in 2.65 seconds**, outside the
managed sandbox with `not live` and `--skip-host-runtime`.

This preserves existing v1 recovery when the complete prefix is valid. It does
not add native Resume enrollment, parent registration, sealed enumeration,
v2 event writers, new admission grants or a production settlement adapter.
Unfenced installed old writers remain unsupported; this source fix cannot
retroactively change their repair behavior.


The change-specific check plan (`--base bf29c05d`) selected documentation,
architecture dependency facts, Harness and host-runtime follow-up. Documentation
checks (9), dependency-fact regeneration checks, Harness Ruff and Harness mypy
(771 source files) passed. The initial Make test invocation was interrupted
because its legacy entry did not attach the safety selectors; no result from
that interrupted run is claimed. The remaining full Harness test invocation
uses `PYTEST_ADDOPTS='-m "not live" --skip-host-runtime' make test-harness`
outside the sandbox and was still running at this checkpoint. It is not yet a
passing full-suite result. Host-runtime follow-up remains excluded from this
non-live run and is still required for the final delivery scope.


#### Definition original-journal Resume registration

The prior non-live Harness test completed: **5712 passed, 124 skipped,
33 warnings in 1611.25 seconds**. This covers the prior `f812e14e` runtime
repair scope. The newly added context module had not been exercised by that
run, and the later Definition enrollment/registration/seal implementation is
not covered by that earlier full-suite result.

The Definition original journal now persists owner-validated enrollment,
parent context atomically with native consume/reserve, and a digest-checked seal
of exact native use membership. Existing native decisions, instance revisions,
Host/import-realm identities, transitions and original lock/CAS remain the
state authority. No second effect ledger or new permission issuer was added.
V1 payloads stay unchanged; explicit v2 event types refuse unsupported decoding.
The parent value uses the accepted exact fields and a 2 KiB encoded limit.

New regressions cover durable consumption followed by lost Ack, one native use
on retry, unknown/missing enrollment, scope and contract mismatch, conflicting
intent under one attempt, multiple native uses, seal/consume contention,
late-start fencing in both the API and semantic replay, cross-boot STARTING
remaining unknown, strict context decoding, and partial-tail byte preservation.
The final focused run included all Approval tests, the real Definition
evaluator, component Host, shared journal and context tests:
The 202-test protocol run passed in 5.22 seconds, outside the sandbox with
`not live` and `--skip-host-runtime`. The later evaluator integration adds two
actual import-sentinel cases; its final result is recorded below. Ruff, focused
mypy and dependency-fact checks passed.

The change plan still selects Harness and host-runtime follow-up. The new
protocol has not passed a final full-tree Harness/release matrix; the earlier
5712-test result is not substituted for that requirement. Integration and the
remaining original owners must be completed, then the selected final gates
must run before delivery. The production Product selection has not been wired to supply the committed
Resume parent context, and no default writable route or supported downgrade is
claimed from these tests. Next implement component/native Worker association
and trusted original-owner participation from the committed v2 intent; then
join those facts to the existing continuation coordinator.


The original Definition evaluator now takes an optional typed parent context.
Its initial original-journal snapshot requires that exact parent to be enrolled
and open before any tail repair; consume repeats the same parent validation in
its atomic owner transaction. Ordinary non-Resume evaluation keeps its existing
v1 route. Actual existing synthetic-plugin import sentinels verify that missing
enrollment leaves the complete/partial native source unchanged and performs no
Definition import, while enrolled evaluation persists the original parent and
native use, runs verified source, and returns the original EVALUATED fact.
These invocation-return facts still do not settle arbitrary external effects.
Product selection/committed-intent propagation remains outstanding.


The final focused evaluator/owner run completed with **204 passed in 5.97
seconds**. Focused mypy covered the journal, shared parent context and actual
Definition evaluator. The selected full Harness check for this new protocol is
launched separately; it is not replaced by the earlier tail-repair gate.

That exact Definition implementation (`28803be8`) completed its selected gate:
docs, dependency facts, Harness Ruff and mypy (772 source files), followed by
**5751 passed, 124 skipped, 33 warnings in 2051.84 seconds**. The command exited
0. This is local non-live evidence with host-runtime checks excluded; Actions
must still cover platform, installation and real-LSP checks. It does not cover
the subsequent Component protocol implementation below.

#### Component original-journal Resume registration

The original Activation journal now has explicit v2 enrollment, atomic
contextual consumption and sealed membership. Native reservations and legacy
v1 payloads retain their existing identities and shapes. Both in-process Hosts
propagate optional typed context through their shared lifecycle, validate exact
enrollment before recovery/consumption/import, and recover only that parent's
registered native uses. Enrollment remains inert and grants no execution.

Native CAS/replay fence new registrations and late starts after seal. STARTING
and STARTED refuse sealing. Cross-boot recovery preserves the legacy FAILED
fact but additionally projects the original recovery of a possibly running
factory: no new boot identifier proves the old factory stopped. Those recovered
uses remain unfenced and prevent seal. Rejected sealing and sealed late starts
preserve the incomplete journal tail byte for byte.

Focused original-journal/evaluator/Component Host/shared-loader tests completed
with **218 passed in 6.60 seconds**, including actual factory import/publication,
unknown enrollment with partial tails, durable consume acknowledgement loss,
exact recovery scope and both STARTING/STARTED cross-boot recovery. Ruff and
mypy over the four affected implementation files passed. The selected full
gate for this Component change is separate and must be observed to completion.

Remaining delivery requirements include committed v2 intent and Binding
propagation, complete trusted startup owner participation, Worker containment
settlement, original custodian retention/domain reconciliation, Embedded and
Hosted integration, background planning/performance, released artifact
compatibility, PR merge and Issue backwrite. Default writable Resume and
Issue #696 remain incomplete.

#### Transcript v2 projection and Product parent prerequisite

The Transcript owner now advertises an explicit
`coding.resume-continuation/v2` writer capability. Its v2 path commits and
reloads the exact activation intent and first UserMessage Binding, while the
shared history and Plan projections understand both v1 and v2 facts. Unknown
future versions remain sticky, malformed v2 facts remain invalid, and a future
writer capability is refused before source acquisition or repair. The focused
writer, Binding, history and Plan regressions are included in the result below.

Coding Product capability preparation can now receive the two exact original
Definition and Component parent contexts as one typed prerequisite. It verifies
both enrollments and their common committed intent before Definition evaluation,
then passes each context to the existing original journal owner. Either missing
enrollment refuses without a native use or journal byte change. This is
dependency plumbing only: the default continuation does not yet construct,
enroll, seal or settle these parents, and Worker ownership is still outstanding.

The combined focused run for Transcript v2 projection, Product parent
prerequisites and the existing native Definition/Component integrations passed:
**131 passed in 13.86 seconds**, outside the managed sandbox with `not live` and
`--skip-host-runtime`. Ruff, focused mypy and `git diff --check` also passed.
This evidence does not enable default writable v2 Resume or replace final
Embedded, Hosted, performance, installation, platform and selected-tree gates.

#### Restricted v2 continuation and original Plugin enumeration

The continuation now negotiates all four accepted writer protocol capabilities
before current admission or any durable source access. A v2 intent with no
startup effect owners can use the existing single-input coordinator when the
current composition also selects no capability Plugin startup owners. If the
current composition selects those Plugins, the frozen intent must contain the
exact Definition and Component pair with their native scope/contract digests
and fixed declaration/activation phases. Current composition selection is
rechecked before Product preparation; a caller-supplied empty owner list cannot
silently bypass a selected capability Plugin.

After the Transcript intent commit, the coordinator idempotently enrolls that
pair in the two original journals. Product preparation carries the exact parent
contexts into native Definition evaluation and Component construction. After
the runtime graph is prepared, the coordinator seals exact native membership
in both original journals before first-input preparation. Retry after a crash
between the two enrollments is supported. Unsupported owner IDs, declared
external effect classes and Worker candidates refuse before admission and
Writer acquisition; Worker containment remains a required later slice.

The real no-effect-owner v2 continuation committed exactly one v2 Binding and
reloaded it through the history projector. Enrollment retry/seal, unsupported
pre-Writer refusal and direct Transcript v2 tests passed together: **11 passed
in 10.40 seconds** outside the managed sandbox. Ruff and focused mypy passed.
A broader diagnostic continuation run exposed eight existing published-mode
assertion failures where the current Product test setup retained the literal
`/skill` command instead of expanding its Skill text; the v2 record-construction
failure from that run was fixed. Those Skill fixtures were subsequently
corrected and closed by the exact Catalog evidence recorded below; they are not
counted as passing evidence in this earlier run.

This remains a restricted internal continuation path. Product application
operation reconciliation, native Worker participation and domain-specific
external effect settlement are not implemented, so default Embedded/Hosted
writable v2 Resume remains unavailable.

#### Worker C5 parent propagation in the restricted continuation

The restricted v2 continuation can now select one exact Worker plugin rather
than treating the presence of Worker candidates as a selection. Its frozen
owner set must include `harness.worker-activation` with the exact native scope
and contract digests and the fixed `reservation`/`start` phases. The current
composition recheck includes that owner alongside any selected Definition and
Component owners. A v1 intent, an omitted Worker owner, a Worker owner without
an exact selected plugin, or an unsupported phase/effect class still refuses.

The selected Worker bootstrap carries the parent into the original C5 owner on
both POSIX and Windows. Enrollment and current C5 admission occur before Worker
payload materialization; native attempt registration then co-commits the parent
association before effect start. The existing graph publication callback
publishes the native attempt and seals the complete original membership. The
ordinary path retains its prior ordering and uses no Resume state. Windows uses
a pre-materialization view of the same stable cleanup evidence domain only for
parent enrollment; the exact request-bound evidence authority still owns all
attempt settlement.

Enrollment is idempotent across retry and re-reads the original journal after a
lost durable acknowledgement. A lost seal acknowledgement is recovered from
the committed original state on retry. Focused parent, native C5 and v2 tests
passed: **21 passed in 11.29 seconds** outside the managed sandbox with
`not live` and `--skip-host-runtime`. The existing Linux Worker candidate
regression passed its non-host case with **1 passed, 7 skipped in 19.86
seconds**. Ruff, focused mypy, compile checks and `git diff --check` passed.

This slice does not provide the remaining application-operation reconciliation,
external-effect disposition, default Embedded/Hosted entry, background planning
integration, Windows host-runtime execution, release artifact matrix or final
full-tree gate. The pre-existing broader continuation `/skill` assertion
failures are closed by the exact Catalog evidence below. Default writable
Resume stays unavailable.

#### Embedded history starts bounded background planning

The default Embedded CLI/TUI Root now retains the selected current composition,
its original ResourceLoader, workspace root and live native subject/policy
fingerprint readers as data-only planning inputs. After the continuity provider
has loaded and revalidated a full selected-branch history snapshot for display,
it starts the existing bounded Resume planning slot. An unconfigured Root does
not report preparation, and an unavailable planner is projected as a display
status without failing historical access.

Planning still constructs no Agent, Runtime, Writer, Package selection,
approval fact or execution grant. The slot continues to revalidate fresh owner
inputs before returning a cached Plan and closes only its own waiter reference.
The focused planning, continuity and Embedded Root tests passed: **22 passed in
11.55 seconds** outside the managed sandbox with `not live` and
`--skip-host-runtime`. Ruff, focused mypy and `git diff --check` passed.

This first production trigger does not yet consume the completed Plan during
foreground admission, provide the corresponding Hosted history trigger, or
establish the required latency measurements. Default writable Resume remains
unavailable.

#### Exact Catalog Skill fixture closure

The published Resume fixtures now establish their project-native Resource root
with `AGENTS.md` before creating `skills/review/SKILL.md`. This follows the
current Catalog project-root contract, so first-input preflight reads the exact
current Skill body and persists its content digest. No temporary Resource source
or Product admission exception was added.

The three representative continuation, publication and Root first-input cases
passed together. The full canonical continuation parameterization plus every
publication preflight variant then passed with **22 passed, 23 deselected in
116.57 seconds** outside the managed sandbox with `not live` and
`--skip-host-runtime`. Ruff and `git diff --check` passed. This closes the
previous `/skill` test failures but does not provide Embedded foreground Plan
consumption, Hosted planning, performance evidence or a writable default route.

#### Foreground promotion and fresh Plan input check

The native Root now exposes one configured foreground Plan entry for the first
continuation input. It submits through the same Resource owner with foreground
priority, which promotes matching in-flight background work. A completed
background Plan is returned only after fresh Resource, subject and Policy input
observations match it; changed inputs invalidate the cached value and return the
fresh foreground Plan. This comparison grants no Writer, approval, settlement
or execution authority.

All **10 Resume planning tests passed in 4.30 seconds** outside the managed
sandbox with `not live` and `--skip-host-runtime`. Ruff, focused mypy and
`git diff --check` passed. The entry is ready for the Embedded history input
coordinator, but that production coordinator, Hosted invocation and latency
evidence remain outstanding.

#### Audited first-party Plugin startup settlement adapter

The Coding Product now freezes the exact Definition and Component original-
journal obligations from their native scope and contract digests without
opening or creating either journal. After graph preparation, its first-party
settlement adapter accepts only sealed exact membership, `EVALUATED`
Definition uses, `COMMITTED` Component uses, no unfenced recovered factory,
and a one-for-one match with the current Product receipt's selected LSP or
Architecture instance revisions. Missing enrollment, an empty or partial
membership, failed or starting uses, a changed revision, an unknown Plugin, or
a declared external effect remains `input.effect_settlement_unknown` or an
unsupported owner set.

This is a narrow audited closure. The checked-in LSP factory constructs a lazy
runtime and cannot launch a server until later Tool use; the checked-in
Architecture factory constructs an unloaded cache and cannot read or write it
until later analysis or Tool use. The current Session independently
revalidates that these instance revisions still belong to the exact
Product-selected first-party Wheels before and after the adapter. The native
terminal states therefore cover the startup contract for these two exact
implementations; they are not generalized into settlement for arbitrary
Plugin code, filesystem, network, process or publication effects.

The continuation also canonicalizes the Product approval state root before
parent enrollment. This preserves the POSIX path and uses the Windows
`product-private` root selected by the original Product owner, avoiding a
second parent journal location on Windows.

Focused original-journal and v2 continuation validation passed **14 tests in
11.12 seconds** outside the managed sandbox with `not live` and
`--skip-host-runtime`; Ruff and scoped mypy passed. The default Embedded
coordinator has not yet invoked this adapter, and Worker C5 settlement remains
a separate native obligation, so writable Resume is still unavailable.

#### Embedded first-input owner coordinator

The Embedded Root now has a production coordinator for the first input shown
over Resume history. It promotes the configured foreground Plan, formally
selects the Product epoch through the retained application owner, obtains an
exact confirmation from the original Root approval owner, rechecks the current
execution profile and Policy, and submits one v2 intent through the existing
single-input continuation. Capability Plugin participation is frozen before the
Writer and reconciled through the audited native journal adapter; an exact
no-participant receipt is required for minimal or Tools-disabled activation.

The coordinator does not create Plugin approval storage while it freezes owner
obligations. A failed continuation releases its retained confirmation. Worker
selection remains fail-closed until C5 readiness, no-start and cleanup
settlement is implemented. Default CLI history routing and Hosted adoption are
still pending. The Embedded coordinator, history screen, v2 continuation and
native Plugin journal suites passed **28 tests in 55.96 seconds** outside the
managed sandbox with `not live` and `--skip-host-runtime`; Ruff, scoped mypy
and `git diff --check` passed.

#### Explicit Embedded Resume enters through history

The early-screen Coding CLI now intercepts explicit `--resume <session>` before
the generic Agent CLI restores a Session. It reads the bounded selected history,
starts the configured data-only Plan, and supplies a placeholder only to the
CLI phase adapter. The screen receives no Agent or writable Session until its
first prompt calls the Embedded coordinator. Model selection, Tools mode,
current services and Policy are forwarded to that coordinator.
The same route now also forwards the parsed thinking level through Runtime,
continuation and the resumed Agent constructor instead of silently reverting
to the service default.

The original Root resolver is presented through a generation-safe Embedded
interaction adapter. Approval decisions use that resolver before Session birth;
after lifecycle delivery the same screen routes decisions to the current
Session interaction. Closing the history presenter clears presentation without
closing the newly active Session owner. A real CLI case also verifies that an
explicit Resume can display history and exit with byte-identical Transcript
content and no eager current Session. The screen-first startup, history screen
and Embedded coordinator regressions passed **77 tests in 51.44 seconds**
outside the managed sandbox with `not live` and
`--skip-host-runtime`; Ruff and scoped mypy passed.

Bare `--resume` still uses the existing continuity picker and eager activation.
Hosted adoption, Worker C5 settlement, background latency evidence and the
remaining release gates are pending.

#### Embedded Worker C5 settlement

The Embedded v2 coordinator now freezes `harness.worker-activation` from the
already selected Product scope without opening the C5 journal. The selected
Worker bootstrap constructs one Session-owned settlement binding beside the
original receipt and parent context. POSIX and Windows pending Hosts bind that
facade only to the actual C5 coordinator whose native evidence authority owns
the attempt; no Worker state is copied into the detached Coding composition
receipt.

After graph publication, continuation and every later Runtime publication or
model-transport admission reread the original parent snapshot. The check
requires a sealed, nonempty exact membership, cleanup contract v2, the exact
receipt/policy/owner generation, and either current `published`/`ready`
admission or an exact `settled` record with protocol, domain, process-tree and
native-containment closure. Registered, unsealed, cleanup-debt, stale receipt,
changed membership and unknown states remain recovery-required. The existing
live candidate check remains independent, so historical cleanup cannot revive
a retired graph.

The Worker owner is reconciled separately from the audited built-in Plugin
owners while both remain in the same frozen v2 intent. Focused native parent,
Embedded coordinator, Plugin settlement and continuation tests passed **52
tests in 81.76 seconds** outside the managed sandbox. Runtime Resume regressions
passed **26 tests in 108.93 seconds**. An earlier combined run reached **57
passes** before 21 later cases failed while creating unrelated fixture journals
with `/tmp` reporting `Disk quota exceeded`; the same Runtime file passed after
moving pytest's base temporary directory into the task worktree. Windows native
host execution, Hosted adoption, bare picker history routing, background
latency and release gates remain pending.

#### Bare Resume picker enters native history before activation

The standalone `--resume` picker now treats selection and Session activation as
separate Product operations. Its admitted native Coding provider revalidates
the selected summary, conflict state and current transcript authority, then
returns only the canonical history source. It does not call
`prepare_restore_session_operation`, consume an activation lease, publish a
Session or open a Writer. The Root reads that source through the same bounded
history preview and starts the existing data-only planning path before the
picker releases the terminal.

After terminal restoration, explicit and picker-selected Resume share one
history host, model-selection adapter and first-input coordinator. The generic
CLI configuration and operation phases recognize the history placeholder and
do not treat it as an Agent Session. A provider other than the admitted native
`coding.sessions` provider is rejected inside the picker because its portable
activation payload is not native transcript authority for the history screen.
The picker remains outside the early loading screen so the two interfaces never
compete for stdin or terminal ownership.

Focused bare Resume, native source-resolution and explicit history-screen
regressions passed **11 tests** outside the managed sandbox with `not live` and
`--skip-host-runtime`. The source-resolution case verifies that neither
preparation nor restoration occurs. A broader CLI, Continuity and screen-first
run passed **355 tests**; its other five cases rejected the worktree's `0775`
ancestor during security path validation, then all **5 passed** with a private
`0700` basetemp under `/tmp`. Ruff, scoped mypy and `git diff --check` passed.
Hosted adoption, Windows native host execution, background latency and the
remaining release gates are pending.

#### Hosted stable first input and explicit stdio execution

Commit `40399e8e` routes the default Coding Hosted client through an explicit
discovery-and-execution stdio profile. The foreground AppHost retains the
authenticated `AppClientScopeV1` used by execution, closes that scope before
the application, and exposes no execution capability to the existing discovery
only profiles. Direct `loushang-hosted` callers remain on their prior stdio
profile unless they explicitly request `--session-execution`; this preserves
the old wire contract while the first-party Hosted client opts into the new
capability.

The Hosted Local Product now owns its transcript roots and exposes its existing
native Session execution registry. Managed Local retains its previous owners
and does not acquire that registry. LMUX stores the complete
`SessionIdentityV1` for each window and submits the first input through one
stable 32-hex submission identity. Known acceptance clears only the exact draft
that was submitted. Unknown delivery retains the draft and recovery state; an
explicit retry of the unchanged text reuses the same identity, while a later
edit cannot be erased by a delayed acceptance. Existing start, steer,
follow-up and interrupt routes keep their previous behavior.

Coding's Hosted Resume handoff projects an input already committed by the
native continuation as one `USER_MESSAGE` event. It does not create a second
Writer or append the input again. The true stdio subprocess case verifies
history selection, approval, one committed user input, one model reply and
idempotent duplicate submission. The complete Hosted subprocess and discovery
subprocess files passed **14 tests in 322.34 seconds** outside the managed
sandbox. The focused connection, foreground, launcher, Hosted bootstrap/CLI,
discovery command and LMUX request set passed **642 tests in 63.27 seconds**.
Ruff and scoped mypy passed for the touched source.

This closes the first-party Hosted writable route and stable submission
boundary. Released N/N+1 artifacts, Windows native host execution, multi-host
load evidence and the final selected-tree gates remain separate acceptance
work.

The final Hosted route changes the earlier G14 reviewability checkpoint. Against
current `main` at `b53afcb0`, the three original G14 owners now measure CLI
290 lines (+34), catalog 1,202 (+316) and Session binding 569 (+195): 2,061
total against the 1,516-line pre-Resume baseline. The additional 207 lines
beyond the earlier 1,854 checkpoint are the explicit execution negotiation,
owned transcript preparation, admitted activation and committed-input handoff
implemented by the later Hosted slices. The G14 architecture supplement and
Wave A file ceilings now record those exact values; no new file or partition
exemption was added.

The writable route also adds 45 net lines to the existing G16 owners against
the same `main`: detachable CLI +1, shared bootstrap +29 and local command
+15. They carry execution negotiation, local execution composition and
post-admission owned-root preparation through the already accepted native
route. The Wave A gate records a 45-line reviewed allowance above its prior
900-line ceiling plus exact per-file ceilings; it does not add a G16 file or
move code out of the counted partition.

Two smaller boundary deltas remain within their existing partitions. Deferred
Product binding grows `hosted_execution.py` to 256 lines while the two-module
execution total remains 389/400. Installed LMUX propagation and the managed
startup override add 1 and 7 lines respectively, so the prior exact LMUX
aggregate receives an 8-line allowance plus ceilings on the two changed files.

#### Instrumented interactive Resume pilot

The Linux interactive startup observer now has an explicit `--resume` mode for
a seeded synthetic installed entrypoint. It preserves the transcript's
canonical file name, gives transcript data, machine state and blob/Writer
authority distinct private domains, enters the real history-first screen,
submits one input, confirms the rendered approval and observes one synthetic
model result. Test-only import observers record the production history preview,
background Plan completion, host input entry, foreground Plan return, durable
input commit and model transport without adding a Product callback. Duplicate,
missing or non-monotonic milestones invalidate the report. The child records
process CPU, Linux peak RSS and open FDs at settled exit.

One local current-checkout sample (`resume696-probe-run-8`) completed with:

| Observed milestone | Result |
| --- | ---: |
| First completed terminal frame from spawn | 12.554 s |
| Authoritative history ready from spawn | 13.943 s |
| History screen ready from spawn | 14.029 s |
| Input accepted after external submit | 0.034 s |
| Foreground Plan ready after external submit | 0.046 s |
| Approval surface visible after external submit | 18.275 s |
| Input durable after external submit | 38.550 s |
| Model transport entered after external submit | 45.257 s |
| First rendered reply after external submit | 45.977 s |
| Background Plan status | ready before input |
| Process CPU / peak RSS / open FDs at exit | 17.142 s / 126352 KiB / 6 |

The milestone observer regression passed **28 tests in 13.32 seconds** outside
the managed sandbox. Separately, the current `verify_resume_scale.py` print-mode
baseline passed with two 1 MiB sparse Catalog fixtures and one valid 40.008 MiB
transcript: cold bounded listing 14.144 s, bounded rebuild 0.022 s, steady query
0.006 s, fresh-process ordinary Resume 23.643 s and model transport entry
8.875 s after the worker began. That print-mode measurement exercises the
ordinary restore route and is retained only as a large-transcript comparison;
it is not evidence for the history-first writable path.

Both results are local single samples from the editable current checkout and
remain classified as pilots. They establish named phase observability and show
that input entry and cached Plan return are distinct from the much longer
approval, Writer, publication and model path. They do not establish fixed
latency thresholds, released-installation comparison, 1/2/8 concurrent
history-first activations, 10k/100k writable continuations, Writer wait/fsync
breakdown or cross-platform resource acceptance.

#### Final installed upgrade, bounded scale and rollback evidence

The final Product tree at `1b9bae91` was built as an isolated wheel and installed
with its declared dependencies. Its SHA-256 was
`73db3cd52ce85597f2ceeb585b804d0d13a4ffc20345a80a20355c12a1cc289c`.
The immutable R2.1 design-merge baseline `e0878dfa` was independently built and
installed; its wheel SHA-256 was
`90f429bbab12fd3cf9114cb208cbe5e4c7353fa07f1fa4dd32a256414c2028bc`.
Both artifacts currently carry package version `0.1.0`, and the repository has
no published GitHub Release. This is commit-pinned installed-artifact evidence,
not a claim about an absent public release.

The baseline wheel created a 32-message legacy Session. The final installed
wheel then entered the real history-first TUI, completed background planning,
obtained confirmation, committed exactly one v2-bound input, invoked one
synthetic model transport and rendered its reply under the original same
Session identity. The instrumented sample reported:

| Installed upgrade milestone | Result |
| --- | ---: |
| First completed terminal frame | 5.095 s |
| Authoritative history ready | 5.732 s |
| Input accepted after submit | 0.0145 s |
| Foreground Plan ready after submit | 0.0221 s |
| Resume Writer acquisition and revalidation | 0.120 s |
| Input durable after submit | 14.605 s |
| Model transport entered after submit | 17.257 s |
| First rendered reply after submit | 17.486 s |
| Process-wide fsync calls / elapsed | 339 / 0.350 s |
| Unrelated full Model Input rebuilds | 0 |
| Process CPU / peak RSS / open FDs at exit | 14.011 s / 128228 KiB / 6 |

The fsync observation covers the complete installed Product process, including
owner journals; it is not attributed only to the Transcript input commit. The
Writer observation covers source verification, original Writer acquisition and
restore. These are one-machine baselines. The accepted deterministic gates are
the existing byte/work/concurrency limits and lifecycle assertions; no fixed
millisecond service objective is introduced from one sample.

The bounded recent-history benchmark then exercised 10,000 and 100,000-record
fixtures at 1, 2 and 8 independent Roots, with three reads per case:

| Records | Roots | First batch | Repeated median | Max bytes / Root | Max rows / Root | Traced Python peak |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 1 | 11.21 ms | 6.65 ms | 131,072 | 52 | 517,985 B |
| 10,000 | 2 | 16.15 ms | 15.30 ms | 131,072 | 52 | 951,726 B |
| 10,000 | 8 | 74.76 ms | 57.24 ms | 131,072 | 52 | 2,076,160 B |
| 100,000 | 1 | 7.78 ms | 7.62 ms | 131,072 | 52 | 517,745 B |
| 100,000 | 2 | 15.24 ms | 13.34 ms | 131,072 | 52 | 985,072 B |
| 100,000 | 8 | 63.80 ms | 61.68 ms | 131,072 | 52 | 2,237,242 B |

Every source retained identical device/inode/size/mtime facts. The 10,000 and
100,000-record files were 12,578,257 and 125,978,257 bytes. Fixture creation
warmed the OS cache; the first column is a fresh-Root data read, not an OS-cold
storage claim. A shared background Resource computation used one native scan;
cancelling one waiter released its reference in 0.063 ms while the peer stayed
pending and completed normally. Resource functional gates separately enforce
the 8 MiB package-text budget, 64 KiB read checkpoints, work limits, priority,
subject/Workspace/Policy isolation and last-reference cleanup.

For rollback, the baseline reader loaded the resulting 35-record v2 transcript,
retained the unknown `coding.runtimeBindingV2` metadata, exported and reloaded
an equal JSONL stream, and left the 20,523-byte source unchanged at SHA-256
`a61cd85997b4c0e6394daf43fc1ad5dd6803d055d9faca922b6926731f7c29a2`.
Older writable rollback is intentionally unsupported because an old process
cannot enforce protocols it predates. The minimum writable contract is
`coding.resume-continuation/v2` plus the selected Definition, Component and
Worker `resume-context/v1` capabilities. Operators may inspect/export with the
baseline reader, but must upgrade forward before another write.

The large matrix measures bounded unverified display. The 2026-10-14 correction
raises final writable revalidation to 64 MiB of selected history, so the verified
12.67 MiB field sample remains writable. An uncompact
100,000-record Session is not claimed as writable. It stays readable through
the bounded preview and fails closed for continuation until its selected
history fits the verified range. This is the published support boundary rather
than a silent full replay or an unmeasured large-session write claim.

#### Hosted submission-mode compatibility closure

The final Hosted compatibility pass separates connection capability from the
delivery contract of one Session binding. `SessionSnapshotV1` defaults to
`legacy`; its encoder omits the field and retains the original App v1 snapshot
shape for every ordinary Session. Deferred and read-only Resume bindings under
the explicit execution profile emit the canonical optional
`submissionMode: execution` value. Both the App and execution codecs accept the
old shape as legacy, accept the execution extension, and reject an explicit
noncanonical `legacy` extension or unknown value.

HarnessTUI now routes ordinary bindings directly through `start_turn` and
clears their exact draft as soon as the bounded action task is published. It
routes only execution-marked Resume bindings through the stable submission
ledger, retaining their draft until known acceptance and reusing the same
submission ID after unknown delivery. This restores G16 approval interaction:
the exact two-Mux approval, detach, reattach and interrupt terminal scenario
passed locally in 58.47 seconds. The protocol, execution-codec, request and
controller regression set passed 85 tests in 40.95 seconds; scoped Ruff, mypy
and the affected architecture budgets also passed.

The CLI uses one Session lifecycle activation path for startup flags, the
startup picker and the in-session picker. The bounded history-first components
remain available below Product-owned activation paths, but screen-first startup
does not introduce a second continuation protocol. This keeps process-death
history recovery, same-ID continuation and a fresh ordinary turn on the same
contract for Linux, macOS and Windows.

#### 2026-10-14 field correction: current environment cannot veto history

Two real local transcripts exposed gaps after the original merge: 1.32 MiB
(126 records) and 12.67 MiB (2,170 records). Both decoded completely and were
unchanged during diagnosis. The old entry rejected changed Resource and Plugin
fingerprints as `effective composition changed`; the history-first entry used a
1 MiB default and unconditionally requested `authority.unknown`, including when
the computed composition differences were empty.

The corrected contract is:

1. A readable historical Header, Runtime Profile, Capability Profile,
   composition receipt and Plugin/Resource receipt are validated against their
   own schema and Product identity. They are not compared for equality with the
   current installation.
2. An unspecified composition choice retains the historical set ID while using
   its current implementation. Current Plugin, Resource, Skill, AGENTS, model,
   thinking, directory and permission inputs build the new turn.
3. Resume does not request a permission grant merely because the historical
   permission baseline is absent or different. The current execution profile
   and Tool policy govern new operations through their normal owners.
4. The full history and Writer revalidation paths share a 64 MiB limit. Larger
   Sessions remain available through the bounded recent-history view until a
   streaming or indexed full-verification path is delivered.
5. Startup `--resume <session>`, the bare startup picker and in-session
   `/resume` all consume the same prepared Session lifecycle activation. Native
   macOS CI proves the real command-line entry after a current Resource change;
   platform-specific Writer implementation is not part of CLI routing.

Regression evidence covers changed Runtime/Capability profiles, AGENTS and
Skill content, current model, permission profile, Plugin catalog fingerprint,
12,000-record history above 8 MiB, headless continuation without a Resume
approval prompt, native macOS same-ID continuation, and the real macOS
command-line `--resume <session>` entry. The #735 CI run `38507720597`
completed with 90 successful checks, one expected skip and no failures; #738
adds the unified-entry regression.

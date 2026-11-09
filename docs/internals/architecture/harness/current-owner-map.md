# Harness Current Owner Map

Status: current architecture reference.

This document is the short, authoritative map of the implemented
`loushang.harness` boundaries. Detailed boundary records explain individual
decisions; migration ledgers record how the code arrived here and are not a
second description of current ownership.

Session's existing Product assembly also owns the complete receipt package
merge into an inert plan, declaration finalization and exact owner completion.
It uses the original Seed/selection values, Host and owner grouping. Coding
retains product/trust/error policy, owner boundary decisions and its three typed
public entries. No generic startup engine, registry or authorization is added;
see [A36](key-designs/startup-session-assembly-convergence.md#14-a36catalog-package-plan-与-selection-的完整接缝).

## Scope

Harness is the cross-Product execution substrate. It owns reusable mechanisms,
contracts, lifecycle shapes, and explicitly overridable platform defaults. A
Product owns domain language, prompts, policy choices, presentation semantics,
and the conversion from user intent or Method output into Product operations.

Harness does not import Product packages. In particular, Harness must not
depend on `loushang.coding`, `loushang.harnesswork`, `loushang.work`, `loushang.method`,
`loushang.channel`, `loushang.harnesstui`, or Product UI packages.

## Implemented Owners

| Owner | Owns | Does not own |
| --- | --- | --- |
| `runtime` | cancellation, retry/scheduling primitives, owner-scoped exact registration lifecycle, runtime-profile declarations, admission, resolution, binding, refresh, disposal | live registry conflict policy, Product capability selection policy, or provider behavior |
| `config` | layered/scoped configuration mechanics and optional Agent settings types, patch commands, schema codec, and manager lifecycle | Product-only fields, paths, activation effects, credentials, or presentation |
| `session` | optional Agent-session profile, Product-neutral assembly, turn/lifecycle coordination, command and maintenance bindings, Session facade and inspection | Product prompt content, domain operations, UI state, Work persistence |
| `multiagent` / `session.subagent` | existing agent tree, run handles and input routing; shared Agent child Session creation, round adaptation and retryable cleanup | Product runtime configuration, roles, tool selection, workspace implementation or persistent child policy |
| `conversation` | Product-neutral conversation identity, records, repository/catalog and replay contracts | Agent/AI message schema or Product-specific payload meaning |
| `transcript` | optional Agent/AI transcript profile, codecs, file/session lifecycle, context rebuild, compaction/retry/navigation mechanisms, and hidden reconstructable Model Input facts | Product compaction prompts, semantic summary policy, Product store selection, or provider transport outcomes |
| `context` | context items, packing, deterministic budget/accounting records, summary evaluation foundations | Product salience policy or model-specific estimation decisions |
| `tools` / `approval` / `policy` / `sandbox` | tool authoring and hosted execution mechanics, action policy evaluation, approval lifecycle, effects, execution-scope process-start authorization, and optional containment binding | Product risk defaults, executable/catalog admission, Product approval wording, arbitrary Product commands |
| `resources` / `extensions` / `capabilities` | resource discovery and precedence, package materialization mechanics, staged Extension/resource generations with exact live-registration retirement, capability composition, and coarse Capability graph contracts, planning, transactional Mount binding, live state, and read-only projection | Product-owned built-in content, trust decisions, activation policy, or Product-specific Provider behavior |
| `host` / `cli` / `events` / `presentation` | Product-neutral host lifecycle, RPC/JSON projection, runtime event contracts and reusable presentation | AppService tenancy, Channel protocol, Product grammar or final UI composition |
| `worker` | original attempt state/CAS/epoch authority; fixed five-stream value/replay and read/fence mechanisms; Supervisor, C5, opt-in, start-gate and receipt storage over their existing Journal profiles; intent-owned preparation and Rooted owner publication/retirement; fixed physical payload validation and four named repair profiles under caller custody | Product selection/approval or GC authority, native process custody, automatic history repair/retirement |
| `journal` | byte codecs, physical append/read/publication and rooted file bindings under caller custody | Worker semantic closure, Product policy or process settlement |
| `diagnostics` / `continuity` / `workspace` | shared diagnostic records/export, continuity provider composition, one-shot execution, and bounded session-owned process primitives | Product-specific recovery UX, business audit retention, protocol/server selection, Product artifact semantics |

Journal's optional `owned` module supports the original retained writer and
borrowed root IO through same-object exports and one forwarding borrow function.
Its supported profile retains fixed subsystem lock/hash hooks,
acquire/check/close and borrowed bind/cleanup, with IO cleanup before root release;
it adds no lease tracking, platform or authority. The optional HarnessWork
[Goal record backend](../harnesswork/key-designs/goal-record-store-convergence.md)
consumes this public seam and the original JSONL/codecs. Product still chooses
paths/labels, holds and closes the actual store; Coding's original GoalJournal
constructor and path function are thin bindings. Goal core has no IO import.

Journal's existing rooted IO module also owns bounded private UTF-8 text reads:
parent/file descriptor custody, private metadata/version checks, one binary read
and ordered cleanup reuse its original parent/version predicates. Coding retains
the acceptance limit, diagnostic/error binding, codecs and operator policy; its
three existing POSIX acceptance consumers still use one thin helper. This does
not add a store, repair authority or new admission requirement. See the
[A30 contract](key-designs/private-journal-parent-binding.md#cod-resp-goal-002-a30受限私有收据文本读取).


The bounded [Worker history convergence](key-designs/worker-history-responsibility-convergence.md)
has connected the Supervisor record/query/reopen/settlement path and the C5/opt-in/start-gate/receipt
history paths to these owners. Worker.payload now also owns the original physical
payload checks, named repair publication and precise remainder deletion. It reuses
Journal write loops and Resources file consumption; Product authorization and
Hosting process custody remain with their original owners.
Coding retains its public value facades, exact Product admission and a narrow
access adapter; the original Product/GC and Hosting authorities remain separate.
Other Worker profiles, Product evidence/preflight and broader cleanup coordination remain
in progress. The [execution record](coding-responsibility-convergence-progress.md)
separates responsibility migration from whole-system source reduction.
Worker history also owns caller-bound checkpoint read/publication, explicit
complete-append repair and tail rollback, plus the existing five-stream V1/V2
snapshot IO and byte-prefix verification. Coding retains the public value
facades and original Product/runtime/GC admission; strict reads and fences do
not gain automatic repair authority.

The original Worker C5 Coordinator also owns the complete Resume parent
observe/enroll/readback/seal and live-or-cleanup proof programs over its existing
state/CAS primitives. Coding retains its concrete input/effect-owner policy,
legacy public facades, same binding fields/lock and error projection. No new
state holder, native replay or stronger stopped-only rule is introduced; Core
has neutral defaults and Product configures only error construction. This is
responsibility migration with an explicit +49-line system cost, not deduplication;
see [A46](key-designs/worker-product-runtime-convergence.md#16-a46c5-resume-parent交接归原authority).

Worker history also owns the three fixed Windows opt-in, receipt and native
approval journal programs. Coding supplies pure value/error/limit profiles and
its original public thin facades. The original Resources WindowsJournalFileIO
retains file/ACL/marker custody; ordinary append binding registers its original
ACL and lock with the caller's standard ExitStack. There is no second store,
Product authorization or new generator boundary. This closes a prerequisite,
while the wider guarded fact-capture/publication path remains in progress;
see [A31](key-designs/windows-worker-semantic-convergence.md#13-a31三windows账本作为发布链必要依赖归位).

Worker.history also owns the complete pure Windows native crash transition and
witness-history predicate in its existing recovery facts module. Coding retains
its two policy modes, typed thin helper and original public value types. Normal
strict history and single-record journal validation remain distinct. This adds
no IO, native cleanup authority or new state; see
[A40](key-designs/windows-worker-semantic-convergence.md#17-a40恢复证明合同澄清与纯历史判据实际归位).

Worker.history also supplies pure reading of the four existing Windows stage-review
record formats using Resources' original RecordSchema. Coding retains the original
public dataclasses, own fields, semantic admission, fingerprints and all encoders.
There is no new I/O, authority or Product coordinator; MRO/private schema metadata
changes are explicit. Future dataclass field changes require wire-format review.
See [A43](key-designs/windows-worker-semantic-convergence.md#20-a43四类windows记录读取去重).

The existing canonical record reader also serves checkpoint, preparation,
cutover, launch-intent and stage-retirement values. Coding keeps each original
concrete class, own fields, encoders and semantic admission; Resources supplies
the original schema traversal. Original error/limit/shape differences remain
explicit policy, and the same reader's 15 existing families retain their default
contracts. See [A45](key-designs/windows-worker-semantic-convergence.md#21-a45其余五类canonical记录复用既有reader).

The same Worker history owner now supplies complete Windows Supervisor and C5
journal custody over the existing state engine, activation replay/projection and
Resource file IO. Coding keeps exact Product admission and a three-operation
access adapter to the original guard, currentness and borrowed-root authorities.
Supervisor marker/history and C5 per-revision committed-head protocols remain
distinct; no repair, additional root ownership or second history is introduced.
See [A32](key-designs/windows-worker-semantic-convergence.md#14-a32supervisor-与-c5-的完整-windows-托管路径).

Worker.payload also supplies Windows stage marker/read/direct checks and common
physical member retirement over the existing Resources native APIs and ACL.
Complete and partial proofs retain their distinct rules; Product root-intent IO,
GC/runtime approval and native process history remain with their original owners.
The private scope borrows descriptors and returns at the original intent boundary;
it adds no automatic retry, transaction log or new deletion authority.
The same Worker history owner serves six source-bound Windows semantic bases
via existing Resources RecordSchema and the original ledger folds. It now also
owns their pure reconstruction, retained replay and joint semantic checks in
`history/_windows_*` methods. Coding retains the concrete public value classes,
typed entry signatures, exact Prepared admission and fixed product/type/limit
bindings; it constructs the six original values in their original order. The
seven source checks, historical receipt policy, native decoder and distinct
observed/effect/launched meanings remain intact. There is no new source reader,
ledger or effect authority; see [KD010](key-designs/windows-worker-semantic-convergence.md).
Existing V2 and other envelope profiles retain their asymmetric capacity and
error behavior.
Worker history also owns the neutral Windows recovery-attempt value, pure exact
identity checks and fixed four-source projection. Its source traversal borrows
existing native IO, ACL and Resources consumption. Coding keeps the real public
value class and typed aliases, and the original two effectful Product root
lookups/ACL envelope and GC decision remain in their original lexical positions.
The 18-field asdict shape participates in semantic digests; future changes need
compatible versioning. Neither observations nor debt labels grant cleanup or
new launch authority.

The existing Session `product_composition_assembly` also implements the pure
relation between ordinary Session inputs and one already-admitted Worker.
It reuses the original compiler, Provider resolver and closure validator;
Coding supplies its Product identity, Consumer requirement and legacy error
profile through two thin public functions. Product/Worker admission, deferred
prepare, Graph visibility, C5 publication and platform cleanup keep their
original owners. See [KD-004 A17](key-designs/worker-history-responsibility-convergence.md#10-a17普通session与worker图关系归原session装配)
for the bounded contract; implementation evidence is tracked in the
[execution record](coding-responsibility-convergence-progress.md).

The bounded [child Session consolidation](multiagent/child-session-composition.md)
keeps Coding configuration in its Product adapter and uses the original Session
Host and queues. Failed child cleanup retains its handle and dependencies until
an explicit retry succeeds; parent release does not run ahead of the child.

The bounded [Session owner retirement handoff](plugin/session-owner-retirement-handoff.md)
uses a private Session integration function to report exact retired-family
evidence through the original management ledgers. Coding retains its evidence
source, fixed report policy and outer lock; Graph cleanup, family release and
fenced Product runtime disposal retain their original owners and retry state.

`runtime.await_owned_task` exposes the existing cancellation-safe owned-task
join used internally by Harness. Coding Continuity, AppHost Product and hosted
application cleanup now use that same function, without another task runtime.
The caller supplies an existing task and retains cleanup ordering, resource
ownership and retry state. Successful settlement returns its result, or
propagates the last caught caller cancellation; task failures and cancellation
retain the original join behavior. Worker joins with different failure
precedence and `journal.settled_io`'s independent native receipt remain separate.
The four focused [owned-task scenarios](../../../../tests/harness/runtime/test_owned_tasks.py)
cover result reuse and repeated caller cancellation with success, failure or
task cancellation; execution results belong to the implementation evidence.

Continuity's internal `_payload_staging` owns the complete private payload
write/pin/identity-checked-delete and cancellation settlement program. It uses
the original journal write-all loop and owned-task join with one pure diagnostic
label; it receives no Product authority or Code IO callbacks. Coding retains
source/cwd/limit admission and restore/abort/lease business. Private DTO aliases
preserve the Code import entry, with definition/reflection metadata moved.
The [bounded custody evidence](key-designs/continuity-payload-custody-convergence.md)
does not complete KD003 bytes import or eliminate the compatibility Path.

The bounded [Product composition input preparation](plugin/composition-route-inputs.md)
keeps owner grouping, structural supplied-binding checks, ordering and selection
seed construction in the existing private Session assembly. Coding retains its
original candidate-projection call, exact owner policy, restricted defaults and
error adapter. The original admission/compiler, workspace selector and owner
lifetimes remain separate; input preparation issues no execution authorization.

The optional [hosted Session control bridge](../apphost/session-control-bridge-convergence.md)
uses these existing Session operations and model-selection owners. AppHost
integration owns the AppService wire conversion; Coding supplies Product identity,
projection types and semantics, resume-input translation and observation hooks.
The same actual Product adapter retains its binding and close task. This adds no
Session/Agent/queue owner or reverse Harness dependency on hosted protocols.

Transcript's existing discovery implementation also owns pinned source checks
and attached-owner/disk observation in its private `_attached_discovery` module.
It directly reuses Directory, the original stable read-only file loader and the
same record codec. Coding keeps concrete Product/Session checks, GC identity,
the actual facade constructor/state and diagnostic/read-limit binding. The
attached owner is viewed through three read methods, without a proxy or new
admission; full SourceReader store/branch rules are not imposed on this path.
See [KD004 §12](key-designs/worker-history-responsibility-convergence.md#12-a29worker发现与附着观察归原transcript).

The [foreground Product ownership adapter](../apphost/foreground-product-ownership-convergence.md)
also reuses the existing Harness owned-task join. AppHost integration retains
only unpublished Session cleanup debt and the original Product runtime handoff;
Coding supplies its Session factory/catalog and Product policy. The borrowed
profile view has no close authority; no new Session business owner is introduced.

The bounded [local Wheel Source catalog convergence](key-designs/local-wheel-source-catalog-convergence.md)
keeps shared POSIX source capture and catalog coordination inside Package Product.
It directly reuses the original Journal and Resources controlled Source IO;
Coding retains concrete records, codecs, admission and Product policy. Existing
namespaces, epochs and Windows behavior remain authoritative. This introduces no
second catalog store or installed-inventory authority.
The same Package Product Source owner now coordinates the complete fixed Legacy
publication, binding append/replay, strict reopen and policy extension program.
Coding retains its real public values, original constructor, Product approval
query and thin typed entries; Resources owns private Source verification and
reuses the existing bounded consumption. Ordinary Source and Legacy share read
scopes while retaining distinct grammar and error contracts. This is a measured
responsibility transfer with system cost, not a claim of net source reduction;
see [A34](key-designs/local-wheel-source-catalog-convergence.md#11-a34legacy-source-目录的完整操作归位).
The same Resources package lifecycle also owns exact Product Source publication
and inspection for the existing builtin and Windows Worker consumers (A25).
Coding supplies fixed content/policy, display text and the live budget; direct
target failure traces remain distinct from staged controlled Sources.
Package Product also owns the Windows Worker immutable-receipt Source catalog
coordination (A26), sharing stable source reads and Plugin policy merging with
the existing POSIX catalogs. Windows keeps its receipt protocol and never uses
the POSIX Journal backend; Coding retains concrete records and admission policy.

The bounded [Worker candidate operation convergence](key-designs/worker-candidate-operation-convergence.md)
(A27) keeps the opt-in selection fact join and four install/update lifecycle
transactions inside the same Package Product component. It reuses original
Desired/GC/committed facts, runtime factory and lifecycle cleanup. Coding retains
approval/revocation, native platform interpretation, CAS and CLI projection;
no additional admission, execution or persistence authority is introduced.

The bounded [Plugin enablement compatibility capture](key-designs/plugin-session-lifecycle-convergence.md#11-d3-实现接缝完整兼容捕获路径候选)
uses Plugin Management for the existing four-lock desired/migration capture,
Resources for the original directory observations and fixed Windows pin, and
Journal for the shared regular-text read. Coding retains its value/error policy
and Product projection. This capture creates no new Ledger, registry or execution authority.

The subsequent Plugin Session integration places process owner references,
claim/incarnation and the original owner-evidence append/replay in
`session/plugin_lifecycle/`, reusing Journal. Package Product owns the original
startup registration, process registry and inactivity observation; Resources
retains directory preparation. Coding retains its deployed values, paths,
identity/error policy and thin adapters. Family acquisition, exact-owner retirement coordination and the outer close
barrier now run through stateless Session mechanisms on the same original
facade fields. PM assembly owns GC sealing and the explicit settled direct-host
handoff/completion. Coding retains domain policy, values and projection;
KD-007's lifecycle cluster is implemented, while broader startup/bootstrap
convergence remains within the active Goal.
The first [startup assembly slice](key-designs/startup-session-assembly-convergence.md)
now places the single ephemeral owner-publication algorithm in Session's existing
Plugin integration. Original AgentProductSession hooks consume optional empty-by-default
bindings. Coding selects domain receipts and retains actual retirement qualifications;
its assembly delegates to the same ordered lease-set fanout. Persistent evidence,
Graph, registration and authorization remain with their original owners.
Session also owns the original shared construction cleanup algorithm and the three
fixed Plugin composition cleanup lifecycles (failed preparation, untransferred
preparation and published assembly). They use the same adopted facade fields,
original Resources runtime and Session leases. Coding keeps domain labels,
selection and binding; its old cleanup exports are compatibility imports.

Resource Catalog also owns the bounded Loader-receipt to source-spec transfer
in its private `_loader_inputs` module. Initial bootstrap, refresh, Product
preview and local discovery reach it through the same public Coding adapter.
It uses the original native/package/embedded specs, verified handles and capture;
the original Adapter retains independent later admission/time checks and cleanup.
Coding keeps canonical source policy, trust/plan compilation, clock and error
projection. This adds no discovery, storage, Graph or fact authority. See
[KD009 §12](key-designs/startup-session-assembly-convergence.md#12-loader回执至catalog输入共同准备的完整交接)
for the complete transfer contract and the ten unchanged baseline test failures.

Approval also owns the original ordered Plugin Resume parent coordination in
its private `_plugin_resume_parents` implementation: checking both enrollments,
retryable enrollment and sealing exact membership. It directly reuses the two
native Plugin journals; no second parent registry, grant or cross-journal
transaction is introduced. Coding retains its actual parent DTO and intent
checks, journal path/writer-capability binding, diagnostic values and audited
LSP/Arch settlement policy. Original snapshot locking and tail repair remain.
See [KD009 §13](key-designs/startup-session-assembly-convergence.md#13-a28双plugin-resume-parent协作归原approval).



## Accepted Capability Graph Target (Mount Runtime Implemented)

The implemented owner table above remains authoritative for current code. The
accepted [Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md)
decision adds a coarser architecture. Its immutable Definition, Requirement,
Bundle Provider declaration, pure planner, transactional Binder, live per-graph
Runtime, and read-only Projector now exist. `harness.workspace` is a
Definition / Provider / Consumer slice: Consumers receive only declared
filesystem facets or the authorized process-launch port, never the graph
Runtime, raw process host, approval gateway, or sandbox backend.

`harness.resources`, `harness.session` contract version 4, and
`harness.workspace` are production-mounted with `harness.model_input` in the
single Session-owned graph. Model Input directly requires the Session transcript
trio; Session directly consumes Resources and optionally consumes Product-
admitted Workspace. Both generic and Coding plans have only Model Input as a
root; absent Workspace input produces no node.
The Resources Session/bootstrap/sealed Bundle maps the
private resource, prompt, skill, Tool-pack, and Command-pack Profile selections
through focused Consumers. Synchronous bootstrap constructs one root-owned
candidate; the Resource Provider transfers that same candidate to the Graph
instead of constructing a peer binding. Long-lived controllers route through
stable focused ports and generation-scoped Consumers after publication.
Resource content remains call data and changes only the scoped source
publication reference, not the Mount generation.

The combined `harness.session` Provider transfers two already-bound candidates:
the sealed `interaction.side_question` selection and the indivisible transcript
Store/Profile/Compaction lifecycle binding. It does not reconstruct either
Profile binding. Generation-scoped Consumers own live calls after publication;
Model Input and compaction route through a stable narrow port rather than a raw
Store or Profile binding. Shutdown joins active work, publishes the auxiliary
transcript index, and then releases the transcript binding with retryable
retirement semantics. A second focused Session Consumer routes resource,
skill, prompt, Tool-pack, and Command-pack calls through the declared Resources
dependency; the old direct Resources Consumer captures are no longer a
production path. Process-scoped continuity remains outside the Session Graph
and is exposed through the accepted, typed `StableContinuityReference` issued
by the one focused `ContinuityHub` owner.

CLA8 closes the legacy peer-authority path. Managed Product construction binds
one root-owned Resource candidate before Extension discovery, attaches final
admitted Profile facts to that same candidate, and transfers it once to the
Session Graph. The former late candidate factory and construction callback no
longer exist, and executable architecture gates forbid their return.

The Workspace Bundle receives only Product-admitted, root-bounded filesystem
operations and an already-authorized process launcher. Coding constructs one
workspace-scoped binding fingerprinted from the effective authority ceiling;
the combined Session Provider declares one optional aggregate dependency and
projects two narrow Tool/process facets. The Session captures typed Consumers
in the same Graph publication window. Long-lived callers retain lease-aware
proxies, so Session retirement invalidates previously obtained operations and
launchers even when the Workspace node itself is reusable. Raw
process hosts, policy and approval gateways, Sandbox state, and their cleanup
ownership stay outside the Bundle. LSP shares the same authorized launcher
through the typed Consumer path rather than binding a second launcher.

The generated [Harness Capability Catalog](capability-catalog.md) is the
source-backed coverage projection. A target Capability is not reported as
implemented there until its Definition, Provider, requirements, and Consumers
all exist and pass the architecture gate.

The initial top-level Harness Capability IDs are `harness.workspace`,
`harness.resources`, and `harness.session`; current Coding-owned examples are
`coding.lsp` and `coding.arch`. Runtime Profile slots remain finer internal
Binding Facets rather than additional top-level graph nodes.

| Accepted target responsibility | Current implementation status |
| --- | --- |
| plan dependencies, closure, order, and validation | `RuntimeCapabilityGraphPlanner` is implemented as a pure planner under `loushang.harness.capabilities` |
| bind final nodes transactionally and reuse unchanged binding signatures | `RuntimeCapabilityGraphBinder` stages Provider values and owner-scoped registrations, atomically publishes successful generations, reuses unchanged signatures, and reverse-retires replaced nodes |
| own live Mounted Capability state, generations, and scope leases | `RuntimeCapabilityGraphRuntime` owns one Product/runtime graph and issues narrow, generation-scoped Consumer facet leases; it is not global mutable state |
| project read-only graph snapshots, explanations, and impact paths | `RuntimeCapabilityGraphProjector` exposes the committed `MountGraphSnapshot`, separate registration inventory, explanations, dependency/dependent paths, and impact without live values |

Mount Graph and registration inventory remain separate authorities and clocks.
The Mount snapshot references the existing Runtime Profile fingerprint rather
than copying its selections or changing the persisted Session-header contract.
No global mutable registry, second graph projector, or effective-runtime
selection authority is introduced.

Extension reload has its own narrower generation clock. One stable
`ExtensionRunner` stages declaration/resource discovery and owner-scoped live
bindings, synchronously publishes the selected Extension composition with the
resource bundle, then reverse-retires the replaced generation. It reuses
`RegistrationLease` and `RegistrationScope`; it is not a second Capability
graph or runtime projector. Historical model-visible Tool schemas remain owned
by committed Model Input facts rather than the current Extension generation.
The runner freezes candidate declaration facts, while the Product/Session
composition root owns the accepted declaration baseline and injects the pure
admission preflight. Graph-owned input drift is restart-required before live
candidate effects; content-only reload remains source-local and does not
publish another Mount generation.

The initial live Binder supports direct dependency facets. A planned
`stable_reference` edge fails closed before Provider construction until a
separate stable-indirection and refresh transaction is implemented; the Binder
does not satisfy that declaration by leaking a concrete refreshable value.

## Dependency Direction

The intended direction is:

```text
Product composition root
        -> Harness public contracts and optional profiles
        -> Agent / AI public contracts where an optional profile requires them

AppService / Product host
        -> Product narrow ports
        -> Harness Session or Work adapter

Harness -/-> Product, HarnessWork/Work, Method, Channel, Harnesstui, or Product UI
```

`session` is an assembly owner and therefore has high fan-out. High fan-out is
acceptable at that composition boundary; cycles, Product imports, and lower
layers importing the Session public barrel are not.

## Session Assembly Shape

The standard Agent-session composition has three explicit phases:

1. Foundation: diagnostics, tools, resources, navigation, and bash.
2. Maintenance: compaction and retry mechanisms with Product policy inputs.
3. Product bindings: model, identity, command, extension, maintenance, and
   inspection bindings.

`SessionCompositionPorts` stores those phase inputs as cohesive records.
`SessionComposition` stores the corresponding phase results and retains flat,
read-only compatibility properties for existing consumers. No generic bridge
or second coordinator is introduced merely to forward callbacks.

## Public API And Loading

`loushang.harness` is the narrow base entrypoint. Optional, larger profiles such
as `loushang.harness.session` and `loushang.harness.transcript` preserve their
published symbols through lazy facades: importing a profile does not construct
or import all implementation runtimes, while accessing a symbol loads its owner
module and caches the result.

Compatibility facades remain stable while large implementation pipelines are
split internally. The implemented dependency direction is:

```text
resource loader facade -> package policy
resource loader facade -> snapshot pipeline
                            -> context discovery
                            -> built-in discovery -> descriptor parsing
                            -> temporary discovery -> filesystem discovery
                                                       -> descriptor parsing
                            -> other source coordinator
                                 -> filesystem discovery -> descriptor parsing
                                 -> package policy
                            -> resolution -> precedence policy

runtime profile facade -> types + admission + resolution + binding + standard slots
admission / resolution / binding / standard slots -> profile types

Agent settings manager -> typed settings patch + settings schema codec
typed settings patch -> settings schema codec field rules
settings schema codec / typed settings patch -> Agent settings types

workspace read tool + Host prompt input -> workspace image payload owner

tool definition owner -> execution bindings
session execution scope -> tool execution host -> structural definition port
```

Context-file ancestor traversal, configured filename precedence, descriptor
construction, and nearest-context selection belong to
`harness.resources._loader_discovery_context`. Package-root and filter
normalization, descriptor-selection patterns, root diagnostics, and per-root
resource accounting belong to `harness.resources._loader_package_policy`.
Source-neutral prompt/skill frontmatter projection, descriptor construction,
and skill metadata validation belong to
`harness.resources._loader_descriptor_parsing`; it performs no filesystem or
package-resource I/O.
Filesystem directory traversal and reads, recursive skill discovery and ignore
rules, extension entry lookup, and theme JSON validation belong to
`harness.resources._loader_discovery_filesystem`. External-package and
project/user source coordination remain in `_loader_discovery`; the coordinator
consumes filesystem discovery and package policy. Temporary runtime-path
resolution, single-file/directory dispatch, source metadata, and path diagnostics
belong to `harness.resources._loader_discovery_temporary`. Built-in package
traversal, logical package paths, resource reads, and built-in category
diagnostics belong to `harness.resources._loader_discovery_builtin`. The snapshot
pipeline calls the source coordinator, context discovery, built-in discovery,
and temporary discovery directly but does not depend directly on their leaf
policies. Context discovery, built-in discovery, temporary discovery,
filesystem discovery, descriptor parsing, and package policy do not depend on
discovery coordination, resolution, the pipeline, or the public loader facade.
Loader option normalization and system-prompt source resolution remain with the
public loader owner rather than discovery coordination. The loader projects its
normalized state into one immutable pipeline-owned discovery request. The
pipeline owns candidate-source aggregation, including the single expression of
temporary, built-in, external-package, user-global, and project-local candidate
order; discovery diagnostic order remains an explicit, separate contract.
Resolution never imports any discovery owner or package policy, live profile
binding never imports profile resolution, and internal leaf modules never
import their public facade. The tool execution host consumes a private
structural definition port; `harness.tools.execution` does not import the
`ToolDefinition` owner in `harness.tools.core`.
The Agent settings manager depends only on the explicit codec/patch ports
enforced by the architecture tests, not on field-level serializer helpers.
Image MIME validation, header dimensions, base64 encoding, inline limits, and
resize preparation belong to `harness.tools.workspace.image_payload`; neither
prompt input nor the read tool owns a second copy of those rules or the
inspect/resize/recompute sequence. Consumer-specific omission and presentation
policy remains with Host prompt input and the read tool.

## Opt-in Product Transcript Continuation

The private [Transcript continuation profile](../../../../src/loushang/harness/transcript/_resume_continuation.py)
owns the local first-input stage/commit/unknown/publication fence and guarded
history-update program. It runs on the same Product Session instance and calls
the original lifecycle/Artifact-aware committer and authoritative lookup. The
standard ProductTranscriptSession remains unchanged; no second Writer, ledger,
controller, pending lock or execution authorization is introduced.

Coding retains real public classes and wire/data records, namespace/version/
canonical hashes, Plan/source/owner/composition policy, logical-query decoding,
neutral-record classification and runtime-ready publication. The profile reads
borrowed logical identities and Product-classified history, not a default
Transcript extension schema. Historical success never grants current execution
or retry authority. Ten ephemeral defaults have a single profile definition;
private Manager annotations/MRO/method source changes are bounded compatibility
limits. See the [boundary](product-transcript-session-boundary.md#opt-in-resume-continuation-profile)
and [KD009 implementation](key-designs/startup-session-assembly-convergence.md#19-a58恢复首输入提交与发布边界的完整候选).

## Ordinary Worker Preparation And Windows Attempt Custody

The implemented internal [Session Worker integration](../../../../src/loushang/harness/session/_worker_provider.py)
now drives native preparation in the same Task and owns the returned
Graph/Prepared handoff, facet visibility, commit and release-once integration.
The original Graph remains the publication authority. The
[Worker preparation programs](../../../../src/loushang/harness/worker/_ordinary_prepare.py)
borrow the original Coordinator, Supervisor, Router, Hosting and resource
objects. Worker keeps a selected manifest opaque while passing it to its
original provisioning store; concrete Product selection and validation remain
with their upper owner, avoiding a Worker-to-Package-Product dependency. Native
acquisition cleans its own failed, unreturned attempt; Session
owns failure cleanup after the attempt is returned. POSIX and Windows retain
their distinct settlement and publication contracts, without another task,
execution engine or recovery state.

Selected POSIX payload materialization uses the original PayloadStorage through
[Worker payload preparation](../../../../src/loushang/harness/worker/payload/_selected_payload.py).
Windows physical stage work remains in the original
[stage IO owner](../../../../src/loushang/harness/worker/payload/_windows_stage_io.py),
including live root/ACL/handle lifetime at completion. No second file engine is
introduced. Product checks and selection remain at their original call points.

The existing [Package Product boundary](../../../../src/loushang/harness/package_product/_worker_windows_attempt.py)
now owns fixed Windows intent read/inventory/commit, provisioning load/CAS and
the outer cleanup-fact acquisition sequence under the original GC/currentness
scope. It uses the same original Resources receipt writer, Journal, C5 and
Hosting authorities. It adds no writer, journal, retained descriptor or fact
index. Coding retains exact receipt/request/selection policy, error and layout
bindings, and real public record/Prepared dataclasses with their own fields.

The same Package Product boundary also owns the fixed inner orphan/runtime
join, recovery-fact acquisition and retirement-root observation. Both payload
and native inventory readers reuse one GC/currentness/root-borrow program.
The original registry-before-GC lock order, normal-only final checks and
supplied empty native-fact semantics remain. Worker StageIO owns the complete
payload directory inventory using original Resources primitives; it observes
crash-retained identities without certifying child ACLs or clean state.
Coding retains exact admission, name/parser/error bindings and the original
public record construction and repair policy. Orphan native errors propagate;
the separate offline observation policy may report unknown. These reads grant
no new cleanup authority. Other offline/backup/recovery decision paths and the
rest of Coding remain convergence work; this does not make all callers thin.
The bounded implementation and limits are recorded in
[KD008 §22](key-designs/worker-product-runtime-convergence.md#22-a56联合方向接受实际接通与主线同步)
and [§23](key-designs/worker-product-runtime-convergence.md#23-a57完整windows查询取得与同构reader复用).

## Architecture Gates

`make check-harness` is the integration gate. The architecture tests enforce:

- an acyclic internal Harness dependency graph;
- no Session-module import from the Session public barrel;
- one-way Harness, Work, and Channel dependencies;
- explicit Agent/AI import allowlists for optional profiles;
- one-way resource loader, context/built-in/temporary/filesystem discovery,
  descriptor parsing, package policy, runtime profile, and Agent settings
  internals with an exact manager-to-codec/patch import allowlist;
- one-way tool-definition-to-execution dependencies;
- one shared workspace image-payload owner consumed by Host prompt input and
  the read tool;
- Product-neutral Harnesstui and shared runtime owners;
- canonical coarse Capability IDs and Mount terminology in architecture
  documents, without representing Product, Plugin, Package, or Extension
  identities as graph nodes; and
- the capability-runtime convergence inventory, exact existence of implemented
  graph owners, no-second-runtime rule, and narrow graph API parameters.

New boundaries must update this map when they change current ownership. A
migration ledger alone is not sufficient evidence of the resulting boundary.

## Product-Owned Exclusions

The following remain Product-owned unless a separate accepted boundary record
demonstrates multiple real Product implementations:

- prompts, model defaults, domain vocabulary, and policy defaults;
- user-intent parsing and Product operation resolution;
- Method-to-Work preparation and Product Work execution;
- Product event vocabulary and final UI projection;
- Product storage roots, retention policy, and artifact meaning;
- cloud tenancy, billing policy, credentials, and AppService authorization.

## Document Authority

When documents disagree, use this order:

1. current source and architecture gates;
2. this current owner map;
3. accepted boundary documents linked from the Harness README, including the
   Capability dependency and Mount lifecycle decision;
4. proposed architecture documents;
5. migration plans, ledgers, slice status, and historical inventories.

Completed migration records should be retained for traceability but must not be
read as current ownership specifications.


A48有界更新：原AppHost local的私有应用startup层承接原Code外层托管寿命，保原两层
custody与同一Code实例；Coding保Launch/constructor、产品根与attempt/managed政策。
原LocalStartup/phase/wait直接共用，无新owner/记录。Code−105/接收+201/系统+96，
G17迁前同故障与17项managed权限限制仍在，不外推全链或整个Goal。见[专项接受](../apphost/local-startup-convergence.md#a48完整外层应用寿命归原apphost2026-11-09)。


A49有界更新：固定snapshot批停及全部原清债程序归原AppHost managed stop；Code
StopAll保真实入口/构造/JSON呈现，同一self/entry/task，不新建执行框架或事实权威。
原单服务stop整体不改，确认/预算授予仍在Code；+20为接收成本而非净去重。19项原失败/
准入受限项仍未通过；G17本轮原条件两次过但历史超时根因未证。见[专项边界](../apphost/managed-stop-batch-convergence.md)。


## Opt-in Live Session Continuation

The private [live Session profile](../../../../src/loushang/harness/session/_resume_continuation.py)
is selected by Coding's existing AgentSession and inherits the original
AgentProductSession. It owns the fixed candidate/input/publication/once-dispatch
program on the same instance, reusing the original Graph, Prompt, Request Evidence,
Transcript and Host owners. It adds no controller, queue, Writer or persistent
recovery authority. Default AgentProductSession behavior stays unchanged.

Coding retains real candidate/publication dataclasses, current selection/receipt
and digest policy, Worker settlement, owner claims/receipts, Tool activation and
Product ready markers. Core borrows readonly logical views, never historical
execution permission. Eight local fields remain single-owned; their private keys
and method defining module change. Four existing test observations follow the
renamed dispatch flag with assertions preserved. See [KD009 A59](key-designs/startup-session-assembly-convergence.md#20-a59原session接管live恢复协调程序)
for the exact costs and current verification limits; installed code is not by
itself a completed whole-Goal acceptance.


## Selected Worker Attempt Lifecycle

The implemented private [Worker lifecycle program](../../../../src/loushang/harness/worker/_product_attempt_lifecycle.py)
owns the original selected-attempt start, failure reclaim, latch-first rollback,
recovery and normal close sequence. Coding's real Canary object inherits it,
keeping one state/operation lock and the original injected Coordinator,
Supervisor, Router, native, domain and cleanup authorities. No second activation
engine, journal, controller or resource owner is created.

Coding retains selection/binding admission, real Status/Error classes and own
fields, explicit public signatures and domain output policy. Ordinary Graph
handoff has different C5 publication and failure semantics; the programs borrow
the same existing owners without a generic phase dispatcher. Current integration
and bounded compatibility evidence are recorded in [KD008 A61](key-designs/worker-product-runtime-convergence.md#24-a61在已接受联合方向内接通完整canary生命周期).
Remaining binder/native-selected work and full Coding convergence are not completed.

## Selected Worker Single Query

The private [Session query program](../../../../src/loushang/harness/session/_worker_operator_query.py)
coordinates the original POSIX operator query from Product runtime activation
through final disposal. It uses the original Worker Supervisor, C5, Hosting,
selected-source IO and Session Graph. Graph preparation returns before the
separate C5 publication and original Consumer query; all original acquisition,
cleanup and exception boundaries remain in that single plain async program.
It adds no controller, authority, journal, cleanup task or phase dispatcher.

Coding retains existing Session/Product selection, public entry/error,
query contract and provider policy, query-only settings and thin semantic
adapters. Its ordinary and operator adapters share selected-source materialization
and native field projection while preserving their different native reads.
The exact integration cost and bounded evidence are in
[KD008 A63](key-designs/worker-product-runtime-convergence.md#26-a63完整单次查询接通原session);
controlled ports do not establish real native settlement or whole-Goal completion.

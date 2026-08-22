# Review: Unified Plugin Lifecycle And Coding Pluginization Delivery Plan

## Verdict

**PLC0 accepted locally; recommend the coordinating plan with two explicit UPA
sequencing revisions.**

The plan correctly gives the common lifecycle priority over a
`coding.base`-specific loader, uses `coding.base` as the Resource-heavy
production sample, and retains `coding.lsp` as the first Provider/Graph proof.
PLC0 restored the source-backed architecture baseline at `25cfc170`; see
[Plugin Lifecycle PLC0 Baseline](plugin-lifecycle-plc0-baseline.md). PLC1A's
inert authoring primitives are implemented at `2ebac237` and hardened against
the implementation reviews through `8a3c94fd`; see the
[PLC1A baseline](plugin-lifecycle-plc1a-baseline.md). PLC1B is technically next
after issue attachment and independent review. This review does not approve the
security, lifecycle, production cutover, or public SDK slices as one batch.

The two sequencing revisions are now accepted in the authoritative UPA delivery
order:

1. move the minimum durable `PluginManagementService` control core before the
   `coding.base` production cutover, while leaving rich management projections,
   isolation and GC in final closure; and
2. move production `coding.base` after `coding.lsp` and before `coding.arch`,
   while keeping the stable SDK gated on LSP, Base and Arch evidence.

The initial review found nine high-priority risks; five later PLC1B review
rounds found additional declaration, evidence and lifecycle freeze gaps. The
plan and normative PLC1B Contract include their required corrections. None
requires a second Graph, Resource runtime, Profile resolver, Plugin-owned
approval store, registration owner, or effective projector.

## PLC1B First Documentation Remediation

Three independent read-only reviews of the PLC1B documentation increment found
no P0 but rejected it as an implementation freeze because several P1 contracts
were incomplete or contradictory. The current remediation applies their shared
requirements:

1. one `PluginDeclarationSourceGroup` owns an exact sorted reservation closure,
   closes over every index entry sharing its source, is decoded/evaluated once,
   and all non-overlapping groups join before one preflight finalization;
2. group-owned `data_only`/`execution_preflight` gates are distinct from final
   `document_decoded`/`in_process_evaluated` evidence, executable evidence
   requires the durable group consumption receipt, and non-accepted preflight
   outcomes create no token, reservation, or group;
3. Contribution Index and Declaration IR advance to runtime-only v2, with draft
   v1 rejected rather than retained as a peer parser;
4. direct self-requirement fails in the payload codec, while transitive cycles
   remain solely with the existing Graph Planner over the PLC4 complete set;
5. exact Tool/Command owner admission returns typed requirements, one Product
   requirement set feeds Provider roots, and post-Graph typed capture remains
   the only external Consumer path;
6. Capability Bundles own tool-runtime support while independently selected
   model-visible definitions/registrations remain sibling Tool-owner
   contributions;
7. semantic fingerprint v1 is a precisely scoped pre-owner/pre-Host-
   normalization conformance diagnostic; and
8. PAP4R makes the Resource/Tool/Command bridge explicit, while PAP8 source
   implementation remains PLC8 work.

This section records the first remediation, not approval. A fresh three-agent
review of `7b2062bd` completed and produced the second remediation below.

## PLC1B Second Documentation Remediation

Three new independent read-only reviews of `de7006d5..7b2062bd` again found no
P0, but all rejected the PLC1B-1 freeze. Their shared and independently verified
P1 corrections are now incorporated:

1. `preflight()` builds a non-authoritative proposal; pending exposes only
   canonical subjects, and approval is followed by a fresh full revalidation
   before accepted groups/reservations/token exist;
2. only `PluginDeclarationSourceGroup` owns the group gate; reservations retain
   only its immutable ID/fingerprint;
3. PLC1B proves document-only single finalization, while mixed document/in-
   process input aborts `execution_not_consumed` with zero finalization; the
   successful mixed proof moves to PLC3;
4. Definition/Builder returns declarations only, and the Host evaluator/
   coordinator exclusively attaches evidence and constructs a Batch;
5. the accepted aggregate has only `FINALIZED`, `ABORTED` and `EXPIRED`
   terminals; later-group failure never revives a consumed decision;
6. Candidate `decision_id` becomes strict tagged evidence, group execution
   subject advances to v2 with v1 rejection, and canonical JSON matches the
   actual `ensure_ascii=True` encoder;
7. the document envelope, locator-stage boundary and declaration/runtime source
   type names are frozen precisely;
8. UPA now normatively orders LSP, Base and Arch; Tool ownership no longer uses
   a Tool/Resource joint owner; and
9. the Product Consumer requirement set preserves per-Consumer constraints and
   provenance instead of performing an undefined lossy merge.

This remediation also requires fresh independent review before PLC1B-1 source
work begins; it does not self-approve the implementation freeze.

## PLC1B Third Documentation Remediation

Three new independent read-only reviews of `491817aa` again rejected the
PLC1B-1 freeze. One reviewer classified the package-hash fixed point as P0; the
other two classified the surrounding exact-record gap as P1. The corrected
contract now resolves the shared substance:

1. package-internal `sourceDescriptorFingerprint` excludes package revision;
   Host-only `sourceGroupFingerprint`, attempt-specific `sourceGroupId`, Batch,
   Evidence and Candidate add revision/runtime provenance after publication;
2. the new normative PLC1B Contract freezes exact Source/Index/Declaration/
   Document/Subject/Decision/document-evidence/candidate fields, hash domains,
   canonical bytes and distinct version diagnostics before code changes;
3. static Document/Source records no longer claim to exact-match dynamic
   Product/scope/configuration. Host-created group/evidence records bind that
   accepted context;
4. each accepted attempt receives a unique `preflightUseId`; document evidence
   and future execution receipts bind it and the attempt-specific group ID, so
   aborted evidence cannot cross a fresh preflight;
5. the aggregate adds group claim/in-flight fencing, monotonic expiry, host-
   epoch rejection and deterministic process-local terminal tombstones;
6. the decision selection view has independent `decisionRecordVersion: 2` and
   `subjectSchemaVersion: 2`; pure preflight/instance identity is frozen before
   PLC2, which later owns its durable lifecycle without redefining it;
7. PLC1B accepts no executable declaration ingress, and the old public subject/
   finalize/rollback routes are deleted or private-scoped rather than wrapped;
   Coordinator/evaluator placement remains in the higher `plugin_authoring`
   layer to avoid a dependency cycle; and
8. PAP2/PAP3/PAP5 now distinguish the future durable Approval journal from the
   current Session grant store, persist import/activation use start states,
   conservatively fence polluted Hosts, and require fresh decisions for retries.

This is the third remediation, not approval. A fresh independent review must
confirm the exact PLC1B Contract and cross-document corrections before PLC1B-1
source work begins.

## PLC1B Fourth Documentation Remediation

Three new independent read-only reviews of immutable baseline `1dde5706` all
returned `NOT READY`. One found a P0 package-digest fixed point in the existing
Capability Provider payload; the others found no P0 because PLC1B remains
inert, but all agreed that the P1 contract gaps would produce incompatible or
unsafe implementations. This remediation incorporates their combined blockers:

1. package-internal `CapabilityProviderDeclarationPayload` and
   `PluginSymbolReference` advance to v2 and contain no package digest; only a
   Host-resolved view binds the published package digest, with a real document-
   backed Provider fixture proving no fixed point;
2. Index, Declaration, Subject, Evidence and Candidate now have complete
   domain-wrapped fingerprint inputs, strict wire types, diagnostic precedence,
   and golden canonical-byte/digest requirements; Candidate inputs are
   reconstructable from its own owned fields;
3. `PluginSelectionPlanV2` is the single Product context/trust/configuration/
   authority authority. Product owns overlay/delete/secret normalization and
   PLC1B receives an exact resolved map with versioned non-secret secret refs;
4. preflight reads decisions only through an Approval-owner lookup port. The
   production pre-PAP2 adapter is pending-only; a private test double may prove
   mixed-source abort routing but cannot consume, import, or create evidence;
5. the aggregate now uses `ACTIVE_OPEN`, explicit un-cancellable/help-
   completable closing states, atomic claim/in-flight updates, deadline-aware
   finalize CAS, CAS-loser candidate destruction, bounded tombstones and exact
   race regressions;
6. the canonical manifest boundary detects duplicate keys, rejects unsorted
   wire input and preserves typed codec diagnostics; architecture inventories
   expand through `plugin_authoring` and freeze the sole verified document-read
   callpoint; and
7. PAP2/PAP3 must transactionally create consumption plus its use reservation,
   linearize execution start against close without callbacks under the
   aggregate lock, and persist import-realm/host-boot identity for recovery.

This fourth remediation still does not self-approve PLC1B-1. Source migration
may begin only after a narrow independent freeze review reports no P0/P1 and a
tracking issue is attached.

## PLC1B Fifth Documentation Remediation

Three independent read-only reviews of immutable baseline `0b770267` all
returned `NOT READY` with no P0. The package-digest fixed point was closed, but
the reviewers found remaining P1 implementation ambiguity. This remediation
incorporates their blockers:

1. Index v2 independently owns `contributionExecutionModel`; Provider payload
   v2 removes its redundant configuration fingerprint and freezes required
   factory plus required nullable disposer, while Host symbol validation remains
   structural and defers loading;
2. the Subject golden fixture now uses its matching in-process Source digest;
   Candidate construction exact-matches package/evidence/Batch/group membership;
   Product owns raw-secret classification; and every non-version codec failure
   has one finite diagnostic code and nested priority;
3. manifest and DeclarationDocument schemas share one low-level strict JSON
   primitive, Coordinator owns exactly one verified document read, and
   architecture inventories count concrete calls so a second read/decoder in an
   already-allowed function is detected;
4. deadline claims atomically enter expiry, a process-owner reaper is installed
   before accepted publication, only the actual execution unit may settle its
   claim lease, and close waits for physical completion rather than treating a
   cancellation request as completion; and
5. PLC3 execution requires an aggregate start permit before the atomic Approval
   consume/use transaction, adds `CANCELLED_BEFORE_START`, freezes exact
   Reservation/Receipt boot and realm fields, and makes `hostEpoch` the local
   typed name for the same `hostBootId` rather than a third identity.

This fifth remediation is not self-approval. The next review, if requested,
should be narrowly limited to these five corrected boundaries; PLC1B-1 source
migration remains blocked until it reports zero P0/P1 and a tracking issue is
attached.

## Review Scope

The review compared the plan against:

- [Unified Plugin Architecture](unified-plugin-architecture.md), including its
  parse/declare/select/bind-once invariants, Coding decomposition, lifecycle,
  security-revoke, management, and UPA0-UPA8 sequence;
- [Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md)
  and its [self-review](plugin-authoring-primitives-plan-review.md);
- existing Capability Definition, Provider, requirement, Graph Planner/Binder,
  Registration Scope and Resource-generation contracts;
- current `PluginContributionReservation`, `PluginDeclaration`, selection,
  package revision and mount contracts;
- current `coding.bootstrap`, CLI built-in Tool registration, Coding Tool-pack,
  LSP deferred runtime, Arch Tool registration and prompt assembly paths; and
- the source-backed architecture bypass inventory.

This is a coordinating-plan self-review. PLC2, PLC3, PLC4, LSP/Base/Arch
cutovers, and removal/data-deletion paths still require fresh independent
source-backed review when their actual code exists.

## Findings

### P0-01 — Common lifecycle must precede the `coding.base` cutover

**Evidence.** `coding.base` needs package identity, declaration, Product
selection, Resource/Tool/Command owner admission, Session publication,
disable/update/retirement and explanation. Implementing only a Coding loader or
CLI flag would skip most of that path.

**Risk.** A base-specific implementation would create another parser,
selection source, registry and unload protocol, reproducing the multi-route
problem the UPA is intended to remove.

**Correction accepted.** PLC0-PLC4 build the common minimum path first. PLC1
may compile a no-effect shadow package to drive schemas, but PLC6 is the first
live Base cutover.

### P0-02 — Unified lifecycle cannot mean one global live transaction

**Evidence.** Existing CLA and Capability boundaries give Resource generations,
Capability Graph Mounts, Extension generations and Registration Scopes
different exact owners and publication clocks.

**Risk.** A global Plugin transaction that binds or disposes all contributions
would become a peer publication authority, obscure rollback and require unsafe
cross-owner restoration.

**Correction accepted.** The plan treats the Product Session as the startup
visibility boundary while each exact owner stages, publishes, drains and
retries its own generation. Plugin management aggregates references and
outcomes only.

### P0-03 — Management control cannot remain entirely after the SDK

**Evidence.** A Plugin cannot honestly support install, enable, disable, update
and uninstall while CLI/settings adapters mutate selection and package state
independently. The accepted UPA currently groups all management work in UPA8.

**Risk.** `coding.base` could be described as pluggable while lacking one
durable desired-state transition path, atomic cutover, crash recovery or exact
retirement status.

**Correction accepted.** PLC2 moves only the minimum typed management command
and state-transition core earlier. PLC9 retains UI/RPC/SDK projections,
marketplace concerns, isolation, GC, repair and destructive data cleanup. This
is a required accepted sequencing revision, not an implicit reinterpretation
of UPA8.

### P0-04 — `coding.base` must not become a synthetic Capability

**Evidence.** Base prompts, Skills, Tool packs and Command packs aggregate into
existing `harness.resources` and `harness.session`. They do not own an
independent runtime state or typed Consumer service.

**Risk.** A `coding.base` Graph node would duplicate Resource ownership and give
a misleading Graph lifecycle test while increasing startup and disposal
coupling.

**Correction accepted.** `coding.base` remains a Plugin ID and Composition Set
member only. LSP remains the complete-Bundle Graph proof.

### P0-05 — Data-only and executable declaration sources need one IR but different gates

**Evidence.** Current declaration reservations support only
`capability_provider` with an `in_process` entrypoint. Base resources do not
need arbitrary Python evaluation, while LSP Provider construction does.

**Risk.** Forcing Base through Python needlessly expands import and approval
risk. Giving document declarations a separate IR would create identity and
compatibility skew.

**Correction accepted.** PLC1 introduces `document` and `in_process` source
arms that produce the same tagged IR v2. Within one preflight context,
selecting any contribution closes its group over every index entry sharing the
exact source/revision; the group binds its gate, sorted closure and
configuration-map fingerprint, while reservations retain only the group
fingerprint. Pending exposes proposed subjects only; approval is followed by a
fresh full preflight before an accepted group exists. `data_only` carries no
execution subject, while `execution_preflight` carries one positive group
decision. Those gates do not become final evidence: document decoding emits
`document_decoded`, executable evaluation emits `in_process_evaluated` bound to
the durable group receipt, and an unconsumed positive decision cannot form a
candidate. A coordinator processes each group once and owns the aggregate
terminal transition. PLC1B finalizes complete document-only input once and
aborts mixed input with zero finalization; PLC3 owns the successful mixed path.
Declaration source kind remains separate from any contributed factory/service
execution model.

### P0-06 — Kernel Prompt must remain truthful without Plugins

**Evidence.** The current default Coding prompt claims file reading, command
execution and editing abilities and contains Tool-specific guidance. Those
abilities depend on the base Tool pack.

**Risk.** `coding-minimal` could tell the model that absent Tools are available,
or disabling Base could accidentally remove mandatory safety and Product
identity text.

**Correction accepted.** PLC6 splits mandatory Kernel identity/safety from
optional Resource/Tool prompt sections and adds minimal/standard Model Input
snapshots. Tool capabilities are described only by selected Tool packs.

### P0-07 — Shadow migration must not create double publication

**Evidence.** Current CLI directly registers Coding built-in and Arch Tools;
bootstrap directly registers LSP Tools against a deferred runtime. A shadow
Plugin package could collide with these live identities.

**Risk.** Comparison mode could silently publish both paths, making parity
appear successful while duplicate resolution or last-writer behavior masks the
problem.

**Correction accepted.** PLC1 shadow mode stops at frozen declarations and
validates pinned catalog/schema identities without Host-environment resolution.
Its versioned semantic fingerprint covers only strict canonical payload before
owner/Host normalization; full fingerprints retain source/reservation/evidence
provenance, and live behavior parity waits for PLC4/PLC6. Each production slice
includes a final caller inventory and peer-route deletion commit.

### P0-08 — Base-first evidence cannot replace Provider/Graph evidence

**Evidence.** Resource-owned Base contributions do not exercise
Capability-owner eligibility, Product Provider closure, factory resolution,
Graph facets, typed Provider Consumers or Capability disposer rollback.

**Risk.** Publishing the public SDK after Base alone would freeze a
resource-only author model and leave executable security and Graph seams
untested.

**Correction accepted.** PLC5 keeps LSP as the first production Graph proof.
PLC8 remains gated on synthetic, LSP, Base and Arch evidence.

### P0-09 — Installation and activation stages are not Plugin Instance states

**Evidence.** The accepted UPA gives Plugin Instance Revisions only the direct-
host execution state machine `ACTIVE -> DRAINING/REVOKING -> RETIRED` and gives
Materialized Package Revisions a separate cache lifecycle. Selection,
preflight, declaration, admission, startup and update are different operations
or facts.

**Risk.** One apparent `NOT_INSTALLED -> ... -> ACTIVE -> REMOVED` state machine
would collapse package cache, desired state, activation work, Session
publication, owner generations and instance leases. Recovery and explain could
then infer one authority's state from another authority's clock.

**Correction accepted.** The plan now specifies independent desired-state,
activation-operation, Plugin Instance, package-cache and update state families.
`restart-required` is an operation/Session outcome, not an Instance state, and
owner generations retain their existing lifecycle contracts.

### P1-01 — Tool packs must reference owner catalogs, not capture services

**Evidence.** The existing Coding Tool pack selects names, while current
registration builds definitions with Exec, Diagnostics, external-tool policy,
environment and command configuration.

**Risk.** Passing these services to a Plugin author or recording live
`ToolDefinition` callables in declaration IR would create a global Plugin
context and non-serializable declaration model.

**Required implementation gate.** The Tool owner resolves declarative catalog
identities and injects only approved narrow runtime dependencies at binding.
The declaration remains data-only. Unsupported custom executable Tool cases
fail with a feature diagnostic rather than falling back to direct registration.

### P1-02 — Composition Sets must not become another Profile resolver

**Evidence.** Runtime Profile already selects Bundle-private variations. Top-
level Capability Provider selection belongs to the Product seam after owner
admission.

**Risk.** A `coding-standard` resolver invoked during Session construction
could rewrite defaults, select Providers, or cause the Profile resolver to run
twice.

**Required implementation gate.** `ProductCompositionCompiler` expands named
sets once while constructing one derived Product plan. It preserves provenance
and cannot admit or bind live objects.

### P1-03 — Startup atomicity needs precise wording

**Evidence.** There is no accepted cross-owner rollback transaction. Each owner
has its own publication linearization point, and notifications cannot roll a
committed generation backward.

**Risk.** Saying “the Plugin publishes atomically” could lead implementers to
restore already committed owner snapshots after a later failure.

**Correction accepted.** The plan says a usable Product Session is the
visibility boundary. Unpublished candidates roll back under exact owners;
post-owner-publication failure follows the accepted drain/restart/recovery
contract and is never described as global rollback.

### P1-04 — Active Session disable and update must remain conservative

**Evidence.** Existing accepted lifecycle permits content-only single Resource
owner refresh and private turn-refreshable facets, but Provider, authority,
process topology, executable digest or multi-owner changes require restart/new
Session behavior.

**Risk.** Marketing `coding.base` as hot-unloadable could remove Tools or
commands during an active turn, invalidate Model Input, or dispose state still
captured by a Session.

**Correction accepted.** Selection changes apply to new Sessions. Only an
already accepted single-owner Resource transaction may refresh live content;
other changes report `restart_required` and pin old generations until drain.

### P1-05 — Skill must remain a Resource

**Evidence.** A Skill body is model-visible content plus optional referenced
assets/scripts. It normally has no independent live Provider, facet or
disposer.

**Risk.** One Plugin instance per Skill would create another activation,
precedence, refresh and unload system.

**Correction accepted.** PLC8 converges Skill source providers and catalogs on
`resource_item`; individual `SKILL.md` files never become Graph nodes or Plugin
instances.

### P1-06 — MCP expansion is not needed for this milestone

**Evidence.** Base, LSP and Arch can prove Resource, Tool, Command, complete-
Bundle Provider, dependency, management and retirement seams without dynamic
MCP discovery.

**Risk.** Broad MCP work would enlarge transport, approval and dynamic-surface
scope before the common lifecycle is closed.

**Correction accepted.** Dynamic MCP surfaces remain explicitly deferred.
Later declarative external-service support must use the same owner admission,
process, transport and Tool publication rules.

### P1-07 — Plugin classification must remain orthogonal to contribution authority

**Evidence.** One package may carry Resource items, Tool/Command consumers, and
a Capability Provider, while Product/OEM composition and Host trust describe
selection and provenance rather than executable ownership.

**Risk.** A mutually exclusive package `pluginType`, hierarchical numeric code,
or capability bitmap would either reject valid mixed packages or become a
second compatibility/admission language that drifts from strict contribution
records and exact-owner checks.

**Correction accepted.** Canonical manifests and IR classify each contribution
with readable tagged records and keep Resource subtype, declaration source,
verified provenance/trust, and Product/OEM selection as separate dimensions.
Catalog/UI labels may be derived after validation but grant no authority and
do not participate in canonical identity, compatibility, admission, or binding.

### P2-01 — PLC2 and PLC3 are separate high-risk boundaries

**Evidence.** Durable management state transitions and Approval/import
consumption have different owners, persistence, lock ordering and recovery
rules.

**Risk.** Combining them into one convenience manager could let desired state
serve as execution authority or create an undecidable crash state.

**Required review gate.** PLC2 defines Product management state and CAS
transitions without importing code. PLC3 separately defines Approval-owner
decisions, import-start reservations and recovery. Each must merge and be
reviewed independently.

### P2-02 — Remove and private-data deletion must be separate commands

**Evidence.** Active Sessions, replay, owner cleanup, migrations and backup
retention may continue to reference a disabled or removed Plugin revision.

**Risk.** Treating remove as recursive deletion could destroy replay evidence
or user data while the lifecycle still needs it.

**Correction accepted.** PLC2 remove changes desired selection and requests
retirement. PLC9 performs reference-aware package GC. Private data deletion is
a distinct confirmed operation after lease checks.

## Priority And Dependency Review

The reviewed critical path is:

```text
PLC0 baseline
  -> PLC1A capability_provider declaration baseline
  -> PLC1B source/Resource/Tool/Command declarations and Base shadow
  -> PLC2 management state core
  -> PLC3 executable trust
  -> PLC4 exact-owner admission/binding
  -> PLC5 LSP production Graph proof
  -> PLC6 Base production Resource/Composition proof
  -> PLC7 Arch second-Provider proof
  -> PLC8 public SDK and Skill convergence
  -> PLC9 management/isolation/cleanup closure
```

Permitted internal parallelism after interfaces freeze:

- PLC1B Resource and Tool/Command codecs may proceed beside each other only
  after v2 source-group, evidence, locator and identity fields freeze; PLC1A's
  Provider codec remains the first compatibility fixture;
- PLC2 inert management records may proceed beside PLC3 Approval design, but
  executable evaluation cannot merge before Approval consumption exists;
- PLC4 Resource-owner and Capability-owner adapters may proceed independently;
  and
- the `coding.base` shadow package may evolve after PLC1 without live effects.

The critical path must not be shortened by publishing a public SDK, importing a
Definition from an in-memory allow record, binding Base directly, or keeping a
legacy live registrar behind a facade.

## Retain / Adapt / Delete / Defer

### Retain

- existing Capability Definition/Provider/Requirement/Consumer semantic types;
- existing Graph Planner/Binder/Runtime/Projector;
- existing Registration Scope and exact-owner disposal;
- existing CLA Resource candidate and Resource generations;
- resolve-once package/revision identity;
- complete Model Input persistence and replay authority; and
- current Product/Harness import direction.

### Adapt through one-way bridges

- generic Plugin payload into typed declaration codecs;
- document/Python declaration sources into the same frozen IR;
- owner-admitted Plugin contributions into existing Resource and Graph inputs;
- management desired state into Product selection inputs;
- Coding prompt assembly into Kernel plus selected Resource/Tool sections; and
- Skill source adapters into one Resource-owned catalog.

### Delete after parity

- direct Coding built-in Tool registration;
- direct Arch Tool registration;
- deferred LSP runtime and early LSP Tool registration;
- hard-coded optional Coding prompt/capability defaults;
- any Plugin-specific Skill discovery path; and
- any settings/CLI path that independently mutates Plugin lifecycle state.

### Defer

- dynamic MCP surfaces;
- untrusted in-process execution;
- cross-owner live hot replacement;
- public event, Agent and generic component SDKs;
- marketplace UX and remote publishing;
- per-Agent service recomposition; and
- implicit private-data deletion.

## First Implementation Gate

PLC0 and PLC1A satisfy the baseline entry gates through `8a3c94fd`. PLC1B source
work is eligible only after the documentation remediation passes fresh
independent review and the missing tracking issue is attached:

1. the known architecture inventory failures are reconciled and green;
2. exact parser, source-open, declaration, selection and live-publication sites
   are recorded without broad allowlists;
3. runtime-only v2 is the one canonical index/IR path and draft v1 fails closed;
4. proposal/pending/fresh revalidation produces no accepted state before the
   fully accepted arm, and only SourceGroup owns its gate;
5. the exact PLC1B Source/Index/Declaration/Document/Subject/Decision/evidence/
   candidate records, hash domains, version diagnostics and canonical document
   bytes are frozen;
6. revision-independent descriptor identity prevents package self-reference;
   Host-only group/evidence facts bind revision and accepted dynamic context;
7. each accepted attempt has a unique use ID, evidence cannot cross attempts,
   and group claim/in-flight fencing linearizes abort/expire/finalize;
8. PLC1B mixed-source accepts no executable declaration ingress and fails with
   one abort/zero finalize while PLC3 owns its
   successful join/finalize proof;
9. Candidate evidence, execution-subject/decision-record v2 rejection and canonical byte
   encoding are frozen without nullable decision peers;
10. the old public subject constructor and direct finalize/rollback routes are
    removed/private, while Coordinator/evaluator placement remains acyclic;
11. the existing Provider codec remains inert and separates declaration source
   from contributed factory/disposer execution model;
12. the document source model cannot import code, while isolated in-process
    Builder codec output cannot enter the Coordinator;
13. direct self-requirement fails in the codec and transitive cycles remain with
   the existing Graph Planner;
14. the `coding.base` shadow fixture stops before owner/Host normalization,
   admission or publication;
15. no stable public SDK symbol is exported and no Graph, Resource, Tool,
   Command, Extension or Session behavior changes;
16. targeted Plugin and architecture tests plus `git diff --check` pass; and
17. rollback requires no live-state cleanup or data migration.

## Review Conclusion

The combined plan is coherent after the sequencing corrections but remains
subject to the fresh independent documentation gate above. The common
lifecycle is the platform priority; `coding.base` is the Resource and Product
composition acceptance sample; `coding.lsp` is the executable Provider/Graph
acceptance sample; and `coding.arch` is the second-Provider and optional-
dependency sample. Together they provide the production diversity needed
before a stable author SDK is published.

PLC0 and PLC1A are complete locally, and PLC1B is the next implementation slice
only after the revised exact contract passes fresh independent review and issue
binding. The next mandatory high-risk design reviews are PLC2's
management transaction and PLC3's Approval/import-start protocol. Skipping
either to make Base appear pluggable would preserve the current duplication
under a new manifest rather than deliver a unified Plugin lifecycle.

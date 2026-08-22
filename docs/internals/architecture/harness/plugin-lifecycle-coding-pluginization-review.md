# Review: Unified Plugin Lifecycle And Coding Pluginization Delivery Plan

## Verdict

**PLC0 accepted locally; recommend the coordinating plan with two explicit UPA
sequencing revisions.**

The plan correctly gives the common lifecycle priority over a
`coding.base`-specific loader, uses `coding.base` as the Resource-heavy
production sample, and retains `coding.lsp` as the first Provider/Graph proof.
PLC0 restored the source-backed architecture baseline at `25cfc170`; see
[Plugin Lifecycle PLC0 Baseline](plugin-lifecycle-plc0-baseline.md). PLC1 is
technically eligible after its tracking issue is attached. This review does not
approve the security, lifecycle, production cutover, or public SDK slices as
one batch.

The two proposed sequencing revisions are justified but require architecture-
owner acceptance before their source implementation:

1. move the minimum durable `PluginManagementService` control core before the
   `coding.base` production cutover, while leaving rich management projections,
   isolation and GC in final closure; and
2. move production `coding.base` after `coding.lsp` and before `coding.arch`,
   while keeping the stable SDK gated on LSP, Base and Arch evidence.

This review found nine high-priority risks. The plan includes their required
corrections; none requires a second Graph, Resource runtime, Profile resolver,
approval store, registration owner, or effective projector.

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
arms that consume the same reservation model and produce the same tagged IR.
Document declarations still require digest, schema, selection and owner
admission. Only executable evaluation consumes execution approval and crosses
the verified import gate.

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
later may compare owner candidate outputs before publication. Each production
slice includes a final caller inventory and peer-route deletion commit.

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
  -> PLC1 canonical declarations
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

- PLC1 Resource codecs may proceed beside the Provider codec, but the Provider
  codec remains PAP1's first compatibility fixture;
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

PLC0 satisfies the following technical entry gates at `25cfc170`. PLC1 source
work is eligible after the missing tracking issue is attached:

1. the known architecture inventory failures are reconciled and green;
2. exact parser, source-open, declaration, selection and live-publication sites
   are recorded without broad allowlists;
3. `PluginDeclaration` remains the one canonical IR;
4. the first Provider codec remains inert and compatible with the current
   preflight/finalize slice;
5. the document source model cannot import code;
6. the `coding.base` shadow fixture stops before owner admission/publication;
7. no stable public SDK symbol is exported;
8. no Graph, Resource, Tool, Command, Extension or Session behavior changes;
9. targeted Plugin and architecture tests plus `git diff --check` pass; and
10. rollback requires no live-state cleanup or data migration.

## Review Conclusion

The combined plan is coherent after the sequencing corrections. The common
lifecycle is the platform priority; `coding.base` is the Resource and Product
composition acceptance sample; `coding.lsp` is the executable Provider/Graph
acceptance sample; and `coding.arch` is the second-Provider and optional-
dependency sample. Together they provide the production diversity needed
before a stable author SDK is published.

PLC0 is complete locally and PLC1 is the next implementation slice after issue
binding. The next mandatory design reviews are PLC2's management transaction
and PLC3's Approval/import-start protocol. Skipping either to make Base appear
pluggable would preserve the current duplication under a new manifest rather
than deliver a unified Plugin lifecycle.

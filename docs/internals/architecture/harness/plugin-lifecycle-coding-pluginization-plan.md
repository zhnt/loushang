# Unified Plugin Lifecycle And Coding Pluginization Delivery Plan

## Status And Authority

- Status: proposed coordinating delivery plan and accepted-boundary revision
  candidate.
- Baseline: `harness/plugin-authoring-primitives-plan` at `2e6f481d`, based on
  the implemented resolve-once package path and inert
  `capability_provider` preflight/finalize slice.
- Delivery status: PLC0 is implemented locally at `25cfc170`; its exact source
  inventory and verification evidence are recorded in
  [Plugin Lifecycle PLC0 Baseline](plugin-lifecycle-plc0-baseline.md). PLC1A's
  inert typed Capability Provider codec and reservation-bound builder are
  implemented at `2ebac237`, review-hardened at `27715416`, and recorded in the
  [PLC1A baseline](plugin-lifecycle-plc1a-baseline.md). PLC1B and later slices
  remain unimplemented.
- Scope: one delivery order for the common Plugin lifecycle, ordinary
  Definition / Provider / Consumer authoring primitives, `coding.lsp`,
  `coding.base`, `coding.arch`, management control, and later Skill adoption.
- Authority: the accepted
  [Unified Plugin Architecture](unified-plugin-architecture.md),
  [Capability Composition Lifecycle Authority Plan](composition-lifecycle-authority-plan.md),
  [Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md),
  and
  [Extension And Resource Generation Lifecycle](extension-generation-lifecycle-boundary.md)
  remain authoritative unless this plan explicitly identifies a proposed
  sequencing revision.
- Detailed Provider-authoring work remains specified by the
  [Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md).
- Review: [Unified Plugin Lifecycle And Coding Pluginization Review](plugin-lifecycle-coding-pluginization-review.md).

This document is a coordinating plan. It does not claim that document-backed
Plugin declarations, owner admission bridges, executable Plugin evaluation,
Plugin management control, or Coding Plugin cutovers are already implemented;
PLC1A stops at frozen authoring IR.

## Executive Decision

The common Plugin lifecycle has higher priority than a `coding.base`-specific
loader. `coding.base` is the first production Resource-heavy adopter of that
lifecycle, not a separate implementation path. `coding.lsp` remains the first
production complete-Bundle Provider/Graph adopter because `coding.base` cannot
prove Provider selection, Graph construction, Consumer facet capture, or
Capability-owner disposal.

The delivery order is:

```text
restore and freeze the source-backed architecture baseline
  -> freeze one tagged declaration IR and two declaration source models
  -> close minimum install/select/instance/update/retirement control
  -> close executable approval and verified Definition evaluation
  -> add exact-owner admission for Resource and Capability contributions
  -> bind through existing Resource generations and the existing Session Graph
  -> prove both no-code Resource and executable Capability fixtures
  -> migrate coding.lsp and delete its peer runtime path
  -> migrate coding.base and delete CLI/bootstrap peer registrations
  -> migrate coding.arch and prove a second Capability/optional dependency
  -> stabilize the public author SDK
  -> converge Skill sources on the Resource path
  -> finish management projections, isolation, retained-version GC and UX
```

Two controlled overlaps are allowed:

1. a declaration-only `coding.base` shadow package may be built as soon as the
   document-backed Resource declaration codecs exist; it cannot publish live
   Tools, Commands, prompts, or Skills while the legacy path still does; and
2. Resource-owner and Capability-owner adapters may be developed independently
   after the shared declaration identity and lifecycle records freeze.

## Goals

1. Give first-party and ordinary external Plugin authors one declaration model
   and owner-specific typed builders rather than direct registries.
2. Make installation, declaration, selection, admission, binding, execution,
   disable, update, retirement, removal, and explanation one continuous,
   reconstructible lifecycle.
3. Turn `coding.base` into a Product-owned, default-selected, disableable
   Plugin without inventing a `coding.base` Capability or Graph node.
4. Turn `coding.lsp.default` and `coding.arch.default` into selectable
   top-level Capability Providers bound by the existing Graph runtime.
5. Remove duplicate CLI/bootstrap registration, deferred runtime, source scan,
   selection, and binding paths after compatibility evidence is green.
6. Keep Skill as a Resource item while allowing Skill source providers to be
   packaged and selected as Plugins.
7. Preserve exact owner publication, disposal, Model Input reconstruction, and
   Product-neutral Harness boundaries.

## Non-Goals

This milestone does not add:

- a universal mutable `PluginContext`, registry bag, or service locator;
- a Plugin-specific Graph, Profile resolver, Resource candidate, approval
  store, effective projector, or registration owner;
- one Plugin or Capability instance per Skill;
- arbitrary third-party publication of `coding.*` or `harness.*` Capability
  Definitions;
- cross-owner live hot replacement;
- untrusted in-process Python;
- dynamic MCP Tool discovery or broad MCP feature work;
- remote marketplace UX, generic event/Agent SDKs, or per-Agent service
  recomposition; or
- deletion of Plugin private data as an implicit side effect of disable.

## Non-Negotiable Invariants

1. **Resolve once.** `plugin.json` is parsed by one parser and all later stages
   consume immutable package locators and verified revision handles.
2. **Declare once.** One contribution reservation is consumed by one tagged
   declaration identity. A file, manifest, compatibility adapter, and Python
   entrypoint cannot each emit the same Tool, Command, Skill, or Provider.
3. **Select once.** Product Runtime Plan/OEM Profile expansion and
   `ProductCompositionCompiler` produce one derived Product plan. Plugin code
   never enables itself and no downstream default rewriter runs afterward.
4. **Admit by exact owner.** The Plugin layer produces candidates only. The
   Resource, Capability, Command, Tool, Event, Agent, or Presentation owner is
   the sole final admission/conflict authority for its contribution kind.
5. **Bind once per owned object.** Resource owners publish Resource generations;
   Capability owners bind complete Bundles through the existing Graph Binder;
   Extension owners publish Extension generations. There is no global Plugin
   bind transaction.
6. **Publish once.** A new Product Session is the visibility boundary over the
   independently staged owner outputs. A startup failure publishes no usable
   Session.
7. **Retire by exact owner.** Plugin management aggregates owner retirement
   handles and results but never disposes foreign scopes directly.
8. **Persist complete facts.** Package digest, declaration, selection,
   admission, owner generation, Consumer capture, and actual model-visible
   content remain reconstructible after mutable source removal.
9. **Fail before import.** Disabled, denied, stale, incompatible, or untrusted
   executable declarations never cross the import/launch boundary.
10. **Delete the peer path.** A migration is incomplete while a legacy caller
    can independently construct or publish the same live object.

## One Lifecycle, Several Exact Owners

“Unified lifecycle” does not mean one transaction owns every live object. It
means every Plugin contribution passes through the same package, declaration,
selection, provenance, management, and retirement coordination path while the
existing exact owners retain publication and disposal authority.

```text
Source / embedded package
  -> PluginResolutionAuthority
  -> PublishedPluginPackage + VerifiedRevisionHandle
  -> PluginManagementService desired-state transaction
  -> PluginSelectionResolver inert preflight
  -> document decoder OR approved PluginDefinitionEvaluator
  -> frozen PluginDeclaration union
  -> PluginSelectionResolver final reservation match
  -> exact owner candidate resolver and admission record
  -> ProductCompositionCompiler / Product Provider resolver
  -> exact owner Component Host or generation builder
  -> Resource generation OR Session Graph Mount OR other owner generation
  -> Product Session captures final Consumers and publishes
  -> owner retirement; Plugin management aggregates the result
```

### Distinct state identities

The implementation must not collapse these identities:

| Identity | Examples | Owner |
| --- | --- | --- |
| Materialized Package Revision | digest, dependency lock, verified files | Package/revision authority |
| Plugin Installation | installed source, Product/workspace scope, desired version | Plugin management control |
| Plugin Instance Revision | selected configuration, decisions, lifecycle state | Product Plugin host |
| Contribution Candidate | reservation-bound frozen declaration | Declaration/selection path |
| Owner Admission | admitted/rejected identity and policy revision | Exact contribution owner |
| Owner Generation | Resource, Capability Mount, Extension, Command, Tool generation | Exact live-object owner |
| Product Session capture | pinned owner generations and Consumer facets | Product Session composition root |

One package revision may support multiple scoped instances. One Plugin may
produce several contributions. One contribution maps to one exact owner. A
Plugin Instance state must never be inferred from a package-cache state or one
owner generation alone.

### Independent lifecycle state machines

Installation, activation work, Plugin Instance execution, package cache,
updates, and owner generations must not be represented by one apparent linear
state machine. The minimum durable state families are:

```text
Installation desired state
  absent | installed-disabled | installed-enabled(current revision)

Activation operation
  preparing -> preflighted -> declared -> admitted -> starting
            -> committed | failed | restart-required

Plugin Instance Revision execution state
  ACTIVE --graceful--> DRAINING --> RETIRED
  ACTIVE --security--> REVOKING --> RETIRED
  DRAINING --security--> REVOKING

Materialized Package Revision cache state
  verified | quarantined | gc-eligible

Update transaction
  update-staged -> migrating -> committed | failed
```

The activation operation records how one Product Session candidate reached or
failed before its visibility boundary; it is not the Plugin Instance state.
The Plugin Instance Revision owns only its accepted direct-host execution state
and acquisition references. Owner generations retain their existing states and
clocks. `restart-required` is a typed outcome for affected Sessions or an
activation/update operation, not an extra Instance execution state. None of
these records grants Plugin management authority to publish or dispose an
owner generation.

## Declaration And Authoring Model

### One tagged IR

Extend the existing `PluginDeclaration` rather than creating a second semantic
model. The target tagged union is:

| Kind | Meaning | Sole binding/admission owner |
| --- | --- | --- |
| `capability_provider` | Complete top-level Bundle Provider metadata and verified factory/disposer references | Capability owner, Product Provider resolver, Graph Binder |
| `capability_component` | Component aggregated inside an existing Bundle | Exact Capability component owner/generation |
| `resource_item` | Prompt, Skill, method, theme, asset, or raw source descriptor | Resource generation owner |
| `tool_pack` | Typed Tool selection/definition pack | Owning Bundle Tool facet |
| `command_pack` | Typed Command pack referencing admitted resources | Owning Bundle Command facet |
| later accepted kinds | Events, Agent definitions, presentation, external services, configuration | Their exact accepted owners |

Only the initial production set is in the first implementation scope:
`capability_provider`, `resource_item`, `tool_pack`, and `command_pack`.
`capability_component` follows after the complete-Bundle LSP path is stable.

### Two declaration source models

The current declaration reservation requires an in-process entrypoint. That is
too strong for `coding.base`. The canonical source union must support:

```text
document
  contained immutable JSON document or Resource descriptor
  no Python import and no executable decision consumption

in_process
  contained Python Plugin Definition entrypoint
  durable execution decision consumption and verified import closure required
```

Both source models produce the same frozen `PluginDeclaration` union and
consume the same reservation identity. A document declaration still requires
package digest verification, schema/engine compatibility, Product selection,
owner admission, and exact provenance; “no code” does not mean “trusted or
admitted automatically.”

### Ordinary author primitives

The internal authoring SPI first exposes data-only helpers such as:

```text
plugin_definition(...)
capability_provider(...)
capability_requirement(...)
resource_item(...)
tool_pack(...)
command_pack(...)
contained_resource(...)
```

They compile directly to existing semantic records and the canonical Plugin
IR. They do not expose a Graph, Session, registry, approval store, secrets,
credentials, `RegistrationScope`, mutable Product context, or arbitrary host
services. Decorators are optional ergonomics after the explicit builders and
feature negotiation stabilize.

### Tool and Command packs

The first-party `coding.base` packs should be declarative references to
host-owned catalogs:

```text
tool_pack coding.builtin
  catalog: harness.workspace.core
  tools: bash/read/ls/find/grep/write/edit
  activation: default

command_pack coding.standard
  catalog: harness.session.standard
  commands: Product-approved Coding command identities
```

The owner resolver maps those identities to existing implementations and
injects narrow execution, diagnostics, policy, workspace, and presentation
facets. The Plugin receives neither a `WorkspaceToolRegistry` nor a service
bag. A future custom executable Tool uses its own approved declaration and host
path; `coding.base` does not require that surface to prove its v1 migration.

## Product And Capability Ownership

### Definition

`CapabilityDefinition` remains published by the Product or Capability namespace
owner. Ordinary Plugins may provide an implementation compatible with an
existing Definition; they cannot claim arbitrary `coding.*`, `harness.*`, or
another Product namespace.

### Provider

A `capability_provider` declaration normalizes to existing
`CapabilityBundleProvider` metadata plus serializable requirements,
factory/disposer locators, non-secret binding inputs, requested authorities,
and provenance fingerprints. It becomes live only after:

```text
Capability-owner eligibility
  -> Product/OEM bounded normalization
  -> Capability-owner final admission
  -> Product selection of one complete Provider closure
  -> Graph planning
  -> approved Component Host resolution
  -> existing Graph Binder construction/publication
```

### Consumer

There are only two runtime Consumer paths:

1. Provider requirements receive narrow typed dependency facets through the
   existing `CapabilityProviderContext`; and
2. Product runtime consumers capture generation-scoped typed facets after Graph
   publication.

No Tool, Command, Plugin, or Product code may locate a live Provider by Plugin
ID or through an ambient container.

## Coding Product Decomposition

### Non-pluggable Coding Kernel

The Kernel must boot when all optional Plugins are disabled. It retains:

- Product identity and domain goals;
- mandatory system/developer identity and non-negotiable safety instructions;
- Session/turn/model-call correctness;
- Product-to-Harness composition root;
- risk, approval, Sandbox and workspace ceilings;
- context/compaction, transcript and artifact semantics;
- Product instruction loading and complete Model Input commit; and
- minimum diagnostics, recovery, and presentation policy.

The Kernel must not claim optional abilities that are absent. The current
default prompt therefore needs a content split: Coding identity, project
instruction handling, and mandatory safety remain Kernel-owned; “read/write
files,” “execute commands,” specialized-Tool preference, and Tool-specific
usage text are composed only from selected Tool packs and Resource prompt
sections.

### `coding.base`

`coding.base` is a Product-owned Plugin ID selected by `coding-standard`, not a
Capability ID. Its v1 package is document-backed and contributes:

- optional standard Coding prompt fragments;
- standard Coding Skills and related Resource descriptors;
- the standard workspace Tool pack;
- Product-approved Coding Command packs; and
- optional presentation or adapter descriptors only where an accepted owner
  schema already exists.

It aggregates into existing `harness.resources` and `harness.session` facets.
It owns no process, supervisor, graph node, Resource registry, or Session.

### `coding.lsp.default`

`coding.lsp.default` is the first executable complete-Bundle Provider Plugin.
It provides `coding.lsp`, consumes narrow `harness.workspace` read/process
facets, and publishes semantic runtime, Tools, and diagnostics together in one
Graph Mount generation. Its migration deletes deferred LSP runtime and early
Tool registration.

### `coding.arch.default`

`coding.arch.default` is the second complete-Bundle Provider Plugin. It proves
a second Capability contract, durable indexed state policy, owner-internal
analyzer aggregation, and later an optional typed dependency on `coding.lsp`.

### Composition Sets

```text
coding-minimal
  Kernel + mandatory Harness capabilities

coding-standard
  coding-minimal + coding.base + coding.lsp.default(on demand)

coding-architecture
  coding-standard + coding.arch.default(on demand)
```

Composition Set expansion runs exactly once in
`ProductCompositionCompiler`. It produces one derived Product Runtime Plan with
Plugin/contribution/digest provenance. It is not another Runtime Profile layer
and cannot select an owner-rejected Provider.

## Current Migration Inventory

The initial caller inventory that each implementation slice must refine is:

| Current path | Target | Deletion condition |
| --- | --- | --- |
| `coding.cli.build_builtin_tool_registry()` directly calls `register_coding_builtin_tools()` | admitted `coding.base` `tool_pack` resolved by the Tool/Resource owner | standard-mode parity and no direct registrar callers |
| CLI directly calls `register_coding_arch_tools()` | mounted `coding.arch.default` Bundle Tools | Arch Graph migration and caller inventory green |
| Coding bootstrap calls `register_coding_lsp_tools()` against a deferred runtime | mounted `coding.lsp.default` Bundle Tools | LSP Graph migration, cancellation and leak tests green |
| `_CODING_AGENT_PRODUCT_CONSTRUCTION` binds one monolithic default Coding prompt | Kernel prompt plus admitted Resource/Tool prompt sections | minimal/standard prompt snapshots and Model Input provenance green |
| Product plan and settings infer built-in capability mount modes | Composition Set and owner-admitted Provider selection | compatibility telemetry shows no independent selection caller |
| Skill filesystem/package discovery has multiple source adapters | one Resource-owned provider-neutral Skill catalog | Skill convergence gates pass; individual Skills remain Resources |

Compatibility adapters may forward into the canonical path temporarily. They
may not independently register, construct, publish, or retire the same object.

## Startup, Update, Disable, And Removal Semantics

### New Session startup

```text
commit desired Plugin selection
  -> resolve/pin package revisions
  -> decode/evaluate frozen declarations
  -> exact owners admit all required contributions
  -> compile one Product plan and complete Provider closure
  -> stage Resource generation and Graph inputs independently
  -> bind the existing Session Graph once
  -> capture typed Consumers
  -> publish the usable Product Session
```

If any required declaration, owner admission, factory, facet, or Consumer
capture fails, the new Session is not published. Each unpublished owner
candidate rolls back under its own accepted rules. The design does not publish
several owner generations and then attempt snapshot restoration.

### Disable

- the committed selection change affects every subsequently created Session;
- a content-only single Resource-owner change may use the existing accepted
  Resource refresh transaction;
- a Provider, dependency, authority, process-topology, executable digest, or
  multi-owner change marks active Sessions `restart_required`;
- existing sealed Sessions keep pinned revisions and owner generations until
  normal drain; and
- disabling preserves Plugin data and installed package revisions by default.

### Update

An update stages a new immutable revision and declarations without moving the
active selection pointer. Owner admission, data migration, and validation run
against the staged identity. Selection cutover is one compare-and-swap Product
decision. Before cutover new Sessions continue using the old revision or an
explicit wait/fail policy. In-process digest changes require host restart until
an accepted isolated import realm proves coexistence.

### Security revoke

Security revocation is not graceful disable. It blocks new acquisition,
invalidates enforceable leases, identifies the exact instance/revision blast
radius, and asks the exact owners to terminate or quarantine their generations.
A compromised in-process realm requires Product Host stop/restart; the system
must not claim arbitrary imported Python was safely unloaded.

### Remove

Remove commits desired state only after new selection no longer references the
Plugin. Package bytes become garbage-collection candidates only after all
Session, instance, replay, migration, owner-retirement, and retained-version
leases release them. Private data deletion is a separate confirmed command.

## Plugin Management Control Core

The minimum typed `PluginManagementService` control core moves before the
`coding.base` production cutover. Otherwise install/disable/update/remove would
remain configuration-specific side paths and the lifecycle would not be
closed.

The early control core owns durable commands and state transitions for:

- install or register an embedded first-party package;
- enable/disable at an explicit Product/workspace scope;
- stage/update/cut over a revision;
- remove desired selection and request retirement;
- query/list exact package, instance, contribution, admission and generation
  references;
- explain and diff desired versus effective state; and
- report `restart_required`, `draining`, partial retirement, or failed cleanup.

CLI, RPC, UI, and SDK are adapters over this service. Rich marketplace UX,
remote acquisition, untrusted-worker isolation, retained-version GC policy,
and destructive private-data cleanup remain later closure work.

## Integrated Delivery Slices

Each source-changing slice uses the high-risk lifecycle workflow: tracking
issue, isolated Harness task branch, focused green baseline, regression-first
contracts, small commits, source-backed review, and explicit peer-route
deletion.

### PLC0: Baseline And Authority Inventory

Implementation status: complete locally at `25cfc170`; see
[Plugin Lifecycle PLC0 Baseline](plugin-lifecycle-plc0-baseline.md). A tracking
issue must still be attached before PLC1 PR work.

Scope:

- complete PAP0 and restore the known architecture inventory failures to green;
- record exact source baseline and public semantic exports;
- freeze all current parser, source-open, selection, registration, Tool,
  Command, LSP, Arch, prompt, Skill and Graph binding call sites;
- add forbidden-peer architecture checks; and
- create inert Resource and Capability conformance package fixtures.

Exit gate:

- architecture tests are green without broad exemptions;
- every live publication sink has one named owner; and
- no public Plugin author API is introduced.

### PLC1: Canonical Declaration Foundation

Scope:

- complete PAP1's typed `capability_provider` codec and reservation-bound
  internal builder first;
- version the declaration source union for `document` and `in_process`;
- add strict owner-specific codecs for `resource_item`, `tool_pack`, and
  `command_pack` without importing executable code;
- reject unknown fields, duplicate identities, path traversal, callable data,
  unsupported engine features, owner mismatch, and post-freeze mutation; and
- compile a document-backed `coding.base` shadow package to frozen IR only.

Exit gate:

- hand-authored, document-backed, and internal-builder declarations produce the
  same canonical fingerprints;
- one reservation cannot be consumed through multiple source models; and
- the shadow package has no live registration or model-visible effect.

### PLC2: Minimum Lifecycle And Management Control

Scope:

- define Package Revision, Installation, Plugin Instance Revision, desired
  selection, lifecycle transition, retirement aggregate, and cleanup handoff
  records;
- introduce the internal typed `PluginManagementService` command core;
- make enable/disable/update/remove durable and scope-explicit;
- implement compare-and-swap desired-selection cutover, crash recovery, and
  exact `restart_required` reasons; and
- keep all outputs inert until owner binding exists.

Exit gate:

- every transition is reconstructible and idempotent;
- package cache state cannot impersonate Plugin Instance state;
- remove never deletes pinned bytes or private data; and
- no CLI or settings adapter writes lifecycle state directly.

### PLC3: Executable Trust And Definition Evaluation

Scope:

- complete PAP2 durable Approval-owner decision issue/query/consume/revoke and
  start reservations;
- complete PAP3 verified Plugin Definition evaluation and import-closure gate;
- produce the same frozen declaration IR as document sources; and
- fail closed to isolated-worker or clean-host restart when closure cannot be
  proven.

Exit gate:

- disabled, denied, expired, stale, wrong-scope, wrong-digest, revoked, or
  incompatible code is never imported;
- consume/revoke and consume/crash races have tested linearization; and
- evaluation cannot bind or publish a contribution.

### PLC4: Exact-Owner Admission And Binding Bridges

Scope:

- complete PAP4 Capability-owner eligibility/final admission and pure Product
  Provider closure selection;
- add Resource-owner admission codecs and records for `resource_item`,
  `tool_pack`, and `command_pack`;
- add the narrow Capability Component Host from PAP5;
- adapt Resource declarations into one root-owned Resource candidate and
  Capability Providers into separate Session Graph inputs;
- publish a new Session only after both paths succeed; and
- retain the existing Graph Binder, Runtime Profile resolver, Registration
  Scope, Resource generation, and projector as the only live authorities.

Exit gate:

- no-code Resource and executable Capability fixtures traverse the lifecycle
  through typed Consumers and exact disposal;
- one failed required contribution publishes no usable Session;
- duplicate Tool/Command/Resource identities fail with both provenance records;
  and
- no second Graph, Resource candidate, registry bag, or effective clock exists.

### PLC5: `coding.lsp.default` Production Provider

Scope and gates are PAP6, including packaging the complete Bundle, narrow
workspace requirements, Tool/runtime co-publication, alternate Provider
selection, rollback, replay, restart reconstruction, owner-correct disposal,
and deletion of deferred/early-binding peers.

This remains the first production Graph proof.

### PLC6: `coding.base` Production Resource Plugin

Scope:

- split the current Coding prompt into mandatory Kernel and selected optional
  sections;
- package prompts, Skills, workspace Tool pack, and Coding Command pack as
  document-backed contributions;
- define `coding-minimal`, `coding-standard`, and `coding-architecture` sets;
- run shadow composition against current standard behavior without double
  publication;
- select `coding.base` by default only through `coding-standard`;
- route enable/disable/update/remove through the management control core; and
- delete direct CLI/bootstrap registrations and hard-coded optional defaults.

Exit gate:

- `coding-minimal` boots with no optional Plugin and no false Tool claims;
- `coding-standard` is behaviorally compatible with the current supported
  default;
- disabling `coding.base` affects new Sessions and reports exact active-Session
  refresh/restart behavior;
- install-to-remove provenance is explainable after mutable source deletion;
  and
- no old caller can independently publish a base Prompt, Skill, Tool, or
  Command.

### PLC7: `coding.arch.default` Second Provider

Scope:

- package and mount the Architecture Bundle through the same Provider path;
- keep it initially independent of LSP, then add the optional typed LSP
  requirement only with contract evidence;
- bind analyzers, facts, diagnostics, Tools, index generation and disposer
  together; and
- prove versioned private data, migration fencing, rollback and quota policy.

Exit gate:

- a second Capability requires no new Plugin or Graph path;
- optional dependency closure and absent-LSP behavior are deterministic; and
- the direct Arch Tool registration path is deleted.

### PLC8: Public SDK And Skill Convergence

Scope:

- after synthetic, LSP, Base and Arch evidence, freeze declaration IR and
  engine-feature negotiation and publish the minimum public author SDK;
- provide validation without import and a separate approved execution
  conformance command;
- keep each `SKILL.md` a `resource_item`;
- converge filesystem, embedded and admitted-package Skill sources on one
  Resource-owned catalog snapshot and lazy body loader; and
- route Skill scripts through existing Tool/Policy/Approval/Sandbox execution.

Exit gate:

- ordinary authors never receive owner authority objects;
- two IR/engine versions have explicit compatibility fixtures;
- all Skill list/enable/load/refresh callers use one catalog path; and
- model-visible Skill content is committed with source revision and digest.

### PLC9: Management, Isolation And Cleanup Closure

Scope:

- add CLI/RPC/UI/SDK projections over the already durable management core;
- complete isolated-worker evaluation before untrusted executable admission;
- implement retained-version and orphaned-generation GC;
- add separately confirmed private-data deletion and backup retention;
- remove superseded Package/Plugin/Extension compatibility adapters; and
- add operational repair for partial retirement and failed cleanup.

Exit gate:

- every supported management surface calls one service;
- remove, retirement, GC and data deletion are visibly distinct operations;
- incomplete termination cannot be reported as disabled or removed; and
- no compatibility path independently mutates package, selection, owner, or
  effective state.

## Proposed Sequencing Revisions

This coordinating plan proposes two explicit revisions to the accepted UPA
delivery order. They require architecture approval before implementation
claims the revised milestone names:

1. split the UPA8 management work, moving the minimum durable management
   control core before the `coding.base` cutover while retaining UI, isolation,
   GC and destructive cleanup in the final closure; and
2. deliver production `coding.base` after `coding.lsp` but before
   `coding.arch`. The Base shadow package may start earlier, while the public
   SDK remains gated on all three production samples.

This ordering proves one executable Capability first, then closes the default
Product composition and removal of duplicate base paths, then proves a second
Capability and optional dependency. It does not weaken the existing stable-SDK
gate.

## Verification Matrix

### Lifecycle contract groups

| Contract | Required evidence |
| --- | --- |
| Resolve/install | immutable revision identity, containment, dependency lock, scoped installation |
| Declare | strict tagged IR, one reservation/identity, document and approved executable parity |
| Select | deterministic Composition Set expansion, desired-state CAS, no self-enable |
| Admit | exact owner records, conflict/compatibility diagnostics, no Product grant widening |
| Bind/publish | existing Resource generation and Graph Binder only, cancellation boundary, typed Consumers |
| Execute | exact approval/authority/policy/sandbox revalidation and complete Model Input facts |
| Update | staged revision, migration fence, atomic pointer cutover, restart-required policy |
| Disable/retire | new-Session behavior, pinned old Sessions, exact owner drain and retryable cleanup |
| Remove/GC | no pinned-byte deletion, distinct private-data command, retained-version policy |
| Explain/replay | package-to-generation lineage, skew visibility, replay after source removal |

### Coding behavior gates

- minimal mode starts with no optional Plugins;
- standard mode reproduces supported base Prompt, Tool, Command and Skill
  behavior through one path;
- LSP Tools never appear without the mounted LSP runtime;
- Arch Tools never appear without the mounted Arch runtime;
- optional Plugin absence never changes Kernel safety ceilings;
- disabled Plugin code is not imported and document-only `coding.base` imports
  no Plugin code at all;
- no Tool, Command, Skill, prompt section, Provider or owner disposer is
  registered twice; and
- exact package/declaration/admission/generation/model-input provenance is
  available to diagnostics and replay.

### Focused commands

Each slice runs only relevant subsets first, then expands at PLC4 and each
production cutover:

```text
.venv/bin/python -m pytest tests/harness/resources/plugins -q --skip-host-runtime
.venv/bin/python -m pytest tests/harness/capabilities -q --skip-host-runtime
.venv/bin/python -m pytest tests/harness/session -q --skip-host-runtime
.venv/bin/python -m pytest tests/coding -q --skip-host-runtime
.venv/bin/python -m pytest tests/architecture/test_unified_plugin_architecture.py -q --skip-host-runtime
.venv/bin/ruff check <changed Python files>
git diff --check
```

Architecture scans are defense-in-depth. Behavioral tests at the parser,
management transaction, Approval owner, declaration evaluator, exact-owner
admission, Component Host, Resource generation, Graph Binder, Session
publication, retirement and replay seams are the completion evidence.

## Mandatory Adversarial Scenarios

- same Plugin ID/version with changed bytes or dependency closure;
- source mutation after package publication;
- document and Python declarations attempt to consume the same reservation;
- duplicate Tool/Command/Skill/Provider identity from legacy and Plugin paths;
- unknown declaration fields, traversal locators, callable payloads, and owner
  mismatch;
- enable/disable/update CAS races and crash during state transition;
- decision consume/revoke and consume/import-start races;
- Product tries to select an owner-rejected or expired Provider;
- owner admission and binding-spec fingerprints disagree;
- factory returns wrong facets or fails after staged registration;
- cancellation immediately before and after each owner publication point;
- base prompt claims a disabled Tool or Skill;
- active Session observes disable, update, security revoke, and host restart;
- package source disappears before cold replay;
- disposer fails and later repair retries without duplicate disposal;
- remove races a pinned Session or retained replay lease; and
- private data survives disable/remove unless a distinct confirmed deletion
  command succeeds.

## Definition Of Done

The combined milestone is complete only when:

1. package, declaration, selection, owner admission, binding, execution,
   update, disable, retirement, remove and explain share one reconstructible
   lifecycle;
2. document and executable declarations produce one canonical tagged IR while
   executable code crosses a durable approval/import gate;
3. the exact owner remains the only publisher and disposer for every live
   object;
4. `coding.lsp.default` mounts through the existing Graph and its deferred and
   early Tool paths are deleted;
5. `coding.base` is selected through Composition Sets, can be disabled or
   updated through Plugin management, and has no direct CLI/bootstrap peer
   registrations;
6. `coding-minimal` remains usable and Kernel safety/identity is independent of
   optional Plugins;
7. `coding.arch.default` proves a second Provider and optional dependency
   without a new runtime path;
8. complete Model Input and lifecycle facts replay after mutable source
   removal;
9. active-Session refresh/restart/revoke behavior and exact-owner retirement
   pass adversarial tests;
10. stable public author APIs expose declarations and narrow typed inputs, not
    owner authority; and
11. Skills converge as Resource items without per-Skill Plugin identities or a
    parallel loader.

Landing one builder, one manifest, or one demo does not satisfy this definition.

## Commit And Review Shape

Each PLC slice should normally land as:

1. `test(...): freeze <slice> lifecycle contracts`
2. `feat(...): implement <slice> owner path`
3. `refactor(...): remove <slice> peer route`

The third commit is omitted for inert-only work. PLC0 must be green before PLC1
source changes merge. PLC2, PLC3, PLC4, every production cutover, and every
destructive cleanup path require a fresh source-backed lifecycle review. The
review must identify exact state owners, linearization points, cancellation
behavior, recovery, Model Input evidence, retirement owner, and peer-route
deletion before approval.

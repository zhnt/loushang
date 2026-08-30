# Unified Plugin Lifecycle And Coding Pluginization Delivery Plan

## Status And Authority

- Status: active coordinating delivery plan under Plugin Architecture V2. It is
  not a second architecture authority.
- Baseline: `harness/plugin-authoring-primitives-plan` at `2e6f481d`, based on
  the implemented resolve-once package path and inert
  `capability_provider` preflight/finalize slice.
- Delivery status: PLC0 is implemented locally at `25cfc170`; its exact source
  inventory and verification evidence are recorded in
  [Plugin Lifecycle PLC0 Baseline](plugin-lifecycle-plc0-baseline.md). PLC1A's
  inert typed Capability Provider codec and reservation-bound builder are
  implemented at `2ebac237`, review-hardened through `8a3c94fd`, and recorded
  in the [PLC1A baseline](plugin-lifecycle-plc1a-baseline.md). PLC1B-1 through
  PLC1B-4 are implemented on the current delivery branch: source-union and
  Host composition, inert Resource/Tool/Command payloads, the compiler-owned
  semantic fingerprint, and the document-backed `coding.base` shadow are
  complete. PLC2-1 through PLC2-4D, PLC3-1 through PLC3-3, the PLC4/PAP4
  owner-admission and Provider-selection primitives, and PLC4.5 through
  RCP4.10 are implemented. PLC5.0's private Product Provider assembly seam is
  also implemented. PLC5.1a's installed-distribution evidence resolver,
  Product-owned co-distribution grant, canonical lock integration, checked-in
  `coding.lsp.default` package, inert declaration evaluation, and private
  activation-symbol import proof are implemented. The Product composer now owns
  package publication, selection, Definition Approval
  consumption, Tool-owner admission, Provider resolution, Activation Approval
  issuance/verification, Component Host construction and exact Session input
  binding. The one-shot activation decision remains unconsumed until Session
  Graph preparation. A bind-once `CodingLspToolOwner` now projects the exact
  admitted Tool pack only from its Graph Consumer capture, stages invisible
  runtime Tool leases, publishes the complete generation and retires it in
  reverse order. Coding bootstrap now selects this Plugin route by default when
  the capability is enabled: Provider ownership transfers once to the Binder,
  Tools publish only after capture, and the Product retains only a non-owning
  semantic view. Real-process vertical regressions now prove the Plugin path in
  both `always` and `on_demand` modes through Tool execution, status, explicit
  stop and exact-generation retirement. The Product-owned exact-policy Approval
  owner, default cutover and deletion of the deferred runtime, early Tool
  registrar and legacy cleanup input are implemented. PLC6A through PLC6E now
  freeze the inert Composition Set request and Kernel/Base Prompt boundary,
  publish Prompt/Skill through Resource Catalog and publish Tool/Command only
  through their exact Session owners. PLC6D binds the requested base package to
  the common durable desired-state/Instance authority, preserves explicit
  disable and remove, pins active Session families across update, and reopens
  selected immutable revisions after mutable source removal. PLC6E now removes
  Coding's Resource authority mode, legacy Resource discovery, and peer CLI
  Tool publisher. PLC6 production validation and its terminal three-view review
  completed on 2026-08-30. PLC7's second Provider, shared Capability-Plugin
  composition, Arch Tool owner, source-backed private index and optional LSP
  edge are implemented, terminally reviewed, and merged. PLC8's public author
  SDK, exact engine negotiation, inert validation, managed Skill-action
  declaration/execution path, and Resource-owner Catalog selection binding are
  implemented as a review candidate; PLC8's terminal review and PLC9 remain
  open.
- Scope: one delivery order for the common Plugin lifecycle, ordinary
  Definition / Provider / Consumer authoring primitives, `coding.lsp`,
  `coding.base`, `coding.arch`, management control, pre-LSP internal Resource/
  Skill catalog convergence, and later public SDK stabilization.
- Authority: the canonical target
  [Plugin Architecture V2](architecture.md),
  [Capability Composition Lifecycle Authority Plan](../composition-lifecycle-authority-plan.md),
  [Capability Dependency And Mount Lifecycle](../capability-dependency-and-mount-lifecycle.md),
  and
  [Extension And Resource Generation Lifecycle](../extension-generation-lifecycle-boundary.md)
  remain authoritative unless this plan explicitly identifies a proposed
  sequencing revision.
- Detailed Provider-authoring work remains specified by the
  [Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md).
- The [PLC1B Contract](plugin-declaration-foundation-plc1b-contract.md)
  normatively freezes PLC1B wire records, kind payloads, fingerprint layers,
  attempt identity, aggregate claims and version diagnostics.
- Review history is retained in its issue/PR and Git history, not as a parallel
  architecture document.

This document is a coordinating plan. PLC1B claims only document-backed frozen
declarations and inert shadow parity. It does not claim owner admission,
executable Plugin evaluation, Plugin management control, live Resource/Tool/
Command publication, or any Coding Plugin production cutover.

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
  -> implement Resource-owner components, one Catalog, and typed lazy Resource
     loading while retaining manifest-free native Skills
  -> prove both no-code Resource and executable Capability fixtures
  -> migrate coding.lsp and delete its peer runtime path
  -> migrate coding.base and delete CLI/bootstrap peer registrations
  -> migrate coding.arch and prove a second Capability/optional dependency
  -> stabilize the public author SDK
  -> stabilize the Resource/Skill author SDK over the converged path
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
8. Make one Resource Catalog authoritative before LSP/Base/Arch migrations so
   later Product Plugins do not bind to legacy Loader or Skill fallback paths.

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
   entrypoint cannot each emit the same Tool, Command, Skill, or Provider. One
   exact source group is decoded/evaluated once and the complete preflight is
   finalized once.
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
  -> PluginSelectionResolver inert preflight proposal/outcome
  -> accept directly if every proposed source requirement is already satisfied
     (all data-only is the no-decision special case)
     OR, only when a current decision is missing, pending subjects; Approval
        owner records decisions, then fresh preflight revalidation
  -> accepted active token + exact PluginDeclarationSourceGroups
  -> document decoder OR approved PluginDefinitionEvaluator once per group
  -> source-evidenced PluginDeclarationBatch values
  -> PluginDeclarationCoordinator joins the complete non-overlapping set
  -> PluginSelectionResolver final reservation match once per preflight
     OR Coordinator-owned aggregate abort/expiry
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
  absent | installed_disabled | installed_enabled(current revision)

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
| `tool_pack` | Typed Tool selection/definition pack with Capability requirements | Tool definition/contribution owner |
| `command_pack` | Typed Command pack referencing admitted resources and Capability facets | Command/Presentation owner |
| later accepted kinds | Events, Agent definitions, presentation, external services, configuration | Their exact accepted owners |

Only the initial production set is in the first implementation scope:
`capability_provider`, `resource_item`, `tool_pack`, and `command_pack`.
PLC4.5 adds only the two internal Resource-owner `capability_component` schemas
`resource.catalog_engine` and `resource.source` before LSP. Generic, public, or
cross-owner component authoring follows after the complete-Bundle LSP path is
stable.

These tags classify contributions, not packages. A canonical Plugin package
does not declare one `pluginType`, numeric hierarchy, or capability bitmap.
Contribution kind, owner-specific subtype, declaration source model,
Host-verified origin/trust, and Product/OEM selection are separate facts. A
package may contain several kinds. Any resource-only, executable, Capability,
or mixed label is a derived catalog/UI projection and has no effect on
identity, compatibility, trust, admission, or binding.

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

PLC1B uses runtime-only `ContributionIndex` v2 and `PluginDeclaration` IR v2,
plus `PluginDeclarationDocument` envelope v1. The local PLC1A v1 draft is an
explicit unsupported-version fixture after cutover, not a second runtime
parser. Every source and Resource locator is revision-root-relative and is
opened only through `VerifiedRevisionHandle`; `packageRoot` does not rebase it.

Within one Product/scope/policy preflight context, selecting any contribution
closes its proposed reservation group over every index entry sharing the exact
package revision and `sourceDescriptorFingerprint`. The descriptor fingerprint
excludes revision and is safe inside package bytes. Each accepted
`PluginDeclarationSourceGroup` adds Host-computed `sourceGroupFingerprint` and
attempt-specific `sourceGroupId`, then binds that context, its gate kind, sorted
reservation closure, and a canonical group-configuration fingerprint over the
per-reservation map. The same declaration source cannot be split across groups
in one preflight, one group is decoded or evaluated exactly once, and one
reservation belongs to one group; a mixed package may still have several
distinct source groups. Once every group has source-appropriate evidence, the
declaration coordinator joins the complete batches and invokes finalization
once. Otherwise it moves the accepted aggregate once to `ABORTED` or `EXPIRED`
without finalization. Finalization may emit only the Product-selected candidate
subset, but it must first validate the source's complete declared closure.

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
When a Capability Plugin distributes a Provider with Tool or Command consumers,
the three remain sibling contributions joined by typed requirements and the
Product selection closure. The Provider never contains their declaration or
registration authority.

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

Tool and Command owner admission returns normalized declared
`CapabilityRequirement` values. Before Provider selection,
`ProductCompositionCompiler` combines those admitted requirements with
mandatory Product roots into one `ProductCapabilityConsumerRequirementSet`.
The Provider resolver uses its Capability IDs/contract/facet constraints to
select the complete closure, and the existing Graph request receives the
resulting root IDs. After Graph publication, the Product runtime capture path
hands exact typed views to the Tool/Command owners. This is path 2 above, not a
third Consumer route or a direct Tool-to-Provider lookup.

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
facets, and publishes semantic runtime, typed tool-runtime support, and
diagnostics in one Graph Mount generation. Model-visible Tool definitions are
an admitted sibling `tool_pack`: the Tool owner captures that runtime facet and
the Product Session makes the Tool generation visible only with the Mount. Its
migration deletes deferred LSP runtime and early Tool registration.

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
| `harness.resources` exposes Tool/Command pack facets consumed during Session composition | facets retain only immutable references to exact owner-admitted pack snapshots; Tool/Command owners stage definitions and registrations | no Resource-generation value can publish or retire a Tool/Command definition |
| `coding.cli.build_builtin_tool_registry()` directly calls `register_coding_builtin_tools()` | admitted `coding.base` `tool_pack` owned and registered only by the Tool owner; Resource owner resolves referenced source items | standard-mode parity and no direct registrar callers |
| CLI directly calls `register_coding_arch_tools()` | admitted sibling `tool_pack` consuming the mounted `coding.arch.default` runtime facet | Arch Graph/Tool migration and caller inventory green |
| Retired: Coding bootstrap called `register_coding_lsp_tools()` against a deferred runtime | admitted sibling `tool_pack` consuming the mounted `coding.lsp.default` runtime facet | completed; the registrar, deferred runtime and bootstrap binder are deleted |
| `_CODING_AGENT_PRODUCT_CONSTRUCTION` binds one monolithic default Coding prompt | Kernel prompt plus separately owner-admitted Resource prompt fragments and Tool usage sections combined by Product composition | minimal/standard prompt snapshots and Model Input provenance green |
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

PLC1A completed PAP1's typed `capability_provider` codec and
reservation-bound internal builder. PLC1B is the next source-changing slice and
is divided into four independently reviewable declaration-only increments.

#### PLC1B-1: Versioned Declaration Source Union

Scope:

- advance `ContributionIndex` and `PluginDeclaration` to runtime-only v2 and
  add strict `PluginDeclarationDocument` envelope v1; draft v1 input fails
  closed and no compatibility parser remains beside v2;
- advance unpublished `CapabilityProviderDeclarationPayload` and
  `PluginSymbolReference` to v2, remove `packageDigest` from package-internal
  symbol references plus the redundant payload configuration fingerprint, add
  Index-owned `contributionExecutionModel`, and let only the Host-resolved view
  attach the exact published package digest and validate that model;
- replace the implicit entrypoint-only source with one strict tagged
  `PluginDeclarationSource` union;
- define `document` as a contained immutable document locator plus exact
  schema/media identity, with no import or executable decision consumption;
- define `in_process` as the existing contained Python Definition entrypoint,
  still without importing it in this slice;
- bind source kind and the revision-independent descriptor fingerprint into
  reservation and declaration provenance;
  revision/context provenance is Host-attached only in group/evidence/candidate
  records. Locators are revision-root-relative and opened only by
  `VerifiedRevisionHandle`;
- distinguish package installation/trust `package_source_identity` from the
  package-internal `sourceDescriptorFingerprint`, Host-computed
  `sourceGroupFingerprint`, and attempt-specific `sourceGroupId`, and use
  a separate `PluginContributionExecutionModel` type for factory/service
  runtime identity;
- within one Product/scope/policy preflight context, partition selected
  contribution facts by exact revision and source descriptor fingerprint;
  selecting any item closes the proposed group over every index entry sharing
  that source, then
  binds the accepted `PluginDeclarationSourceGroup` to its gate kind, sorted
  closure and canonical per-reservation configuration-map fingerprint; reject
  attempts to split one source descriptor across multiple groups;
- revise `PluginDeclarationReservation` to retain only package/contribution/
  reservation identity plus its source-group ID/fingerprint; dynamic Context,
  trust, Product/scope, policy, configuration and authority facts live once on
  `PluginDeclarationSourceGroup`, which is also the sole
  owner of the strict gate union: `data_only` for `document`, or
  `execution_preflight` with one positive group-level
  `PluginExecutionApprovalSubject` and decision reference for the complete in-
  process reservation closure;
- replace partial/exceptional preflight returns with the strict
  `PluginPreflightOutcome` union. A first call returns only canonical proposed
  subjects when approval is pending; after decisions are recorded, a fresh call
  recomputes revision/trust/policy/scope/configuration and materializes the
  active token, groups and reservations atomically only on the fully accepted
  arm;
- add pure-data `PluginPreflightContextV1` and `PluginInstanceRevisionRef` as
  Product-supplied identities; PLC1B validates but does not persist/invent them,
  while PLC2 later owns the same durable lifecycle without schema redefinition;
- make `PluginSelectionPlanV2` the sole Product context, trust-policy-revision,
  effective-configuration and allowed-authority input; preflight accepts the
  Approval-owner read-only decision lookup port, not peer context/overlay/
  policy arguments or a caller decision tuple. The pre-PAP2 production lookup
  is pending-only. The Plan configuration set covers the union of proposed
  closures, while each SourceGroup hashes only its closure-local projection; a
  disjoint group's configuration cannot alter this group's Subject/decision key;
- reuse one low-level `resources.plugins` strict JSON primitive for manifest and
  DeclarationDocument schema codecs; Coordinator imports no raw JSON decoder
  or Path reader and isolates byte ingress in a concrete-
  `VerifiedRevisionHandle` method with
  exactly one `open_file`, stream `read`, and direct document-codec
  `decode_bytes` call. It accepts no callback; architecture guards freeze the
  import/call edge and reject any stored/mutable codec instance, import
  shadowing, decoder aliases or imported helper calls;
- implement the exact Source/Index/Declaration/Document/Subject/Decision/
  document-evidence/candidate fields, canonical bytes, fingerprint domains and
  diagnostics frozen by the PLC1B Contract;
- advance the group-level `PluginExecutionApprovalSubject` to v2 and
  `PluginExecutionDecisionRecord` to v2 with independent
  `decisionRecordVersion: 2` and `subjectSchemaVersion: 2`; old
  single-contribution subjects and unversioned decision records fail with
  separate exact unsupported-version diagnostics;
- introduce source-appropriate `document_decoded` and
  `in_process_evaluated` declaration evidence rather than propagating a
  preflight decision as final evidence; PLC1B finalizes document batches but
  rejects in-process finalization as `execution_not_consumed` until PLC3;
- add the inert document decoder and `PluginDeclarationCoordinator`. It owns
  the active token, pre-scans the full group set, rejects overlapping/extra/
  missing declarations, and invokes finalization once for a complete document-
  only preflight. A mixed source preflight accepts no executable declaration or
  Builder input, aborts as `execution_not_consumed`, and invokes finalization
  zero times until PLC3 supplies executable evidence;
- replace candidate `decision_id` with strict source-group/evidence provenance,
  bind evidence to `preflightUseId`/attempt-specific group ID, and define group
  claim/in-flight fencing under explicit
  `ACTIVE_OPEN -> FINALIZED|CLOSING_ABORT|CLOSING_EXPIRE` aggregate states;
  consumed decisions remain consumed after aggregate abort and retry starts a
  fresh preflight/decision;
- install a process-owner expiry reaper before accepted publication, atomically
  expire deadline claims, and let only a claim worker's shielded physical
  completion decrement in-flight; close requests cancellation but cannot settle
  for the worker;
- reject nullable peer fields, unknown tags, noncanonical locators, and one
  reservation consumed through more than one source model; and
- delete/private-scope the top-level subject builder, `PluginPreflight`, direct
  `finalize()` and `rollback()` entry points; only the higher
  `plugin_authoring` Coordinator holds the private terminal handle.

Exit gate:

- v1 index/IR fixtures fail with exact unsupported-version diagnostics; v2
  index/IR and document v1 round trips/fingerprints are canonical;
- a document-backed Capability Provider payload/symbol-reference v2 contains no
  `packageDigest`, publishes without a digest fixed point and is Host-bound to
  the exact package digest and Index-owned contributed model; required nullable
  disposer fixtures are exact, the payload has no configuration-fingerprint
  peer, and both unpublished v1 shapes fail their own version diagnostic;
- document v1 has only `documentVersion` and a non-empty declaration list sorted
  by `(pluginId, contributionId)`; unknown fields, wrong order, duplicates and
  closure mismatch fail closed;
- both source arms exact-match verified package revision and descriptor identity
  through Host validation. Host-created Batch/Evidence, not the document/source
  record, binds Product/scope/policy/configuration, attempt and closure;
- same-source multi-contribution and same-package document multi-source fixtures
  prove one decode per group, exact group closure and one finalization per
  preflight;
- mixed document/in-process fixtures prove exact partitioning, zero import,
  zero executable declaration ingress, typed `execution_not_consumed`, one
  aggregate abort and zero finalization; the accepted mixed fixture uses only a
  private decision-lookup test double because the production pre-PAP2 lookup is
  pending-only;
  successful mixed evaluation/join/single-finalization is a PLC3 exit gate;
- a document batch carries verified `document_decoded` evidence without an
  execution subject/decision/receipt; isolated in-process Builder codec output
  cannot enter the Coordinator or form a Batch/candidate until PLC3 supplies the
  evaluator and receipt evidence;
- document candidates serialize no subject/decision/receipt field; executable
  decision identity appears only within `in_process_evaluated` receipt evidence;
- declaration source kind remains distinct from any factory, disposer, or
  external-service execution model recorded by the contribution payload;
- parsing, selection, and authoring remain inert; and
- Product override/delete/missing/extra configuration, secret-reference
  rotation/Product-owner pre-handoff raw-secret rejection, and a two-group
  isolation case have regression fixtures; the latter changes only group B and
  proves group A configuration/group/Subject digests remain fixed; duplicate
  manifest keys, unsorted Index items, the exhaustive condition-to-code map,
  and typed diagnostic preservation also have regression fixtures; and
- semantic digest fixtures freeze `allow_nan=False`, `ensure_ascii=True`, sorted
  keys/no whitespace, CJK escaping, normalization-form distinction and unpaired-
  surrogate rejection; and
- no compatibility shim retains the old entrypoint-only parser as a peer path.

Required current-source migration inventory:

- `declarations.py`: version constants, contribution source/gate/group,
  independent contribution execution model, descriptor/reservation
  fingerprints, declaration IR v2, exact wire fields/
  domains/document ordering, duplicate-key/noncanonical-byte rejection, strict
  Unicode scalar validation and golden digest fixtures;
- `manifest.py`: `_contribution_index()` containment checks move from
  `entrypoint_path` to the one revision-root-relative source locator codec. Its
  mutable-root `resolve(strict=True)` remains only a pre-publication diagnostic;
  strict duplicate-key decoding precedes Index extraction, Index order is
  rejected rather than silently normalized, typed codec diagnostics are
  preserved, and declaration bytes are read only through
  `VerifiedRevisionHandle.open_file()`;
- `resources/plugins/_strict_json.py`: the only low-level UTF-8/BOM/constant/
  duplicate/depth decoder and canonical encoder; manifest and document schema
  codecs share it, with canonical-byte equality enabled only for the document;
- `selection.py`: subject and decision-record schemas advance to group-level v2;
  the decision record binds `decisionRecordVersion: 2` and
  `subjectSchemaVersion: 2`; preflight is the
  fresh proposal/pending/revalidation/accepted protocol; only SourceGroup owns
  the gate; candidate `decision_id` becomes attempt-bound evidence provenance;
  the Plan contains the one Context/trust/configuration/authority authority,
  the decision input becomes an Approval-owner lookup port, and private
  claim/settle/finalize/close CAS serializes explicit open/closing/terminal
  transitions;
  old public subject/finalize/rollback exports disappear;
- `plugin_authoring/coordinator.py`: the only terminal-handle consumer, document
  group claimant, one verified `open_file()` caller, Host evidence/Batch
  constructor and finalization caller; it imports no JSON or Path reader;
- `plugin_authoring/reservations.py` and `builder.py`: retained views/builders
  bind exactly one source group and reject cross-group or overlapping input;
- `plugin_authoring/capability_provider.py`: payload and symbol reference advance
  to v2, package digest/configuration-fingerprint peers leave package payload,
  required disposer becomes `SymbolReferenceV2|null`, factory/disposer execution
  model becomes `PluginContributionExecutionModel`, and the Host validates both
  refs against Candidate package provenance plus Index model rather than
  declaration source kind;
- exact finite callers/fixtures in `plugin_authoring/builder.py`,
  `plugin_authoring/reservations.py`, `resources/plugins/__init__.py`,
  `tests/harness/conftest.py`, manifest/selection/authority/builder/provider
  tests, `tests/harness/resources/plugins/test_plc0_fixture.py`, and the
  architecture export freeze move explicitly to v2 or the
  matching unsupported-version expectation. No v1 decision digest is accepted
  by the v2 group subject; and
- architecture inventories include `plugin_authoring` raw JSON/read sinks,
  count exact call expressions, freeze the sole document `open_file()` and
  strict decoder callpoints, verify the concrete handle annotation/receiver,
  reject stored/mutable codec routes, import shadowing and any helper call from
  the byte-ingress method, and use synthetic
  peer-route tests for assignment/module/third-party aliases, a second decoder
  (including `JSONDecoder.decode` inside an allowed function), Path read,
  Subject builder, or terminal caller. `resources/plugins/types.py`
  is explicitly audited and requires no PLC1B schema field change.

#### PLC1B-2: Resource Item Declaration

Scope:

- add the strict `resource_item` payload arm;
- define an owner-versioned Resource subtype union initially covering `skill`,
  `prompt`, `method`, `theme`, `asset`, and raw `source` descriptors;
- bind every Resource locator to immutable package bytes, media/schema facts,
  owner namespace, and configuration fingerprint using the same revision-root
  locator base; and
- keep each Skill a Resource identity that may be packaged with other items,
  not a Plugin instance or a separately executable Definition.

Exit gate:

- every Resource subtype round-trips through canonical JSON and rejects
  cross-package, duplicate, traversing, callable, or owner-mismatched data;
- document-backed Resources acquire no live Resource generation; and
- Resource subtypes cannot mint Tool, Command, or Capability identities.

#### PLC1B-3: Tool And Command Consumer Declarations

Scope:

- add strict `tool_pack` and `command_pack` payload arms referencing
  owner-controlled catalogs or future owner-approved definitions;
- express Capability use only through typed requirements and requested facets;
- keep Provider, Tool pack, and Command pack as sibling contributions even when
  one package and Product selection closure require them together; and
- reject embedded registries, live callables, arbitrary service bags, Provider
  self-admission, an explicit Provider requirement on its own Capability, and
  duplicate requirements. Transitive cycles are deferred to the existing Graph
  Planner after PLC4 produces the complete selected Provider set.

Exit gate:

- declaration codecs do not resolve Tool/Command implementations or access a
  live Provider;
- a Provider cannot contain or emit a sibling contribution; and
- owner/catalog and Capability requirement fingerprints are canonical and
  exact-match the reserved facts.

#### PLC1B-4: `coding.base` Shadow Declaration

Scope:

- compile a document-backed `coding.base` shadow package containing optional
  prompt/Skill Resources plus standard Tool and Command packs;
- validate only frozen declaration IR, pinned catalog/schema revisions and
  catalog identities without resolving Host-environment implementations; and
- compare `PluginContributionSemanticFingerprint` v1 values over canonical
  pre-owner/pre-Host-normalization payloads with equivalent hand-authored/
  internal-builder outputs; complete declaration/candidate fingerprints stay
  source-bound.

Exit gate:

- the shadow package has no Tool registration, Resource publication, Session or
  Model Input effect;
- hand-authored, document-backed, and internal-builder routes produce the same
  canonical catalog-reference payload and semantic fingerprint, while full
  declaration/candidate fingerprints preserve source/reservation/evidence
  provenance; Host-specific normalization and live behavior parity remain
  PLC4/PLC6 gates; and
- disabling or removing the shadow fixture requires no disposer or live-state
  cleanup.

PLC1 overall exit gate:

- all four PLC1B increments have independent regression and architecture gates;
- no top-level Plugin type code or bitmap participates in parsing, identity,
  trust, admission, selection, or binding;
- the generic Resource Plugin path exists before any `coding.base` production
  cutover; and
- PLC1 remains rollback-safe by deleting only inert codecs, fixtures, and IR.

### PLC2: Minimum Lifecycle And Management Control

Implementation is split by the normative
[Plugin Lifecycle PLC2 Contract](plugin-lifecycle-plc2-contract.md): PLC2-1
delivers only the inert desired-state ledger and durable Instance identity;
PLC2-2 adds the single typed management command core; PLC2-3 adds staged update
and exact restart outcomes; PLC2-4 adds retirement/cleanup handoff and recovery.
No earlier slice may impersonate the authority assigned to a later slice.
PLC2-1, PLC2-2, PLC2-3 and PLC2-4A through PLC2-4D are implemented.

Scope:

- define Package Revision, Installation, desired selection, lifecycle
  transition, retirement aggregate, and cleanup handoff records; durably issue
  and own the already frozen PLC1B `PluginInstanceRevisionRef` identity without
  changing its fields or meaning;
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

Implementation status (2026-08-23): the internal PLC3-1 through PLC3-3 path is
complete and regression-gated. Production `PluginDeclarationHost` ingress and
all PLC4 owner admission/binding remain disabled.

Scope:

- complete PAP2 durable Approval-owner decision issue/query/consume/revoke and
  the installation/workspace-scoped decision journal plus attempt-bound use
  reservations, with one subject/decision bound to each exact in-process source
  group and complete sorted reservation closure;
- require claim then aggregate start permit before the atomic Approval consume/
  use-reservation transaction; close-before-permit forbids execution, while
  permit-before-close continues under in-flight fencing and makes close wait for
  actual worker completion;
- persist exact `hostBootId`/`importRealmId`, reconcile external-boot
  `CONSUMED_NOT_STARTED` to `CANCELLED_BEFORE_START`, and commit `STARTING`
  before loader invocation; only current-realm `EVALUATED` produces receipt
  evidence, while `STARTING`/`FAILED_AFTER_START` fences the polluted import realm
  until a clean Host restart unless idempotent re-evaluation was accepted;
- complete PAP3 verified Plugin Definition evaluation and import-closure gate;
- import each source group once; Definition/Builder returns only frozen
  declarations, while the Host evaluator alone attaches
  `in_process_evaluated` receipt evidence and constructs the Batch;
- join executable and document batches before the one finalization call;
- produce the same frozen declaration IR v2 and semantic payload fingerprints
  as document sources while retaining distinct full provenance; and
- fail closed to isolated-worker or clean-host restart when closure cannot be
  proven.

Exit gate:

- disabled, denied, expired, stale, wrong-scope, wrong-digest, revoked, or
  incompatible code is never imported;
- consume/revoke, permit/close, consume/crash and recovery races have tested
  linearization with no resumable before-start orphan; and
- mixed document/in-process success evaluates each group once, joins all
  evidence and finalizes exactly once;
- later-group failure/cancellation aborts exactly once, publishes no candidate,
  and never reuses a consumed decision/receipt across `preflightUseId`; and
- evaluation cannot bind or publish a contribution.

### PLC4: Exact-Owner Admission And Binding Bridges

Scope:

- complete PAP4 Capability-owner eligibility/final admission and pure Product
  Provider closure selection;
- complete PAP4R exact Resource, Tool and Command owner admission codecs/records
  for `resource_item`, `tool_pack`, and `command_pack`;
- have Tool/Command admission return normalized Capability requirements and
  compile them with mandatory Product roots into one
  `ProductCapabilityConsumerRequirementSet` before Provider selection;
- retain canonically sorted per-Consumer requirement/admission provenance;
  required constraints extend roots and apply conjunctively, while optional-
  only entries receive explicit satisfied/unsatisfied Product decisions rather
  than being silently merged or promoted; only `satisfied` adds the root/view;
- add the narrow Capability Component Host from PAP5;
- give every factory/bind/spawn attempt a one-use activation lease and exact-
  owner `ActivationUseReservation`; the Binder/Host starts the effect and no
  retry or external-service restart replays an old activation receipt;
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
- direct Provider self-requirement fails in the declaration codec, and every
  transitive Provider cycle is rejected only by the existing
  `RuntimeCapabilityGraphPlanner` over the complete selected set;
- Tool/Command owner generations receive only captured typed facets through the
  Product runtime Consumer path and never look up a Provider directly; and
- no second Graph, Resource candidate, registry bag, or effective clock exists.

### PLC4.5: Resource Catalog And Source Component Foundation

The normative plan is
[Resource Catalog And Source Pluginization Plan](resource-catalog-pluginization-plan.md).

Scope:

- implement the minimum exact-owner `capability_component` lifecycle for the
  two Resource schemas `resource.catalog_engine` and `resource.source`;
- select one Catalog engine, aggregate filesystem/admitted-package/embedded
  source generations, and publish one immutable Catalog generation;
- normalize admitted items and Extension-generation hook output through one
  exact-generation source-snapshot ingress;
- retain native `SKILL.md` loading without Plugin packaging;
- adopt one prepared Resource owner generation through the existing
  `harness.resources` Provider and the single Session Graph;
- bind exact lazy body loads to source generation and content digest;
- bind native body identity during discovery, classify refresh before mutating
  mounts/handles, and preserve old generation handles to drain; and
- cut CLI, activation, prompt, command, refresh, and Model Input Skill callers
  to one focused Resource Consumer before deleting peer Loader paths.

Exit gate:

- one Catalog and one Resource-owner merge policy choose every effective Skill;
- Package Catalog remains non-effective installation inventory;
- Resource component changes require a new Session, while accepted content-only
  refresh publishes only at the next Resource/Model Input boundary;
- exact old generations drain and disposers cannot remove sibling sources; and
- no public universal component SDK, `harness.skills`, per-Skill Plugin, or MCP
  expansion is introduced.

This is the first production owner-component aggregation proof. It does not
replace PLC5 as the first production complete-Bundle Provider/Graph proof.

### PLC5: `coding.lsp.default` Production Provider

Implementation status (2026-08-26): PLC5.0 implements the private,
unpublished Product assembly seam needed before the LSP package cutover. Given
one finalized `PluginSelection`, exact Capability-owner bindings, the shared
Capability definitions, explicit Product Provider roots/choices, and any
prebound host Providers, it projects Provider candidates through the existing
authoring bridge, grants bounded owner eligibility/admission, and delegates the
closure to the existing `ProductCapabilityProviderResolver`. The result retains
the exact package, owner snapshot, and trust snapshot for every resolved
Provider and accepts only an exact map of externally issued activation-decision
IDs when forming the existing Session composition inputs.

The first narrow post-implementation review found that root partition and
Consumer contract/facet compatibility were still rechecked only by
`AgentProductSession`, after a caller could already request a durable activation
decision. PLC5.0 now closes that ordering gap with one shared pure closure
validator. The Product request explicitly identifies its host Capability IDs;
before component candidates are returned, the validator exact-matches the
remaining Consumer roots to the resolved external roots and validates satisfied
Consumer entries against the supplied host plus resolved Provider metadata.
`AgentProductSession` reuses the same validator with its actual built-in set as
the final defense rather than maintaining a peer rule. Regression coverage also
selects one of two admitted Provider alternatives and proves that its exact
package, trust snapshot, owner snapshot, and resolution remain aligned.

PLC5.0 deliberately does not issue Approval decisions, import or start Provider
code, publish a registry or API, choose defaults, or alter LSP behavior. The
complete lifecycle test now uses this seam from finalized Plugin selection
through external Approval, the existing Component Host and single Session
Graph, typed Tool Consumer capture, and reverse owner disposal. This removes
the last test-only manual Provider admission/resolution assembly path before a
real production adopter. The checked-in `coding.lsp.default`
declaration/package now reaches finalized inert Provider IR and its activation
symbols import through the unchanged Component Host boundary. Its sibling
data-only Tool pack declares the typed `coding.lsp` runtime Consumer without
registering Tools. A private `CodingLspPluginOptInRequest` carries only the
Approval-owner port; the Product composer expands it through package
publication, selection, executable-Definition Approval consumption, exact Tool
owner admission and Provider resolution. It then asks that same sole owner for
the exact Provider Activation decision, verifies that the returned record is
durably present under the same Subject, constructs the existing Component Host,
and binds the exact Session composition inputs. The decision remains AVAILABLE:
only Session Graph preparation may consume it through `prepare_component()`,
import/start the Provider and transfer its value to the Binder. Product-issued
Approval and Provider admission share the same bounded 300-second construction
window; expiry requires a fresh composition. The opt-in
assembly now also has a bind-once `CodingLspToolOwner`: it accepts only the exact
admitted pack and the captured `coding.lsp` Tool-runtime facet, constructs only
those two admitted Tool definitions, stages them through a narrow live-Session
port, commits after the complete generation is ready and disposes its
registration scope in reverse order. `on_demand` publication does not
accidentally activate the new Tools. Coding bootstrap now selects this complete
route whenever the Product mount is enabled and binds the owner to the live
Session Tool controller. A failed Graph preparation rolls back Provider and
Tool generations and never falls back. The Graph-backed semantic capture is non-owning; Session
retirement disposes Tools before Provider retirement, while `AgentSession`
never closes the Plugin runtime directly. A real fake-server vertical slice now
executes both generated Tools through the live Session in `always` and
`on_demand` modes, observes the mounted status view, explicitly stops the
Server, and proves disposal removes the Tool generation without a second Server
shutdown. The default cutover and old deferred-route deletion are complete.
Non-persistent Sessions place Definition and Activation journals in
assembly-owned temporary state, so CLI help discovery and other ephemeral
construction do not materialize a persistent Session directory.

The adopter-specific design review freezes the following PLC5.1 boundaries
before implementation:

- the migration rollout accepted one Product-owned
  `CodingLspPluginOptInRequest | None`,
  not a boolean treated as authority and not a caller-assembled Session
  composition. During migration, `None` retained the legacy route. The default
  cutover now constructs the request only inside Coding Product policy and has
  no caller-controlled bootstrap input. The Coding
  Product composer alone expands the request into finalized Plugin selection,
  exact owner admission, Provider resolution and Session assembly. The Approval
  owner remains the sole decision issuer; an opt-in request is neither a
  declaration-execution decision nor a Provider-activation decision;
- the mounted LSP Bundle value transfers to Graph ownership exactly once. A
  Graph-backed `CodingLspSessionAccess` is a non-owning query/control view;
  the retired legacy LSP cleanup was represented separately during migration.
  `AgentSession` never calls `close()` on a Graph-owned LSP runtime, and Binder
  rollback/retirement remains its sole disposer;
- a dedicated `CodingLspToolOwner` receives only the admitted `runtime` Consumer
  capture, stages invisible Tool registration leases, activates them only after
  the complete owner generation is ready, and retires them in reverse order.
  Bootstrap neither constructs LSP Tool definitions nor owns their leases; and
- the executable Definition reads only its own frozen effective configuration
  through a reservation-scoped, read-only Builder accessor. A strict
  `CodingLspPluginConfigV1` codec validates that JSON input before the Provider
  uses it. The first-party package may exact-lock the matching Loushang
  distribution and import a private narrow `loushang.coding.lsp._provider_api`;
  this neither widens the Component Host API prefixes nor publishes a stable
  third-party SDK.

The checked-in package may therefore reuse the current LSP engine while the
Plugin remains the selected lifecycle owner. Definition evaluation and Provider
activation still cross their distinct durable Approval gates. No per-workspace
package generation, ambient service locator, hidden fallback, or second LSP
runtime path is introduced.

#### PLC5.1a: Co-Distributed Dependency Evidence

Implementation status (2026-08-26): the Harness Host port, canonical lock
assembly path, and first checked-in consumer are implemented.
`PackageMaterializer` defaults to no grants,
accepts one injected Product resolver, proves every granted normalized
distribution through `InstalledPythonDistributionEvidenceResolver`, and unions
the resulting exact identities with the materialized-root scan before emitting
the existing v1 lock. Publication and binding both recompute that same closure.
Coding supplies a fixed resolver that grants only `loushang` to the exact
registered source of the reserved `coding.lsp.default` ID and rejects that ID
from any other source. Coding now ships that package as distribution data. Its
approved Definition imports the exact-version private adapter and emits only
reservation-bound Provider IR; the factory/disposer wrappers also resolve under
the unchanged Component Host prefix tuple using the same evidence policy. The
later PLC5.1b slice now supplies the private bootstrap mount; this subsection's
claim remains limited to co-distribution evidence and lock/import integrity.

The planned checked-in package exposed one narrower foundation gap. Before this
foundation, the canonical dependency-lock assembler discovered Python
distributions only below the materialized Plugin root, while
`coding.lsp.default` and its private
Provider adapter are files in the same installed Loushang distribution. Copying
distribution metadata into the Plugin directory, adding Loushang to the global
Host API prefixes, or publishing through a Coding-only binding path would each
create a second authority. PLC5.1a introduces none of those routes.

The frozen design has two roles:

- a Harness-owned `InstalledPythonDistributionEvidenceResolver` derives an
  exact normalized distribution name/version and its verifiable import origins
  from the running environment. It is used both while constructing a dependency
  lock and while checking an import from that lock; and
- a private Product-owned `CoDistributedPluginDependencyGrantResolver` maps an
  exact `(pluginId, sourceIdentity)` to a small tuple of distribution names.
  The initial Coding registry contains only the checked-in
  `coding.lsp.default -> loushang` relationship. Neither a manifest,
  declaration, user configuration nor Plugin code can add a grant.

The grant resolver is injected into `PackageMaterializer` as a read-only Host
port. Its default grants nothing, so existing local, Git and Python-package
publication semantics remain unchanged. The canonical
`PackageMaterializer._plugin_dependency_lock()` remains the only assembler: it
unions distribution facts discovered below the immutable revision with exact
identities proven for Product grants, canonicalizes once, rejects conflicting
versions, and emits the existing
`loushang.plugin-dependency-lock/v1` document.

```text
immutable verified revision distributions ----\
                                                +-> one dependency-lock assembler
Product-owned exact source grant -> installed --/          |
                                   evidence                 v
                                               existing lock digest / Approval

existing lock -> the same installed-distribution evidence -> verified import
```

The grant is package evidence, not a Plugin type, Capability grant, execution
decision, import result or lifecycle owner. It contains no caller-supplied
version and does not survive as a second durable record. The derived exact
distribution identity is already covered by the dependency-lock digest used by
selection, declaration execution, admission and activation. Package content
remains covered independently by the verified revision digest and source
binding. Publication and binding/restart recompute the same closure; absence or
change of the Product grant therefore produces the existing fail-closed lock
mismatch rather than a fallback.

Installed-distribution evidence has two accepted origin proofs:

- a normal wheel/install proof requires matching installed metadata and RECORD
  files that contain the checked-in Plugin source and any imported Loushang
  module; and
- a development-only editable proof requires PEP 610 `direct_url.json` with a
  local `file:` URL and `dir_info.editable == true`, matching installed
  name/version, an exact Product registry source, and both the Plugin source and
  imported module origin contained by that project root. Editable acceptance is
  a Product-owned development policy, never a Plugin setting. A plain source
  tree without matching installed metadata is not evidence.

The import checker uses exact recorded files for a normal install and proven
top-level package roots for an editable install. It does not execute `.pth`
files, follow a remote direct URL, accept name-only `sys.path` coincidence, or
trust an already imported module without checking its origin. The first-party
package may then import `loushang.coding.lsp._provider_api` because it is part of
the exact locked Loushang distribution. This is a same-trust-domain private
code boundary, not a public SDK or a claim that a distribution lock is a Python
module sandbox; source identity, Product selection and both Approval gates
remain the security authorities.

The resolver enumerates every installed candidate with the normalized name; it
never accepts whichever candidate a name-only metadata lookup happens to
return. Publication must select one candidate with the exact checked-in source
files and rejects a missing or ambiguous match. Import preflight may retain
multiple candidates only when they share the locked version, then admits the
single candidate whose RECORD/editable boundary contains the actual module
origin. Candidate paths are never unioned into one wider installation.

The following cases fail before Definition evaluation or Provider activation:

| Case | Required result |
| --- | --- |
| reserved `coding.lsp.default` ID from any other source identity | reject the Product grant; do not publish an executable candidate |
| exact checked-in source outside the proven Loushang install/project root | reject co-distribution evidence |
| missing distribution, version drift, malformed/non-local editable metadata, or unverifiable origin | reject dependency closure/import with a stable diagnostic |
| published lock differs when binding or reconstructing after restart | reject as dependency-closure change; require republish/reselection |
| opted-in LSP package cannot obtain its required grant | fail the opt-in Session; never use the legacy LSP route |
| ordinary Plugin has no Product grant | use only its current materialized-root dependency closure |

PLC5.1a is complete only when tests prove wheel and explicit editable evidence,
copied-source/ID impersonation rejection, missing-grant and version/origin drift
rejection, publication-to-bind recomputation, private adapter import under the
unchanged Component Host prefix tuple, and unchanged behavior for an ordinary
Plugin. It does not add arbitrary host-package dependencies, a dependency
installer, a second lock schema, public authoring API, MCP behavior, or a new
Plugin category.

#### PLC5.1b: Default Session Mount And Real-Process Parity

Implementation status (2026-08-26): implemented and cut over as the sole
enabled Product route. The checked-in package passes the complete publication, selection,
Definition Approval, owner admission, Provider resolution, Activation Approval,
Component Host and Session Graph path. Its sibling Tool owner publishes only
after the exact runtime-facet capture. Focused real-process regressions prove
that both `always` and `on_demand` modes execute `inspect_symbol` and
`document_outline` against the same fake LSP Server, expose status and stop
through the non-owning semantic facet, then retire Tools before Graph-owned
Provider cleanup. Unit regressions separately prove partial Tool publication
rollback. Product policy creates the private assembly request with an exact
first-party Approval owner that rejects any different Plugin, Product, scope,
entrypoint, Provider, owner, trust revision, facet or authority closure. The
request is not a public SDK parameter and no boolean is treated as authority.
Disabled mode and `no_tools=all` skip package resolution entirely. The legacy
reader callback remains in the public signature for compatibility but a
non-`None` value now fails closed: all LSP reads go through the admitted
`harness.workspace` facet.

The same atomic change deletes the deferred runtime, early Tool registrar,
bootstrap process binder and separate legacy cleanup input. There is no fallback
or second parser, binding or disposal path. Fresh reconstruction obtains fresh
Definition and Activation evidence for the new exact execution Subject rather
than replaying a stale decision.

Scope and gates are PAP6, including packaging the complete Bundle, narrow
workspace requirements, Tool/runtime Session co-visibility across their exact
owners, alternate Provider selection, rollback, replay, restart reconstruction,
owner-correct disposal, and deletion of deferred/early-binding peers.

This remains the first production Graph proof.

### PLC6: `coding.base` Production Resource Plugin

PLC6A through PLC6E implementation status (2026-08-30): the conservative production
boundary is frozen in the
[PLC6 contract](plugin-lifecycle-plc6-contract.md). Coding now exposes one
canonical, fingerprinted and side-effect-free expansion for
`coding-minimal`, `coding-standard`, and `coding-architecture`. The records are
Product requests only: they do not mutate management desired state or perform
Plugin selection, admission, publication, refresh, or retirement. PLC6B adds a
generic Product-selected package ingress that takes an independent verified
revision lease without mutating settings or rediscovering a source. The
default Catalog-owned `coding-standard` Session now mounts the checked-in
`coding.base`, seeds one combined Product selection with configured Resource
Plugins, publishes its Prompt and Skill through the sole Resource Catalog, and
assembles Kernel plus the admitted standard fragment exactly once. Refresh
reacquires the loader lease while the sealed Session retains its Product-owned
package evidence until disposal. PLC6C captures the configured Resource receipt,
combines its verified packages with `coding.base` and optional
`coding.lsp.default`, then prepares one Product compilation before workspace
Provider construction. It binds that exact compilation to Resource Catalog and
the Session, and stages the admitted base Tool and Command packs through
`tools.workspace` and `commands.session`. Both generations become visible only when the usable
Session composition commits, retire through their exact registration leases,
and appear in effective-runtime provenance. The CLI no longer registers the
base Tool pack directly, and the standard Catalog-owned Session no longer
obtains Commands from an unconditional peer publisher. Management desired-state
binding now consumes the same durable Coding Product snapshot used by the
common Harness management and Instance ledgers. Only a never-seen first-party
Installation receives idempotent default install/enable commands; explicit
disable and remove remain authoritative. Active Sessions retain a durable
family over their old revision and return an exact restart-required diagnostic,
while new Sessions select the current revision or omit the base package. Replay
opens the content-addressed revision through its durable binding after mutable
source deletion. PLC6E removes the Coding SDK/CLI Resource-authority selector,
the peer CLI Tool registrar, legacy Method adaptation, and every Coding
bootstrap branch that could execute legacy Resource discovery. Catalog receipt
preparation, publication, refresh, Prompt/Skill body reads, and Base/LSP Product
composition are now one mandatory path. Production validation and the terminal
architecture, correctness/security, and Product/test review completed on
2026-08-30. The final regressions cover exact delegate argv through the real
file-backed CLI/Catalog Session, canonical read-only Product policy before cwd
Extension preview, refresh-stable Resource and Tool isolation, platform-native
multi-agent prompts, public management update/disable/remove, cleanup retry,
and the one-compilation/no-Base paths.

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
- bind analyzers, facts, diagnostics, index/runtime support, and disposer in the
  Capability generation, while an admitted sibling `tool_pack` consumes its
  typed facets and becomes visible only with the usable Product Session; and
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
- stabilize the PLC4.5 filesystem, embedded and admitted-package Skill path and
  expose only the proven data-only helpers and advanced component surface; and
- add a strict native/package managed Skill-action declaration bound to exact
  script digest, runtime, argv/cwd/environment policy, effects, and containment,
  while retaining the existing authorized generic Tool path during migration;
- compile public builders to the same canonical manifest and declaration IR;
  validation/inspection remain inert and execution conformance is explicit;
  and
- expose a small Product build facade that distinguishes embedded contributions
  without Plugin identity from independently selectable built-in Plugins.

Exit gate:

- ordinary authors never receive owner authority objects;
- two IR/engine versions have explicit compatibility fixtures;
- all Skill list/enable/load/refresh callers use one catalog path; and
- model-visible Skill content is committed with source revision and digest;
- authoring has no ambient `PluginContext` or generic registry escape hatch;
  and
- both native and packaged Skill actions prove no execution during validation,
  exact Approval use, required-containment failure, and revision pinning.

### PLC9: Management, Isolation And Cleanup Closure

Scope:

- add CLI/RPC/UI/SDK projections over the already durable management core;
- add a versioned `local_worker` declaration arm and supervised Worker envelope
  over the authorized Process Host, while keeping semantic IPC protocols and
  publication with exact domain Component Hosts;
- evaluate `remote_service` only as a separate topology with explicit identity,
  authentication, egress, tenant, revocation, and data-residency contracts;
- complete required-containment Worker evaluation before untrusted executable
  admission; a same-user child process never counts as a Sandbox;
- make Package lifecycle the sole safe-materialization owner: bounded
  quarantine extraction, regular-file/directory-only trees, no path/link escape,
  digest-pinned dependency closure, no runtime source build or install hook, and
  atomic immutable publication. Python artifacts are verified wheel-only unless
  a separately contained build service is accepted and returns a verified
  artifact. Source adapters authenticate/fetch and deliver provenance plus
  bytes only through the Package lifecycle owner's bounded sink; they cannot
  choose quarantine paths, publish revisions, bind runtimes, or bypass final
  verification;
- migrate `manifest.enabled` once into an install-time default, treat
  `source.enabled` only as Source Authority availability, and remove their peer
  runtime-selection veto after `PluginManagementService` desired state is the
  sole selection writer;
- implement retained-version and orphaned-generation GC;
- add separately confirmed private-data deletion and backup retention;
- remove superseded Package/Plugin/Extension compatibility adapters; and
- add operational repair for partial retirement and failed cleanup.

Exit gate:

- every supported management surface calls one service;
- execution topology, trust, authority, lifetime, and placement remain
  independently diagnosable;
- malicious archives and source distributions cannot write outside quarantine
  or execute during install, inspect, validation, or activation;
- remove, retirement, GC and data deletion are visibly distinct operations;
- incomplete termination cannot be reported as disabled or removed; and
- no compatibility path independently mutates package, selection, owner, or
  effective state.

## Sequencing Decisions

The former UPA0-UPA8 sequence has been retired from the architecture master
document. This coordinating plan retains the three sequencing decisions already
reflected by the implemented PLC work:

1. split the UPA8 management work, moving the minimum durable management
   control core before the `coding.base` cutover while retaining UI, isolation,
   GC and destructive cleanup in the final closure; and
2. deliver production `coding.base` after `coding.lsp` but before
   `coding.arch`. The Base shadow package may start earlier, while the public
   SDK remains gated on all three production samples; and
3. insert PLC4.5 before `coding.lsp` to implement the internal Resource Catalog
   and source-component foundation, while leaving universal public component
   authoring and SDK stabilization in PLC8.

This ordering first closes the shared Resource aggregation substrate, then
proves one executable complete-Bundle Capability, closes the default Product
composition and duplicate base paths, and finally proves a second Capability
and optional dependency. It does not weaken the existing stable-SDK gate.

## Verification Matrix

### Lifecycle contract groups

| Contract | Required evidence |
| --- | --- |
| Resolve/install | immutable revision identity, containment, dependency lock, scoped installation |
| Declare | v2 strict tagged IR, exact source groups, one decode/evaluation per group, one finalization per preflight, source-appropriate evidence |
| Select | deterministic Composition Set expansion, desired-state CAS, no self-enable, admitted external-Consumer requirements compiled into Provider roots |
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
- revision-dependent descriptor fingerprint or other package self-reference;
- source mutation after package publication;
- document and Python declarations attempt to consume the same reservation;
- same-source multi-contribution, same-package multi-source, mixed-source,
  overlapping, missing, extra, and duplicate source-group closures;
- pending proposal followed by approval while revision/trust/policy/config
  changes before fresh preflight revalidation;
- draft v1 index/IR and per-contribution subject v1 presented after the runtime-
  only v2 cutover;
- decision record missing its independent `decisionRecordVersion`, or adding
  only a v2 subject version to an old record;
- document candidate attempts to serialize an empty/nullable decision peer;
- concurrent finalize/abort/expire and later-group failure after one decision
  has been consumed;
- group claim/execution-start permit racing aggregate close, permitted
  consumption continuing while close waits for physical completion, and
  evidence from an aborted/expired `preflightUseId` replayed into a fresh
  accepted attempt;
- duplicate JSON keys, BOM and noncanonical document bytes;
- CJK/combining-form semantic fingerprints and unpaired-surrogate input;
- executable declaration carries a positive decision but no current group
  consumption receipt;
- duplicate Tool/Command/Skill/Provider identity from legacy and Plugin paths;
- unknown declaration fields, traversal locators, callable payloads, and owner
  mismatch;
- enable/disable/update CAS races and crash during state transition;
- decision consume/revoke and consume/import-start races;
- import failure after durable `STARTING`, followed by retry in the same polluted
  Host;
- Product tries to select an owner-rejected or expired Provider;
- admitted Tool/Command Capability requirement is omitted from Product roots;
- conflicting required Consumer constraints or an optional-only requirement
  without an explicit Product satisfaction decision;
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
4. `coding.lsp.default` mounts through the existing Graph, the Graph remains its
   sole runtime disposer, and its deferred and early Tool paths are deleted;
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

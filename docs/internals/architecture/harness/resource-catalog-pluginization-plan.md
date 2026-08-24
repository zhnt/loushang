# Resource Catalog And Source Pluginization Plan

## Status And Authority

- Authority: proposed implementation plan under the accepted Harness Capability,
  Plugin lifecycle, exact-owner admission, Session Graph, Resource generation,
  and Model Input boundaries. It does not amend those boundaries implicitly.
- Design status: proposed.
- Implementation status: not started. The current `ResourceLoader`,
  `ResourceSnapshot`, `ResourceBundle`, and `SkillLoader` paths remain the
  implemented runtime until a phase below passes its cutover gate.
- Baseline: `main` at `e55db475`, tracked by issue `#495`.
- Scope: pluginize the Resource catalog mechanism and Resource source/loading
  mechanisms, converge Skill onto a typed Resource projection, and retain plain
  native `SKILL.md` loading.
- Explicit exclusions: one Plugin or Graph node per Skill, a second Skill
  registry, a new top-level `harness.skills` Capability, a global mutable
  service registry, stable public source-provider SDK publication, LSP/Base/Arch
  migration, remote marketplace work, and new MCP functionality.

The accepted
[Unified Plugin Architecture](unified-plugin-architecture.md),
[Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md),
[Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md),
[Extension And Resource Generation Lifecycle](extension-generation-lifecycle-boundary.md),
and [Session Resource Refresh Runtime Boundary](session-resource-refresh-boundary.md)
remain authoritative wherever this plan is silent.

## Executive Decision

Pluginize mechanisms, not every piece of content.

Inside the one existing `harness.resources` Capability owner, introduce two
owner-defined component schemas:

1. `resource.catalog_engine`: exactly one selected executable component that
   compiles admitted source snapshots and Resource items into one immutable
   effective catalog generation; and
2. `resource.source`: zero or more selected executable components that discover
   candidate summaries and lazily load exact Resource bodies.

Both are `capability_component` contributions owned and aggregated by
`harness.resources`; neither is a peer Capability Graph, a nested Plugin host,
or a registry that a contributor can mutate. The existing
`harness.resources` Capability Provider remains the only top-level Resource
Bundle seam during this delivery. A future complete-Bundle replacement may use
`capability_provider`, but it is not required to make Catalog and source
mechanisms pluggable.

Individual Skills, prompts, themes, methods, and assets remain `resource_item`
data. A native filesystem Skill remains loadable as an ordinary
`<skill>/SKILL.md` without a Plugin manifest, Python entrypoint, install record,
or executable activation decision. Packaged data-only Resources use the
existing verified revision and exact Resource-owner admission path.
An Extension entry may be cataloged as a Resource descriptor, but Extension
construction, approval, registration, publication, and retirement remain with
the existing Extension owner; the Catalog never imports or starts it.

```text
Plugin/OEM packages                         Native workspace/user roots
  |                                            |
  |-- resource.catalog_engine component       |-- plain SKILL.md / prompts
  |-- resource.source components              |
  `-- resource_item declarations              |
                 \                             /
                  exact harness.resources owner
                  |-- select one catalog engine
                  |-- aggregate selected source generations
                  |-- admit data-only Resource items
                  `-- publish one Catalog generation
                                 |
                    typed Resource Consumers
                      |-- Skill projection
                      |-- prompt/command projection
                      `-- exact lazy body load
```

The Plugin package is merely a packaging and selection unit. Catalog engine,
source adapter, and Resource item declarations are sibling contributions. A
Catalog engine cannot contain, select, approve, bind, unload, or replace its
source components or itself. Those actions remain with the Host, Product, and
exact Resource owner.

## Why This Shape

### Why not one Plugin per Skill

A Skill normally has content, metadata, referenced assets, and invocation
policy, but no independently live service, Capability facet, or disposer. Giving
every Skill a Plugin instance would duplicate install state, precedence,
refresh, enable/disable, and unload semantics. It would also make native Skills
need manifests for no runtime benefit.

### Why not a `harness.skills` Capability

Skill is one typed Resource view. A second Capability would create a second
catalog, merge policy, refresh clock, and Model Input projection. CLI listing,
prompt summaries, explicit load, and commands would then be able to disagree.
The Skill Consumer must derive only from the Resource catalog snapshot.

### Why not make every source a top-level Capability Provider

The Graph selects one Provider for a Capability, while a Resource catalog must
aggregate filesystem, admitted package, embedded/OEM, and optional future
sources. One Capability per source type would hard-code the source vocabulary;
one aggregate Provider per Product would make a small source addition replace
the whole Bundle. Owner-defined multi-component aggregation is the proper seam.

### Why not put source Plugins inside the Catalog Provider

A `capability_provider` may replace one complete Capability Bundle. It may not
host a nested Plugin runtime or grant authority to itself. Source components
are independently declared, admitted, selected, started, and retired by the
Resource owner. The Catalog engine receives only narrow generation-scoped
source views.

## Implemented Baseline And Duplicate Paths

The current code has already converged some semantics, but not the catalog
authority:

| Current path | Current role | Required disposition |
| --- | --- | --- |
| `harness.resources.loader.ResourceLoader` | Discovers all source kinds and owns the effective `ResourceSnapshot`. | Become a compatibility facade over one Catalog Consumer, then lose independent discovery authority. |
| `harness.resources._loader_precedence` | Owns the current source priority and ordering. | Move unchanged first into a versioned Resource-owner policy, then remove the peer policy module after parity. |
| `ResourceSnapshot` / `ResourceBundle` | Mix candidate evidence, effective winners, loaded bodies, and Product/session projection. | Retain `ResourceBundle` as a compatibility projection; make Catalog snapshot and load receipt authoritative. |
| `harness.resources.skills.SkillLoader` | Thin facade over `ResourceLoader`, plus a private disabled-name set. | Become a narrow Skill Consumer adapter; delete private discovery, precedence, body-cache, and activation state. |
| `harness.cli.skill_listing` | Reads `resource_bundle.skills`, then falls back to `resource_loader.get_skills()`. | Cut over to one Skill Catalog Consumer and delete the fallback. |
| `harness.resources.packages.catalog` | Inventories package/install/materialization state. | Remain the Package Catalog; never choose effective Resources or become an alias of the new Resource Catalog. |
| `harness.resources.refresh` and `session.resource_refresh` | Reload a bundle and commit it through existing Resource/Extension generation rules. | Stage and commit a next Catalog generation; project the compatibility bundle from that generation. |
| `harness.resources` Capability v1 | Publishes activation, prompt composition, Tool packs, and Command packs, but no typed Catalog/load facets. | Cut over atomically to an internal v2 contract; do not silently change v1 semantics. |
| Plugin `resource_item` admission | Admits inert verified locators under the exact Resource owner. | Feed the new catalog as data; do not create a second Plugin or source registry. |

The first implementation slice must freeze an executable caller inventory for
`discover_resources`, `reload_resources`, `get_resource_snapshot`,
`get_resource_bundle`, `get_skills`, `ResourceBundle.skills`, direct
`SkillDescriptor.content` reads, and package source mounts. No old caller may
remain able to discover or select an effective Skill after final cutover.

## Authority And Role Model

| Role | Owns | Must not own |
| --- | --- | --- |
| Host control plane | Package verification, immutable revision handles, executable trust and approval, activation-use journal, import realm, process/filesystem authority | Resource precedence, Product selection, model-visible wording |
| Product composition | Desired Plugin/component selection, native root configuration, OEM composition, activation settings, Product policy revision | Candidate parsing, owner admission, source disposal |
| `harness.resources` owner | Component definitions, exact admission, component selection validation, precedence/merge policy, Catalog generation publication and retirement | Package installation, executable approval, arbitrary Product defaults |
| Catalog engine component | Pure deterministic composition, resolution, conflict explanation, immutable snapshot construction | Plugin selection, source startup/disposal, direct filesystem/network access, self-replacement |
| Resource source component | Candidate discovery and exact body load through least-authority handles | Global precedence, effective-winner publication, Model Input commit, other source generations |
| Resource item | Inert schema/media/locator declaration bound to one verified revision | Code execution, registry mutation, lifecycle authority |
| Resource/Skill Consumers | Query a captured generation and request an exact load | Independent cache, precedence, fallback discovery, source unloading |

The Resource owner, not the Catalog engine implementation, is the public
authority. This permits replacing the engine without transferring policy or
admission authority to Plugin code.

## Component Foundation Required Before LSP

`capability_component` exists in the accepted architecture vocabulary but is
not yet an implemented ordinary authoring/runtime arm. PAP5.5 implements only
the minimum generic owner-component substrate required by Resources:

1. a versioned `CapabilityComponentDefinition` published by an exact Capability
   owner, including component kind, payload schema, compatible Bundle contract,
   multiplicity, selection/conflict rules, refresh boundary, and disposer
   contract;
2. immutable component Candidate, exact-owner Admission, Product Selection,
   Host Binding, and owner-generation records with independent fingerprints;
3. a narrow component factory context containing only owner-defined inputs and
   approved dependency views;
4. approval-gated verified construction for external in-process components,
   reusing the existing durable consume/start/commit/recovery semantics without
   reusing a complete-Bundle Provider approval subject as if it were the same
   authority;
5. atomic owner-generation staging: all selected components construct before
   publication, failure disposes in reverse order, and exact old generations
   remain pinned until consumers drain; and
6. exact-generation disposer leases. A disposer can retire only the component
   generation named by its admission/binding chain.

The first implementation supports only the two Resource-owner schemas in this
plan. It does not publish a universal component decorator or stable public SDK,
and it does not let arbitrary owners accept an untyped object bag. LSP remains
the first production complete-Bundle `capability_provider` proof; Resources
becomes the first production owner-component aggregation proof.

The existing internal class named `CapabilityComponentHost` currently prepares
complete `CapabilityBundleProviderBinding` values. Implementation must not
silently overload that class with owner-component semantics. Either retain it
as the complete-Bundle Host and introduce a distinctly named
`CapabilityOwnerComponentHost`, or perform a reviewed rename with compatibility
evidence.

## Resource Component Contracts

### Catalog engine

The exclusive `resource.catalog_engine` component is deterministic and has no
ambient I/O. Its owner-facing protocol consumes:

- immutable source snapshots;
- admitted data-only Resource candidates;
- one versioned Resource merge-policy snapshot;
- one Product activation-policy snapshot; and
- cancellation/deadline facts supplied by the owner.

It returns an immutable `ResourceCatalogSnapshot` plus complete conflict and
diagnostic evidence. It never invokes source discovery or lazy body reads by
itself. The Resource owner orchestrates those calls so cancellation, limits,
fault containment, and source ownership remain outside replaceable engine code.

The engine also does not own precedence merely because it executes the
composition algorithm. The Resource owner supplies a versioned pure
merge-policy evaluator. The engine must account for every input candidate and
use that evaluator; before publication, an owner validator canonicalizes the
output and verifies every effective entry/rejection against the same policy.
This validator holds no catalog state and performs no source I/O, so it is an
invariant enforcement layer rather than a second Catalog. A mismatch fails the
candidate generation.

Exactly one engine must be selected. No engine selected, more than one engine
selected, incompatible schema/contract, stale admission, or changed Product
policy fails before Catalog publication. The first-party standard engine is
default-selected by the Product composition set and can later be replaced for
new Sessions through the normal Plugin lifecycle.

### Source adapter

Each aggregate `resource.source` component exposes two narrow operations:

```text
discover(ResourceDiscoveryRequest) -> ResourceSourceSnapshot
load(ResourceLoadHandle) -> LoadedResource
```

Both operations may be asynchronous, cancellable, and budgeted. The source
receives only handles authorized for its declared source class. It cannot
receive a Session, Graph, global registry, approval store, credential bag, Tool
registry, or another source component.

`discover` returns summaries and opaque locators, not eager bodies. `load`
accepts only a handle minted from that source's still-live exact generation.
It must return exact bytes/text and a receipt; it may not redirect to a new
winner or a newer source generation.

Discovery may read bounded frontmatter or metadata needed to construct a
summary, but it does not retain that read as an authoritative loaded body. On
lazy load, the source revalidates identity and summary-relevant metadata against
the candidate discovery fingerprint. A change produces stale-generation
evidence and refresh rather than pairing an old summary with a new body.

The initial source component set is:

| Source component | Input authority | Initial behavior |
| --- | --- | --- |
| Native filesystem | Product-approved workspace/user/temporary roots and contained read handles | Standard Resource layout, including `<name>/SKILL.md`; no Plugin manifest for content |
| Admitted package | `VerifiedRevisionHandle`, admitted `resource_item` locators, package instance revision | Load only contained verified files/directories; no mutable package path authority |
| Embedded/OEM | Product-selected immutable package-resource handles | Built-in prompts/Skills/themes with stable source identity and content digest |

Remote/network source adapters, marketplace search, and MCP-backed discovery
are not initial source kinds. A later external service source must declare its
service dependency and pass the existing approval/policy/transport boundaries;
`resource.source` grants no implicit network authority.

### Data-only source descriptors

`resource_item(resource_kind="source")` remains an inert descriptor for roots,
collections, or source data understood by an admitted source component. It is
not executable source-provider code. This lets ordinary Plugins configure the
first-party filesystem/package engines without gaining a factory/disposer.

## Canonical Catalog Records

The first contract slice freezes strict internal records before moving any
caller:

The internal `harness.resources` contract v2 adds focused `resource.catalog`
and `resource.load` facets beside the existing activation/prompt/Tool-pack/
Command-pack facets. `SkillCatalogConsumer` requires only those two Resource
facets and applies its typed projection; there is no `skill.catalog` facet or
Skill Capability. The top-level Provider remains `refresh_boundary="sealed"`.
Content refresh replaces an owner-private Catalog generation under the already
accepted Resource-generation rule and does not rebind the sealed Provider.

### `ResourceIdentity`

```text
resource_kind
schema_id
schema_version
public_id
```

The tuple is the logical collision key unless the Resource-kind definition
declares an additive collection policy. Display names and source paths are not
identity.

### `ResourceSourceGenerationRef`

```text
source_id
component_contribution_id
component_candidate_fingerprint
component_admission_fingerprint
binding_fingerprint
product_id
scope_id
generation
plugin_instance_revision_ref (nullable only for native Host sources)
package_content_digest (nullable only for native Host sources)
```

Native sources still receive a Host-minted source identity, policy revision,
scope, and generation; absence of a Plugin instance never means absence of
provenance.

### `ResourceCandidateSummary`

```text
identity
canonical_name
description
media_type
invocation_policy
source_generation_ref
opaque_locator
discovery_fingerprint
declared_content_digest (optional)
diagnostics
```

The opaque locator is meaningful only to the named source generation. It is not
a general filesystem path and cannot be used with another source.

### `ResourceCatalogSnapshot`

```text
catalog_contract_version
catalog_generation
engine_binding_fingerprint
source_generation_fingerprints
merge_policy_revision
activation_policy_fingerprint
candidate_summaries
effective_entries
merge_decisions
diagnostics
complete
snapshot_fingerprint
```

Candidate, effective-entry, source, and diagnostic collections are canonical
identity-sorted. The fingerprint excludes wall-clock time and object addresses.
`complete=false` is explicit evidence and Product policy decides whether an
optional-source failure may publish a degraded snapshot.

### `ResourceLoadReceipt` and `LoadedResource`

```text
catalog_generation
snapshot_fingerprint
candidate_fingerprint
source_generation_ref
schema_id / schema_version / media_type
content_digest
content_length
```

`LoadedResource` adds the exact immutable body. A receipt without the exact
model-visible body is insufficient for Model Input reconstruction. Package
Resources normally have a declared digest before load; native filesystem bodies
gain their authoritative digest from the bytes actually read.

## Precedence, Merge, And Activation

The Resource owner publishes the merge policy. A source component may report
scope and provenance facts but cannot assign itself global priority.

The first cutover preserves the current source priority exactly:

```text
temporary > project_local > user_global > external_package > built_in
```

Within a class, Product-declared root order is retained. New canonical
tie-breakers use stable source identity, contribution identity, canonical
Resource identity, and contained relative locator; absolute host paths and
discovery completion order must not decide a winner. Any behavior difference
from the current `_loader_precedence` rules needs an explicit parity exception
fixture and Product decision.

Merge is Resource-kind-specific:

- named Skills, themes, templates, and exclusive assets select one winner;
- context files and explicitly additive prompt collections retain an ordered
  admitted set under their existing nearest-scope semantics; and
- duplicate identity within one source generation is invalid rather than
  silently last-write-wins.

Every conflict produces a `ResourceMergeDecision` naming all candidates,
winner or rejection, policy revision, and reason. Input order does not affect
the result.

Enable/disable is not a Skill-owned registry. Product settings compile one
`ResourceActivationPolicySnapshot`; the Catalog generation derives enabled and
model-invocable views from that snapshot. CLI enable/disable changes Product
settings and requests a next Resource generation. It does not mutate
`SkillLoader._disabled` or remove a source candidate.

## Skill As A Typed Projection

`SkillCatalogConsumer` is a focused Consumer over the captured Resource Catalog
and load facets. It provides typed summary listing, exact resolution, and lazy
body loading for `resource_kind="skill"`. It owns no store, precedence, watcher,
disabled-name set, or source disposer.

All Skill-facing paths converge on it:

- CLI list and JSON projection;
- enable/disable status and explanation;
- prompt-visible Skill summaries;
- explicit Skill load;
- `skill:<name>` command projection;
- watcher/refresh visibility; and
- Model Input evidence.

`SkillDescriptor` may remain temporarily as the compatibility projection, but
its `content` field is no longer the discovery authority. Lazy load returns a
typed loaded Skill bound to the Catalog and source generation. A command or
prompt that needs only name/description does not force body I/O.

For legacy Skills without an explicit frontmatter description, the filesystem
source may derive the existing bounded description during discovery, or the
specific compatibility projection may request an exact lazy load. It may not
reintroduce a second eager body store merely to preserve the fallback.

Scripts referenced by a Skill are not imported as Plugin code and are not
executed by the Resource source adapter. Execution goes through existing Tool,
Policy, Approval, Workspace, and Sandbox authorities.

## Native Skill Compatibility

Native Skill compatibility is a first-class path, not a legacy exception:

1. the Product supplies approved standard or explicit filesystem roots;
2. the first-party native filesystem source component scans those roots under
   bounded depth/file/byte limits and symlink-containment rules;
3. `<name>/SKILL.md` and supported flat Markdown layouts compile to the same
   `ResourceCandidateSummary` schema as packaged Skills;
4. frontmatter and body parsing use the shared Resource parser;
5. the Catalog owner applies the same identity, precedence, activation, and
   diagnostics rules; and
6. lazy load commits the exact body digest and content to Model Input.

The author needs no SDK, manifest, Python, installation, or approval dialog.
Moving the same Skill into a Plugin package adds verified package provenance and
data-only owner admission, not a different Skill runtime.

## Bootstrap, Publication, Refresh, And Retirement

### Initial Session

```text
verified desired Plugin revisions + native root policy
  -> declarations and exact Resource-owner admissions
  -> Product selects one engine and a source-component closure
  -> Host prepares executable component uses
  -> Resource owner starts one unpublished owner generation
  -> sources discover; engine composes Catalog generation 1
  -> compatibility ResourceBundle is projected from generation 1
  -> existing Session bootstrap uses only that projection
  -> harness.resources Provider adopts the exact owner generation
  -> Session Graph publishes once
  -> component activation uses commit; focused Consumers capture generation 1
```

The pre-publication object is a `PreparedResourceOwnerGeneration`, not a second
Capability Graph or another effective catalog. It has exactly one transferable
owner. Bootstrap may read only its narrow root-owned projection. On successful
Graph construction, the existing `harness.resources` Provider adopts it; on any
failure, the root aborts activation uses and disposes components in reverse
order. `StagedResourceCompositionCandidate` remains the sole Resource Profile
mechanism candidate.

The Resource Provider binding fingerprint includes selected component
definitions, implementation revisions, exact binding inputs, and owner/Product
policy revisions. Resource candidate summaries and body bytes belong to Catalog
generation fingerprints and never pollute the Provider construction
fingerprint.

### Refresh

Content-only refresh reuses the still-live exact component generation:

1. stage source snapshots and Catalog generation `N+1`;
2. run Resource/Extension declaration preflight and build the compatibility
   projection;
3. keep the current model request pinned to generation `N`;
4. atomically publish `N+1` at the accepted next Model Input/Resource-generation
   boundary; and
5. retire `N` only after its Consumers and loads drain.

Native file body edits and data-only Resource changes may use this path. Source
component code/digest changes, engine replacement, trust/approval changes,
component-selection changes, or multi-owner executable topology changes apply
to new Sessions and report `restart_required` for active Sessions.

A load against generation `N` never silently falls through to the winner in
`N+1`. If its exact source generation is stale or unavailable, the load fails
with typed stale-generation evidence and requests refresh.

### Disable, update, unload, and Session disposal

- Removing one data-only Resource stages a Catalog generation without that
  exact admitted identity; it cannot remove another source's candidate.
- Disabling/updating a component changes desired selection for new Sessions.
  Active Sessions retain their admitted component and Catalog generations until
  drain unless the accepted single-owner content-refresh rule applies.
- A source disposer receives only its exact generation lease. It cannot access
  another source, the Catalog engine, the Resource Provider, or the Graph.
- Session disposal invalidates Consumer captures, drains lazy loads, retires
  Catalog generations, disposes sources in reverse owner order, disposes the
  engine, then releases verified revision handles through their existing owner.
- Partial disposal remains explicit retryable retirement evidence; generic
  cleanup never claims global rollback.

## Model Input And Resume Evidence

Before a model request, the Product constructs visible Skill summaries from one
captured Catalog/activation generation. An explicit body load records:

- Catalog snapshot fingerprint and generation;
- effective candidate and source-generation identity;
- activation-policy fingerprint;
- exact body content digest; and
- the exact model-visible text/bytes, or the existing durable content reference
  that reconstructs those exact bytes.

Refresh never rewrites an already committed request. Cold transcript replay
does not need to reopen the original path or restart the original source Plugin
to explain a historical request. Current-session reconstruction may rebuild a
new Catalog from current desired state, but historical Model Input remains
bound to its committed content and receipt.

## Security And Fault Containment

The first implementation must freeze adversarial behavior for:

- path traversal, absolute locator, symlink escape, mutable package-root swap,
  and verified-handle digest mismatch;
- source discovery timeout/cancellation, file-count/depth/body-size budgets,
  invalid encoding/frontmatter/schema, and diagnostic redaction;
- duplicate identity, unstable ordering, provider-supplied priority, and
  source completion races;
- stale Catalog handle, load-after-dispose, unload while a load is active, and
  disposer failure;
- executable component approval revoked before start, crash after consume,
  failure after start but before owner publication, and stale owner/Product
  policy;
- Catalog engine returning foreign locators, changing candidate identity,
  omitting input candidates without a merge decision, violating the
  owner-supplied merge-policy result, or emitting a non-canonical snapshot; and
- a cataloged Extension, Tool, Command, or Skill script attempting to execute
  through Resource loading instead of its exact owner lifecycle; and
- native Skill scripts attempting to bypass Tool/Approval/Sandbox execution.

Required built-in sources fail initial publication. Optional source failure may
publish only when Product policy explicitly permits a degraded
`complete=false` snapshot; the diagnostic and omitted source-generation
fingerprint remain visible. No exception may silently reuse a previous body as
if it came from the new generation.

## SDK And Author Experience

There are three deliberately different author paths:

1. **Native author:** place a standard `SKILL.md` or Resource file under an
   approved root. No Plugin SDK is required.
2. **Ordinary Resource Plugin author:** use data-only helpers such as
   `resource_item(...)`, a future `skill(...)`, and `resource_bundle(...)` to
   reserve verified locators. These helpers emit the same strict declaration
   IR and grant no executable authority.
3. **Advanced source/engine author:** implement an owner-defined component
   factory/disposer against the least-authority Resource component protocol.
   This remains internal/preview until two production implementations and the
   complete-Bundle LSP proof establish compatibility.

The data-only convenience builders may stabilize earlier than the advanced
component SDK, but the stable top-level public Plugin SDK remains governed by
PAP7. No SDK helper may expose the Graph, a mutable registry, a Session,
filesystem paths outside approved handles, approval stores, or arbitrary
services.

## Delivery Sequence

### RCP0: Freeze baseline and contract

- attach delivery to issue `#495` and retain the isolated Harness lane;
- freeze caller/sink inventories and current precedence/merge parity fixtures;
- freeze the records, failure codes, lifecycle state transitions, and forbidden
  peer routes in this plan; and
- add architecture gates distinguishing Package Catalog from Resource Catalog.

Exit: current behavior is green, every duplicate caller has a named migration
or deletion phase, and no implementation symbol is falsely public.

### RCP1: Implement one inert Catalog core

- add immutable identity, candidate, snapshot, decision, activation, handle,
  loaded-body, and receipt records;
- implement the standard deterministic Catalog engine as pure logic;
- adapt the current `ResourceSnapshot` into/out of the new records in shadow
  mode; and
- prove order independence and current precedence parity.

Exit: shadow Catalog fingerprints and compatibility bundles match current
supported fixtures; no live caller has changed authority.

### RCP2: Implement owner-component lifecycle

- implement the minimum `CapabilityComponentDefinition` and exact
  candidate/admission/selection/binding/generation chain;
- add distinct Host preparation for owner components with durable activation
  transitions and exact disposer leases;
- package the standard Catalog engine and native filesystem source as
  first-party component contributions; and
- run them in unpublished shadow generations beside the current loader.

Exit: construction, cancellation, rollback, publication, drain, and disposal
are proven without a second Graph or live registry; current Product behavior is
unchanged.

### RCP3: Converge package and embedded sources

- adapt admitted package `resource_item` locators through verified revision
  handles;
- adapt embedded/OEM Resources through immutable handles;
- remove package-path reads that bypass the source generation; and
- prove native/package/embedded conflict and exact-unload semantics.

Exit: all supported source kinds produce one candidate schema and the Catalog
engine alone chooses effective entries.

### RCP4: Mount Resource Catalog generation

- introduce the internal `harness.resources` v2 Catalog/load facets and exact
  Consumer requirements;
- stage the initial owner generation during bootstrap, transfer it once to the
  existing Resources Provider, and capture focused Consumers after the one
  Session Graph publication;
- route refresh through next Catalog generation publication; and
- make `ResourceBundle` a projection of the captured generation.

Exit: v1 and v2 construction cannot both publish one Session; Provider disposal
retires only its adopted owner generation; model calls pin a Catalog generation.

### RCP5: Converge Skill and delete peer paths

- implement the typed Skill Catalog Consumer and lazy body load;
- move CLI list, activation status, prompt summary, command projection,
  explicit load, refresh, and Model Input evidence to that Consumer;
- turn `SkillLoader` and `ResourceLoader` into forwarding compatibility
  adapters; then delete adapters when caller inventory reaches zero; and
- remove `resource_bundle.skills -> resource_loader.get_skills()` fallback,
  independent disabled-name state, eager body authority, and duplicate watcher
  refresh.

Exit: one Catalog path serves every Skill operation; native Skills need no
Plugin; same-name selection is source-explainable; current-request immutability
and exact body receipts are proven.

RCP0 through RCP5 precede the `coding.lsp` production migration. They deliver
the missing bottom Resource aggregation primitive and prevent LSP/Base/Arch
from later depending on legacy Resource discovery. They do not publish a stable
advanced component SDK.

### RCP6: Author preview and production sample

- add concise data-only Skill/Resource declaration helpers and validation;
- add one non-example production-shaped Resource bundle fixture spanning
  native, package, embedded, enable/disable, refresh, and uninstall;
- retain source/engine factories as an internal preview until PAP7; and
- document migration for native authors and package authors.

Exit: ordinary Resource authors do not handle admission, binding, registries,
or disposal; advanced API stabilization remains gated by LSP and a second owner
component adopter.

## Verification Matrix

| Gate | Required proof |
| --- | --- |
| Architecture | One `harness.resources` Graph seam; one Catalog authority; no `harness.skills`; Package Catalog remains inventory-only; no new MCP path |
| Contract | Strict round trips, exact versions, canonical fingerprints, unknown/duplicate field rejection |
| Catalog | Order-independent winners, kind-specific merge, complete decisions, activation overlay, deterministic diagnostics |
| Sources | Native/package/embedded parity, containment, lazy body digest, stale handle, cancellation and budgets |
| Lifecycle | Approval consume/start/commit, pre-publication rollback, exact adoption, refresh pin/drain, reverse disposal, retry evidence |
| Consumers | CLI/prompt/command/load all observe one captured generation; no fallback discovery |
| Model Input | Summary and body evidence reconstruct exact visible input across file change, refresh, uninstall and cold replay |
| Product parity | Coding supported roots, context ordering, disabled Skills, extension/resource refresh, built-in Resources, and package filtering remain compatible |

Each implementation slice follows regression-first delivery and the repository
high-risk workflow. Focused tests expand to Harness resource, capability,
Plugin, Session, Coding bootstrap/CLI, persistence, and architecture suites in
proportion to the slice. Live/network tests remain excluded unless separately
authorized.

## Reference Design Assessment

The useful pattern from current plugin-first Harness references is a
provider-neutral summary catalog, opaque provider locators, lazy body loading,
scoped source layers, explicit invalidation, and reversible registration. This
plan adopts those separations.

Loushang must retain stronger existing guarantees rather than copy an ambient
service registry: exact owner admission, Product selection separate from owner
policy, verified package revisions, durable executable activation, one Session
Graph, exact-generation disposal, and committed Model Input content. In
particular, rediscovering a body later from a mutable source without a source
revision/content receipt is insufficient for Loushang continuity.

## Design Review Conclusions

The plan is acceptable to implement only with these corrections frozen:

1. Catalog and source mechanisms are owner components, not new top-level
   Capabilities or nested Plugins.
2. Skill remains a typed `resource_item` projection, and native Skill loading
   remains manifest-free.
3. Package Catalog and Resource Catalog are different authorities.
4. `ResourceBundle` becomes a compatibility projection and cannot remain a
   second effective store.
5. Component code changes are new-Session changes; only admitted data/content
   refresh uses the current single-owner Resource transaction.
6. Catalog/load receipts bind exact source generations and actual body bytes;
   lookup never falls forward to a newer winner.
7. The minimum component foundation lands before LSP, while stable advanced
   SDK and MCP work remain deferred.

The primary residual risk is bootstrap ownership: Resources are discovered
before the Session Graph is currently published. RCP2/RCP4 must prove the
single-transfer `PreparedResourceOwnerGeneration` path with failure injection
before any caller cutover. If that proof cannot preserve one owner and reverse
disposal, implementation stops at shadow mode rather than adding a second live
Catalog.

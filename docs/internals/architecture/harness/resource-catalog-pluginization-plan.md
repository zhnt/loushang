# Resource Catalog And Source Pluginization Plan

## Status And Authority

- Authority: proposed implementation plan under the accepted Harness Capability,
  Plugin lifecycle, exact-owner admission, Session Graph, Resource generation,
  and Model Input boundaries. It does not amend those boundaries implicitly.
- Design status: RCP0 contract frozen pending narrow freeze re-review.
- Implementation status: RCP0 baseline implemented and verified locally; RCP1
  has not started. The current `ResourceLoader`,
  `ResourceSnapshot`, `ResourceBundle`, and `SkillLoader` paths remain the
  implemented runtime until a phase below passes its cutover gate.
- Baseline: `main` at `e55db475`, tracked by issue `#495`.
- Review status: three independent architecture, lifecycle, and security reviews
  completed against `541408d0`. They conditionally accepted RCP0 only and
  identified the Extension/Catalog transaction, candidate normalization,
  content identity, custody, refresh classification, root authority, bootstrap
  synchrony, sequencing, and peer-deletion contracts corrected below. A narrow
  freeze re-review remains required before RCP1.
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
The source-backed [RCP0 Baseline](resource-catalog-rcp0-baseline.md) freezes the
implemented caller/sink inventory, parity anchors, and per-path disposition;
it does not introduce target runtime authority.

## Executive Decision

Pluginize mechanisms, not every piece of content.

Inside the one existing `harness.resources` Capability owner, introduce two
owner-defined component schemas:

1. `resource.catalog_engine`: exactly one selected executable component that
   compiles normalized source snapshots—including admitted Resource items only
   after their source normalization—into one immutable effective catalog
   generation; and
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
| `extensions.resources.ExtensionResourceRuntime` | Runs `resources_discover` and directly merges returned descriptors into `ResourceBundle` before the Extension candidate publishes both runtime and bundle. | Preserve hook behavior, but normalize its output into one Extension-generation-owned `ResourceSourceSnapshot` before the Resource owner performs the only final Catalog merge; delete direct post-Catalog bundle merge authority. |
| `harness.resources` Capability v1 | Publishes activation, prompt composition, Tool packs, and Command packs, but no typed Catalog/load facets. | Cut over atomically to an internal v2 contract; do not silently change v1 semantics. |
| Plugin `resource_item` admission | Admits inert verified locators under the exact Resource owner. | Feed only the matching admitted-package source, which emits the standard source snapshot; never feed the engine directly or create a second Plugin/source registry. |

The first implementation slice must freeze an executable caller inventory for
`discover_resources`, `reload_resources`, `get_resource_snapshot`,
`get_resource_bundle`, `get_skills`, `ResourceBundle.skills`, direct
`SkillDescriptor.content` reads, and package source mounts. No old caller may
remain able to discover or select an effective Skill after final cutover.
The inventory also covers `ExtensionResourceRuntime.discover*`, every direct
`ResourceBundle.merge()` of Extension Resources, `ResourceSnapshot`,
`_loader_precedence`, `_loader_resolution`, `_loader_pipeline`, and Package
Catalog summary construction through `ResourceLoader`.

## Authority And Role Model

| Role | Owns | Must not own |
| --- | --- | --- |
| Host control plane | Package verification, immutable revision handles, executable trust and approval, activation-use journal, import realm, process/filesystem authority | Resource precedence, Product selection, model-visible wording |
| Product composition | Desired Plugin/component selection, native root configuration, OEM composition, activation settings, Product policy revision | Candidate parsing, owner admission, source disposal |
| `harness.resources` owner | Component definitions, exact admission, component selection validation, precedence/merge policy, Catalog generation publication and retirement | Package installation, executable approval, arbitrary Product defaults |
| Catalog engine component | Pure deterministic composition, resolution, conflict explanation, immutable snapshot construction | Plugin selection, source startup/disposal, direct filesystem/network access, self-replacement |
| Resource source component | Candidate discovery and exact body load through least-authority handles | Global precedence, effective-winner publication, Model Input commit, other source generations |
| Extension owner | Runs the already-admitted generation's `resources_discover` hooks and freezes their output with exact Extension/runtime/generation provenance | Final Resource precedence, direct post-Catalog Bundle merge, starting Extensions through the Catalog |
| Resource item | Inert schema/media/locator declaration bound to one verified revision | Code execution, registry mutation, lifecycle authority |
| Resource/Skill Consumers | Query a captured generation and request an exact load | Independent cache, precedence, fallback discovery, source unloading |

The Resource owner, not the Catalog engine implementation, is the public
authority. This permits replacing the engine without transferring policy or
admission authority to Plugin code.

Least-authority contexts and opaque handles are architectural authority
scoping, not an in-process isolation boundary. An executable engine or source
still requires the existing host-equivalent trust and activation approval; a
narrow context does not lower that trust class.

## Component Foundation Required Before LSP

`capability_component` exists in the accepted architecture vocabulary but is
not yet an implemented ordinary authoring/runtime arm. PAP5.5 implements only
the minimum internal owner-component substrate required by Resources:

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

- immutable, normalized `ResourceSourceSnapshot` values, including snapshots
  produced from admitted package items and Extension-generation hooks;
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

There is no direct candidate ingress beside `ResourceSourceSnapshot`. An
admitted `resource_item` is only authorization input to the matching package or
embedded source; that source normalizes it, binds it to one exact source
generation, and emits the same snapshot record as every other source. The
engine never parses raw Plugin declarations or invents load handles.

Exactly one engine must be selected. No engine selected, more than one engine
selected, incompatible schema/contract, stale admission, or changed Product
policy fails before Catalog publication. The first-party standard engine is
default-selected by the Product composition set and can later be replaced for
new Sessions through the normal Plugin lifecycle.

### Source adapter

Each aggregate `resource.source` component exposes two narrow operations:

```text
discover_initial(ResourceDiscoveryRequest) -> ResourceSourceSnapshot
load(ResourceLoadHandle) -> ResourceBodyRead | Awaitable[ResourceBodyRead]
```

RCP0 through RCP5 require `discover_initial` to be synchronous, non-awaiting,
bounded, and cancellable through checked budget/deadline facts because the
current pre-Graph bootstrap has no await seam. The already asynchronous refresh
path may use an optional `discover_refresh_async` operation. A general async
initial-bootstrap migration is separately gated and is not hidden inside the
component Host. `load` may be asynchronous because the model-call/explicit-load
path already has an async boundary.

The source receives only handles authorized for its declared source class. It
cannot receive a Session, Graph, global registry, approval store, credential
bag, Tool registry, or another source component.

Discovery returns summaries and opaque locators, not eager body injection.
`load` accepts only a handle minted from that source's still-live exact
generation.
It must return one contained stable read with exact bytes, length, and observed
digest; it may not redirect to a new winner or a newer source generation. The
Resource owner validates that read against the candidate/snapshot and mints the
final `LoadedResource` and `ResourceLoadReceipt`; source code cannot mint its
own authoritative receipt.

Discovery may read bounded frontmatter or metadata needed to construct a
summary, but lazy loading delays only body injection, never body identity. For
every model-visible native file, discovery performs one stable contained
no-follow read and binds the resulting expected content digest and length to
the candidate; an implementation may retain those bytes in a content-addressed
cache. On lazy load, the source first obtains the exact generation lease and
either returns the retained bytes or performs another stable read whose digest,
length, identity, and summary-relevant metadata all match the candidate. A
change produces stale-generation evidence and refresh rather than pairing an
old summary/generation with a new body.

The initial source component set is:

| Source component | Input authority | Initial behavior |
| --- | --- | --- |
| Native filesystem | Product-approved workspace/user/temporary roots and contained read handles | Standard Resource layout, including `<name>/SKILL.md`; no Plugin manifest for content |
| Admitted package | `VerifiedRevisionHandle`, admitted `resource_item` locators, package instance revision | Load only contained verified files/directories; no mutable package path authority |
| Embedded/OEM | Product-selected immutable package-resource handles | Built-in prompts/Skills/themes with stable source identity and content digest |

Extension hook output is an additional normalized snapshot input, not another
pluggable source-component kind. The Extension owner runs the already-selected
generation, freezes one non-recursive hook pass into exact generation-bound
candidates, and supplies that snapshot to the Resource owner. The Catalog never
imports, starts, routes, or recursively discovers Extensions.

For each hook-produced body, the Extension owner must resolve the contribution
through its admitted contained handle or capture the returned immutable bytes,
bind expected digest/length during normalization, and retain a
generation-scoped body-read adapter or content-addressed value until loads
drain. A mutable descriptor/path that cannot prove exact body identity is
rejected. This adapter belongs to the Extension generation and implements only
the same `ResourceBodyRead` contract; it is not a new source component or
Catalog authority.

Remote/network source adapters, marketplace search, and MCP-backed discovery
are not initial source kinds. A later external service source must declare its
service dependency and pass the existing approval/policy/transport boundaries;
`resource.source` grants no implicit network authority.

### Data-only source descriptors

`resource_item(resource_kind="source")` remains an inert descriptor for roots,
collections, or source data understood by an admitted source component. It is
not executable source-provider code. This lets ordinary Plugins configure the
first-party filesystem/package engines without gaining a factory/disposer.

Such a descriptor may reference only a package-contained verified locator or
an opaque root/collection handle already minted by the Host and approved by the
Product. It may narrow a handle's relative subtree or filters, but may not name
an absolute host path, create a new root, widen the effective handle set,
select implementation code, or add authority. Source class, effective handle
set/root-policy fingerprint, and Product policy revision enter the source
generation/binding identity.

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
product_id
scope_id
generation
source_class
source_policy_fingerprint
producer (strict tagged union)
content_origin (strict tagged union)
```

The producer union has no ambiguous nullable peers:

```text
resource_component:
  component_contribution_id
  component_candidate_fingerprint
  component_admission_fingerprint
  binding_fingerprint
  plugin_instance_revision_ref
  package_content_digest

extension_owner:
  extension_id
  runtime_id
  extension_generation
  extension_owner_fingerprint
```

The independent content-origin union is:

```text
verified_plugin_resource:
  resource_contribution_id
  resource_admission_fingerprint
  plugin_instance_revision_ref
  package_content_digest

native_host:
  host_root_handle_id
  root_policy_fingerprint
  workspace_or_user_scope

embedded_oem:
  embedded_collection_id
  embedded_revision
  collection_content_digest

extension_output:
  extension_generation_ref
  route_set_fingerprint
  hook_snapshot_fingerprint
```

This keeps executable producer identity separate from content origin: the same
first-party source-component implementation can read native, verified-package,
or embedded content without erasing either provenance. Native and embedded
origins receive Host-minted immutable revision evidence without pretending to
be Plugin instances. Extension candidates retain their actual Extension owner
generation and never impersonate a Resource source component.

### `ResourceSourceSnapshot`

```text
source_generation_ref
discovery_request_fingerprint
candidate_summaries
diagnostics
complete
snapshot_fingerprint
```

The snapshot is the sole Catalog candidate ingress. Its candidates and
diagnostics are canonical identity-sorted, every candidate refers back to the
same source generation, and duplicate identity inside the snapshot fails. An
Extension hook snapshot obeys the same record even though its producer is the
Extension owner rather than a `resource.source` component.

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
expected_content_digest
expected_content_length
diagnostics
```

The opaque locator is meaningful only to the named source generation. It is not
a general filesystem path and cannot be used with another source. Expected
content identity is mandatory for every model-visible file/body. A Resource
kind with no body encodes an explicit no-body variant rather than omitting
identity ambiguously.

### `ResourceBodyRead`

```text
source_generation_ref
opaque_locator
body
observed_content_digest
observed_content_length
```

This is an untrusted/non-authoritative source result. The Resource owner checks
the live generation lease, locator/candidate binding, expected digest/length,
schema/media constraints, and body bytes before constructing a loaded Resource
or receipt.

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

### Stable diagnostic taxonomy

RCP0 freezes the following minimum owner-visible codes:

```text
resource_source_discovery_failed
resource_source_discovery_budget_exceeded
resource_source_snapshot_invalid
resource_catalog_proposal_invalid
resource_body_identity_mismatch
resource_catalog_generation_stale
resource_component_start_failed
resource_component_dispose_failed
resource_extension_snapshot_invalid
```

The code names the stable failure class. Structured metadata carries phase,
source/producer/generation identity, redacted cause, and a finite reason such as
duplicate identity, locator escape, non-canonical order, policy mismatch, or
foreign generation. Implementations must not mint one code per component,
source kind, or exception text. `restart_required` is a refresh classification,
not a failure code.

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
and embedded Resources normally have a declared digest before discovery;
native filesystem discovery binds the digest from its stable read. The Resource
owner compares the eventual body read with that expected identity before it
mints the receipt.

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
3. one stable no-follow discovery read binds `<name>/SKILL.md` or a supported
   flat Markdown layout to the same summary, expected digest, and length schema
   as packaged Skills;
4. frontmatter and body parsing use the shared Resource parser;
5. the Catalog owner applies the same identity, precedence, activation, and
   diagnostics rules; and
6. lazy load must match that expected identity, after which the Resource owner
   commits the exact body digest and content to Model Input.

The author needs no SDK, manifest, Python, installation, or approval dialog.
Moving the same Skill into a Plugin package adds verified package provenance and
data-only owner admission, not a different Skill runtime.

## Bootstrap, Publication, Refresh, And Retirement

### One Extension/Catalog publication transaction

The existing `resources_discover` behavior remains supported, but it cannot
remain a post-Catalog `ResourceBundle.merge()` path. One unpublished joint
transaction owns the order:

1. native/package/embedded sources produce base snapshots;
2. the Resource owner applies its policy only far enough to freeze the
   unpublished Extension descriptor set for this pass;
3. the Extension owner prepares that exact Extension generation and runs one
   non-recursive `resources_discover` pass against a read-only or defensive
   generation-bound projection; mutating the hook input has no authority;
4. the Extension owner normalizes the returned prompt/Skill/theme/Extension
   descriptors and diagnostics into one `extension_generation` source snapshot,
   retaining exact body reads under that Extension generation;
5. the Catalog engine computes the final proposal from all base and Extension
   snapshots, and the Resource owner validates it and builds one immutable
   Catalog generation plus compatibility projection;
6. Extension registrations and the Catalog generation remain unpublished until
   both are ready; and
7. one synchronous, no-await commit publishes Extension state, Catalog
   generation, and its Resource projection. Failure restores the previous three
   values before candidate cleanup.

For active refresh, the existing Extension candidate's
`publish(commit_resource)` boundary becomes that linearization point; its
`commit_resource` callback commits the Catalog generation and projection, not a
separately merged Bundle. For initial Session construction, the same joint
candidate remains root-private through Graph preparation and commits before the
Session becomes externally usable. A failure after Graph adoption disposes the
adopted Resource generation through the Provider/Binder path and rolls back the
unpublished Extension candidate. No Extension hook may publish Resources after
the final Catalog composition, and hook-produced Extension descriptors do not
recursively execute in the same generation.

### Initial Session

```text
verified desired Plugin revisions + native root policy
  -> declarations and exact Resource-owner admissions
  -> Product selects one engine and a source-component closure
  -> Host prepares executable component uses
  -> existing staged Resource candidate creates and exclusively owns one
     unpublished Resource owner generation
  -> base sources discover synchronously
  -> Extension owner emits one exact-generation source snapshot
  -> engine proposes and Resource owner validates Catalog generation 1
  -> one read-only Resource projection is derived from generation 1
  -> harness.resources Provider adopts it during the one Graph construction
  -> Session Graph publishes once
  -> joint Extension/Catalog projection commits
  -> component activation uses commit; focused Consumers capture generation 1
  -> Product Session becomes externally usable
```

The pre-publication object is a `PreparedResourceOwnerGeneration`, not a second
Capability Graph or another effective catalog. It has exactly one transferable
owner and is exclusively held as a child of the existing
`StagedResourceCompositionCandidate`; it is never passed beside that candidate
as an independently disposable object. Bootstrap may read only its narrow
root-owned projection. `StagedResourceCompositionCandidate` remains the sole
Resource Profile mechanism candidate.

The custody state machine is:

| State | Effective owner and permitted cleanup |
| --- | --- |
| `root_owned` | The Session construction root owns the staged Resource candidate and its prepared owner-generation child. Only candidate-root rollback may dispose it. |
| `graph_constructing` | The Resources Provider `create` has begun one no-await adoption. Failure before adoption commit restores root custody; no disposer may run concurrently. |
| `graph_owned` | Adoption committed. The generation is reachable only through the Resources Provider value; any later Graph-node/joint-publication failure is cleaned by the Binder/Provider disposer and never handed back to a second root owner. |
| `retiring` | New captures/loads are closed. The same Provider owner retains in-flight drain and retryable cleanup debt; no root may reacquire custody. |
| `disposed` | Exact reverse disposal and debt closure completed. No capture/load is valid. |

Component activation uses commit only after Graph construction and the joint
Extension/Catalog publication both succeed. A failure before adoption is root
rollback; a failure after adoption is Provider/Binder rollback. Neither path
may claim the other's custody or invoke the same disposer twice.

The authoritative generation projection uses tuples/read-only mappings and is
bound to the Catalog fingerprint. A legacy `ResourceBundle` with mutable lists
may exist only as a short-lived compatibility copy; mutating it cannot change
the generation, be accepted as refresh input, or publish an effective Resource
view. It is deleted after the caller inventory reaches zero.

The Resource Provider binding fingerprint includes selected component
definitions, implementation revisions, exact binding inputs, and owner/Product
policy revisions. Resource candidate summaries and body bytes belong to Catalog
generation fingerprints and never pollute the Provider construction
fingerprint.

### Refresh

Refresh first computes a pure, non-mutating `ResourceRefreshClassification`
from current and desired component/binding/trust/selection/root-policy
fingerprints. This happens before changing settings-bound mounts, source
generations, revision handles, Extension state, or the current projection:

```text
content_refresh:
  exact engine/source component and binding fingerprints are unchanged;
  only data candidates, native body identity, or activation policy changed

restart_required:
  engine/source code or package digest, trust/approval, component selection,
  binding inputs, effective root-handle set, or multi-owner executable topology
  changed
```

`restart_required` returns without mutating the active Session. Package mounts
and verified revision handles are immutable children of their owning source/
Catalog generation; generation `N` retains them until all Consumers and load
leases drain.

This Resource classification does not replace the existing Extension
declaration/grant preflight. An Extension generation may still use its accepted
hot-replacement path when its owner proves unchanged graph inputs and grants;
its new hook snapshot then participates in the joint transaction. A changed
Extension Provider/dependency/grant/trust topology returns `restart_required`
before candidate publication, while the old Extension/Catalog/handle set stays
pinned.

An accepted content-only refresh reuses the still-live exact component
generation:

1. run declaration preflight and stage base source snapshots;
2. prepare the Extension candidate and normalize its hook output into one
   Extension-generation source snapshot;
3. compose and validate Catalog generation `N+1` and its read-only projection;
4. keep the current model request pinned to generation `N`;
5. atomically publish Extension state, `N+1`, and its projection at the existing
   synchronous candidate publication/next Model Input boundary; and
6. retire `N` and close its handles only after its Consumers and loads drain.

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
- discovery-bound expected content digest and length;
- activation-policy fingerprint;
- exact body content digest; and
- the exact model-visible text/bytes, or the existing durable content reference
  that reconstructs those exact bytes.

Refresh never rewrites an already committed request. Cold transcript replay
does not need to reopen the original path or restart the original source Plugin
to explain a historical request. Current-session reconstruction may rebuild a
new Catalog from current desired state, but historical Model Input remains
bound to its committed content and receipt.

The Catalog generation therefore determines body identity before a request
loads it. A receipt proves both that the loaded bytes match the selected
generation and what entered Model Input; it is not merely an after-the-fact
digest of whichever mutable bytes happened to exist at load time.

## Security And Fault Containment

The first implementation must freeze adversarial behavior for:

- path traversal, absolute locator, symlink escape, mutable package-root swap,
  data-only descriptor root widening, and verified-handle digest mismatch;
- source discovery timeout/cancellation, file-count/depth/body-size budgets,
  invalid encoding/frontmatter/schema, and diagnostic redaction;
- duplicate identity, unstable ordering, provider-supplied priority, and
  source completion races, or one `resource_item` entering through direct and
  source-snapshot paths;
- stale Catalog handle, load-after-dispose, unload while a load is active, and
  disposer failure;
- native body replacement with unchanged frontmatter/summary between discovery
  and load;
- executable component approval revoked before start, crash after consume,
  failure after start but before owner publication, and stale owner/Product
  policy;
- Catalog engine returning foreign locators, changing candidate identity,
  omitting input candidates without a merge decision, violating the
  owner-supplied merge-policy result, or emitting a non-canonical snapshot;
- a cataloged Extension, Tool, Command, or Skill script attempting to execute
  through Resource loading instead of its exact owner lifecycle;
- an Extension hook directly merging effective Resources after final Catalog
  composition; and
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
- freeze caller/sink inventories and current precedence/merge parity fixtures,
  including Extension hook merges, Package Catalog summary construction, and
  every old discovery/resolution module;
- freeze the records, failure codes, lifecycle state transitions, and forbidden
  peer routes in this plan;
- freeze the one Extension/Catalog transaction, exact custody state machine,
  sync initial discovery contract, pure refresh classification, tagged
  provenance, mandatory model-visible content identity, and descriptor handle
  narrowing rules; and
- add architecture gates distinguishing Package Catalog from Resource Catalog,
  forbidding direct raw `resource_item` engine ingress and the conflicting
  all-components-after-LSP wording.

Exit: current behavior is green, every duplicate caller has a named migration
or deletion phase, no implementation symbol is falsely public, and every
independent-review P1 above is represented by an executable contract/parity or
forbidden-route fixture. RCP1 may not begin before a narrow freeze re-review.

### RCP1: Implement one inert Catalog core

- add immutable identity, candidate, snapshot, decision, activation, handle,
  loaded-body, and receipt records;
- implement the standard deterministic Catalog engine as pure logic;
- adapt the current `ResourceSnapshot` into the new records through source
  snapshots in shadow mode, never as direct engine candidates; and
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
unchanged. Initial discovery is synchronous/budgeted, owner components use the
frozen custody state machine, and narrow contexts are not described as process
isolation.

### RCP3: Converge package and embedded sources

- adapt admitted package `resource_item` locators through verified revision
  handles;
- adapt embedded/OEM Resources through immutable handles;
- replace Package Catalog's effective `ResourceLoader.discover_resources()`
  summary dependency with a pure package inventory/summarization port;
- remove package-path reads that bypass the source generation; and
- prove native/package/embedded conflict and exact-unload semantics.

Exit: all supported source kinds produce one snapshot/candidate schema; the
engine computes proposed effective entries, and the Resource owner validates,
canonicalizes, and exclusively publishes them. Package Catalog performs no
effective Resource selection.

### RCP4: Mount Resource Catalog generation

- introduce the internal `harness.resources` v2 Catalog/load facets and exact
  Consumer requirements;
- stage the initial owner generation as the exclusive child of the existing
  Resource candidate, transfer it once to the Resources Provider, and capture
  focused Consumers after the one Session Graph publication;
- publish Extension state, Catalog generation, and Resource projection through
  the frozen joint transaction;
- route refresh through pure classification and next Catalog generation
  publication without replacing/closing old handles early; and
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
  refresh;
- delete production effective-selection imports of `ResourceSnapshot`,
  `_loader_precedence`, `_loader_resolution`, and `_loader_pipeline`; and
- forbid direct Extension `ResourceBundle.merge()` publication after Catalog
  cutover. Parity fixtures may retain old helpers only in the cutover commit.

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

RCP6 follows the LSP production proof and does not block starting LSP after
RCP5. Stable public publication still follows PAP7's broader evidence gate.

Exit: ordinary Resource authors do not handle admission, binding, registries,
or disposal; advanced API stabilization remains gated by LSP and a second owner
component adopter.

## Verification Matrix

| Gate | Required proof |
| --- | --- |
| Architecture | One `harness.resources` Graph seam; one Catalog authority; no `harness.skills`; Package Catalog remains inventory-only; Resource-only internal components before LSP but generic public component authoring after LSP; no new MCP path |
| Contract | Strict round trips, exact versions, canonical fingerprints, unknown/duplicate field rejection |
| Catalog | Every candidate arrives through one exact-generation source snapshot; order-independent winners, kind-specific merge, complete owner-validated decisions, activation overlay, deterministic diagnostics |
| Sources | Native/package/embedded/Extension-snapshot parity, descriptor handle narrowing, containment, discovery-bound body identity, stale handle, synchronous initial budgets and async refresh cancellation |
| Lifecycle | Explicit custody states, approval consume/start/commit, joint Extension/Catalog publication, pre-publication rollback, exact adoption, pure refresh classification, generation-owned handle pin/drain, reverse disposal, retry evidence |
| Consumers | CLI/prompt/command/load all observe one captured generation; no fallback discovery, mutable effective Bundle, or direct Extension merge |
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
5. Every candidate, including admitted `resource_item` and Extension hook
   output, enters through one exact-generation `ResourceSourceSnapshot`.
6. Extension state, Catalog generation, and projection publish in one existing
   no-await candidate transaction; no direct effective merge follows it.
7. Component code changes are new-Session changes; only a pure preclassified
   admitted data/content refresh uses the current single-owner transaction.
8. Native model-visible body identity is bound at discovery; lazy load matches
   it and receipts bind exact source generations and actual body bytes.
9. Data-only descriptors only narrow Host/Product-approved handles and cannot
   launder filesystem authority through a first-party adapter.
10. Initial discovery stays synchronous until a separately gated async
    bootstrap exists, and generation custody follows one explicit transfer
    state machine with generation-owned revision handles.
11. The minimum internal Resource component foundation lands before LSP, while
    generic public component authoring, the stable advanced SDK, and MCP work
    remain deferred.

The primary residual risks are the current synchronous pre-Graph bootstrap and
the existing Extension/resource joint publication boundary. RCP2/RCP4 must
prove the frozen single-transfer custody and Extension/Catalog failure matrix
before any caller cutover. If either proof cannot preserve one owner, one final
Catalog, old-generation handle pinning, and reverse disposal, implementation
stops at shadow mode rather than adding a second live Catalog.

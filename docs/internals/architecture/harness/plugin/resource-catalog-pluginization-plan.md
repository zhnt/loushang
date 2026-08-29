# Resource Catalog And Source Pluginization Plan

## Status And Authority

- Authority: proposed implementation plan under the accepted Harness Capability,
  Plugin lifecycle, exact-owner admission, Session Graph, Resource generation,
  and Model Input boundaries. It does not amend those boundaries implicitly.
- Design status: RCP0 contract frozen; final narrow freeze re-review passed.
- Implementation status: RCP0 through RCP3 are complete on the Harness lane;
  RCP4 has ten unpublished foundation slices and RCP5 has started with one
  conservative, unpublished typed-Consumer slice.
  RCP2's first unpublished foundation slice implements the generic
  `CapabilityComponentDefinition`, exact candidate/admission/selection/binding
  records, atomic owner generations, cancellation-safe reverse rollback,
  generation-pinned Consumer leases, and exact-binding disposal. It is not
  exported by `harness.capabilities`, imported by a production caller, or wired
  to the current resource loader. The second unpublished slice adds the distinct
  external `CapabilityOwnerComponentHost`, an independently fingerprinted
  owner-component activation Subject, verified Plugin revision/import-realm
  construction, current-authority revalidation, and durable
  consume/start/commit/recovery transitions without changing the legacy
  complete-Bundle Subject bytes. Its final unpublished slice adds the exclusive
  standard Catalog engine and aggregate native source as exact first-party
  contributions, Host-minted `context`/`standard`/`combined` root handles,
  synchronous bounded no-follow discovery, generation-retained exact body
  bytes, owner-validated Catalog proposals, and a disposable shadow-generation
  runner beside the current loader. Catalog records, sources, and orchestration
  remain private, and `harness.resources` does not export them. The RCP4
  preparation bridge is their sole path toward a Provider. One private optional
  Agent Session bootstrap adapter now calls that bridge. A private Product
  preparation adapter can mint exact native/package/embedded inputs for it. One
  private Session/Product composition root now turns a finalized Plugin
  selection plus explicit exact owner bindings into the existing Product
  compilation, and Coding's private initial shadow consumes that assembly
  request. No Product bootstrap invokes the path by default and no refresh route
  calls it.
  RCP5.1 adds a body-free typed Skill summary over the exact captured Catalog
  projection and a Skill-narrowed lazy load handle returning the validated
  Resource receipt. It has no legacy loader, `ResourceBundle`, Product, or
  public SDK dependency. Default Product callers and all legacy peer paths are
  unchanged pending a fresh cutover review.
  RCP3 adds admitted-package and embedded/OEM source components beside the
  native source. Capability-aware orchestration converts exact Resource-owner
  admission into a capability-neutral verified input with an independently
  disposable revision lease; the source itself reads only through that lease.
  Embedded packages are copied once into immutable Host-minted collection
  handles and are not reopened through import paths during discovery or load.
  All three sources emit the same candidate/snapshot records and compose through
  the same engine. Package Catalog summary construction now delegates to a pure
  inventory port and performs no effective Resource discovery or selection.
  The first RCP4 slice adds the internal v2 Definition and focused
  `resource.catalog`/`resource.load` requirements, makes one prepared owner
  generation the exclusive asynchronous child of the existing staged Resource
  candidate, and lets the Resources Provider adopt that complete candidate once.
  Real isolated Graph tests prove root rollback, cancellation, successful load,
  Graph reuse rejection of a second content generation, retryable graph-owned
  retirement, and exact disposal. The second slice adds the previously missing
  Extension-owner snapshot input: an exact routed hook pass receives defensive
  Bundle copies, preserves owner-supplied source class/scope/root order, freezes
  candidate provenance and immutable body bytes, and exposes only a borrowed
  generation-bound body reader to the Resource owner. The same unpublished
  Catalog and real Graph load path now compose and load those candidates without
  stealing Extension disposal authority. The joint Extension/Catalog commit
  foundation now adds an exact offered/claimed/released borrow lease, owner-side
  drain after retirement begins, one root-private Extension/Resource candidate,
  a synchronous visible-state publication port and cancellation-safe root or
  Graph rollback with retryable debt. The fourth slice gives every native,
  verified-package, embedded/OEM, and Extension source an immutable descriptor
  sidecar that carries no selection authority. The Resource owner derives the
  final projection only from exact Catalog effective entries, binds it to the
  Catalog snapshot and selected descriptor fingerprints, retains Catalog order
  for additive Extensions and user-to-inner ordering for context, and creates a
  fresh mutable `ResourceBundle` only as a compatibility copy. The joint commit
  now carries this final Catalog projection rather than the Extension hook-pass
  Bundle. The fifth slice adds the optional initial-Session bridge: it derives
  Extension-set provenance from the prepared generation, prepares the v2
  Resources binding only after the owner generation is frozen, adopts it into
  the Session Graph, installs the compatibility Consumer, and synchronously
  publishes Extension state, Catalog snapshot, projection, and a fresh Bundle.
  Graph failure, publication failure, cancellation, and unprepared shutdown all
  reverse exact custody; absence of the adapter leaves the v1 path unchanged.
  The sixth slice adds the reusable Product input adapter: immutable selection
  specs become fresh Host-minted native/embedded handles per Session, and a
  synchronous custody callback closes partial minting or failed construction
  before transferring ownership. The seventh slice adds a private Coding-only
  initial shadow: the existing discovery call emits one immutable, single-take
  source-input receipt; Coding maps its supported project/context, user, and
  captured built-in inputs to the Product adapter and fails closed for package,
  temporary, kind-switch, or disabled-Skill cases. Only the private construction
  helper can opt in and its default is false. Public/default enablement, active
  refresh, typed production Catalog/Skill consumers, and legacy-loader cutover
  remain pending.
  The eighth slice extends that seam only for exact owner-admitted package
  Resources. Product preparation acquires an independent verified-revision lease
  per Session, while Coding joins admissions one-to-one with package candidates
  observed by the same legacy discovery. Conventional directories, incomplete
  admission sets, package diagnostics/Extensions, and subroot mounts reject.
  The ninth slice removes the parallel raw-admission ingress: package specs must
  exact-match `ProductCompositionCompilation.resource_admissions`, share its
  Product policy revision, and retain that exact compilation through Session
  construction. Coding accepts only that existing compiler output. It does not
  rerun Plugin selection, declaration parsing, trust, or owner admission.
  The current `ResourceLoader`, `ResourceSnapshot`, `ResourceBundle`, and
  `SkillLoader` paths remain the implemented runtime until a phase below passes
  its cutover gate.
- Baseline: `main` at `e55db475`, tracked by issue `#495`.
- Review status: three independent architecture, lifecycle, and security reviews
  completed against `541408d0`. They conditionally accepted RCP0 only and
  identified the Extension/Catalog transaction, candidate normalization,
  content identity, custody, refresh classification, root authority, bootstrap
  synchrony, sequencing, and peer-deletion contracts corrected below. The first
  narrow freeze re-review against `811f0fdb` found no P0 but rejected RCP0 exit
  because the Skill parity oracle, dynamic Extension/Skill ingress, legacy
  discovery/import, refresh-handle, Extension collision, and body-load
  diagnostic freezes were incomplete. Corrections at `ed364062` and
  `b387d542` closed every finding. Final independent architecture, lifecycle,
  and security rechecks each passed with no P0/P1. RCP1 then implemented the
  frozen records, deterministic kind policies, strict proposal validation,
  explicit-provenance legacy adaptation, compatibility projection, and the one
  evidence-checked Extension collision exception. Its focused and full
  Resource-domain suites pass. A subsequent primary-agent narrow authority
  review required owner-supplied source class/scope/root-order facts, exact
  `extension_output`/Extension-owner-generation matching, generation-scoped
  diagnostics, immutable body bytes, and context projection-order parity; those
  corrections are implemented and green. RCP1 has not yet received an
  independent code re-review. RCP3 adds focused architecture, precedence,
  conflict, exact-load/unload, budget, cancellation, and failed-Binding custody
  gates; this status does not claim a new independent RCP3 code re-review.
- Scope: pluginize the Resource catalog mechanism and Resource source/loading
  mechanisms, converge Skill onto a typed Resource projection, and retain plain
  native `SKILL.md` loading.
- Explicit exclusions: one Plugin or Graph node per Skill, a second Skill
  registry, a new top-level `harness.skills` Capability, a global mutable
  service registry, stable public source-provider SDK publication, LSP/Base/Arch
  migration, remote marketplace work, and new MCP functionality.

The canonical target
[Plugin Architecture V2](architecture.md),
[Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md),
[Capability Dependency And Mount Lifecycle](../capability-dependency-and-mount-lifecycle.md),
[Extension And Resource Generation Lifecycle](../extension-generation-lifecycle-boundary.md),
and [Session Resource Refresh Runtime Boundary](../session-resource-refresh-boundary.md)
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
select implementation code, or add authority. The allowed source-class set,
effective handle set/root-policy fingerprint, and Product policy revision enter
the source generation/binding identity. The Resource owner stamps or validates
each candidate's actual class/scope/order facts against that generation; a
descriptor cannot self-assign priority.

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
generation
source_policy_fingerprint
producer (strict tagged union)
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
  runtime_id
  extension_generation
  extension_set_fingerprint
  extension_owner_fingerprint
```

`ResourceSourceGenerationRef` therefore names the common executable/owner
generation, not one candidate's precedence or content provenance.
The independent content-origin union is candidate-scoped:

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
  extension_id
  route_id
  route_set_fingerprint
  hook_snapshot_fingerprint
```

One Extension-owner snapshot may aggregate several routed Extensions: the
generation producer names the exact runtime generation/set, while each
candidate names its own source class/scope/order and contributing Extension/
route content origin. This keeps executable
producer identity separate from content origin: the same
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

The snapshot is the sole Catalog candidate ingress. Its candidates are
canonical `(ResourceIdentity, candidate_fingerprint)`-sorted, diagnostics are
canonical identity/code-sorted, every candidate refers back to the
same source generation, and an exact duplicate candidate fingerprint/locator
inside the snapshot fails. Repeated logical `ResourceIdentity` values remain
distinct candidate evidence for the kind-specific collision policy; they are
not silently deduplicated before a merge decision. An Extension hook snapshot
obeys the same record even though its producer is the Extension owner rather
than a `resource.source` component.

### `ResourceCandidateSummary`

```text
identity
canonical_name
description
media_type
invocation_policy
source_generation_ref
source_class
scope_id
source_root_order
content_origin (strict tagged union)
opaque_locator
discovery_fingerprint
candidate_fingerprint
expected_content_digest
expected_content_length
diagnostics
```

The Resource owner derives or verifies `source_class`, `scope_id`,
`source_root_order`, and `content_origin` from admitted handles, Product root
order, package admission, or the exact Extension route. They are evidence for
the owner-supplied merge policy, not contributor-assigned priority. The
candidate fingerprint covers those validated fields together with identity,
generation, locator, invocation/media facts, and expected content identity.

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

Candidate collections are canonical `(ResourceIdentity,
candidate_fingerprint)`-sorted; effective-entry, source, and diagnostic
collections use their declared canonical identities. The fingerprint excludes
wall-clock time and object addresses.
`complete=false` is explicit evidence and Product policy decides whether an
optional-source failure may publish a degraded snapshot.

### Stable diagnostic taxonomy

RCP0 freezes the following minimum owner-visible codes:

```text
resource_source_discovery_failed
resource_source_discovery_budget_exceeded
resource_source_snapshot_invalid
resource_catalog_proposal_invalid
resource_body_read_failed
resource_body_validation_failed
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

The phase-to-code mapping is fixed:

| Phase/outcome | Code |
| --- | --- |
| Source invocation or source I/O before a snapshot exists | `resource_source_discovery_failed` |
| Discovery count/depth/time/body-identity budget | `resource_source_discovery_budget_exceeded` |
| Source snapshot structure, provenance, locator, duplicate-candidate, or canonical-order rejection | `resource_source_snapshot_invalid` |
| Engine output omission, foreign candidate/locator, owner-policy mismatch, or non-canonical proposal | `resource_catalog_proposal_invalid` |
| Exact body adapter I/O or decode failure before owner validation | `resource_body_read_failed` |
| Owner schema/media/encoding/body-size validation failure | `resource_body_validation_failed` |
| Observed digest/length differs from the selected candidate | `resource_body_identity_mismatch` |
| Catalog/source generation lease is stale, retiring, or disposed | `resource_catalog_generation_stale` |
| Owner-component start or dispose failure | `resource_component_start_failed` / `resource_component_dispose_failed` |
| Extension hook output/body adapter cannot be frozen under its exact generation | `resource_extension_snapshot_invalid` |

Cancellation remains control flow and is propagated. If Product diagnostics
record the cancelled operation, they use the phase's stable code plus a finite
`reason="cancelled"`; exception text appears only in redacted metadata.

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

Within a class, Product-declared root order participates only where the
Resource-kind policy permits a winner. New canonical tie-breakers use stable
source identity, contribution identity, canonical Resource identity, and
contained relative locator; absolute host paths and discovery completion order
must not decide a winner. Any behavior difference from the current
`_loader_precedence` and `_loader_resolution` rules needs an explicit parity
exception fixture and Product decision.

Merge is Resource-kind-specific:

- named Skills and prompt templates select the sole candidate at the highest
  source precedence; multiple enabled candidates at that same precedence reject
  the logical identity with `same_precedence_conflict` and no winner;
- themes and other permissive exclusive assets select one winner by source
  precedence, Product root order, and the stable tie-break;
- Extension descriptors retain the current ordered-additive rule: all enabled
  candidates remain active and the decision records the first ordered candidate
  only as explanatory evidence, not an exclusive winner;
- context files and explicitly additive prompt collections retain an ordered
  admitted set under their existing nearest-scope semantics; and
- an exact duplicate candidate fingerprint/locator within one source generation
  is invalid rather than silently last-write-wins.

Extension hook Resource candidates inherit the admitted owning Extension
descriptor's source class, scope/root-order facts, and exact Extension
generation provenance. They receive no special priority. At RCP4 cutover they
enter the same kind-specific policy as base candidates. This is one explicit
Product-approved parity exception: the legacy post-discovery
`ResourceBundle.merge()` currently retains duplicate named Skills/prompts in
route order, whereas the joint Catalog transaction will resolve or reject them
exactly like any other candidates. RCP0 freezes both the old behavior and this
cutover decision; RCP1 shadow comparison reports the known exception instead of
pretending byte-for-byte Bundle parity, and no live behavior changes before
RCP4.

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

Status: complete. The implementation is private and shadow-only; its
architecture gate forbids imports from production modules and top-level
publication. The legacy adapter requires caller-supplied source-generation and
content-origin evidence plus owner-supplied source class, scope, and root order,
which must match the frozen legacy evidence. Extension output must belong to
the exact Extension-owner generation. The compatibility `ResourceBundle` it
creates is a disposable test projection rather than a live candidate or
refresh input.

- add immutable identity, candidate, snapshot, decision, activation, handle,
  loaded-body, and receipt records;
- implement the standard deterministic Catalog engine as pure logic;
- adapt the current `ResourceSnapshot` into the new records through source
  snapshots in shadow mode, never as direct engine candidates; and
- prove order independence and current precedence parity.

Exit: shadow Catalog fingerprints and compatibility bundles match current
supported fixtures except the frozen Extension post-discovery collision parity
exception, which is reported explicitly and remains non-live until RCP4; no live
caller has changed authority.

### RCP2: Implement owner-component lifecycle

Status: complete. The first foundation slice completes the inert Definition
through Binding chain and an unpublished owner-generation runtime. It proves
construction, cancellation, reverse rollback, atomic publication, exact old-
generation pinning, drain, retryable retirement, and exact-binding disposal.
The second slice adds `CapabilityOwnerComponentHost` and a tagged
`OwnerComponentActivationApprovalSubject`. It reuses the durable activation-use
state machine and verified ImportRealm but neither overloads
`CapabilityComponentHost` nor serializes a component as the complete-Bundle
Provider Subject. The final slice packages the standard engine and native
filesystem source as first-party contributions and runs their exact admitted
bindings in an unpublished Resource owner generation. The source receives only
Host-minted layout-scoped root handles; root kind, class, scope, order, and root
policy enter binding/source-generation identity. Discovery is synchronous,
budget/deadline/cancellation checked, no-follow, and retains the exact bytes
whose digest and length entered each model-visible candidate. Lazy load serves
only that still-live generation. The pure owner validator independently
recomputes the proposal from the same immutable source/policy inputs.
Executable assembly and the runner live in the private sibling
`harness.resource_catalog` orchestration package, which depends one-way on
`capabilities` and `resources`; placing them inside `resources` would create a
forbidden package cycle because Capability admission already consumes Plugin
revision records. Legacy and native discovery share source-neutral conventions,
prompt/Skill parsing, and Skill-ignore matching rather than cloning those
declaration rules.

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
isolation. The exit gate is satisfied by side-by-side legacy/native fixtures,
project-over-user precedence, retained-byte lazy loading after path mutation,
foreign-generation rejection, root/symlink narrowing, budget/cancellation
control flow, owner proposal rejection, and private/unmounted architecture
gates. The temporary shadow discovery route is not a new production peer: RCP4
performs the single publication cutover and RCP5 deletes the legacy loader
route.

### RCP3: Converge package and embedded sources

Status: complete and unpublished. A sibling Resource orchestration adapter
validates exact `resource_item` admission and acquires a source-owned
`VerifiedRevisionHandle` lease, then passes only capability-neutral contribution
facts and the verified lease into the package source. The package source has no
Capability dependency or raw package path, binds candidate digest/length to
`file_identity()`, and serves lazy bodies only through `open_file()` on that
same lease. The embedded source receives immutable, eagerly copied Host-minted
collection handles; import-package traversal occurs only during capture, not in
the source generation. Native, package, and embedded sources share descriptor
projection and the standard snapshot/engine path. Budget, deadline,
cancellation, conflict, failed-Binding rollback, load, and disposal tests prove
that source custody closes independently from the caller's original revision.
Package Catalog now delegates summary work to a read-only inventory port and no
longer constructs a `ResourceLoader` or invokes effective discovery. No live
Provider, Session Graph, refresh route, or compatibility projection was changed;
those remain RCP4 work.

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

Status: ten unpublished foundation slices complete. The v1 Provider path is
unchanged when no prepared generation exists. A candidate with one prepared
generation selects only contract/provider v2, contributes the two Catalog/load
facets, transfers parent and child through the same
`root_owned -> graph_constructing -> graph_owned` boundary, and retires the
child before its parent mechanisms. Provider construction fingerprints include
the selected owner-component binding identity but exclude Catalog snapshot and
body identity. The next slice freezes Extension route outputs through a
defensive, non-publishing pass, binds exact Extension owner/generation/route
provenance, retains immutable body bytes, and lets the unpublished Catalog
borrow that body reader without gaining its disposal authority. Those first two
slices are exercised through a real isolated Capability Graph. The third gives that
borrow an exact offered/claimed/released lease, stops new borrows when the
Extension owner retires while draining accepted reads, and joins the prepared
Extension and staged Resource candidates under one root-private coordinator.
It proves one no-await visible-state commit, failed-commit restoration, exact
lease identity, root/Graph rollback, retryable retirement debt, and
cancellation-atomic cleanup. The fourth makes source descriptor sidecars
non-authoritative inputs, validates their body and candidate identity, derives
one immutable projection solely from Catalog effective entries, and binds that
projection to the exact Catalog snapshot. It preserves ordered-additive
Extension order and context ordering, returns only fresh defensive
`ResourceBundle` compatibility copies, and changes the unpublished joint commit
to carry the final Catalog projection instead of the hook-pass Bundle. The
fifth adds one private optional `AgentProductSession` bootstrap adapter. Before
Session publication it freezes the Extension candidate, prepares the Resource
owner, replaces the construction-time v1 Resources graph input with the exact
v2 binding, binds and captures the Graph, then publishes Extension/Catalog/view
state through the existing no-await joint commit. It also restores the prior
Session view on failed commit and finishes root/Graph rollback under
cancellation. No Product invokes the input adapter by default, so Coding and
other existing Products still use v1; refresh, production typed consumers, and
cutover remain pending.

#### RCP4.6 implemented: Product initial-input adapter

The sixth slice adds one private, reusable Product preparation primitive; it
does not add a Coding setting or change any default construction path. A
Product opts in only through the adapter's synchronous `construct_session`
custody callback. The adapter creates one single-use bootstrap for that call and
transfers it to `AgentProductSession` only when Session construction returns
successfully. It accepts only exact pre-admission facts and performs no
legacy-loader inspection:

- native root specifications contain an opaque handle id, Product-approved
  path, source class, root kind, and stable root order;
- embedded collection specifications contain a Product-owned collection id,
  immutable revision, and finite copied bytes; and
- one non-empty Product policy revision binds the selection. The adapter mints
  fresh native/embedded handles per Session, derives Session/Resource runtime
  ids from the admitted Product and conversation ids, and uses a narrow
  injected-clock admission window only during initial preparation.

Raw paths and byte mappings stop at this preparation boundary. The Resource
owner receives only the existing opaque handles. If minting or the custody
callback fails, every already-minted closeable input is released in reverse
order; after the callback succeeds, the existing Session bootstrap is their
sole owner. The callback is synchronous and must return a Session rather than an
awaitable. Adapter reuse creates independent per-Session handles and never
shares a generation.

The slice deliberately supports native and embedded sources only. It exposes no
package field, does not infer package/native/context/temporary inputs from a
`ResourceBundle`, and therefore is not a source-completeness claim for Coding.
The current legacy Bundle remains only the defensive Extension hook input.
RCP4.7 below meets the next gate with a same-discovery source receipt and
fail-closed unsupported-input admission before invoking this primitive.

Acceptance is proven by one production-shaped sample that carries a native
`SKILL.md` and an immutable embedded Resource through adapter construction,
declaration, owner preparation, Graph adoption, publication, and disposal.
Tests also prove duplicate selection rejection, partial-mint cleanup,
independent adapter reuse, Session-construction failure cleanup, and unchanged
v1 behavior when no adapter is supplied. No refresh, LSP, MCP, package
admission, public SDK export, typed Skill cutover, or legacy deletion belongs
to this slice.

Freeze review rejects the slice if it creates a second discovery/selection
authority, introspects private loader state, lets raw paths cross the Resource
owner boundary, silently treats a partial source set as Coding-complete, shares
handles between Sessions, weakens the existing joint rollback, or adds a default
Product mount.

#### RCP4.7 implemented: Coding source-input receipt and private initial shadow

The seventh slice adds the first Product consumer without adding a second
discovery entry point. `ResourceLoader` still constructs and executes the one
legacy discovery request. That same pipeline result now also contains an
immutable receipt of its normalized source facts: effective project Resource
root, outer-to-inner project context roots, user roots and explicit-root marks,
built-in import packages, enabled package roots, temporary paths, kind switches,
context filenames, and the context switch. Mutating loader source configuration
invalidates the receipt; each successful discovery replaces it; one private
transfer operation consumes it exactly once. Coding never reads loader fields or
reconstructs the receipt from a resolved `ResourceBundle`.

The private Coding adapter supports the complete initial source set for this
thin slice:

- effective user roots become `user_global` combined (or standard-only) native
  handles with their original root order;
- the shared context search order becomes project context handles, while the
  already-resolved effective project Resource root becomes one standard handle;
  and
- every built-in import package is captured once into finite immutable bytes,
  assigned a content-derived revision, and then passed through the existing
  embedded Product specification.

RCP4.7 admission is deliberately fail-closed. At this slice, any enabled package
root, additional temporary path, prompt/Skill/Extension/theme discovery switch,
disabled-Skill selector, unavailable explicit user root, or inadmissible project
root rejects the shadow before the reusable Product adapter mints a handle.
`no_context_files` is represented exactly by omitting project context handles
and using standard-only user handles. Unsupported cases continue to run normally
on the default v1 path because the shadow is reachable only through the private
`_create_agent_session(..., enable_initial_resource_catalog_shadow=True)` test
and migration seam; the public Coding SDK, CLI, settings, and runtime factory do
not expose it.

The shadow intentionally performs legacy discovery first to build the defensive
Extension hook input, then performs Catalog discovery from the receipt. That
temporary duplicate observation is measured migration debt, not two effective
publishers: only the v2 Catalog generation publishes after Graph adoption in the
opt-in Session. At this slice, the deletion gate still included replacing the
defensive hook input, adding package/temporary/policy parity, and removing the
legacy initial discovery before any default cutover. RCP4.8 below closes only the
exact admitted-package portion of that gate. Focused tests prove receipt fidelity
and single-take custody, finite unsupported reasons, unchanged public SDK
signatures, and a real Coding project context plus native Skill through v2 Graph
publication and exact Session disposal.

No refresh route, package admission, typed Skill Consumer, LSP/MCP work, public
SDK switch, CLI setting, or default behavior changes in this slice.

#### RCP4.8 implemented: admitted-package input and exact candidate join

The eighth slice extends the reusable Product adapter with one typed
`ProductAdmittedPackageResourceSpec`. The spec contains only an existing exact
owner `resource_item` admission, the Product-held live
`VerifiedRevisionHandle`, and the legacy source-root order. It is not a raw path
or a new package declaration format. On each Session construction the adapter
revalidates Product id, Product policy revision, Session-sealed refresh policy,
admission lifetime, and package digest before acquiring a new independently
disposable revision lease through the existing package input primitive. Reusing
an adapter never shares the Session lease. Partial acquisition, failed Session
construction, unpublished bootstrap disposal, and Graph retirement close only
the acquired lease; the Product/loader-held source handle remains with its
original owner.

The same legacy discovery result now records the frozen package mounts plus the
prompt/Skill/Extension/theme candidate paths, source-root order, revision digest,
and diagnostic codes that it already observed. This record performs no new
filesystem scan and carries no winner, admission, or publication authority.
Coding joins supplied owner admissions against these candidate facts before the
Product adapter mints any Session input. The supported set is deliberately
narrow and exact:

- every enabled mount is a live verified revision rooted at the revision root;
- legacy package discovery emitted no diagnostics and no Extension candidate;
- every observed prompt, Skill, or theme candidate matches exactly one admission
  by kind, verified digest, body path, and source-root order; and
- every supplied admission matches one observed candidate.

Missing, extra, foreign, stale, expired, unverified, subroot, or otherwise
incomplete package evidence rejects with a finite reason. A source filter is
therefore respected only through the candidates actually emitted by the one
legacy discovery and the exact admission set supplied for them; the adapter does
not re-read filter configuration. Traditional path-backed package roots and
verified Plugins that have not completed `resource_item` declaration and owner
admission remain on v1 and fail closed in the opt-in shadow.

At RCP4.8, the private Coding construction helper accepted pre-admitted package
Resources solely as a migration/test seam. It did not run Plugin selection,
grant trust, or manufacture owner admission. RCP4.9 removed that raw ingress,
and RCP4.10 adds the private Product assembly primitive; neither change parses
`ResourceBundle` or loader internals. A real Coding Session test proves an
admitted package Skill through v2 Catalog publication, Graph ownership, exact
disposal, and zero pending retirement.

No temporary-source support, disabled-Skill policy projection, kind-switch
parity, refresh route, public SDK/CLI setting, default cutover, LSP, or MCP work
is added in this slice.

#### RCP4.9 implemented: compiled Product-composition ingress

The ninth slice closes that later gate at the Resource Catalog input boundary.
`InitialResourceCatalogProductSelection` now retains the exact existing
`ProductCompositionCompilation` that came after Plugin declaration, trust, exact
owner admission, and Product compilation. Its package Resource specifications
must be a fingerprint-exact set match for
`ProductCompositionCompilation.resource_admissions`, and the Catalog selection
must use the compilation's Product policy revision. A missing, extra, duplicate,
foreign-Product, or policy-mismatched compilation fails before package lease
acquisition.

Coding's private migration constructor now accepts only that compiled Product
composition. It derives Resource admissions from the compilation and joins them
to the same-discovery package candidate facts introduced in RCP4.8. The former
parallel raw `initial_resource_catalog_package_admissions` path is removed, so
there is one declaration/admission/compilation chain and no Coding-owned Plugin
selection or admission codec. The Product adapter rechecks Product identity,
policy, Session-sealed admission semantics, and the half-open admission lifetime
before it acquires any per-Session verified-revision lease.

A production-chain test starts from the checked-in inert `coding.base` Plugin,
runs the existing declaration host and owner-candidate bridge, admits its prompt
and Skill through their exact owners, compiles the Product composition, and
constructs independent Catalog revision leases. Closing those Session leases
does not close the Plugin runtime's source handle.

At RCP4.9 this was a production-compatible composition ingress, not Product
assembly. The public Coding SDK, CLI, and default v1 path still did not construct
or enable Plugin composition. RCP4.10 closes the private assembly primitive but
does not add default Plugin selection or Product owner-policy wiring. No refresh,
temporary-source parity, disabled-Skill projection, kind-switch parity, LSP, or
MCP behavior is added.

#### RCP4.10 implemented: exact-owner Product composition assembly

The tenth slice adds one private Product-root assembly primitive under
`harness.session`. Its inert request contains an already finalized
`PluginSelection`, explicit non-global owner bindings, mandatory Capability
roots, Capability definitions, and a Product-owned optional-requirement
selector. The primitive projects only selected `resource_item`, `tool_pack`, and
`command_pack` declarations through the existing owner-candidate bridge.
`capability_provider` remains on its separate Provider/Graph lifecycle and is
not reclassified as an external owner contribution.

The supplied owner keys must be an exact set match for the selected external
contribution owner keys before any admission is minted. Missing and unused
owners fail with stable finite codes. Each binding carries an existing
`OwnerContributionAuthority` and a bounded admission lifetime; the Product root
supplies one explicit evaluation time, which becomes both the compilation time
and every admission's issue-time basis. The existing compiler performs optional
requirement preview, accepts the Product's explicit choices, and compiles once.
The assembler adds no manifest parser, declaration codec, trust grant, global
owner registry, or second admission representation.

Coding's private initial-shadow construction root now accepts the assembly
request rather than a precompiled value. It samples wall time once, assembles
once, and passes both the resulting compilation and that same evaluation time
to Resource Catalog preparation. The lower Product adapter continues to accept
only the compilation and exact-match its Resource admissions against the
same-discovery package candidates. A production-shaped test starts with the
checked-in inert `coding.base` package, finalizes its existing declaration path,
binds all prompt, Skill, Tool, and Command owners, compiles them, and carries the
package Skill through a real Coding Session and exact disposal. Focused tests
also reject missing and extra owner bindings before Catalog lease acquisition.

This remains unpublished opt-in infrastructure. The caller must still obtain
the finalized selection and supply Product policy bindings; the public SDK,
CLI, and default v1 path remain unchanged. Default Product wiring, temporary
source and resource-policy parity, refresh, typed production Consumers, cutover,
LSP, and MCP behavior remain outside this slice.

The later PLC5.0 foundation extends the same private Product-root module with
the sibling Capability Provider assembly path: exact Capability-owner
eligibility/admission, explicit Product selection through the existing
resolver, and exact binding of externally issued activation-decision IDs into
the existing Session composition inputs. It is not RCP4.11 and does not change
Resource Catalog scope or behavior; it only lets the already compiled external
Consumer requirements and the resolved Provider closure enter one Session
Graph without another Product-specific assembly route.

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

#### RCP5.1 implemented: exact-generation typed Skill read path

The internal Skill Catalog Consumer validates that the captured descriptor
projection and Catalog snapshot belong to the same generation, exposes only
body-free immutable effective-Skill summaries, and mints Skill-narrowed wrappers
around owner-issued Resource load handles. A successful body load returns the
exact bytes, strict UTF-8 content, and the validated Resource receipt. Foreign
generation, foreign projection, non-Skill, unselected, and post-disposal loads
fail closed. Inactive/status projection remains explicit RCP5.2 debt, so this
first API cannot be mistaken for the all-Skills CLI cutover surface.

This slice changes no default Product construction or legacy caller. Its
rollback surface is limited to the internal Consumer and the projection
accessor on the existing private v2 Catalog facet. The ordered production
cutover and peer deletion remain RCP5.2 through RCP5.5 and require fresh
source-backed review before default wiring changes.

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

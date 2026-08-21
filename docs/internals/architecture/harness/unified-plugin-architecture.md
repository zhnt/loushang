# Unified Plugin Architecture

## Status

Target architecture, revised to address two rounds of independent boundary,
reference-parity, and lifecycle/security findings; this revision is pending
re-review. The existing Capability Graph, Runtime Profile,
Registration Scope, Extension/Resource generation, Effective Runtime, Resource
Package, and Plugin source-management runtimes remain authoritative while this
migration is incomplete. This document does not claim that `coding.lsp`,
`coding.arch`, or the unified Plugin lifecycle are already implemented.

Canonical Product, Capability, Mount, Package, Plugin, Extension, and Resource
terms remain defined by the
[Product And OEM Glossary](../../glossary/loushang-product.md). The
[Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md)
remains authoritative for the Capability Graph, the
[Extension And Resource Generation Lifecycle](extension-generation-lifecycle-boundary.md)
remains authoritative for current Extension/Resource generations, and the
[Effective Runtime Diagnostics Boundary](effective-runtime-diagnostics-boundary.md)
remains authoritative for projection and its four independent clocks.

This document joins their authoring, packaging, and selection entry paths. It
does not introduce a competing Profile resolver, registration owner, graph,
cross-owner transaction, or effective-runtime projector.

## Purpose

Loushang needs one Plugin system in which first-party, OEM, workspace, and user
contributions can be distributed, selected, diagnosed, and retired through the
same contracts. Coding's standard features, LSP support, and architecture
analysis should be composable without turning Harness into a global service
locator or letting installed code acquire authority automatically.

The target relationship is:

```text
Plugin Source
  -> immutable Materialized Package Revision
  -> authority-bound Resolved Plugin Package
  -> inert Plugin Preflight Decision
  -> immutable Plugin Declaration
  -> owner-specific Candidate Sets
  -> existing Runtime Profile layers + Product Capability Provider resolution
  -> owner-specific Admission Records and plans
  -> independent Graph / Extension / Resource owner generations
  -> existing Effective Runtime view + separate Plugin inventory
```

The governing rule is:

> A Plugin is a selectable contribution and management unit. A Capability is a
> stable typed runtime contract. A Package is a distribution unit. An
> Extension is one executable contribution kind. None is a synonym for the
> others, and Plugin provenance never replaces an existing runtime owner.

## Design Inputs And Deliberate Trade-Offs

The target combines four proven design properties without importing another
framework's object model:

- packages resolve to inert, source-authority-bound descriptors before any
  executable component is loaded;
- component kinds use focused hosts instead of one unrestricted executable
  Plugin context;
- installation, enablement, scope, policy, dependency, refresh, and repair are
  explicit management states;
- every reversible live registration belongs to an exact owner generation;
  irreversible external effects are admitted, recorded, and compensated by
  their domain owner rather than being described as rollbackable;
- Sessions and Agents pin the model-visible composition they actually used.

Loushang deliberately remains stricter than a universal service-context Plugin
runtime:

- typed Capability Definition / Provider / Consumer seams remain the runtime
  injection model;
- Product Kernel, policy enforcement, and owner-defined invariants are not
  replaceable merely because code is packaged as a Plugin;
- cross-owner live hot replacement is not promised; changes spanning Graph,
  Extension, and Resource owners require a new Session or `restart_required`;
- existing owner publishers and independent fact clocks remain authoritative.

This is a safety and explainability trade-off, not a claim of complete parity
with a runtime that can unload and restart any Plugin when any injected service
changes.

## Non-Negotiable Invariants

1. Plugin identity is not a Capability Graph node. Plugin provenance is a
   selection fact attached to owner-controlled contributions.
2. `RuntimeCapabilityGraphBinder` remains the only Capability Graph publisher.
3. `RuntimeProfileResolver` remains the final selector of Bundle-private
   Product runtime slots and variation. A Product-owned
   `ProductCapabilityProviderResolver` is the sole selector of top-level
   `CapabilityBundleProvider` candidates; the Graph Planner validates its
   already unique Provider set.
4. `RuntimeCapabilityGraphProjector` remains the only Graph/effective-runtime
   projector and retains the four-clock contract.
5. Every manifest format has one parser. In particular, `plugin.json` has one
   manifest parser; Package projection consumes its resolved descriptor and
   must not parse it again.
6. A contribution has one discriminated declaration kind, one declaration
   identity, and one binding owner. A source locator is evidence used by a
   contribution, not a second declaration of that contribution.
7. Every live registration remains owned by its exact Capability, Extension,
   Resource, Tool, or other `RegistrationOwner` and owner generation. A Plugin
   may aggregate retirement handles but never becomes the Registration owner.
8. A Product Runtime Plan or OEM Profile selects Plugins and authority
   ceilings; Plugins do not select themselves or widen their own authority.
9. Installed code is inert. Parsing a manifest or recording inventory never
   imports Python or launches a process. The state relation is
   `installed != enabled != preflight-approved != declared != requested !=
   owner-admitted != mounted`.
10. Built-in Plugins use the same resolution, declaration, selection,
    owner-binding, inventory, and retirement contracts as external Plugins.
    Only their source resolver and trust provenance differ.
11. Plugin revision/fingerprint facts supplement provenance. They never replace
    the complete canonical Model Input committed before every model request.
12. No API exposes a global mutable Plugin context, `dict[str, Any]` service
    bag, or unconstrained registry lookup.

## Vocabulary And Independent Identities

| Concept | Meaning | Runtime authority |
| --- | --- | --- |
| Plugin Source | A configured built-in, local, materialized, or registry-backed location. | None |
| Materialized Package Revision | Immutable/content-identified bytes from which resolution and execution occur. | Package cache owner |
| Resolved Plugin Package | Inert descriptor containing Plugin identity, version, digest, source authority, root, manifest, and typed locators. | None |
| Plugin Preflight Decision | Pure Product/OEM decision over manifest facts that determines whether executable declaration is allowed. | Permission to evaluate one digest-bound declaration entrypoint only |
| Plugin Definition | Host-equivalent trusted authoring entrypoint evaluated only after executable preflight. | Declaration evaluation only; never registration or activation |
| Plugin Declaration | Immutable serializable versioned tagged union of contributions, requirements, configuration schema, requested authorities, and factory/entrypoint references; never live callables. | None |
| Plugin Composition Set | Ordered reusable Plugin selections and default configuration expanded by a Product Runtime Plan or OEM Profile. It is not another Profile or Capability Bundle. | None |
| Resolved Plugin Candidate Set | Pure result containing Product-selected Plugins and owner-requested contributions after preflight/declaration; it never claims final owner admission. | Candidate input only |
| Resolved Capability Provider Set | Product-owned pure result containing one selected `CapabilityBundleProvider` metadata value and one matching binding specification per top-level Capability. | Graph planning/binding input only |
| Plugin Instance Revision | One selected Plugin descriptor/configuration at a concrete scope. It references owner generations but owns no Mount or foreign registration. | Provenance and direct-host lifetime only |
| Owner Generation | Capability Graph, Extension, Resource, Tool, external-service, or other owner-controlled generation. | Existing owner |
| Plugin Retirement Set | Read-only aggregation of exact owner retirement handles/results for one Plugin revision. | Coordination only |
| Component Host | Focused adapter that prepares and retires one contribution kind under its exact owner. | Its owned component only |
| Capability | Stable owner-qualified contract such as `coding.lsp`. | Capability owner and Graph |

The identities remain distinct even when their display strings look similar:

```text
Plugin ID:                  org.loushang.coding-lsp
Capability ID:              coding.lsp
Provider ID:                org.loushang.coding-lsp/default
Plugin instance revision:   plugin + workspace + descriptor/config fingerprint
Capability mount:           coding.lsp@workspace:repo-123 generation 4
Extension owner generation: extension-id + runtime-id + generation
Resolved Profile:           existing Runtime Profile fingerprint
```

A Plugin can contribute several candidates. Several Plugins can contribute to
one owner-controlled aggregate. An aggregate `harness.resources` generation is
not owned by every contributing Plugin and is not retired one Plugin at a time.
Removing one member prepares a new owner generation; the old owner generation
retires only under its existing owner lifecycle.

## Four-Phase Pipeline

### 1. Resolve once

Source acquisition/materialization is explicit and precedes resolution:

```text
configured source
  -> source policy
  -> immutable/content-addressed quarantine materialization
  -> PluginSourceResolver
  -> manifest and locked dependency-closure validation
  -> ResolvedPluginPackage
```

`PluginSourceResolver` performs no Python import, process launch, registry
mutation, or Product activation. The resolved descriptor contains at least:

- canonical Plugin ID, version, source kind, source identity, immutable content
  digest/revision, and locked dependency closure;
- an authority-qualified immutable package root and typed resource locators;
- the parsed canonical manifest, inert contribution index, declaration-IR
  version, and engine range;
- trust provenance, execution model, requested authorities, and compatibility;
- structured diagnostics for broken, mutable, unsupported, or untrusted
  packages.

Every locator carries its logical relative path, content identity, and
environment/source authority. Resolution normalizes paths after symbolic-link
resolution and proves containment within the immutable package revision.
Component Hosts open only the verified revision. They do not resolve the same
mutable source path again.

The canonical parsing boundary is:

```text
plugin.json           -> PluginManifestParser -> ResolvedPluginPackage
loushang-package.json -> PackageManifestParser -> ResolvedResourcePackage
ResolvedPluginPackage -> Package/Resource views without another file read
```

The current `resources.plugins.resolver` and
`resources.packages.manifest` handling of `plugin.json` must converge on one
parser. Compatibility aliases normalize into the canonical descriptor and do
not survive downstream.

All executable contributions, including local development Plugins, require a
content digest. Bind/import/launch revalidates that identity. A local source
change invalidates the plan and approval; it never causes previously approved
paths to execute changed bytes. The manifest's inert contribution index must
contain every executable contribution ID, kind, entrypoint locator, execution
model, requested authority ceiling, and security-relevant configuration field
needed to decide whether evaluating its declaration is permissible. It is not
a second contribution declaration: the later declaration must match it exactly
or fail closed.

Remote dependencies are disabled until the resolver can produce an immutable
lock over the complete dependency closure. Source trust is not transitive.
Materialized revisions remain reference-counted while selected, running, or
required for configured cold resume.

Discovery records broken packages rather than silently dropping them. A
Product Runtime Plan/OEM Profile that requires a broken Plugin fails before
activation; an unselected broken Plugin remains visible in inventory
diagnostics.

### 2. Preflight, then declare once

Executable declaration has a mandatory pure preflight. The same narrow
`PluginSelectionResolver` exposes two non-overlapping operations:

1. `preflight(packages, profile, overlays)` resolves installed/enabled/required
   state, immutable dependency locks, engine compatibility, source trust,
   Product/OEM Plugin and contribution allowlists, runtime scope, and the
   package-level execution approval subject using only inert manifest facts;
2. `finalize(preflight, declarations)` validates declaration/index identity,
   applies Product-selected contribution enable/deny/order/config requests, and
   emits owner-specific candidates. It does not make final owner admission or
   conflict decisions.

Only a digest-bound package with a positive preflight decision may evaluate an
executable declaration. Disabled, unselected, incompatible, untrusted, denied,
or unapproved packages are never imported and never launched. If information
required to make preflight is available only by executing code, that package is
invalid for in-process declaration; discovery must move to an accepted isolated
worker or the information must move into the inert manifest.

There are two explicit approval subjects:

- `PluginExecutionApprovalSubject` gates declaration import or service launch
  and binds Plugin ID, package digest, complete dependency-lock digest,
  execution model, immutable entrypoint, source/trust provenance, Product ID,
  tenant/workspace/installation scope identity, the ambient-host-authority bit,
  normalized security-relevant configuration fingerprint, and the maximum
  requested authority ceiling;
- `ContributionActivationApprovalSubject` gates final binding and additionally
  binds Contribution ID, owner/scope, selected Provider or host identity,
  requested authorities, and the final effective grants returned by the owner.

Security-relevant configuration includes executable/argv, endpoint/transport,
working-directory or workspace locator, behavior mode, sandbox profile, and
credential-reference identity. Changing any subject field invalidates the
approval. Secret material is never part of either subject. Products that use
action-level approval may still require a fresh decision for individual
effects; package approval never silently substitutes for action policy.

The declaration phase converts one resolved descriptor into one immutable,
versioned `PluginDeclaration` after positive preflight. It may import a
host-equivalent-trusted in-process Plugin Definition from the verified
revision, but it must not publish effects. Resource-only and declarative
external-service Plugins need no Python import.

A candidate internal authoring seam is:

```python
class PluginDefinition(Protocol):
    def declare(
        self,
        context: PluginDeclarationContext,
    ) -> PluginDeclaration: ...
```

`PluginDeclarationContext` exposes immutable package locators, preflighted
configuration input, engine features, and declaration builders. It does not
expose registries, live Providers, a Session, credentials, or arbitrary
services. For host-trusted in-process Python this is an authoring discipline,
not a security sandbox. The returned IR contains only strict serializable data
and verified locator/factory references; a callable captured in the IR is a
schema violation.

The declaration IR is a mutually exclusive tagged union:

| Declaration kind | Meaning | Sole binding owner |
| --- | --- | --- |
| `capability_provider` | Data-only Provider metadata plus a verified factory/disposer reference for an owner-defined top-level Capability. | Product Capability Provider resolver, then Graph Binder |
| `resource_item` | Prompt, Skill, theme, asset, method, or raw source descriptor. | Resource generation owner |
| `tool_pack` | Typed Tool pack referencing any required source items. | Owning Capability Bundle Tool facet |
| `command_pack` | Typed Command pack referencing any required source items. | Owning Capability Bundle Command facet |
| `event_definition` | Owner-qualified, versioned event contract in a namespace the Product/Capability owner granted to the contributor. | Product/Capability domain Event Definition catalog |
| `event_subscription` | Typed observer over an admitted Event Definition. | Extension/event owner |
| `interceptor` | Ordered typed interceptor/decorator/reducer/first-match contribution. | Extension/router owner |
| `agent_definition` | Typed Agent role referencing prompts, model policy, Tool/Skill selectors, memory policy, and an optional named Composition Set. | Product Agent Host |
| `presentation` | Renderer, shortcut, flag, or UI contribution. | Presentation/Extension owner |
| `external_service` | Declarative MCP, LSP-server, or other process/transport service. | Kind-specific service host |
| `configuration_schema` | Namespaced settings, defaults, sensitivity, and refresh policy. | Product configuration runtime |

A command Markdown file may be a `resource_item` locator, but its executable
command identity exists only in one `command_pack`. The same rule applies to
Tool schemas and other file-backed declarations. The compiler rejects an
identity emitted by more than one manifest, resource, Extension, or executable
entrypoint path and reports both provenance records.

Typed event/hook support is not hidden behind a generic `register_*` bag. A
Product/Capability domain owns an `EventDefinitionCatalog`; it may contribute
built-in definitions or admit an `event_definition` only inside a namespace
explicitly delegated to that Plugin. The catalog is the sole definition and
version authority. Subscriptions can only reference its admitted snapshot.
`EventDefinition` is owner-qualified and versioned, and states:

- payload schema/codec and compatible version range;
- live versus durable ownership;
- process, tenant, workspace, Session, turn, or Channel routing scope;
- exactly one dispatch mode: awaited serial broadcast, awaited parallel
  broadcast, ordered interception, reduction, or first-match;
- duplicate-subscription identity and suppression rules;
- deterministic ordering, result aggregation, error containment, delegation,
  cancellation, per-listener/whole-dispatch timeout, and late-result policy.

Durable events are committed by their domain owner before live dispatch. A
Plugin subscription never becomes the durable event authority. There is no
unspecified `broadcast` mode and no fire-and-forget callback hidden behind an
awaited contract. The existing Extension `observe` route maps initially to
awaited serial broadcast; interceptor, reducer, and first-match routes retain
their explicit modes. Awaited parallel broadcast requires a distinct owner
implementation and conformance tests before use.

An `agent_definition` is declarative and does not create an Agent while being
bound. The Product Agent Host admits it, resolves its referenced
Resource/Tool/Skill facts from owner snapshots, and persists its definition ID,
composition request, and model-visible material. Starting an Agent then joins
the parent Session composition or creates the explicit child Product Session
required by its Composition Set. Agent definitions cannot mutate parent
selection or introduce a side-channel Profile.

The current Extension `register_*` authoring API becomes a compatibility
adapter. During declaration compilation it captures typed calls into a private
builder and freezes the same tagged IR without mutating a live registry.
Binding later realizes those declarations under exact owner scopes. For a
canonical Plugin, calling a declaration-forming `register_*` after IR freeze or
owner publication fails closed. A dynamic declaration change must prepare a
new owner generation; it is never appended to the published Plugin revision.
The existing post-publication one-entry scopes remain temporarily available to
legacy non-Plugin Extensions only, are inventoried as a migration surface, and
must not be used by the canonical Plugin adapter. New SDK code returns
declarations directly.

The IR is frozen before the public SDK:

- manifests and declaration IR carry independent schema versions and compatible
  engine ranges;
- unknown-field behavior is explicit per versioned object;
- Capability contract/facet version negotiation happens before admission;
- host feature negotiation produces structured incompatibility diagnostics;
- the Python SPI remains internal/unstable until cross-version fixtures prove
  the IR stable.

### Existing Profile And Selection Authority

There is no new Plugin Profile resolver. Product Runtime Plans and OEM Profiles
expand Plugin Composition Sets and supply Plugin-selection/configuration
overlays. A narrow `PluginSelectionResolver` owns only the preflight/finalize
split above. Its
final output says which Plugins Product policy selected and which contribution
candidates they request. It never labels a contribution `admitted`, chooses a
live Provider, or resolves an owner-specific conflict.

Top-level Capability Providers have an explicit Product-owned seam that is not
a Runtime Profile slot:

```text
capability_provider declaration
  -> data-only CapabilityProviderCandidate(metadata + factory reference)
  -> ProductCapabilityProviderResolver
  -> ResolvedCapabilityProviderSet
       - one CapabilityBundleProvider metadata value per Capability
       - one matching CapabilityProviderBindingSpec per selected Provider
  -> RuntimeCapabilityGraphPlanner(metadata only)
  -> Capability Component Host verifies the selected revision and resolves the
     spec into one CapabilityBundleProviderBinding
  -> RuntimeCapabilityGraphBinder(plan + matching bindings)
```

`ProductCapabilityProviderResolver` is pure and is the sole top-level Provider
selection/admission authority. It receives Product baseline candidates plus
eligible OEM/Plugin candidates, Product roots/definitions, explicit selection
rules, scope, compatibility and authority ceilings. It rejects zero/multiple
Providers where the Product requires exactly one and emits structured owner
admission records. It does not import a factory or construct a Provider.
`CapabilityProviderBindingSpec` holds only the selected immutable locator,
factory/disposer reference, normalized binding inputs and approval subject; the
Component Host resolves the callable only after final activation approval.
Metadata and binding specs must have an exact `(capability_id, provider_id,
implementation_version, digest)` match or binding fails before construction.

`RuntimeProfileResolver` remains the sole final selector for Bundle-private
Product runtime slots and variation semantics. A top-level Capability ID such
as `coding.lsp` is never used as a Runtime Profile slot. Other owner-specific
contribution resolvers remain sole admission/conflict authorities for aggregate
resources, Tools, Commands, Event Definitions/subscriptions, Agent Definitions,
and presentation. Each returns an immutable `OwnerContributionAdmissionRecord`
containing requested/admitted/rejected identities and policy provenance.
`RuntimeCapabilityGraphPlanner` receives the already unique Provider metadata
set and only validates contracts, facets, authority, dependencies, scope, and
DAG order.

Plugin is provenance, not a new Runtime Profile source rank. Each emitted
Bundle-private layer uses the authority that selected it: Product, OEM,
Extension, or Session. The Plugin ID, contribution ID, and digest remain
structured provenance on that selection rather than altering precedence.

Plugin-to-Plugin runtime service lookup is forbidden. A distribution dependency
guarantees an immutable package revision is available and selected; runtime
needs use typed Capability requirements or owner-defined contribution
contracts.

The Product Host continues to supply named low-to-high configuration layers
through the existing layered configuration contract. Managed policy is an
admission ceiling, not a value that a later layer can overwrite. Secret values
remain references. A binding fingerprint includes the non-secret reference
identity, credential provider, authority class, and rotation epoch when it can
affect reuse; it never includes secret material.

### 3. Bind once

“Bind once” means one owner path for each live object, not one global Plugin
transaction over unrelated owners.

For a new Session, the existing composition root is the visibility boundary:

```text
resolve packages and inert preflight decisions
  -> evaluate only preflight-approved declarations
  -> compile owner-specific candidate sets
  -> create one root-owned StagedResourceCompositionCandidate
  -> discover data-only Extension/Resource contributions
  -> RuntimeProfileResolver selects final Bundle-private slots
  -> ProductCapabilityProviderResolver selects top-level Provider metadata/specs
  -> Graph Planner validates metadata and Component Hosts resolve approved bindings
  -> attach final Profile/Provider facts to the same Resource candidate
  -> transfer that candidate once to the Session-owned Graph Binder
  -> bind final Graph and existing owner generations
  -> capture typed Consumers
  -> publish the usable Product Session
```

This preserves the CLA0-CLA8 bootstrap/final single-candidate handoff. No late
peer Resource candidate, construction callback, or second Graph bind is
introduced. A startup failure disposes the unpublished Session candidate and
its independently owned effects; no existing Session is retroactively changed.

Every owner retains its exact `RegistrationOwner` and `RegistrationScope`:

- Capability registrations remain in Capability generation scopes;
- Extension registrations remain in Extension generation scopes;
- Resource, Tool, Command, event, presentation, and external-service
  registrations remain with their owner runtime;
- one lease never belongs to two scopes.

`PluginRetirementSet` contains only opaque owner retirement handles, owner and
generation references, contribution IDs, and redacted outcomes. It does not
capture `RegistrationScope`, publish, deactivate leases, or dispose foreign
owners itself.

Disable/remove has one unambiguous lifecycle:

- selection changes affect every subsequently created Session immediately;
- an active Session may apply a single-owner change only through that owner's
  already accepted live transaction;
- an active Session whose change affects a Capability Provider, dependency,
  authority, process topology, or more than one owner records
  `restart_required` and does not ask any affected owner to recompose;
- after a permitted single-owner commit, its replaced generation drains under
  that owner; after `restart_required`, old owner generations remain pinned
  until the active Session exits normally;
- the Plugin layer aggregates the resulting owner references and retirement
  outcomes but never triggers a second retirement.

Existing Session refresh follows an intentionally conservative rule:

| Change | Allowed live path |
| --- | --- |
| Content-only Resource change | Existing Resource owner transaction and source-publication clock |
| Extension-only change that preserves Graph inputs | Existing Extension/Resource generation transaction |
| Private turn-refreshable facet | Existing owner turn-refresh contract |
| Capability Provider, dependency, authority, process topology, or multi-owner change | `restart_required` or a new Session |

Trusted in-process Python has an additional v1 boundary: changing its package
digest is Product-Host `restart_required`. A new revision cannot coexist in the
same interpreter with an old revision unless a separately accepted
digest-qualified import realm proves module namespace, `sys.modules`, native
extension, dependency environment, singleton, and disposer isolation. Until
then the Product Host drains Sessions using the old revision and restarts
before importing the new one. Resource/declarative or isolated-service
revisions may coexist when their own owner contracts permit it.

There is no sequential Graph/Extension/Resource publish followed by snapshot
restoration. Publication of an owner generation is its linearization point.
Cancellation before that point aborts the candidate; cancellation after it
does not roll the committed owner backward. Notifications and user callbacks
run only after their owner commit and cannot convert post-commit failure into a
rollback.

If future evidence justifies cross-owner live hot replacement, it requires a
separate accepted design with invisible versioned owner snapshots, a shared
read barrier, one atomic epoch pointer, post-commit notifications, and rules
for irreversible effects. It is not implied by this v1 architecture.

A Component Host is intentionally narrow:

| Host | Accepted input | It must not do |
| --- | --- | --- |
| Resource Component Host | Verified locators and typed resource declarations | Reparse Plugin manifests or bind Capabilities |
| Extension/Event Host | Admitted typed declarations and verified entrypoint | Select Product policy or publish the Graph |
| External Service Host | Declarative service spec and authorized launch/transport facets | Launch through raw subprocess APIs |
| Capability Host | Selected Definition/Provider/Consumer inputs and factories | Bypass Runtime Profile or Graph Planner/Binder |
| Plugin Inventory Host | Package/selection/provenance snapshots | Infer Graph, Extension, Resource, or Model Input state |

There is no universal `activate(plugin_context)` callback. Provider factories
receive least-authority typed dependency views and an exact-owner registration
collector. External integrations obtain process/network/workspace access only
through admitted and enforceable host facets.

### 4. Project once

`RuntimeCapabilityGraphProjector` and `EffectiveRuntimeView` remain the sole
effective-runtime projection. Their four clocks remain:

1. current Runtime Profile fingerprint;
2. committed Mount Graph identity/generation/fingerprint;
3. registration inventory revision and Mount reference;
4. optional Model Input snapshot and the runtime clocks it observed.

Plugin selection is represented through redacted Runtime Profile selection
provenance, owner-generation provenance, and the existing scoped Resource
source-publication reference. It does not create a fifth effective clock or an
atomic effective snapshot.

A separate `PluginInventoryProjector` may report package-management facts only:

- Plugin ID, version, source authority, digest/revision, trust/execution model,
  and installation scope;
- directly owned installed, enabled, preflight-approved, declared, requested,
  disabled, broken, or removal-pending state;
- requested cooperative facets/authorities plus references to owner-recorded
  effective grants;
- declared and filtered contribution identities plus references to
  owner-recorded admitted/rejected identities;
- configuration provenance with secret material redacted;
- exact references to Runtime Profile selections and owner generations;
- materialization, compatibility, retirement, and repair diagnostics.

Its input is an immutable `PluginInventorySnapshot` with its own monotonic
package/selection inventory revision. That snapshot stores package and
preflight facts directly and only opaque references to already-published
Runtime Profile snapshots, `OwnerContributionAdmissionRecord` values, owner
generation snapshots, and retirement results. It never joins live mutable
registries or upgrades `requested` to `admitted` by inference. Cross-owner skew
is represented by the referenced owner revisions, not hidden behind a synthetic
atomic generation.

The projector never labels a Capability mounted, reconstructs effective
Tool/Resource state, or supplies a model-facing view. CLI, RPC, and UI combine
this inventory with the existing Effective Runtime view without rebuilding
either authority.

### Model-Visible Persistence

Before every model request, the transcript/Model Input authority commits the
actual canonical request material required for independent reconstruction:

- normalized system/developer prompts and messages;
- complete Tool definitions and schemas;
- options, budgets, compaction lineage, and Provider payload;
- Runtime Profile, Mount, and registration references already required by the
  Model Input boundary;
- optional Plugin ID/contribution/digest provenance for explanation.

Plugin, prompt, Skill, or Tool fingerprints are supplementary provenance only.
Replay reads committed Model Input material and never reopens the current
Plugin package or current registries. A request prepared across refresh uses
the owner generations and complete input facts captured at its commit seam.

## Composition Sets, Overlays, And Fine-Grained Policy

A Plugin Composition Set is a reusable list of Plugin selections and defaults
expanded by an existing Product Runtime Plan or OEM Profile. It is not a live
object and not a second Profile. Stable selection and contribution IDs allow
an authorized overlay to:

- insert, require, enable, or disable a Plugin selection;
- pin/replace a source revision subject to trust policy;
- enable/deny/order one contribution without disabling the entire Plugin;
- patch namespaced configuration and authority requests;
- invalidate the applicable execution/activation approval whenever any bound
  digest, dependency lock, execution model, source/trust, scope,
  security-relevant configuration, requested authority, or effective grant
  changes.

Unknown IDs, duplicate IDs at one layer, ambiguous contribution selection, and
invalid patches fail before effects. Runtime state never persists back into a
source manifest, Composition Set, Product Profile, or OEM Profile.

An explicit user mention such as a Codex-style `plugin://...` token is a
turn-scoped request, not installation, enablement, or authority. The Product
input parser resolves it to stable Plugin/contribution IDs; the existing
Resource/Tool owner may project only contributions already admitted and pinned
by the Session. A mention that requires a new Plugin, owner generation, or
authority returns a structured unavailable/`restart_required` diagnostic. The
Model Input commit records the mention, resolution provenance, and exact
injected prompt/Skill/Tool material, so replay does not rerun current Plugin
selection.

## Scope, Membership, Leases, And Reclamation

The current runtime scopes remain canonical:

```text
process -> tenant -> workspace -> session -> turn
                  -> channel
```

Installation scope, runtime owner scope, and composition membership are
different concepts. A Plugin declaration uses the existing process, tenant,
workspace, Session, turn, or Channel owner scopes. A longer-lived owner cannot
capture a shorter-lived concrete dependency; it uses a stable reference/lease
or joins the dependent-closure refresh.

Agent is a composition membership boundary, not a new Capability scope in v1:

- a live Agent atomically joins its parent Session's resolved selection and
  package-revision leases at creation;
- a subagent inherits the same selection by default;
- an admitted `agent_definition` requesting a different Composition Set must
  create an explicit child Product Session/Graph through the Product Host;
- a child cannot mutate its parent's selection;
- cold resume uses persisted Profile/selection/digest facts and fails with a
  repair diagnostic when a locked revision is unavailable.

This is less dynamic than per-Agent service-context recomposition and is
recorded as an intentional v1 gap.

Direct Plugin-host instances and materialized revisions use a race-free lease
state machine:

```text
ACTIVE -> DRAINING -> RETIRED
```

- `acquire_current()` reads the current revision and increments its lease count
  under the same runtime gate;
- `DRAINING` rejects new acquisition, causing callers to retry the replacement
  or return `restart_required`;
- Session/Agent membership holds package-revision leases; turns, Tool tasks,
  and external-service calls hold their applicable owner/facet leases;
- every owner generation, disposer, external-service shutdown record, and
  retryable cleanup task that may reopen package bytes or entrypoints holds its
  own package-revision lease until cleanup reaches a terminal result;
- release is idempotent and cancellation-safe;
- shutdown blocks new acquisition, waits for held leases, and keeps failed
  cleanup visible/retryable;
- `DRAINING -> RETIRED` and cache reclamation occur only after acquisition
  counts, running Session/Agent membership, owner-generation/cleanup leases,
  configured cold-resume references, and lockfile references all reach zero;
  a retryable cleanup failure therefore retains its revision.

Owner generations continue using their own lease/invalidation rules. A Plugin
join count never substitutes for Capability or Extension leases.

## Trust, Authority, Secrets, And Private Data

Installation proves only that verified bytes were materialized. Admission is
the intersection of source trust, content identity, Product/OEM allowlist,
Profile ceiling, contribution authority, and execution-time policy.

Execution models are explicit:

| Execution model | Security meaning |
| --- | --- |
| Resource/declarative | No arbitrary in-process code; host enforces typed parsing and authority. |
| Isolated external service | Process/transport authority is enforceable only to the extent of the Sandbox and host facets. |
| In-process Python | Host-equivalent trusted code with ambient Python/process authority. Typed facets provide architecture, portability, and audit—not isolation. |

Workspace, user, or OEM code that is not trusted as host-equivalent cannot use
in-process Python. It must remain resource/declarative or run through an
accepted isolated worker. Diagnostics distinguish cooperative facet grants
from enforceable sandbox/host grants. Even host-equivalent code is never
imported merely because it is installed: source trust and the complete
`PluginExecutionApprovalSubject` must pass inert preflight first.

Security contracts include:

- immutable/content-addressed executable revisions and bind-time digest checks;
- containment and no mutable-path re-open after validation;
- execution and activation approvals bound to hash, dependency lock,
  security-relevant configuration, source/trust, scope, requested ceiling, and
  final effective authority as applicable;
- source policy before materialization and again before activation;
- locked dependency closure and no transitive registry trust;
- execution-time revalidation for policy/approval-controlled actions;
- structural redaction for diagnostics and projections;
- secret-reference identity/provider/rotation epoch in binding fingerprints,
  while secret material never enters plans, logs, fingerprints, or errors;
- revocable secret leases and an explicit live-rotation versus
  `restart_required` policy per field.

Plugins that need persistent private state receive a Product-authorized
`PluginDataFacet`, not a raw home-directory path. It is namespaced by Plugin ID
and runtime/installation scope and defines quota, schema version, migration,
backup/export policy, and cleanup. Disable preserves data by default; update
runs an explicit migration; final uninstall deletes data only through a
separate confirmed operation after all installations and leases are gone.

## Coding Product Decomposition

The Coding Product Kernel remains deliberately small and non-pluggable. It owns
Product identity, domain goals, the mandatory system prompt, Session/turn
correctness, Product-to-Harness composition, context/compaction and risk
defaults, transcript/model-call policy, artifact semantics, presentation
policy, and mandatory safety enforcement. The Coding Product Kernel must remain
usable when every optional Plugin is disabled.

`coding.base` is a Product-owned Plugin ID selected by the default Composition
Set, not a top-level Capability ID. It contributes optional prompt fragments,
Skills, commands, Tool packs, and adapters. It does not own the mandatory
Coding identity, system prompt, or policy defaults.

The initial first-party decomposition is:

| Plugin | Main contribution | Capability effect |
| --- | --- | --- |
| `coding.base` | Optional standard Coding resources, commands, and Tool packs | Aggregates into `harness.resources` and `harness.session`; no new graph node |
| `coding.lsp.default` | LSP admission, supervisor/document runtime, semantic tools, and diagnostics | Provides `coding.lsp`, requiring narrow `harness.workspace` read/process facets |
| `coding.arch.default` | Repository analyzers, architecture facts, queries, and tools | Provides `coding.arch`, requiring `harness.workspace` and optionally consuming `coding.lsp` |

Suggested named Coding Composition Sets, selected by the Product Runtime Plan
or OEM Profile rather than a new Product Profile type, are:

| Profile | Selections |
| --- | --- |
| `coding-minimal` | Product Kernel plus mandatory Harness capabilities |
| `coding-standard` | `coding-minimal` plus `coding.base` and on-demand `coding.lsp.default` |
| `coding-architecture` | `coding-standard` plus on-demand `coding.arch.default` |

The LSP vertical slice replaces the multi-stage
mode/discovery/deferred-runtime/process-launch/Tool pre-binding chain:

```text
coding.lsp.default declaration
  -> CapabilityProviderCandidate for coding.lsp
  -> ProductCapabilityProviderResolver selects one metadata/binding spec pair
  -> requirement on harness.workspace(read, process.launch)
  -> Capability Component Host resolves the approved factory reference
  -> one selected Provider factory receives typed facets
  -> Graph Binder mounts one coding.lsp Bundle
  -> Bundle exposes semantic runtime + tools + diagnostics
```

Tools are part of the selected Bundle and become visible with the runtime they
call. They are not registered earlier against a deferred LSP object.

## Single-Authority Matrix

| Concern | Sole authority | Forbidden peer path |
| --- | --- | --- |
| `plugin.json` parsing | `PluginManifestParser` | Package catalog or Component Host reparsing |
| Source bytes/path authority | immutable `ResolvedPluginPackage` locators | Raw mutable path joining in consumers |
| Plugin executable preflight and candidate selection | Product Runtime Plan/OEM Profile plus two-phase `PluginSelectionResolver` | Import-before-preflight or self-enable in Plugin code |
| Top-level Capability Provider selection | Product-owned `ProductCapabilityProviderResolver` | Runtime Profile slot or Plugin code choosing a live Provider |
| Bundle-private slot/variation selection | `RuntimeProfileResolver` and owner variation policy | Top-level Capability ID masquerading as a slot |
| Final contribution admission | Exact owner resolver and `OwnerContributionAdmissionRecord` | Plugin inventory inferring admission |
| Contribution declaration | versioned tagged `PluginDeclaration` compiler | Manifest/resource/runtime duplicate identities |
| Agent Definition admission/binding | Product Agent Host | Resource loader or Plugin directly creating an Agent |
| Event Definition contract | Product/Capability domain Event Definition catalog | Subscription inventing an event or dispatch mode |
| Capability DAG validation | `RuntimeCapabilityGraphPlanner` | Plugin dependency graph as a service graph |
| Capability publication | `RuntimeCapabilityGraphBinder` | Plugin runtime publishing Mounts |
| Registration ownership | exact owner `RegistrationScope` | Root Plugin scope capturing foreign leases |
| Extension publication | Extension generation owner | Plugin runtime mutating Extension registries |
| Resource publication | Resource generation owner and CLA single candidate | Plugin runtime rebuilding Resource state |
| Model-visible input | complete committed Model Input facts | Fingerprint-only replay or current registry reads |
| Effective diagnostics | `RuntimeCapabilityGraphProjector` / `EffectiveRuntimeView` | Plugin projector rebuilding effective state |
| Plugin inventory | package/selection-only inventory projector | Claiming Capability or Resource effectiveness |
| Retirement | each exact owner; Plugin aggregates handles/results only | Plugin directly disposing foreign scopes |

Multiple source adapters and typed Component Hosts are allowed. There is still
one normalized descriptor, one declaration identity, one preflight owner, one
final admission authority per contribution kind, one binding owner per live
object, and one effective projection path.

## Current Gap And Reference Trade-Offs

| Area | Current Loushang position | Remaining gap or deliberate difference |
| --- | --- | --- |
| Typed Capability composition | Strong Planner/Binder/Runtime/Projector and exact registration ownership | Add Product-owned top-level Provider resolver; mount `coding.lsp` and `coding.arch` without treating them as Runtime Profile slots |
| Package resolution | Resource-oriented source registry/materialization | Immutable descriptor, mandatory digest/lock, one manifest parser, stable scope inventory |
| Plugin lifecycle | Enablement resolves roots; owner lifecycles are separate | Unified selection/provenance and retirement aggregation without replacing owners |
| Declarations | Manifest and executable Extension registrations converge late | Versioned mutually exclusive IR and compatibility capture adapter |
| Profiles/composition | Product/OEM Runtime Profiles already exist | Composition Sets must compile into existing Profile layers, not a peer Profile |
| Events/hooks | Extension routing exists | Owner-qualified Event Definition catalog, explicit dispatch modes, public subscription/interceptor SDK, and compatibility mapping |
| Agent definitions | Agent runtime/session composition exists | First-class `agent_definition` contribution and Product Agent Host admission/persistence |
| Scoping | Six runtime scopes exist | Agent membership inheritance, child-Session Composition Sets, and cold-resume locks |
| Refresh/HMR | Owner transactions and restart-required boundaries are strong | No universal dependency-triggered Plugin reload; cross-owner live HMR is intentionally deferred |
| Fine-grained policy | Product/Extension admission exists | Contribution-level enable/deny/order/config/authority and hash-bound approval |
| Private Plugin state | No unified Plugin data contract | Scoped data facet, quota, migration, preservation, and final deletion semantics |
| Operations | Package/plugin commands and diagnostics exist | One installed/enabled/preflight/declared/requested inventory that references, but never infers, owner admission/effectiveness |
| Ecosystem surfaces | Coding-centric integrations | Stable SDK, external host, MCP/ACP/JSON-RPC and multi-Product adapters in later waves |
| Model-visible persistence | Complete committed Model Input is a Loushang strength | Preserve inline facts; add Plugin provenance only |

The largest immediate implementation gap is the missing single flow from
package revision through declaration and existing Runtime Profile/owner plans.
That does not erase separate gaps in typed events, Agent composition, dynamic
dependency-driven reload, private state, management UX, or ecosystem adapters.

## Delivery Sequence

Every slice preserves the CLA authority inventory and adds a regression before
implementation.

### UPA0: Baseline And Authority Freeze

- freeze current `plugin.json` readers, Runtime Profile selection sites, Graph
  Binder/Projector definitions, exact Registration owner paths, Extension and
  Resource publishers, Model Input commit sites, and LSP/Arch construction;
- preserve CLA AUTH-01–AUTH-15, ENTRY-01–ENTRY-05, the one root-owned Resource
  candidate, final Profile attachment, and one-time Graph transfer;
- classify existing document tests as documentation contracts, not proof of
  runtime exclusivity;
- add negative fixtures proving a second parser/publisher/mutation route fails.

### UPA1: Immutable Resolve Once

- introduce the canonical manifest parser and `ResolvedPluginPackage`;
- make Package/Resource projection consume that descriptor;
- require executable digests, immutable materialization, dependency lock,
  source-qualified containment, revalidation, and broken-package inventory;
- keep registry-backed dependencies disabled until complete locks exist;
- migrate built-in, local, and materialized sources through the same result.

### UPA2: Inert Preflight, Versioned Declaration, And Candidate Selection

- implement the inert contribution index and the preflight/finalize operations
  of `PluginSelectionResolver`; prove denied/disabled code is never imported;
- add both approval-subject schemas, the serializable tagged declaration IR,
  internal `PluginDefinition`, Composition Sets, contribution selectors,
  policy ceilings, and security fingerprints;
- compile only requested candidates into existing Bundle-private Runtime
  Profile and owner-specific inputs;
- define Event Definition/subscription/interceptor and Agent Definition
  contributions plus the fail-closed Extension capture adapter;
- add schema/engine/feature negotiation fixtures before public SDK exposure.

### UPA3: Owner-Preserving Bind, Lease, And Inventory

- bind through the existing CLA single-candidate and Graph path;
- add `ProductCapabilityProviderResolver`, matching metadata/binding specs, and
  exact Product-owned top-level Provider admission records;
- add Plugin Instance Revision, exact-owner retirement aggregation, package
  revision leases, `ACTIVE/DRAINING/RETIRED`, and Agent membership inheritance;
- add package/selection inventory references without another effective
  projector or clock;
- prove refresh/shutdown/acquire races and `restart_required` for multi-owner
  changes.

### UPA4: LSP Vertical Slice

- package the default LSP implementation as a first-party Plugin;
- select `coding.lsp` through `ProductCapabilityProviderResolver` and mount it
  through the Session Graph; Runtime Profile remains Bundle-private;
- remove deferred LSP/process/Tool pre-binding paths;
- prove alternate Provider selection, startup rollback, restart reconstruction,
  complete Model Input facts, and owner-correct disposal.

### UPA5: Architecture Vertical Slice

- package the default architecture implementation as a first-party Plugin;
- mount `coding.arch`, initially independent of LSP;
- add the optional typed LSP requirement only after contract evidence;
- bind analyzers, facts, diagnostics, and Tools in one owner Bundle generation;
- exercise the Plugin private-data migration/quota contract for indexes.

### UPA6: Base Coding Composition

- define `coding.base` and minimal/standard/architecture Composition Sets;
- move only optional Coding contributions, preserving Kernel-owned domain and
  safety semantics;
- delete duplicate CLI registrations and hard-coded capability defaults after
  compatibility telemetry proves no callers remain.

### UPA7: Public SDK And External Components

- publish the stable manifest/declaration IR and SDK after cross-version
  conformance passes;
- add declarative MCP/external-service hosting through authorized process and
  transport facets;
- add OEM compatibility, contribution-policy, trust, upgrade, and data-migration
  tests.

### UPA8: Management And Isolation Closure

- unify install, remove, enable, disable, update, refresh, repair, list,
  explain, and diff across CLI/RPC/UI;
- complete isolated worker evaluation before admitting untrusted executable
  code;
- define retained-version and private-data garbage collection;
- remove superseded Plugin, Package, and Extension compatibility adapters.

## Acceptance Gates

The architecture is complete only when these statements are executable:

- `plugin.json` is parsed once and Package/Plugin consumers share identical
  immutable locator/containment semantics;
- disabled, denied, incompatible, or unapproved executable packages are never
  imported, and every executed declaration has a persisted positive preflight;
- execution and activation approvals are bound to digest, dependency lock,
  source/trust, scope, security configuration, and effective grants;
- built-in and external Plugins produce the same descriptor/declaration shapes;
- two Product Runtime Plan/OEM Profile combinations select different Plugins;
  Bundle-private contributions flow through existing Runtime Profile layers
  without Product code branches;
- contribution kinds are mutually exclusive and a duplicate command/tool/event
  identity fails with both provenance records;
- an `agent_definition` has one Product Agent Host admission/binding path and a
  different Composition Set creates a child Product Session rather than
  mutating its parent;
- every Event Definition has one owner/version and every dispatch has an
  explicit awaited mode, ordering, timeout, failure, and aggregation contract;
- an alternate `coding.lsp` Provider is selected without changing Session, CLI,
  or Tool implementation code, and no `coding.lsp` Runtime Profile slot exists;
- a failed/cancelled unpublished Session candidate leaks no owner registration;
- multi-owner live changes return `restart_required` rather than exposing mixed
  or retroactively restored generations;
- disabling a Plugin affects new Sessions immediately; a permitted single-owner
  active change recomposes that owner once, while an active multi-owner change
  performs no partial recompose and returns `restart_required`;
- acquisition cannot race `ACTIVE -> DRAINING -> RETIRED`, shutdown blocks new
  joins, and retained revisions are reclaimed only after Session, owner,
  cleanup, cold-resume, and lock references end;
- trusted in-process Python digest changes are restart-only until a tested
  digest-qualified import realm exists;
- restart and source deletion still replay the complete committed Model Input;
- in-process Python is always reported as host-equivalent trust, never as
  sandbox-isolated authority;
- Plugin inventory and existing Effective Runtime views never infer each
  other's owner state;
- architecture gates reject a third current parser path and, after UPA1, the
  remaining duplicate parser; later gates similarly freeze publishers and
  mutation routes.

## Explicit Non-Goals

- making every Tool, hook, Skill, analyzer, or service a top-level Capability;
- making Product identity, Product Kernel, OEM Profile, Package, or Plugin a
  Capability Graph node;
- exposing a universal dependency-injection container or mutable Plugin
  context;
- treating trusted in-process Python facets as a security sandbox;
- cross-owner live hot replacement in v1;
- replacing Runtime Profile, Capability Graph, Registration Scope,
  Extension/Resource generation, Effective Runtime, Model Input,
  configuration, policy, or approval owners;
- allowing runtime state to write back into source manifests or Profiles;
- blocking initial convergence on a remote marketplace, signing service, Web
  client, isolated worker, or every integration protocol.

## Consequences

The architecture makes optional behavior pluggable while preserving Loushang's
strongest existing properties: typed least-authority injection, small
Capability graphs, exact registration ownership, transactional owner
publication, durable Model Input reconstruction, and explicit clock skew.

The revised design gives up the appealing but unsupported fiction of one
atomic cross-owner Plugin generation. Plugin selection/provenance is unified;
live state remains correctly owned. Broader hot reload can be added only after
it has a real visibility and irreversible-effect protocol.

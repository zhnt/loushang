# Unified Plugin Architecture

## Status

Target architecture, revised to address four rounds of independent boundary,
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
  -> owner-specific normalized Candidate Sets
  -> owner-specific Admission Records + one derived Product Runtime Plan
  -> existing Runtime Profile resolution + Product Provider closure selection
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
   Product runtime slots and variation. Each Capability owner remains the sole
   eligibility/replacement-grant and final contribution-admission authority for
   its complete Bundle. A
   Product-owned `ProductCapabilityProviderResolver` is the sole Product
   selector among owner-admitted top-level `CapabilityBundleProvider`
   candidates; the Graph Planner validates its already unique Provider set.
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
| Materialized Package Revision | Immutable/content-identified bytes shared by zero or more Plugin instances. Its cache lifecycle is `verified`, `quarantined`, or `gc_eligible`; it never enters an instance execution state. | Package cache owner |
| Resolved Plugin Package | Inert descriptor containing Plugin identity, version, digest, source authority, root, manifest, and typed locators. | None |
| Plugin Preflight Decision | Pure Product/OEM decision over manifest facts that determines whether executable declaration is allowed. | Permission to evaluate one digest-bound declaration entrypoint only |
| Plugin Definition | Host-equivalent trusted authoring entrypoint evaluated only after executable preflight. | Declaration evaluation only; never registration or activation |
| Plugin Declaration | Immutable serializable versioned tagged union of contributions, requirements, configuration schema, requested authorities, and factory/entrypoint references; never live callables. | None |
| Plugin Composition Set | Ordered reusable Plugin selections and default configuration expanded by a Product Runtime Plan or OEM Profile. It is not another Profile or Capability Bundle. | None |
| Resolved Plugin Candidate Set | Pure result containing Product-selected Plugins and owner-requested contributions after preflight/declaration; it never claims final owner admission. | Candidate input only |
| Capability Provider Candidate Fingerprint | Canonical hash of one normalized complete-Bundle candidate, its declaration/configuration/dependency/source/scope facts, and the Capability Definition it targets. | Identity only |
| Capability Provider Eligibility Grant | Capability-owner-issued data fact allowing one inert candidate envelope to proceed through Product normalization inside stated source/replacement ceilings. | Eligibility only; not final admission, Product selection, or live binding |
| Capability Provider Admission Record | Capability-owner-issued final decision over one fully normalized candidate fingerprint, effective grants, owner-policy revision, expiry, and revocation epoch. | Final complete-Bundle contribution admission only |
| Resolved Capability Provider Set | Product-owned pure selection result containing one owner-admitted `CapabilityBundleProvider` metadata value and one matching binding specification per selected top-level Capability. | Graph planning/binding input only |
| Plugin Instance Revision | One selected Plugin descriptor/configuration at a concrete Product/scope/execution realm. It owns the `ACTIVE/DRAINING/REVOKING/RETIRED` direct-host state and references, but does not own, package bytes or foreign registrations. | Provenance and direct-host lifetime only |
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
one owner-controlled aggregate through an owner-defined `capability_component`
or another typed contribution kind; that never grants them partial ownership of
the complete Capability Bundle. An aggregate `harness.resources` generation is
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
needed to decide whether evaluating its declaration is permissible. Each item
is a security envelope and one-use declaration reservation, not a second
contribution declaration. One declaration must consume exactly one matching
reservation. A second reservation for the same identity, a second declaration
consuming it, an unconsumed required reservation, or any envelope mismatch
fails closed; intended one-to-one reservation fulfillment is not diagnosed as
a duplicate declaration.

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

1. `preflight(packages, plan, overlays, policy_snapshot, decisions)` resolves
   installed/enabled/required state, immutable dependency locks, engine
   compatibility, source trust, Product/OEM Plugin and contribution allowlists,
   runtime scope, and the package-level execution approval subject/decision
   reference using only inert manifest and approval-policy facts;
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

Subjects are requests, not authority. The existing Approval owner issues a
durable, redacted `PluginApprovalDecisionRecord` for either subject. It contains
at least a unique decision ID, exact canonical subject hash, disposition,
authorizing actor/source, retained grant or policy-rule reference, approval and
source-trust policy snapshot revisions, revocation epoch, issued/expiry time,
and one-shot consumption state where applicable. The Plugin runtime does not
invent a second approval store or resolver.

`preflight` may return `pending_approval`, `denied`, or a positive decision
reference. Immediately before import/launch, the Component Host calls the
Approval owner to `consume_execution_decision(subject, decision_id)`. That
operation atomically:

- recomputes the subject over the verified revision and current scope/config;
- rechecks current source trust, policy revisions, expiry and revocation epoch;
- verifies any retained grant/rule is still live;
- marks a one-shot decision consumed; and
- returns an immutable consumption receipt used by the declaration record.

Plugin execution uses one lock order: Approval decision transaction, then
Plugin-instance lifecycle gate, then the process-wide import-realm gate when
applicable. The execution coordinator acquires only in that order; the Approval
owner exposes the decision transaction but invokes no lifecycle callback, and
no code may enter the lifecycle gate and then call Approval. Revocation follows
the same order and increments the decision/instance revocation epoch before it
can enter `REVOKING`.

Under those gates, consumption first persists an `ExecutionUseReservation`
with subject, decision, instance revision, epoch and one of
`CONSUMED_NOT_STARTED` or `STARTING`. The verified handle is handed to the
loader without an await or mutable-path reopen. In-process import crosses its
start point before releasing the gates. External launch durably records a
host-owned containment/process reservation before spawn, binds the resulting
PID/handle to it and changes it to `STARTED` before releasing the lifecycle
gate. Recovery treats `CONSUMED_NOT_STARTED` as safely unused and non-replayable;
it reconciles or terminates every `STARTING` containment before new work. Thus a
crash cannot leave an untracked child between approval consumption and PID
registration.

Revocation linearizes against consumption: a revoke committed first makes
consumption fail without import; consumption committed first permits that one
use and then enters the security-revoke rules below if authority is withdrawn.
The activation subject is consumed with the same protocol immediately before
owner bind or service launch. A positive but stale preflight decision alone can
never authorize execution.

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
| `capability_provider` | Data-only Provider metadata plus a verified factory/disposer reference that may replace one complete top-level Capability Bundle. | Capability-owner eligibility and final admission, Product selection, then Graph Binder |
| `capability_component` | Data-only owner-schema payload for one component aggregated inside an existing Capability Bundle, such as an LSP server route or architecture analyzer; it cannot replace the Bundle. | Exact Capability owner resolver and generation |
| `resource_item` | Prompt, Skill, theme, asset, method, or raw source descriptor. | Resource generation owner |
| `tool_pack` | Typed Tool pack referencing any required source items. | Owning Capability Bundle Tool facet |
| `command_pack` | Typed Command pack referencing any required source items. | Owning Capability Bundle Command facet |
| `event_definition` | Owner-qualified, versioned event contract in a namespace the Product/Capability owner granted to the contributor. | Product/Capability domain Event Definition catalog |
| `event_subscription` | Typed observer over an admitted Event Definition. | Extension/event owner |
| `interceptor` | Ordered typed interceptor/decorator/reducer/first-match contribution. | Extension/router owner |
| `agent_definition` | Typed Agent role referencing prompts, model policy, Tool/Skill selectors, memory policy, and an optional named Composition Set. | Product Agent Host |
| `presentation` | Renderer, shortcut, flag, or UI contribution. | Presentation/Extension owner |
| `external_service` | Declarative MCP, LSP-server, or other process/transport service that another admitted contribution may reference. It does not itself enter a Capability or publish Tools. | Kind-specific service host |
| `configuration_schema` | Namespaced settings, defaults, sensitivity, and refresh policy. | Product configuration runtime |

A command Markdown file may be a `resource_item` locator, but its executable
command identity exists only in one `command_pack`. The same rule applies to
Tool schemas and other file-backed declarations. A manifest reservation and
its one consuming declaration are one identity fulfillment, not two emitters.
The compiler rejects a second reservation or a declaration identity emitted by
more than one resource, Extension, or executable entrypoint path and reports
both provenance records.

Each Capability that supports aggregation publishes a versioned
`CapabilityComponentDefinition`: payload schema, component identity, compatible
Bundle contract, selection/conflict/order rules, requested facets, service
references, refresh behavior and disposer contract. Its owner resolver is the
only component admission authority and atomically publishes the admitted set in
one owner generation. LSP server routes and architecture analyzers use this
generic primitive; Plugin code never appends directly to a live Bundle
registry. A Capability that exposes no component definition remains
complete-Bundle-replacement-only.

Typed event/hook support is not hidden behind a generic `register_*` bag. A
Product/Capability domain owns an `EventDefinitionCatalog`; it may contribute
built-in definitions or admit an `event_definition` only inside a namespace
explicitly delegated to that Plugin. The catalog is the sole definition and
version authority. Subscriptions can only reference its admitted snapshot.
`EventDefinition` is owner-qualified and versioned, and states:

- payload schema/codec and compatible version range;
- `live_decision`, `live_notification`, or `durable_fact` ownership;
- process, tenant, workspace, Session, turn, or Channel routing scope;
- exactly one dispatch mode: awaited serial broadcast, awaited parallel
  broadcast, ordered interception, reduction, or first-match;
- duplicate-subscription identity and suppression rules;
- deterministic ordering, result aggregation, error containment, delegation,
  cancellation, per-listener/whole-dispatch timeout, and late-result policy.

For `durable_fact`, the definition additionally fixes a schema fingerprint,
`required` versus explicitly `ignorable` criticality, codec/upgrader identity
and compatible historical range. The committed fact retains the definition
snapshot needed for cold read. A missing/disabled Plugin or unknown codec cannot
silently change replay semantics: an unknown `required` fact fails closed with
a repair requirement; only an explicitly ignorable pure-notification fact may
remain opaque or be skipped under its persisted policy.

Dispatch combinations are closed rather than freely cross-multiplied:

| Event ownership | Legal dispatch modes | Result contract |
| --- | --- | --- |
| `live_decision` before domain commit | ordered interception, reduction, first-match | typed decision may affect the later commit |
| `live_notification` | awaited serial or awaited parallel broadcast | no domain decision; caller receives settled listener outcomes |
| `durable_fact` after domain commit | durable post-commit serial or parallel notification only | committed fact is immutable; outcome is `committed` or `committed_with_observer_errors` |

A durable interceptor/reducer/first-match declaration is invalid. A domain
transaction that commits a durable fact must atomically append its delivery
outbox, or append to a fact log from which a durable owner cursor can
deterministically reconstruct that outbox. A commit followed by a separate
best-effort journal write is forbidden.

The outbox freezes event ID, ordering key, definition snapshot/fingerprint and
the admitted subscription IDs, owner generations, handler identities and
package digests observed at commit. It provides at-least-once delivery with
idempotency key, acknowledgement, ordered retry/terminal classification and
explicit duplicate handling. Each pending delivery holds the exact owner-
generation and package-revision leases until acknowledgement or recorded
terminal disposition; it never retargets a retry to a newer handler. Listener
failure never changes the domain commit and is returned or projected separately.
A Plugin subscription never becomes the durable event authority. There is no
unspecified `broadcast` mode and no fire-and-forget callback hidden behind an
awaited contract. The existing Extension `observe` route maps initially to
awaited serial `live_notification`; interceptor, reducer, and first-match routes
remain pre-commit `live_decision`. Awaited parallel or durable notification
requires a distinct owner implementation and crash/replay conformance tests
before use.

An `agent_definition` is declarative and does not create an Agent while being
bound. The Product Agent Host admits it, resolves its referenced
Resource/Tool/Skill facts from owner snapshots, and persists its definition ID,
composition request, and model-visible material. Starting an Agent then joins
the parent Session composition or creates the explicit child Product Session
required by its Composition Set. Agent definitions cannot mutate parent
selection or introduce a side-channel Profile.

Agent fields have one authority each:

| Field family | Agent Definition may do | Final authority |
| --- | --- | --- |
| Role prompt/resource references | select admitted optional fragments | Product Kernel owns mandatory system/developer identity; Resource owner resolves bytes |
| Model, effort, budget, turn limit | request or narrow within ceilings | Product model/usage policy |
| Tool/Skill/MCP selectors and disallowed Tools | select or further restrict already admitted identities | Resource/Tool owner plus Product permission policy |
| Permission mode, Sandbox and isolation | request a stricter named mode only | Product security policy and authorized host |
| Memory | reference an admitted typed memory facet | Product Agent Host and facet owner |
| Background execution and parent-cancel behavior | request an allowed mode | Product Agent Host/multi-agent control policy |
| Composition Set | reference one named set | Product Host; a different set creates a child Product Session |
| Hooks/events | no inline hook definitions | Event/Extension contribution owners |
| Initial user prompt | not a definition field | spawn request and committed Model Input |

Unknown fields fail closed. Agent Definition policy can narrow but never widen
Product ceilings, and generic Plugin configuration cannot smuggle any of these
fields through a second path. Supporting every Claude Code Agent field, Codex
role overlay, or DeepSeek preset knob is not a v1 parity claim; unsupported
fields receive structured diagnostics.

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
split above. Its final output says which Plugins Product policy selected and
which contribution candidates they request. It never labels a contribution
`admitted`, chooses a live Provider, or resolves an owner-specific conflict.

Top-level Capability Providers have an explicit Product-owned seam that is not
a Runtime Profile slot:

```text
capability_provider declaration
  -> data-only CapabilityProviderCandidateEnvelope(metadata + factory reference)
  -> Capability owner issues CapabilityProviderEligibilityGrant over the envelope
  -> Product/OEM composition applies only grant-bounded normalization/overlays
  -> Capability owner issues final CapabilityProviderAdmissionRecord
  -> ProductCapabilityProviderResolver
  -> ResolvedCapabilityProviderSet
       - one owner-admitted CapabilityBundleProvider metadata value per selected Capability
       - one matching CapabilityProviderBindingSpec per selected Provider
       - owner admission and Product-selection records
  -> RuntimeCapabilityGraphPlanner(metadata only)
  -> Capability Component Host verifies the selected revision and resolves the
     spec into one CapabilityBundleProviderBinding
  -> RuntimeCapabilityGraphBinder(plan + matching bindings)
```

The Capability owner is the sole eligibility and final complete-Bundle
contribution-admission authority. Its first pure check validates the inert
candidate envelope, source class and replacement ceiling, then issues a
`CapabilityProviderEligibilityGrant`; Product/OEM policy cannot synthesize or
widen it. Authorized overlays may then narrow and normalize configuration,
requirements and requested authority without changing executable/transport
identity. The Capability owner evaluates that completed candidate and returns
the only final `CapabilityProviderAdmissionRecord`, including exact effective
grants. A rejected final candidate cannot participate in selection.

`ProductCapabilityProviderResolver` is pure and owns Product selection only. It
receives owner-admitted Product baseline/OEM/Plugin candidates, Product roots,
Capability Definitions, explicit selection rules, scope and Product ceilings.
Starting from roots, it deterministically selects the complete transitive
Provider closure, records every optional-dependency decision, and rejects an
unadmitted candidate, zero/multiple selections, or a missing/extra closure
member. `RuntimeCapabilityGraphPlanner` validates that already complete set and
never chooses a dependency Provider. The Product selection record retains the
exact owner admission plus Product/OEM selection-policy provenance. Neither
authority imports a factory or constructs a Provider.

`CapabilityProviderBindingSpec` holds only the selected immutable locator,
factory/disposer reference, normalized binding inputs and approval subject; the
Component Host resolves the callable only after final activation approval.
Because current `CapabilityBundleProvider` metadata has no digest field, an
adjacent `CapabilityProviderCandidateFingerprint` canonically binds at least
Capability/Provider/contribution IDs, implementation version, complete Provider
metadata and requirements, declaration IR/configuration, dependency lock,
entrypoint/factory/disposer locators, source revision/digest/trust class,
Product/scope/execution realm and Capability Definition fingerprint. The final
admission also binds owner/policy revision, expiry and revocation epoch. Owner
admission, Product selection, binding spec, activation subject, persisted Graph
provenance and resume must exact-match these facts or fail before construction.
UPA3 adds this adjacent provenance without pretending digest already exists on
the current metadata class.

`RuntimeProfileResolver` remains the sole final selector for Bundle-private
Product runtime slots and variation semantics. A top-level Capability ID such
as `coding.lsp` is never used as a Runtime Profile slot. Other owner-specific
contribution resolvers remain sole admission/conflict authorities for aggregate
resources, Tools, Commands, Event Definitions/subscriptions, Agent Definitions,
and presentation. Each returns an immutable `OwnerContributionAdmissionRecord`
containing requested/admitted/rejected identities and policy provenance.
`RuntimeCapabilityGraphPlanner` receives the already unique Provider metadata
set only after owner-admission/Product-selection fingerprint matching; it
continues to validate contracts, facets, authority, dependencies, scope, and DAG
order rather than becoming another source-policy authority.

Plugin is provenance, not a new Runtime Profile source rank. Product Composition
Set expansion happens once in a pure `ProductCompositionCompiler` while the
Product plan is constructed. Product-selected, owner-admitted Bundle-private
contributions are merged into the `defaults` of one derived
`ProductRuntimePlan`, retaining Plugin/contribution/digest provenance. They are
never supplied as an external `source="product"` layer, which the existing
resolver correctly rejects. For a single/exclusive Product slot, a second
default requires an explicit stable-ID replacement or compilation fails;
ordered slots retain declared Composition Set order.

OEM, Extension and Session contributions continue through their existing
authorized external layer/grant paths. After plan construction no component may
rewrite defaults or expand a Composition Set: the Host calls the existing
`RuntimeProfileResolver` exactly once over the derived plan and admitted
external layers. This compiler chooses no live Provider and is not a second
Profile resolver. Plugin ID, contribution ID and digest remain structured
provenance rather than altering source precedence.

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
  -> exact owners admit Bundle-private candidates used for Product plan defaults
  -> ProductCompositionCompiler builds one derived ProductRuntimePlan
  -> create one root-owned StagedResourceCompositionCandidate
  -> discover data-only Extension/Resource contributions
  -> RuntimeProfileResolver selects final Bundle-private slots
  -> attach only the final Bundle-private Profile to that Resource candidate
  -> Capability owners grant eligibility, then finally admit normalized Providers
  -> ProductCapabilityProviderResolver selects the complete Provider closure
  -> Session composition root independently holds Provider set/plan/bindings
  -> Graph Planner validates metadata and Component Hosts resolve approved bindings
  -> one Session Graph bind consumes the independent Graph inputs and transfers
     that same Resource candidate exactly once into harness.resources
  -> bind final Graph and other existing owner generations
  -> capture typed Consumers
  -> publish the usable Product Session
```

This preserves the CLA0-CLA8 bootstrap/final single-candidate handoff. The
`StagedResourceCompositionCandidate` remains only the Resource/Bundle-private
Profile binding described by its current source contract; it never carries a
`ResolvedCapabilityProviderSet`, Graph plan, Provider binding spec, Product
content, Extension object, or callback. Top-level Provider facts remain
separate data owned by the Session composition root and enter the same Graph
bind beside—not inside—the Resource candidate. No late peer Resource candidate,
construction callback, or second Graph bind is introduced. A startup failure
disposes the unpublished Session candidate and its independently owned effects;
no existing Session is retroactively changed.

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

- committed selection changes affect every subsequently created Session
  immediately; an update in `UPDATE_STAGED` or `MIGRATING` is not committed and
  new Sessions keep the old revision (or follow an explicit Product wait/fail
  policy) until atomic cutover;
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

That graceful path is not a security revocation path. Scope/config/decision/
grant/secret revocation transitions only the exact affected Plugin Instance
Revision or owner generation to `REVOKING`. A source-trust or digest compromise
quarantines the shared Materialized Package Revision and fans out revocation to
every instance referencing those bytes. The revocation record always identifies
the trigger, exact target and execution-realm blast radius; it never infers that
one workspace decision revoked unrelated instances:

- new independent acquisition and parent-derived Agent membership are blocked
  at the revocation linearization point;
- secret, action and enforceable host-facet leases are invalidated before any
  further controlled action; isolated services are cancelled/terminated by
  their owner and pending durable work is marked revoked;
- affected Sessions/Agents receive a structured security-revoke state and a
  bounded drain deadline rather than waiting indefinitely for normal exit;
- a compromised in-process Python realm is treated as ambient host compromise:
  Product Host stops admitting work, persists only safe owner-controlled facts,
  terminates/restarts the host, and never claims action-level policy can revoke
  arbitrary already imported code;
- incomplete termination remains a high-severity operational fact and cannot
  be reported as successfully disabled.

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

The same interpreter also has a process-wide import-realm gate and import-
closure ledger. Under that gate, check and reservation are one atomic operation:
every module, distribution, native extension and locked dependency identity
moves through `RESERVED -> LOADING -> LOADED` or `FAILED`. Concurrent candidates
cannot both observe an empty ledger. A same-name/different-digest or incompatible
dependency claim fails closed and requires a host restart with one compatible
set or an isolated worker.

The admitted import realm installs a host-owned meta-path/loader adapter that
maps every transitive module and native extension to the locked closure and a
`VerifiedRevisionHandle`; undeclared fallback through ordinary mutable
`sys.path` is rejected. Failed reservations remain visible until rollback under
the same gate. If the platform, packaging format or native loader cannot prove
this closure, the Plugin must use an isolated worker or a clean host restart.
Plugin-qualified entry module names alone never pretend to isolate transitive
imports through shared `sys.modules`.

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
| Capability Host | Owner-admitted and Product-selected Definition/Provider/Consumer/component inputs and factories | Bypass owner admission, Product selection, or Graph Planner/Binder |
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

### One Management Mutation Authority

`PluginManagementService` is the sole mutation authority for install,
uninstall, enable, disable, update, refresh, repair and final data deletion.
CLI, RPC, UI, SDK, ACP and JSON-RPC adapters submit the same versioned
`PluginManagementCommand`; they never call a materializer, mutate configuration,
look up optional methods with `getattr`, or trigger owner refresh directly.

Each command carries operation ID, idempotency key, expected inventory revision,
Product and installation/runtime scope, actor/policy provenance, requested
change and any approval reference. The service durably journals
`accepted/pending_approval/running/cancelling/terminal` state, structured
progress, compensation and terminal result. Retry with the same key observes
the same operation; an expected-revision mismatch fails before effects. Startup
recovers incomplete operations before accepting conflicting mutations.

The service coordinates existing package cache, Product configuration,
selection compiler and exact owner transactions; it does not become their data,
admission, publication or retirement owner. Operations spanning owners use the
documented staged/restart-required/compensation rules rather than claiming a
global rollback. `PluginManager`, `PackageOperationsRuntime` and current RPC/
configuration routes are compatibility adapters to migrate behind this service,
not permanent peer mutation paths.

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
Each contribution kind exposes its own patch schema. A generic overlay cannot
alter an immutable executable/transport field, move a policy/interceptor across
an owner-declared mandatory ordering fence, weaken `on_error`, or widen an
authority; those changes require a new declaration/owner admission and, where
applicable, approval.

An explicit user mention such as a Codex-style `plugin://...` token is a
turn-scoped request, not installation, enablement, or authority. The Product
input parser resolves it to stable Plugin/contribution IDs; the existing
Resource/Tool owner may project only contributions already admitted and pinned
by the Session. A mention that requires a new Plugin, owner generation, or
authority returns a structured unavailable/`restart_required` diagnostic. The
lazy start of an external service already admitted inside the pinned owner
generation is activation, not recomposition, and may proceed through that
owner's existing approval/launch contract. The Model Input commit records the
mention, resolution provenance, and exact injected prompt/Skill/Tool material,
so replay does not rerun current Plugin selection.

MCP is intentionally static-surface-only in v1. Every model-visible Tool name
and schema must already exist in the inert reservation/declaration and an
owner-admitted `tool_pack` before Session publication. A post-handshake
`tools/list` may validate that promised surface but cannot add or mutate Tools;
a mismatch, reconnect surface change or `tools/list_changed` yields a structured
unavailable/`restart_required` result while the previous pinned generation
remains authoritative. A future dynamic `McpSurfaceGeneration` would require a
separate accepted owner-generation design. It is not silently implied by lazy
service activation or by UPA7.

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

- a Session acquires one `SessionPluginMembershipLease` over its complete
  selected revision closure while those revisions are `ACTIVE`;
- a live Agent derives an `AgentPluginMembershipLease` from that still-open
  parent lease at creation; derivation is not `acquire_current()` and may retain
  the parent's already pinned revisions during graceful `DRAINING`;
- a subagent inherits the same selection by default;
- an admitted `agent_definition` requesting a different Composition Set must
  create an explicit child Product Session/Graph through the Product Host;
- a child cannot mutate its parent's selection;
- derivation across multiple revisions commits under the parent membership gate
  or rolls every increment back; a closing/security-revoked parent rejects it;
- parent close blocks new derivation and either cascades cancellation/close to
  children or waits for explicitly background-authorized children according to
  Product multi-agent policy before releasing the membership family;
- cold resume uses persisted Profile/selection/digest facts and fails with a
  repair diagnostic when a locked revision is unavailable.

This is less dynamic than per-Agent service-context recomposition and is
recorded as an intentional v1 gap.

Plugin Instance Revisions alone use the execution-state machine:

```text
ACTIVE --graceful--> DRAINING --> RETIRED
ACTIVE --security--> REVOKING --> RETIRED
DRAINING --security--> REVOKING
```

- `acquire_current()` reads the current revision and increments its lease count
  under the same runtime gate;
- `DRAINING` rejects new independent `acquire_current()` calls, causing callers
  to retry the replacement or return `restart_required`; it still permits the
  parent-membership derivation above for the composition already pinned by an
  open Session;
- `REVOKING` rejects independent and derived acquisition and follows the
  bounded security-revoke path;
- Session/Agent membership holds instance leases and the corresponding shared
  package-revision leases; turns, Tool tasks, and external-service calls hold
  their applicable owner/facet leases;
- every owner generation, disposer, external-service shutdown record, and
  retryable cleanup task that may reopen package bytes or entrypoints holds its
  own package-revision lease until cleanup reaches a terminal result;
- release is idempotent and cancellation-safe;
- shutdown blocks new acquisition, waits for held leases, and keeps failed
  cleanup visible/retryable;
- transition of an instance to `RETIRED` occurs only after its acquisition,
  Session/Agent, direct-host and owner-generation counts reach zero. This does
  not itself reclaim shared package bytes.

A Materialized Package Revision has a separate cache lifecycle. Successful
verification publishes immutable `verified` bytes. A source/digest compromise
changes them to `quarantined` and prevents new executable handles; it does not
pretend the bytes are an instance in `REVOKING`. Either state becomes
`gc_eligible` only after every instance, owner/cleanup task, configured cold-
resume record, dependency lock and forensic-retention reference reaches zero.
Package GC runs only after the startup recovery barrier below and rechecks the
same reference inventory under its cache gate.

Retryable cleanup is durable, not an in-memory promise. The package lifecycle
owner maintains a `PluginCleanupJournal` that records owner/generation, package
revision, cleanup and idempotency keys, attempt number, step/compensation state,
redacted result, backoff and terminal disposition. Retirement uses a write-
ahead lease handoff: journal intent, idempotency key and the journal-owned
package lease must durably commit before the previous owner lease can release.
If that commit fails, the previous lease remains held and retirement reports a
retryable failure.

Startup completes journal recovery and reconstructs journal-owned leases before
enabling any package GC; unknown/incomplete attempts are pinned. Disposers and
compensations must be idempotent under their recorded key or expose a journaled
prepare/commit protocol. Only terminal success or an explicit, durably recorded
safe-abandon/repair decision may release the journal lease. `terminal_failure`
quarantines the package revision and external effect until repair or
acknowledgement; a crash cannot silently discard the lease or repeat an
untracked compensation.

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

Materialization has a concrete no-TOCTOU use seam. The package cache writes a
temporary quarantine tree, verifies the complete digest/lock and containment,
then atomically publishes it under a content-addressed, host-owned immutable
revision root. A `VerifiedRevisionHandle`, not a mutable pathname, owns a stable
root/file identity and exposes no-follow relative opens. Component Hosts import,
read or launch the same opened identity they just verified; they do not close
it and reopen a user-controlled source path. The platform adapter must use
dirfd/handle-relative no-follow primitives or an equivalently proven immutable
snapshot, verify identity/digest after open, and keep the handle leased through
use. A platform that cannot prove this rejects executable Plugins rather than
claiming path containment is sufficient.

Security contracts include:

- immutable/content-addressed executable revisions and bind-time digest checks;
- containment and no mutable-path re-open after validation;
- execution and activation approvals bound to hash, dependency lock,
  security-relevant configuration, source/trust, scope, requested ceiling, and
  final effective authority as applicable;
- source policy before materialization, atomically at execution-decision
  consumption before import, and again before activation;
- locked dependency closure and no transitive registry trust;
- execution-time revalidation for policy/approval-controlled actions;
- structural redaction for diagnostics and projections;
- secret-reference identity/provider/rotation epoch in binding fingerprints,
  while secret material never enters plans, logs, fingerprints, or errors;
- revocable secret leases and an explicit live-rotation versus
  `restart_required` policy per field.

Plugins that need persistent private state receive a Product-authorized
`PluginDataFacet`, not a raw home-directory path. Storage is identified by
Plugin ID, runtime/installation scope, and an explicit data-generation/schema
identity; each Plugin revision/owner generation is bound to one data generation
for its lifetime. The facet defines quota, read/write mode, backup/export,
migration and cleanup policy.

A schema-compatible update may share a generation only under an explicit
backward/forward read-write compatibility declaration. An incompatible update
enters `UPDATE_STAGED`, then `MIGRATING`, without changing the current Plugin-
selection or data-generation pointers. A durable migration fence first blocks
new writer leases and waits for every old writer to quiesce. Only then may it
take the final consistent backup/snapshot, build and validate the staging
generation. There is no snapshot-before-quiescence window.

Selection cutover, data-generation pointer flip and new-writer admission share
one Product/data-owner gate and compare-and-swap decision. Before it commits,
new Sessions continue to pin the old revision or receive the configured wait/
unavailable result; they never pair the new revision with old-schema data. Old
owner/disposer cleanup may retain a read-only old generation after cutover but
cannot write it. Zero-downtime change-log replay or dual-write/merge is a
separate accepted protocol, not an implicit v1 behavior. Migration failure
removes the fence and leaves both old pointers/data untouched; post-cutover
rollback requires a declared reverse migration or backup restore and cannot
reopen the old generation for writes.

Disable preserves data by default. Final uninstall deletes a data generation
only through a separately confirmed operation after installation, revision,
owner, cleanup and backup-retention leases are gone.

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
  -> CapabilityProviderCandidateEnvelope for coding.lsp
  -> coding.lsp owner grants complete-Bundle eligibility
  -> Product-normalized candidate receives final coding.lsp owner admission
  -> ProductCapabilityProviderResolver selects one metadata/binding spec pair
  -> requirement on harness.workspace(read, process.launch)
  -> Capability Component Host resolves the approved factory reference
  -> one selected Provider factory receives typed facets
  -> Graph Binder mounts one coding.lsp Bundle
  -> Bundle exposes semantic runtime + tools + diagnostics
```

Tools are part of the selected Bundle and become visible with the runtime they
call. They are not registered earlier against a deferred LSP object.

An additional language server does not replace that Bundle. It declares an
owner-schema `capability_component` referencing an admitted `external_service`;
the `coding.lsp` component resolver validates language/extension routes,
conflicts, facets and disposer, then publishes the complete server set in one
`coding.lsp` owner generation. Architecture analyzer Plugins use the analogous
`coding.arch` component definition. Neither path gives a Plugin a live Bundle
registry or a second Graph bind.

## Single-Authority Matrix

| Concern | Sole authority | Forbidden peer path |
| --- | --- | --- |
| `plugin.json` parsing | `PluginManifestParser` | Package catalog or Component Host reparsing |
| Source bytes/path authority | immutable `ResolvedPluginPackage` locators | Raw mutable path joining in consumers |
| Plugin executable preflight and candidate selection | Product Runtime Plan/OEM Profile plus two-phase `PluginSelectionResolver` | Import-before-preflight or self-enable in Plugin code |
| Complete-Bundle Provider eligibility | Exact Capability owner grant | Product/OEM selecting an ungranted replacement |
| Complete-Bundle Provider final admission | Exact Capability owner and `CapabilityProviderAdmissionRecord` | Product policy calculating effective grants |
| Top-level Capability Provider selection | Product-owned `ProductCapabilityProviderResolver` among owner-admitted candidates | Runtime Profile slot or Plugin code choosing a live Provider |
| Capability-internal component admission/publication | Exact Capability component resolver/generation | Plugin appending a server/analyzer to a live Bundle |
| Bundle-private slot/variation selection | `RuntimeProfileResolver` and owner variation policy | Top-level Capability ID masquerading as a slot |
| Product Composition Set compilation | `ProductCompositionCompiler` creates one derived `ProductRuntimePlan` | External Product layer or downstream defaults rewriter |
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
| Plugin management mutation | `PluginManagementService` with typed durable commands | CLI/RPC/UI/SDK direct materializer, config, or refresh mutation |
| Retirement | each exact owner; Plugin aggregates handles/results only | Plugin directly disposing foreign scopes |

Multiple source adapters and typed Component Hosts are allowed. There is still
one normalized descriptor, one declaration identity, one preflight owner, one
final admission authority per contribution kind, one binding owner per live
object, and one effective projection path.

## Current Gap And Reference Trade-Offs

| Area | Current Loushang position | Remaining gap or deliberate difference |
| --- | --- | --- |
| Typed Capability composition | Strong Planner/Binder/Runtime/Projector and exact registration ownership | Add owner eligibility/final admission, Product closure selection and owner-defined internal components; mount `coding.lsp` and `coding.arch` without Profile slots |
| Package resolution | One manifest descriptor/parser and `PluginResolutionAuthority`; runtime sources publish verified revisions before atomic durable binding, while CLI/Catalog inventory inspection remains read-only | Locked dependency closure, executable-host consumption and retirement of registry-only compatibility APIs |
| Plugin lifecycle | Enablement projects one `PackageResourceMount`; Resource discovery leases and revalidates verified revisions while owner lifecycles remain separate | Unified selection/provenance and retirement aggregation without replacing owners |
| Declarations | Manifest and executable Extension registrations converge late | Versioned mutually exclusive IR and compatibility capture adapter |
| Profiles/composition | Product/OEM Runtime Profiles already exist | Composition Sets compile once into a derived Product plan or existing authorized external layers, never a peer Profile |
| Events/hooks | Extension routing exists | Owner-qualified catalog, transactional outbox/cold-read schema policy, explicit dispatch modes and public SDK |
| Agent definitions | Agent runtime/session composition exists | First-class `agent_definition` contribution and Product Agent Host admission/persistence |
| Scoping | Six runtime scopes exist | Agent membership inheritance, child-Session Composition Sets, and cold-resume locks |
| Refresh/HMR | Owner transactions and restart-required boundaries are strong | No universal dependency-triggered Plugin reload; cross-owner live HMR is intentionally deferred |
| Fine-grained policy | Product/Extension admission and Approval owners exist | Contribution-kind patch schemas, consumable/revocable decision records and security revoke |
| Private Plugin state | No unified Plugin data contract | Versioned data generations, writer quiescence, migration/rollback, quota and final deletion semantics |
| Operations | Package/plugin commands and diagnostics exist through several mutation paths | One durable typed `PluginManagementService` plus inventory that references, but never infers, owner effectiveness |
| Ecosystem surfaces | Coding-centric integrations | Stable SDK, external host and protocol adapters later; MCP v1 exposes only statically declared/admitted Tools, with dynamic surface generations deferred |
| Model-visible persistence | Complete committed Model Input is a Loushang strength | Preserve inline facts; add Plugin provenance only |

The largest immediate implementation gap is the missing single flow from
package revision through declaration and existing Runtime Profile/owner plans.
That does not erase separate gaps in typed events, Agent composition, dynamic
dependency-driven reload, private state, management UX, dynamic MCP surfaces,
or ecosystem adapters.

The current UPA1 convergence seam is `PluginResolutionAuthority`. Its
`inspect` operation parses and projects inventory without publishing, binding,
or writing a lockfile. Its runtime operation accepts only successful
inspections, publishes content-addressed revisions, verifies handle/digest and
source lineage, then atomically binds the full batch. Startup roots, Package
Catalog projection, Package manifest compatibility projection, and CLI Plugin
listing use this seam. `PluginManager.add_plugin_source()` remains only as a
registry-only compatibility adapter; it is not a production runtime admission
path.

## Delivery Sequence

Every slice preserves the CLA authority inventory and adds a regression before
implementation.

### UPA0: Baseline And Authority Freeze

- freeze current `plugin.json` readers, Runtime Profile selection sites, Graph
  Binder/Projector definitions, exact Registration owner paths, Extension and
  Resource publishers, Model Input commit sites, and LSP/Arch construction;
- preserve CLA AUTH-01–AUTH-15, ENTRY-01–ENTRY-05, the one root-owned Resource
  candidate, final Profile attachment, and one-time Graph transfer;
- classify existing document/source tripwires as baseline inventories, not
  proof of semantic runtime exclusivity;
- freeze qualified code units rather than filenames and cover module-scope,
  directory-escape, receiver/container alias, `setattr`, container-write,
  `open/json.load`, import-alias, split-helper and reflected/saved live-binding
  variants with negative fixtures;
- require UPA1-UPA3 behavioral fail-closed tests at canonical parser/publisher/
  frozen-adapter APIs before claiming route exclusivity. Static syntax scans
  remain defense-in-depth and never the acceptance proof by themselves.

### UPA1: Immutable Resolve Once

- introduce the canonical manifest parser and `ResolvedPluginPackage`;
- make Package/Resource projection consume that descriptor;
- require executable digests, immutable materialization, dependency lock,
  `VerifiedRevisionHandle` no-follow use, revalidation, and broken-package
  inventory;
- keep registry-backed dependencies disabled until complete locks exist;
- migrate built-in, local, and materialized sources through the same result.

### UPA2: Inert Preflight, Versioned Declaration, And Candidate Selection

- implement the inert contribution index and the preflight/finalize operations
  of `PluginSelectionResolver`, including one-use reservation fulfillment;
  prove denied/disabled code is never imported;
- add both approval-subject schemas, the serializable tagged declaration IR,
  consumable/revocable decision records, internal `PluginDefinition`,
  Composition Sets, contribution-kind selectors/patch schemas, policy ceilings,
  and security fingerprints;
- compile Product contributions into one derived `ProductRuntimePlan`, preserve
  existing external-layer admission and call `RuntimeProfileResolver` once;
- define the Event ownership/dispatch matrix, transactional outbox/cold-read
  contract and Agent field-authority matrix plus the fail-closed Extension
  capture adapter;
- add schema/engine/feature negotiation fixtures before public SDK exposure.

### UPA3: Owner-Preserving Bind, Lease, And Inventory

- bind through the existing CLA single Resource candidate while Session
  composition separately owns top-level Provider set/plan/binding inputs;
- add Capability-owner eligibility/final-admission records,
  `ProductCapabilityProviderResolver`, full candidate fingerprints, deterministic
  Provider closure and matching binding specs;
- add owner-defined `capability_component` generations for internal aggregation;
- separate Plugin Instance execution state from Materialized Package cache state;
  add exact-owner retirement, parent-derived Agent membership, write-ahead
  cleanup handoff, import-realm reservations and security revoke;
- add package/selection inventory references without another effective
  projector or clock;
- prove refresh/shutdown/acquire races and `restart_required` for multi-owner
  changes.

### UPA4: LSP Vertical Slice

- package the default LSP implementation as a first-party Plugin;
- grant eligibility/final admission through the `coding.lsp` Capability owner,
  select through `ProductCapabilityProviderResolver`, and mount through the
  Session Graph;
  Runtime Profile remains Bundle-private;
- aggregate additional server components only through the `coding.lsp` owner;
- remove deferred LSP/process/Tool pre-binding paths;
- prove alternate Provider selection, startup rollback, restart reconstruction,
  complete Model Input facts, and owner-correct disposal.

### UPA5: Architecture Vertical Slice

- package the default architecture implementation as a first-party Plugin;
- mount `coding.arch`, initially independent of LSP;
- add the optional typed LSP requirement only after contract evidence;
- bind analyzers, facts, diagnostics, and Tools in one owner Bundle generation;
- aggregate optional analyzers through the `coding.arch` owner and exercise
  versioned Plugin data generations, migration fencing/atomic cutover,
  rollback and quota contracts for indexes.

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
  transport facets; MCP Tools remain statically reserved, declared and admitted
  in v1, with dynamic surface generations explicitly deferred;
- add OEM compatibility, contribution-policy, trust, upgrade, and data-migration
  tests.

### UPA8: Management And Isolation Closure

- implement the durable typed `PluginManagementService` and route install,
  remove, enable, disable, update, refresh, repair, list, explain and diff from
  CLI/RPC/UI/SDK through it;
- complete isolated worker evaluation before admitting untrusted executable
  code;
- define retained-version and private-data garbage collection;
- remove superseded Plugin, Package, and Extension compatibility adapters.

## Acceptance Gates

The architecture is complete only when these statements are executable:

- `plugin.json` is parsed once and Package/Plugin consumers share identical
  immutable locator/containment semantics;
- disabled, denied, incompatible, or unapproved executable packages are never
  imported, and every executed declaration has a persisted positive preflight
  plus an atomically consumed, current approval decision receipt;
- execution and activation approvals are bound to digest, dependency lock,
  source/trust, scope, security configuration and effective grants; revocation
  racing consumption has a tested linearization result, lock order is acyclic,
  and crash recovery reconciles every `STARTING` external process reservation;
- built-in and external Plugins produce the same descriptor/declaration shapes;
- two Product Runtime Plan/OEM Profile combinations select different Plugins;
  Product contributions compile once into derived plan defaults, external
  Product layers fail, and `RuntimeProfileResolver` is invoked once;
- contribution kinds are mutually exclusive, each executable declaration
  consumes exactly one manifest reservation, and a true duplicate command/
  tool/event identity fails with both provenance records;
- an `agent_definition` has one Product Agent Host admission/binding path and a
  different Composition Set creates a child Product Session rather than
  mutating its parent;
- every Event Definition has one owner/version and every dispatch has an
  explicit legal ownership/mode combination, ordering, timeout, failure, commit
  and aggregation contract; durable facts atomically create/reconstruct an
  outbox, pin exact subscriber revisions and fail closed on unknown required
  cold-read semantics;
- an alternate `coding.lsp` Provider is selected without changing Session, CLI,
  or Tool implementation code, only after `coding.lsp` owner eligibility and
  final admission over a full candidate fingerprint; Product selection emits a
  deterministic closed Provider set and no `coding.lsp` Profile slot exists;
- additional LSP servers and architecture analyzers aggregate only through
  owner-defined `capability_component` generations, never live registries;
- top-level Provider plans/bindings remain separate Session composition inputs;
  the CLA Resource candidate contains only Resource/Bundle-private Profile state;
- a failed/cancelled unpublished Session candidate leaks no owner registration;
- multi-owner live changes return `restart_required` rather than exposing mixed
  or retroactively restored generations;
- committed disable affects new Sessions immediately; a staged migration keeps
  old selection/data pointers until atomic cutover. A permitted single-owner
  active change recomposes that owner once, while an active multi-owner change
  performs no partial recompose and returns `restart_required`;
- an Agent can derive its open parent Session membership during graceful
  `DRAINING`, cannot derive during `REVOKING`, and multi-revision failure rolls
  back atomically; security revoke has a bounded host/service termination path;
- instance-state acquisition cannot race transitions; package cache state is
  separate, cleanup lease handoff is write-ahead and startup recovery blocks GC
  until Session, owner, cleanup, cold-resume and lock references are restored;
- incompatible private-data migration never races an old writer and failed
  migration leaves both old pointers intact; selection/data cutover and new-
  writer admission share one CAS gate;
- in-process imports atomically reserve their locked closure and a host loader
  rejects undeclared transitive imports; incompatible/native cases restart or
  use an isolated worker;
- every Plugin management adapter submits one typed durable command to
  `PluginManagementService`; no adapter mutates config/materialization/refresh;
- MCP v1 exposes only statically reserved/declared/admitted Tools and a dynamic
  handshake or reconnect cannot mutate a published Tool generation;
- restart and source deletion still replay the complete committed Model Input;
- in-process Python is always reported as host-equivalent trust, never as
  sandbox-isolated authority;
- Plugin inventory and existing Effective Runtime views never infer each
  other's owner state;
- after UPA1 all public Package/Plugin entrypoints behaviorally invoke the one
  canonical parser over the same verified descriptor; after UPA2/UPA3 frozen
  Plugin adapters and owner APIs behaviorally reject post-publication mutation
  and non-Binder Graph publication. Qualified AST inventories and bypass
  fixtures supplement these runtime proofs.

## Explicit Non-Goals

- making every Tool, hook, Skill, analyzer, or service a top-level Capability;
- making Product identity, Product Kernel, OEM Profile, Package, or Plugin a
  Capability Graph node;
- exposing a universal dependency-injection container or mutable Plugin
  context;
- treating trusted in-process Python facets as a security sandbox;
- cross-owner live hot replacement in v1;
- dynamically discovered or `tools/list_changed` MCP Tool surfaces in v1;
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

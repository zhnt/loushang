# Runtime Profile Resolution And Binding

## Status

Implemented and first adopted by Coding. `loushang.harness.runtime.profile`
provides the product-neutral profile contract, resolver, snapshot, registry,
and binding lifecycle. The optional
`loushang.harness.transcript.runtime_profile` composes those primitives
with existing transcript/store/compaction owners. `loushang.coding.product_plan`
now only declares Coding's current selections.

## Purpose And Requirement Traceability

This component turns an explicitly declared Product runtime plan into a
deterministic, inspectable, session-scoped set of live bindings. It satisfies
the common mechanics in PDRI-001 through PDRI-012, with capability-specific
policy remaining in each Product and its later component document.
PDRI-013 through PDRI-015 are implemented by the adjacent top-level Capability
graph Planner, Binder, Runtime, and Projector under
`loushang.harness.capabilities`; they are intentionally not folded into the
finer-grained `loushang.harness.runtime.profile` resolver.

Harness owns resolution, strict data validation, lifecycle sequencing, stale
lease invalidation, and diagnostics. A Product owns its slots, baseline
selections, configuration defaults, source authorization, and policy that
accepts or rejects OEM and extension declarations. Harness never discovers a
plugin, grants authority, or infers a Product default here.

This is not a dependency-injection container or a global service locator. An
implementation can only be retrieved through the exact slot/key/version
selection in a resolved profile and the explicit `RuntimeProfileBinding`
returned by its binder.

The Runtime Profile and top-level Capability graph are related but distinct.
The profile resolves fine-grained Binding Facets and exact provider factories.
The Capability Plan DAG uses coarse owner-qualified Capability IDs, and the live
graph records Mounted Capability instances. The canonical distinction and
arrow convention are defined by
[Capability Dependency And Mount Lifecycle](../../capability-dependency-and-mount-lifecycle.md).

## Internal Module Ownership

`loushang.harness.runtime.profile` is the stable public facade. Its private
implementation modules have one-way responsibilities:

- `_profile_types` owns declarations, diagnostics, resolved values, and the
  current snapshot codec;
- `_profile_admission` owns Product grants, admission results, and admission
  policy;
- `_profile_resolution` owns deterministic source/selection ordering and pure
  plan-to-profile resolution;
- `_profile_binding` owns factory/disposer types, registries, live creation,
  rebind, rollback, leases, and disposal;
- `_profile_standard` owns standard capability slots.

Admission, resolution, binding, and standard slots may depend on profile types.
Binding and resolution do not depend on each other, and types do not import the
higher-level policy or lifecycle modules. Snapshot remains with profile types
until it develops an independently versioned evolution path.

## Data Model

`ProductRuntimePlan` contains a Product identifier, declared
`RuntimeCapabilitySlot` values, and Product baseline
`RuntimeCapabilitySelection` values. Each slot declares:

- its stable string key;
- `single`, `exclusive`, `ordered`, or `append_only` shape;
- process, tenant, workspace, session, turn, or channel scope;
- a `sealed` or `turn` refresh boundary; and
- the allowed sources (`product`, `oem`, `extension`, `session`).

Every selection is pure data: slot, implementation key, positive
implementation version, integer priority, and strict JSON-object
configuration. It never contains a callable, a connection, a credential, a
provider instance, or a Product object.

A `RuntimeCapabilitySlot` is not automatically a top-level Capability graph
node. Slots such as `prompt.sections`, `tool.packs`,
`interaction.side_question`, and `context.compaction` are currently useful
owner-private Binding Facets. Their resolved selections and snapshots remain
authoritative for factory binding while `harness.resources` or
`harness.session` projects the aggregate top-level Capability state.
That future aggregate Mount does not force all of its internal facets into one
scope or refresh generation: it may hold explicit leases or stable references
to broader-lived facets, while focused profile generations remain
authoritative for internal refresh.

The first shared vocabulary is deliberately limited to these neutral slot
identifiers:

| Slot | Shape | Variation semantic | Refresh | Intended contract owner |
| --- | --- | --- | --- | --- |
| `conversation.store` | single | Exclusive Replacement | sealed | `harness.storage` |
| `agent.transcript_profile` | single | Exclusive Replacement | sealed | `harness.transcript` |
| `context.compaction` | single | Exclusive Replacement | turn | `harness.context` |

The vocabulary does not import or prescribe an implementation. A Product can
bind a memory, file, database, or OEM store factory only when its plan and
policy allow it. Database, Redis, and index providers remain non-authoritative
until their own storage contracts are accepted (PDRI-006, PDRI-007).

## Resolution And Authority

`RuntimeProfileResolver` receives a Product plan plus layers that the Product
has already authorized. It applies a fixed source order:

```text
product -> oem -> extension -> session
```

Within a source, layers sort by integer priority and then `layer_id`; selections
sort by priority, implementation key, version, and canonical JSON
configuration. The resolver never uses discovery order or factory side
effects.

- A `single` or `exclusive` slot retains only the final authorized selection
  under the declared source/layer/selection precedence. When its variation
  semantic is Exclusive Replacement, that selected implementation is the only
  active provider.
- An `ordered` slot replaces an earlier selection with the same
  `(implementation, version)` identity while retaining a deterministic
  sequence for distinct identities.
- An `append_only` slot retains every authorized selection, including repeated
  identities, in deterministic order.
- An undeclared slot, forbidden source, duplicate source/layer identity, or
  ambiguous single selection fails with `RuntimeProfileDiagnostic` values.
- Missing required slots and failed bindings fail rather than falling back
  implicitly.

`RuntimeCapabilitySlot.variation_semantic` separately declares
`aggregate_contribution`, `ordered_interception`, or `exclusive_replacement`.
Non-Product or multi-value surfaces must provide it, and the slot constructor
rejects shape/semantic combinations that cannot be executed by the generic
resolver and binder.

The resolver accepts `RuntimeProfileLayer` data; it does not decide whether a
particular extension is trusted. Extension manifests, permissions, dependency
checks, OEM trust, and Product policy must complete before a layer is passed
to the resolver (PDRI-003, PDRI-009).

The resolver also does not turn Product, OEM, Package, Plugin, or Extension
identities into graph nodes. Candidate acceptance, rejection, deterministic
loss, and selection belong in a structured resolution trace. Only the final
Capability dependencies enter the plan DAG, and only successfully bound
Capability instances enter the live Mount Graph.

## Snapshot And Resume

`ResolvedRuntimeProfile.snapshot()` produces `RuntimeProfileSnapshot` schema
version 1. The JSON form records the Product, slot shape/scope/refresh boundary,
variation semantic, selected implementation key/version/configuration, and
source-layer provenance. The variation field is an additive schema-v1 field:
legacy snapshots without it remain readable and Product resume validation
normalizes them against the current declared slot contract.
`RuntimeProfileSnapshot.from_json()` validates that the payload is strict JSON
and rejects boolean or malformed version values.

The snapshot is evidence of what a current Loushang session used; it is not a
factory registry and is not an implicit compatibility importer. Native load
continues to accept the current Loushang format only. Pi, Claude Code, Codex,
or historical Loushang formats require explicit external or native migration
paths rather than permissive profile fallback (PDRI-008).

## Binding Lifecycle

`RuntimeCapabilityRegistry` registers exact `(slot, implementation, version)`
factories. `RuntimeProfileBinder` creates an entire profile in declared slot
order, disposes already-created values in reverse order when a later factory
fails, and exposes values only through `RuntimeProfileBinding`.

For a turn-safe rebind, the binder creates every replacement before disposing
the previous values. A creation failure leaves the previous binding current.
After a successful swap, `RuntimeBindingState` invalidates prior leases, so a
stale callback cannot access a new session binding accidentally.

`sealed` slots, including the initial store and transcript slots, cannot be
rebound during a session. `exclusive` slots are always sealed. `turn` slots
may only rebind through the explicit turn-boundary operation. If a disposer
itself fails after replacement creation, the binder reports the error and
does not publish the new profile; a capability-specific factory must make its
own disposer idempotent because a partially disposed external resource cannot
be made transactionally atomic by this generic layer (PDRI-005, PDRI-006,
PDRI-010).

Declared scope describes ownership and future pooling boundaries. This first
implementation binds an explicit resolved profile and intentionally does not
add a process-global cache or automatic cross-tenant reuse.

## Accepted Mount-Graph Finalization Target

The current binder creates an explicit profile in full and its `rebind`
operation supports only declared turn-safe changes. It must not be described as
the future Mount-graph finalizer: sealed-slot protection is correct after
publication, while construction finalization occurs before the Session graph
is published or sealed.

The accepted target adds separate owners above the focused profile machinery:

| Owner | Target responsibility |
| --- | --- |
| graph planner | pure Capability dependency closure, topology, phase/scope validation, and diagnostics |
| graph binder | bootstrap-closure bind, binding-signature reconciliation, delta creation, rollback, and reverse disposal |
| graph runtime | live Mounted Capability generations and leases |
| graph projector | redacted snapshots, explanations, dependencies, dependents, and impact paths |

Bootstrap binds only the transitive closure required for data-only discovery.
After Extension declarations are admitted and internal facets resolve, final
construction reuses every unchanged binding signature and creates only new or
changed nodes. It publishes and seals the final graph atomically. An unchanged
Capability must not bind twice merely because discovery occurs between
bootstrap and Session construction.

The Runtime Profile snapshot is necessary selection evidence but is not by
itself a complete reusable-node signature. The graph binder must also include
compatible contract versions, selected factory identity/version, dependency
requirements, relevant provenance, and an owner-supplied deterministic
fingerprint of binding-context inputs such as persistence mode, Session path,
workspace identity, and referenced-runtime generation. If those inputs cannot
be completely fingerprinted, the target binder must construct a new node.

Failure or cancellation before atomic publication preserves the previous
generation and reverse-disposes the newly created delta. Once abort cleanup
begins, another cancellation request cannot skip owned cleanup.

Selection diagnostics, graph-plan diagnostics, and binding lifecycle facts are
separate projections. A global mutable DAG manager or a graph-wide arbitrary
object lookup remains prohibited.

## Coding Adoption

`loushang.harness.transcript.AgentTranscriptProfileRuntime` is the
reusable optional Agent-profile adapter. A Product supplies stable identities
and defaults through `AgentTranscriptRuntimeSpec`; the shared runtime declares
the `ProductRuntimePlan` and registers exact factories for:

1. the Product's file or memory conversation store identity, selected by the
   caller's existing `persist` decision;
2. the Product's current Agent transcript profile identity; and
3. `agent_transcript.turn_aware_summary/v1`, the existing Harness-owned
   transcript compaction mechanism.

`loushang.coding.product_plan` instantiates that adapter with the established
Coding identities and declares its standard capability-composition plan.
`SessionManager` creates, loads, and forks the resulting bindings. New session
headers persist the pure JSON `runtimeProfile` snapshot. Persistent resume
validates the snapshot and rejects an unsupported profile instead of silently
choosing a different durable-store or transcript schema. A non-persistent open
may use a memory runtime binding while preserving the source file's durable
snapshot. `AgentSession` supplies the selected Harness capability and Coding
executor to its Product controller, and disposes the binding with the session.

This adoption does not move `coding.settings_manager`, `coding.bootstrap`,
extension discovery, model registry, auth resolution, Coding file naming, or
compaction prompts into Harness. Coding admits trusted OEM selection of
registered compaction mechanisms; extension hooks remain Product adapters and
cannot register arbitrary planners or transcript writers.

No channel is involved in resolution. TUI, Web, RPC, and future channel
adapters consume the same resolved profile or its diagnostics and may bind
channel-local presentation slots only in their own component design
(PDRI-012).

## Contract Tests

`tests/harness/runtime/test_profile.py` covers deterministic precedence,
source rejection diagnostics, ordered versus append-only semantics, strict
snapshot round-trip, turn-boundary rebind lease invalidation, sealed store
rejection, and factory rollback. Existing runtime binding tests retain the
generation-lease contract. Neutral Harness core has no imports from Coding,
Agent, AI, extensions, or concrete store implementations.

`tests/harness/transcript/test_runtime_profile.py` binds a fake Research
Product through the optional Agent/AI-aware profile, validates its snapshot,
and proves that cross-Product resume is rejected. This optional integration
package may depend on stable Agent/AI value and codec contracts; it does not
own providers, credentials, model preference, or Product policy.

`tests/coding/test_runtime_profile.py` verifies the first Product adoption:
new memory/file sessions select the correct factory, headers retain the
snapshot, persistent resume validates it, transient open does not rewrite the
durable file choice, and `AgentSession` consumes then disposes the selected
compaction behavior.

`tests/coding/test_capability_profile.py` verifies the first real external
replacement path: an Agent Extension registers a side-question Provider
factory, Coding derives an explicit grant from its effective policy, the
runtime profile selects one deterministic winner, only that factory binds, and
Session shutdown cancels the active Provider before disposing the factory.

The PDRI-013 through PDRI-015 graph evidence now lives in
`tests/harness/capabilities/test_graph_planning.py`,
`test_graph_binding.py`, and `test_graph_projection.py`, with owner and import
gates under `tests/architecture/`. The separate `stable_reference` refresh
binding still fails closed and is not implied by the implemented direct-
dependency Mount runtime.

## Non-Goals

- No plugin discovery, trust evaluation, permission granting, or OEM loader.
- No dynamic migration or hot swap of durable stores/transcript schemas.
- No universal memory, compaction prompt, artifact, model, auth, or
  presentation policy.
- No persistence of callables, live clients, credentials, or provider state.

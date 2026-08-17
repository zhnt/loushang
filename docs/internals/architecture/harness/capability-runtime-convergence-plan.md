# Capability Runtime Convergence Plan

## Status

Completed delivery record. PR0 through PR9 were integrated by PR `#451`; this
document retains their reviewed dependency order, compatibility decisions, and
acceptance gates. Current source, the generated
[Harness Capability Catalog](capability-catalog.md), and implemented boundary
documents are authoritative for present behavior.

PR0 is tracked by issue `#450`. Its executable pre-change inventory is
[Capability Runtime Convergence PR0 Baseline](capability-runtime-convergence-pr0-baseline.md).

The plan refines, rather than replaces, the accepted decisions in:

- [Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md);
- [Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md);
- [Product Capability Composition Core](product-capability-composition-core.md);
- [Runtime Data Foundations](runtime-data-foundations.md); and
- [Store And Event Protocol Migration](store-event-protocol-migration.md).

## Objective

Converge the Harness plugin and capability substrate around four enforceable
rules:

1. every live registration has an explicit owner and an exact disposer;
2. every replaceable Capability has separate Definition, Provider, and
   Consumer roles;
3. every bound Product runtime can project its final effective profile and
   live Capability assembly graph; and
4. every value visible to a model is projected from committed facts and can be
   reconstructed within the owning Session's declared storage guarantees.

These rules form one lifecycle rather than four independent features:

```text
committed declarations and source facts
  -> deterministic profile resolution
  -> Definition-compatible Provider binding
  -> owner-scoped registrations
  -> atomic Mount Graph publication
  -> composed effective-runtime view
  -> committed model-input snapshot
  -> model request
  -> durable response/tool-result facts
  -> replay and reconstruction
```

The convergence must reuse the current Runtime Profile resolver, profile
binder, transcript repository, resource provenance, and projection contracts.
It must not introduce a second Agent loop, a global service locator, or a
parallel plugin microkernel.

This plan is an implementation plan for the already accepted
`RuntimeCapabilityGraphPlanner`, `RuntimeCapabilityGraphBinder`,
`RuntimeCapabilityGraphRuntime`, and `RuntimeCapabilityGraphProjector`
boundaries. It does not authorize a second graph runtime or projector.

## Current Baseline And Gaps

The current code already provides important foundations:

- `RuntimeCapabilitySlot`, deterministic layered selection, and
  `RuntimeProfileSnapshot` provide fine-grained, JSON-only profile facts;
- `RuntimeCapabilityImplementation` and `RuntimeProfileBinder` provide
  factories, optional disposers, rollback, reverse disposal, and
  generation-scoped binding leases;
- workspace and process modules already expose narrow Protocols that can serve
  as Capability facets;
- transcript profiles replay committed records into model context;
- resource descriptors carry provenance; and
- the accepted Capability architecture already defines a pure graph planner,
  transactional binder, live graph runtime, and read-only projector.

The current profile binder is a useful semantic precursor, not yet the
transaction foundation required by this plan. Its current rebind path can
dispose old entries before publication, cleanup stops at the first disposer
failure, rollback suppresses cleanup errors, and cancellation is not shielded.
Those behaviors must be hardened before live registries or the Mount Graph
depend on the shared lifecycle primitive. `RuntimeBindingLease`, which is a
generation-scoped read/access lease, remains distinct from a registration's
exact removal lease.

The remaining gaps are structural, but the mutable surfaces are not all in the
same state:

- some live registries, notably Tool and selected Extension/Product surfaces,
  identify entries only by public name, silently overwrite or ignore an entry,
  omit an owner identity, and expose no exact removal lease;
- some registries already fail closed on duplicate identity, including Runtime
  Capability declarations, transcript/Conversation codecs, JSONL routes, and
  AI API/provider adapters; convergence must preserve rather than loosen those
  semantics;
- TUI `ExtensionHandle` already demonstrates an idempotent handle shape (object
  registrations are exact, while keyed ExtensionHost handles are not exact
  across replacement), AI adapter registries carry a weaker `source_id` owner scope, and
  `register_side_question_provider()` already separates data-only declaration
  from final binding; these are implementation precedents, not additional
  lifecycle systems;
- Definition, Provider, and Consumer roles exist but are not represented by a
  single vocabulary or enforced import and injection boundary;
- profile snapshots describe selected fine-grained slots but do not yet expose
  a committed top-level live Mount graph, consumer requirements, registration
  inventory, or complete selection explanation;
- prompt/resource/tool/context composition may still pass through transient
  in-memory values without first freezing the exact model-visible projection
  as committed facts; and
- broad `object` bindings and string-keyed operation maps can bypass typed
  Capability requirements and make reconstruction and explanation incomplete.

`RuntimeProfileSnapshot` is already persisted in Session metadata and used by
resume validation. Any new graph or effective-runtime projection must preserve
that authority and use an additive, versioned compatibility path.

## Rule 1: Owned And Reversible Registration

### Decision

A live registry mutation is valid only when it produces an owner-scoped,
idempotent removal handle. A public name is not registration identity.

The minimum common records are:

```python
@dataclass(frozen=True)
class RegistrationOwner:
    owner_kind: Literal[
        "product", "oem", "extension", "capability", "session", "runtime"
    ]
    owner_id: str
    runtime_id: str
    generation: int


@dataclass(frozen=True)
class RegistrationIdentity:
    surface: str
    registration_id: str
    public_key: str | None


@dataclass(frozen=True)
class RegistrationDisposalResult:
    state: Literal[
        "removed", "already_removed", "failed_retryable", "failed_terminal"
    ]
    diagnostic_code: str | None = None


class RegistrationLease(Protocol):
    @property
    def owner(self) -> RegistrationOwner: ...

    @property
    def identity(self) -> RegistrationIdentity: ...

    @property
    def state(self) -> Literal[
        "active", "disposing", "disposed", "failed_retryable", "failed_terminal"
    ]: ...

    async def dispose(self) -> RegistrationDisposalResult: ...
```

The concrete record names may be adjusted during implementation, but the
owner, exact identity, generation, idempotence, and disposal semantics are
mandatory.

Package ownership is layered. A registry owned by AI or another lower package
keeps its own opaque token and does not import Harness owner vocabulary. A
Harness adapter may associate that token with Harness owner/provenance facts.
A pure token protocol may move to Foundation only if it remains free of
Product, Extension, and Harness lifecycle semantics.

### Registry Semantics

Every live registry must satisfy the following rules:

- registration creates an opaque unique identity, even when multiple entries
  share a public key;
- the registry stores owner, provenance, generation, and lifecycle state with
  the entry;
- disposing a lease removes only the exact entry created by that lease;
- one owner cannot dispose another owner's entry by guessing a public name;
- disposal is idempotent and records whether it removed, had already removed,
  or failed to remove the exact entry;
- exclusive surfaces reject implicit overwrite; replacement occurs only
  through explicit resolution and an atomic bind transaction;
- aggregate and ordered surfaces retain all admitted entries and recompute the
  effective view after exact removal;
- a scope owner collects leases, disposes them in reverse registration order,
  continues after individual failure, shields cleanup from cancellation, and
  aggregates disposal outcomes; and
- partial bind, cancellation, refresh, extension unload, Session switch, and
  Product shutdown use the same lease disposal primitive, subject to their
  separately defined publication/commit ordering.

Tool migration adds `bind_tool(..., owner) -> RegistrationLease`, stores an
explicit owner, and avoids implicit name overwrite in the new live path.
`ToolRegistry.register_tool()` remains temporarily as a compatibility facade
with its current `ToolDefinition` return until callers migrate. Existing
same-name behavior is characterized first and becomes explicit replacement or
layered winner resolution rather than an accidental dictionary assignment.
Only genuinely live hook, policy, approval, command, shortcut, renderer,
model-provider, package-source, resource, UI, and Capability-provider
registrations are subject to the same lifecycle rule.

### Declaration Is Not Live Registration

Pure, immutable contribution construction does not need a runtime disposer.
APIs must make this distinction visible:

- `contribute_tool(...) -> ToolContributionDescriptor` constructs data;
- admission resolves immutable descriptors without side effects;
- `bind_tool_contribution(...) -> RegistrationLease` mutates a live registry.

An existing mutable `register_*` declaration builder must either return a
builder-owned removal token until the builder is frozen, or be renamed to a
pure `contribute_*` operation. After admission, only the binding owner may
perform live registration.

This prevents a meaningless disposer requirement from leaking into immutable
configuration while making every real side effect reversible.

### Registration Scope

Runtime binding should use a shared reverse-disposal collector:

```text
open RegistrationScope(owner)
  -> bind Provider A
     -> register tools               lease A1
     -> register command             lease A2
  -> bind Provider B
     -> register policy interceptor  lease B1
  -> commit scope

failure before commit
  -> dispose B1, A2, A1
```

The collector is a lifecycle utility, not a global registry. The scope remains
owned by the Product runtime, Mounted Capability, Extension instance, or
Session that created it.

One scope disposes its leases serially in strict reverse successful-registration
order. Independent scopes may retire concurrently only when dependency order
allows it and their lifecycle owner joins/quiesces every cleanup task before
declaring shutdown complete. A disposed or disposing token cannot be used to
recover the registered value.

The implementation extends and hardens existing lifecycle patterns:

- `RuntimeProfileBinder` supplies the rollback/reverse-disposal shape, after
  cancellation, continue-on-error, and old-generation safety are fixed;
- TUI `ExtensionHandle` supplies a small idempotent handle precedent; only its
  object-capturing registrations are exact, so keyed handles must not be copied
  as registration identity;
- AI adapter `source_id` removal supplies an owner-scoped but non-exact
  precedent and remains AI-owned;
- the Session approval presentation lease prevents a superseded generation
  from closing its replacement, while the continuity activation lease keeps an
  unpublished candidate private until consume and settles abort/close once;
  both remain specialized precedents rather than a shared base class; and
- data-only side-question Provider contribution supplies the declaration/bind
  split to generalize.

These precedents are migrated or adapted; they do not become parallel public
lease hierarchies.

### Diagnostics

Registration facts exposed to diagnostics include:

- registration identity and public key;
- owner and generation;
- contribution provenance;
- surface and variation semantic;
- lifecycle state;
- selected/losing/conflicting status; and
- redacted disposal outcome.

Raw callbacks, Provider objects, credentials, environment values, and tool
arguments are not diagnostic payloads.

### Acceptance Gates

- every inventoried mutable surface is classified as declaration, live
  registration, or subscription, with its existing duplicate semantics
  characterized;
- every new or migrated live binding path returns or is internally captured by
  an exact lease; compatibility facades may retain their old return value
  during the migration window;
- existing fail-closed duplicate registries remain fail-closed, while migrated
  Tool/Extension surfaces cannot silently replace an entry through the new
  live API;
- exact identity and cross-owner disposal tests pass;
- dispose-twice, partial-bind rollback, cancellation, extension unload,
  Session switch, and shutdown tests pass;
- disposer failure does not skip later cleanup, cancellation cannot bypass
  owned cleanup, and every lease held by a disposed scope reaches a recorded
  terminal or retryable-failure state exactly once per attempt; and
- a runtime snapshot can attribute every effective registration to its owner.

## Rule 2: Definition, Provider, And Consumer

### Decision

The three roles are a contract and dependency discipline, not three required
base classes and not a new container.

### Definition

A Definition owns:

- stable owner-qualified Capability ID;
- contract version;
- narrow exported facet Protocols;
- request, result, and error value contracts;
- supported lifecycle scope and refresh boundary; and
- compatibility rules.

A Definition does not own Product defaults, concrete factories, credentials,
plugin discovery, global lookup, or model-facing presentation.

### Provider

A Provider owns:

- implementation identity and version;
- compatible Definition contract range;
- provided facets;
- typed requirements on lower Capability facets;
- authority requirements and non-secret binding fingerprint inputs;
- create/bind behavior; and
- exact disposal behavior.

`RuntimeCapabilityImplementation` remains the fine-grained Provider binding
mechanism and should be extended rather than shadowed by a parallel provider
registry.

### Consumer

A Consumer declares a `CapabilityRequirement` and receives only the requested
typed facet view. It does not select, discover, or look up a Provider.

Tool packs, Session adapters, resource adapters, and Product composition
adapters are representative Consumers. Model-facing `ToolDefinition` values
are Consumer projections, not workspace or process Providers.

### Capability Granularity

The accepted top-level Harness Capability budget remains:

```text
harness.workspace
harness.resources
harness.session
```

Read, write, process launch, prompt sections, tool packs, compaction, and
continuity remain facets or contributions. Definition/Provider/Consumer
separation does not turn each facet into another top-level DAG node.

### Authority Sandwich

Private raw backends must remain below invariant enforcement:

```text
LocalExecBackend
  -> policy
  -> approval
  -> sandbox and limits
  -> audit
  -> AuthorizedProcessLauncher facet
  -> workspace Tool Consumer
```

The Consumer never receives the raw backend. Approval, Sandbox, audit, limits,
and cleanup are not all the same kind of seam. An approval resolver may be an
admitted Exclusive Replacement, as defined by the accepted variation
boundary. The authorization gateway, immutable execution scope,
revalidation, required containment, Host-owned limits, audit requirement, and
cleanup ownership remain non-bypassable internals rather than replaceable
Capability nodes.

### Acceptance Gates

- Definition modules do not import Product, Provider, Extension, or Consumer
  modules;
- Consumers import contracts but not concrete Providers;
- new Capability paths do not use a string-keyed `Mapping[str, object]` or a
  broad runtime object as a service locator;
- a fake or alternate Provider can replace the standard Provider without
  changing Consumer code;
- incompatible contract or missing facet requirements fail before Provider
  construction; and
- Provider disposal releases every owner-scoped registration it created.

## Rule 3: Effective Runtime And Profile Assembly Projection

### Decision

The accepted `RuntimeCapabilityGraphProjector` is the only graph projector.
This rule extends it with profile references, registration inventories, and
composed effective-runtime views; it does not introduce another projector,
graph manager, or selection authority.

The state has separate authorities and change clocks:

1. **Runtime Profile snapshot/revision**: final fine-grained slot selections;
2. **Mount Graph snapshot/generation**: committed top-level Capability Bundle
   bindings, dependencies, scope, and binding signatures;
3. **registration inventory revision**: exact live contributions owned by a
   graph generation or refreshable private facet; and
4. **Model Surface/Model Input snapshot**: the model-visible surface frozen for
   one invocation or retry attempt.

An internal turn refresh may change a private facet, registration revision, or
model surface without changing the public Bundle binding signature. It must
not increment the top-level Mount generation merely to keep one aggregate
snapshot current. `RuntimeProfileSnapshot` remains the persisted fine-grained
selection authority used by Session resume.

`EffectiveRuntimeView` is a versioned, immutable, JSON-only composition of
references to those committed facts. It is a read model, not an atomically
published fourth authority:

The following value is an illustrative minimum shape. PR4 may refine field
names or split representation details while preserving the references and
authority boundaries above.

```python
@dataclass(frozen=True)
class EffectiveRuntimeView:
    schema_version: int
    product_id: str
    runtime_id: str
    profile_fingerprint: str
    mount_graph_id: str
    mount_generation: int
    registration_revision: str
    model_surface_snapshot_id: str | None
    assembly_fingerprint: str
```

The referenced graph snapshot and related projections keep separate:

- **resolution trace**: admitted, rejected, losing, and selected candidates;
- **graph plan diagnostics**: dependency, version, scope, facet, and phase
  validation failures;
- **committed live state**: selected Mounted Capabilities and registrations;
  and
- **assembly attempt facts**: failed construction, rollback, retirement, and
  disposal outcomes.

Rejected and losing candidates do not become graph nodes. Failed or disposed
historical nodes do not masquerade as current effective state. Internal
facets, tools, prompts, and registrations appear as node attachments or
separate inventories, not top-level Capability nodes.

### Required Answers

The projector and composed view must answer:

- which Product, runtime, scope, and generation is this;
- which Provider was selected for each Capability and profile slot;
- which source and deterministic rule selected it;
- which contract version and facets it provides;
- which Consumers require those facets;
- which registrations were produced and who owns them;
- which tools, prompt sections, skills, and resources were model-visible for a
  referenced invocation;
- which invariant enforcement layers protect executable facets;
- which nodes were reused or rebound in the committed graph, and which failed
  or disposed states were recorded by the relevant assembly attempt; and
- which redacted input fingerprints make the assembly reproducible.

### Projection API

The existing read-only projector should grow additive, versioned operations:

```text
snapshot(graph_id)
effective_view(runtime_id, model_input_snapshot_id=None)
explain(capability_id | profile_slot | registration_id)
dependencies(capability_id)
dependents(capability_id)
impact(capability_id | registration_id)
diff(snapshot_a, snapshot_b)
to_json(snapshot)
to_dot(snapshot)  # optional diagnostic export
```

`to_dot` is a diagnostic export. JSON remains the canonical machine-readable
shape. Product adapters own CLI, RPC, TUI, and Web presentation.

### Publication And Transaction Boundaries

A Mount Graph generation is published only after Provider construction,
invariant wrapping, owned registration, dependency validation, and graph commit
all succeed. A failed candidate generation produces attempt diagnostics but
does not replace the previously committed graph snapshot.

Graph binding follows the accepted transaction:

```text
resolve
  -> stage Providers and registrations
  -> stage graph
  -> validate
  -> atomically publish graph generation + MountGraphSnapshot
  -> retire replaced generation with recorded cleanup outcomes
```

Cleanup failure after publication marks degraded retirement; it cannot make a
partially disposed old generation authoritative again. If a boundary requires
the old generation to remain callable until candidate publication, it must use
stable indirection or dependent-closure rebinding rather than the current
profile rebind order.

Session-host publication is a separate outer transaction. This plan does not
silently change the accepted Session switch order. Candidate graph commit and
Product-current Session publication require an explicit nesting contract
before Session switch adopts the graph transaction.

Profile, registration, and Model Input facts publish on their own authority
clocks. The Projector combines their committed identifiers on read and must
never synthesize a new selection to fill a missing reference.

### Redaction And Fingerprints

Snapshots retain canonical JSON configuration only when it is safe to expose.
Credentials, raw environment values, executable callbacks, commands, and live
Provider objects are excluded. Sensitive inputs contribute typed redacted
identities or keyed fingerprints according to Product policy.

The Mount assembly fingerprint covers normalized profile references, contract
and implementation versions, stable configuration, dependency edges, owner
and provenance identities, and binding-input fingerprints. Registration and
Model Input snapshots carry their own fingerprints/revisions. A composed view
may hash their identifiers, but does not rewrite their authority. No
fingerprint includes memory addresses or object repr values.

### Versioning And Compatibility

Every durable Profile, Mount Graph, registration, and Model Input record has an
explicit schema version and reader policy. Readers fail closed on unknown
required fields or unsupported future versions. Additive migrations may emit a
new projection or envelope but do not rewrite historical facts. Existing
Runtime Profile schema/version and Session-header resume validation remain
readable throughout a dual-read/additive-write migration window.

### Acceptance Gates

- two equivalent graph assemblies produce the same canonical graph snapshot
  fingerprint;
- ordering is deterministic across process restarts;
- failed binding leaves the previous graph and its live objects usable and
  authoritative;
- `explain()` attributes every selected Provider and effective registration;
- `diff()` identifies additions, removals, replacements, generation changes,
  registration revision changes, and referenced model-surface changes without
  conflating their clocks;
- graph nodes remain at accepted Capability granularity; and
- no snapshot contains a credential, callback, arbitrary object repr, or raw
  environment value.

## Rule 4: Model-Visible Content Rebuilds From Committed Facts

### Decision

The model request is a projection, never the authority. Before every model
call managed by a Harness-bound Product Session, the system freezes and commits
a versioned `ModelInputSnapshot` describing the exact ordered inputs and their
authoritative fact references. The model call starts only after that commit
succeeds.

```text
committed transcript/resource/runtime facts
  -> Harness provider-neutral logical projection
  -> AI-owned model resolution and provider adapter preparation
  -> freeze/hash final model-visible provider payload
  -> ModelInputSnapshot commit
  -> send the same frozen payload
```

This is a prepare-freeze-commit-send boundary. Committing before provider
adapter materialization is insufficient because adapters may add tool choice,
reasoning, output-format, cache, or provider-specific instruction fields.

AI owns a Product-neutral `PreparedModelRequest` value contract and an optional
async pre-transport commit port after all model-visible normalization and
before network transport. Harness injects the committer through composition;
AI and Agent do not import Harness. The transport sends the exact frozen value,
or verifies its hash immediately before serialization. A transient hook or
adapter may not inject model-visible content after commit.

An Agent- or host-level invariant may verify the provider-neutral logical
projection, but it cannot by itself prove the final provider payload. Standalone
AI/Agent use remains independent; this guarantee applies to Harness-managed
invocations whose profile requires the committer.

DeepSeek Harness is a useful precedent for the first half of this rule: it logs
a request header, freezes the loop-built request, and checks the logical request
against the durable derivation at `llm/stream`. That invariant does not by
itself settle Loushang's stricter claim about fields added by a provider adapter
after logical request assembly; the AI-owned prepared-request seam closes that
additional boundary.

### Model-Visible Surface

The rule applies to every value the provider sends to a model, including:

- ordered system-prompt sections;
- conversation and branch context messages;
- compaction summaries and retained-turn selection;
- active tool names, descriptions, parameter schemas, and model-facing
  behavior metadata;
- activated skill instructions and prompt resources;
- attachments, image/document projections, and artifact references;
- dynamic Product or Extension prompt fragments;
- model-visible workspace or environment summaries; and
- any retry-specific or provider-specific instruction included in the request.

UI status, live callback objects, credentials, transport metadata, and values
that are not sent to the model are outside the model-visible surface.

### Fact And Artifact Requirements

Every snapshot component references one of:

- an append-only transcript, Model Input, or runtime assembly fact;
- a versioned immutable configuration fact;
- a committed compaction artifact with complete input record IDs and hashes;
  or
- materialized canonical content stored with the snapshot when its source is
  dynamic or its projector cannot be guaranteed to remain available.

A source path and hash alone are insufficient if the underlying bytes may be
changed or deleted. Historical reconstruction requires retained immutable
bytes, an immutable package artifact, or canonical inline materialization. The
first vertical closure uses canonical inline bytes in the existing transcript
authority. A content-addressed Blob/Artifact Store is a possible later
protocol, not an implicit expansion of `ConversationStore` and not a second
fact authority.

Tool executable closures are never persisted. The model-facing tool
definition is persisted canonically with an owner, Definition contract,
Provider implementation version, Consumer projection version, and schema
hash. Runtime execution still requires a currently admitted implementation,
but historical model-input reconstruction does not.

### Minimum Model Input Snapshot

The following value is an illustrative minimum shape rather than a frozen
wire schema. PR6 owns the smallest field set that proves one-turn
reconstruction without introducing another storage authority.

```python
@dataclass(frozen=True)
class ModelInputSnapshot:
    snapshot_id: str
    schema_version: int
    projection_version: str
    invocation_id: str
    attempt: int
    purpose: str
    product_id: str
    runtime_id: str
    mount_generation: int
    profile_fingerprint: str
    registration_revision: str
    conversation_id: str
    source_leaf_id: str
    source_revision: int
    commit_revision: int
    provider_id: str
    model_id: str
    api_id: str
    endpoint_id: str | None
    system_sections: tuple[ModelContentReference, ...]
    messages: tuple[ModelContentReference, ...]
    tools: tuple[ModelToolSurfaceReference, ...]
    attachments: tuple[ModelContentReference, ...]
    compaction_artifacts: tuple[ModelContentReference, ...]
    request_options: ModelVisibleRequestOptions
    logical_input_hash: str
    prepared_payload_hash: str
```

The snapshot is appended as a hidden `model.input.prepared` record through the
existing ConversationStore/unit-of-work expected-revision path. The record
stores ordered references plus canonical inline materialization for the first
closure. Canonical inline is the reconstruction fallback, not a requirement to
duplicate one monolithic request body in every snapshot: repeated immutable
components may reference earlier committed component records in the same
authoritative conversation by record ID and hash. Those references must remain
reachable through resume/fork and obey the Store's declared encoded-record
size limit; oversized materialization is chunked in the same Store or rejected
before send. The append result/envelope records the snapshot record ID and
commit revision separately from the source leaf/revision used to prepare it.
Provider credentials and non-model-visible transport options are excluded.

Commit proves that the payload was prepared, not that transport succeeded or
the provider accepted it. `transport_attempted`, `accepted`, and `failed`
remain separate invocation-attempt facts. A retry whose payload changes gets a
new Model Input snapshot; an identical-payload retry may reference the same
snapshot but still records another attempt fact.

### Reconstruction API

```text
rebuild_model_input(snapshot_id) -> RebuiltModelInput
verify_model_input(snapshot_id) -> ReconstructionVerification
diff_model_inputs(snapshot_a, snapshot_b) -> ModelInputDiff
```

Verification rebuilds both the provider-neutral logical input and the frozen
model-visible provider payload and compares their hashes. Structural
prepare/transport separation, rather than adapter tests alone, prevents hidden
model-visible fields from being added after commit.

### Dynamic And Nondeterministic Content

Time, workspace status, generated instructions, Extension hook output, remote
resource responses, and other nondeterministic values must be materialized as
facts before inclusion. Re-running the source function during replay is not
reconstruction.

Projection code versions are recorded. When future code cannot execute an old
projection version, the retained canonical materialization remains the replay
fallback. A migration may create a new projection fact but must not rewrite
the historical model input.

### Storage Boundary And Deferred Decisions

The first closure does not create a generic Fact Store, add blob methods to
`ConversationStore`, or promote the current test-only Memory composition into
a new Product persistence profile. A durable Harness-bound Session appends the
Model Input record and canonical inline materialization through its existing
authoritative ConversationStore. If that commit fails, the model request is
not sent.

Non-persistent runtime compositions may reconstruct only within their existing
lifetime and must not claim restart durability. Formal Product-level
`ephemeral` semantics and a content-addressed Blob/Artifact protocol require
separate boundary decisions, ownership, versioning, and failure-order
contracts. A requested durable composition must never silently fall back to an
in-memory one.

### Secrets And Sensitive Content

Secrets must be removed before commit and before model visibility. If Product
policy explicitly permits sensitive model content, the authoritative artifact
must use an approved encrypted Store and access policy. Harness must not choose
between exact replay and secret retention after a value has already been sent;
that decision occurs before snapshot commit.

### Compaction And Tool Results

A compaction summary is a new committed derived fact. It records its input
record IDs and hashes, prompt/profile version, output artifact, and replacement
range. Context reconstruction uses the committed summary; it does not invoke
the summarizer again.

That complete lineage is additive compaction-v2 behavior. Existing v1
checkpoints remain resumable from their committed summary but are reported as
derivation-unverifiable rather than rejected or silently rewritten.

A tool result becomes eligible for the next model input only after its
transcript commit succeeds. Streaming UI observation may occur separately,
but transient output is not part of later model context until committed.

### Acceptance Gates

- killing and restarting a durable session reproduces the same logical and
  prepared-payload hashes for a recorded snapshot;
- changing or deleting a source prompt file does not alter an old snapshot;
- unloading an Extension does not prevent reconstruction of its previously
  visible prompt or tool schema;
- dynamic hook output has a committed fact or immutable artifact reference;
- every active tool schema in a model request appears in the referenced
  registration/model-surface facts and Model Input snapshot;
- transcript and compaction projection indexes can be deleted and rebuilt from
  authority;
- every Harness-managed main turn, retry, compaction, branch summary, and side
  question eventually uses the AI-owned prepare-freeze-commit-send seam;
- no model adapter or transport adds a model-visible field after commit; and
- a failed snapshot commit prevents the model call.

## Cross-Rule Invariants

The four rules close one explainability and recovery loop:

```text
Capability Definition
  <- compatible Provider selected by effective profile
  <- Provider owns RegistrationScope
  <- registrations identify resulting model surface
  <- Mount Graph and profile facts freeze assembly on their own clocks
  <- effective runtime view composes committed references
  <- Model Input snapshot freezes one prepared provider payload
  <- replay verifies what the model actually saw
```

Consequently:

- an effective tool without a registration owner is invalid;
- a registration without an exact disposer cannot be committed into a runtime
  generation;
- a Consumer without a declared Capability requirement cannot be attributed
  in the assembly graph;
- model-visible content absent from the referenced registration/model-surface
  facts and Model Input record is invalid;
- a Mount generation is not reusable when its binding inputs cannot be
  fingerprinted deterministically; a model invocation is invalid when its
  logical input or prepared payload cannot be fingerprinted; and
- caches, indexes, UI state, and graph projections remain rebuildable read
  models rather than competing authorities.

## Delivery Sequence

The first repository PR must not attempt the four-rule vertical closure. The
first integrated milestone that proves all four rules arrives only after the
lifecycle, Tool, graph, and AI request seams exist.

```text
PR0 contract/fault inventory
  |-> PR1 lifecycle transaction foundation -> PR2 Tool live-binding cutover
  |-> PR3 Definition/Requirement + pure graph planner
  |-> PR5 AI prepared-request barrier
  PR2 + PR3 -> PR4 graph binder/runtime + harness.workspace D/P/C
  PR4 + PR5 -> PR6 Model Input transcript record + one-turn reconstruction
  PR4 -> PR7 Extension/resource generation migration
  PR6 + PR7 -> PR8 Session/all-model-call closure
  PR8 -> PR9 Product diagnostics and optional exports
```

### PR0: Inventory, Contract, And Fault Baseline

- classify every mutable `register_*`, `add_*`, hook, Provider, renderer,
  resource, and package-source surface as declaration, live registration, or
  subscription;
- record existing duplicate, return-value, no-op, unregister, reload, resume,
  wire-format, and error behavior;
- inventory every Harness-managed model-call/normalization/retry path and its
  current authority;
- define package ownership for owner/token, disposal state/result,
  Capability requirement, graph snapshot, and Model Input contracts;
- enumerate failure and cancellation behavior at every lifecycle await point;
  and
- add architecture import, forbidden-service-locator, and no-second-runtime
  gates.

This PR changes no Product behavior and does not prematurely freeze every final
dataclass. Its acceptance gate is a complete evidence matrix plus unchanged
baseline tests.

### PR1: Lifecycle Transaction Foundation

- implement exact opaque identity, owner association, async disposal result,
  and reverse/continue-on-error `RegistrationScope` primitives;
- add cancellation cleanup shielding and aggregated disposal diagnostics;
- harden `RuntimeProfileBinder` partial construction/disposal so cancellation
  cannot skip cleanup and a failed candidate does not leave a nominally live,
  partially disposed old generation; and
- characterize but do not yet alter Session-switch publication ordering.

Acceptance requires fault injection at every create/register/dispose await
point, exact removal, dispose-twice, cross-owner isolation, complete cleanup
after individual disposer failure, and callable old-generation behavior after
candidate failure.

### PR2: Tool Live Binding And Compatibility Cutover

- add owner-aware `bind_tool()` and exact removal;
- retain `register_tool()` and its current return value as a compatibility
  facade with an explicit deprecation/migration path;
- replace accidental same-name assignment with the Tool surface's explicit
  conflict policy: owner-layer winner resolution restores a prior contribution
  after exact removal where Tool composition admits layering; otherwise the
  surface rejects the conflict rather than inventing universal restoration;
- migrate Session Tool runtime and one Extension Tool production path; and
- remove or fail closed on the silent `_ignore_tool` composition path where a
  live Tool contribution is required.

Acceptance requires existing public entrypoints and supported Tool behavior to
remain compatible while the migrated live path proves rollback, prompt/tool
activation consistency, no cross-owner deletion, and the surface-specific
same-name/removal behavior characterized by PR0. ModelCatalog and unrelated
surfaces do not inherit Tool winner-restoration semantics automatically.

### PR3: Capability Contracts And Pure Graph Planning

- define the top-level Definition/Requirement/Bundle Provider vocabulary only
  for the accepted coarse Capability graph;
- keep `RuntimeCapabilitySlot/Implementation` as Bundle-private facets and
  adapt Extension replacements to that mechanism;
- implement pure planning, dependency closure, validation, and deterministic
  diagnostics; and
- reject unknown IDs/facets, incompatible versions, cycles, scope/refresh/phase
  inversion, and authority-ceiling violations before Provider construction.

This work may begin after PR0 while PR1/PR2 proceed, but it cannot integrate a
live graph until the lifecycle foundation is available.

### PR4: Graph Binder/Runtime, Projector Base, And Workspace D/P/C

- implement the accepted graph binder/runtime/projector boundaries rather than
  a parallel effective-runtime manager;
- model `harness.workspace` as a Bundle with typed authorized facets and Tool
  Consumers;
- replace the bootstrap/final double-binding ownership path for this slice;
- publish a committed `MountGraphSnapshot` and registration inventory, with
  Profile authority referenced rather than copied; and
- verify Product neutrality with a fake non-Coding Product/Provider.

Acceptance requires one construction for every unchanged Capability, failed or
cancelled binding leaving the previous graph and objects usable, no broad
runtime object reaching the migrated Consumer, deterministic graph
fingerprints, and additive compatibility with persisted Runtime Profile
metadata.

### PR5: AI Prepared-Request Barrier

- add an AI-owned, Harness-neutral prepared-request value and async
  pre-transport commit port;
- ensure all adapter model-visible normalization completes before freeze;
- send the same frozen payload after the injected committer succeeds; and
- define invocation/attempt identity and retry behavior without adding an
  `AI -> Harness` source dependency.

This AI-owned seam depends only on the PR0 package/contract decision and may be
implemented in the AI lane while PR1-PR4 proceed. Harness integration waits for
both the committed graph references from PR4 and the prepared-request seam.

Acceptance requires structural proof that no adapter/transport model-visible
mutation occurs after commit and that committer failure results in zero
provider transport calls. AI owns the protocol and reusable conformance suite;
Harness runs that suite against its injected committer without AI importing
Harness. Architecture tests also exercise standalone AI/Agent calls with no
committer and enforce that AI/Agent package imports remain Harness-free.

### PR6: Model Input Transcript Record And One-Turn Closure

- append hidden `model.input.prepared` facts through the existing
  ConversationStore/unit-of-work path;
- canonical-inline prompt, messages, Tool schemas, relevant options, and final
  prepared payload for the first closure;
- deduplicate repeated immutable components within one authoritative
  conversation by referencing earlier committed component record IDs and
  hashes, while preserving fork/resume reachability;
- define and test a Store-safe encoded record-size ceiling; oversized canonical
  materialization is chunked through the same authoritative append-only Store
  or fails closed rather than being silently truncated;
- record source versus commit revisions, profile/mount/registration references,
  invocation purpose, attempt, and prepared/transport outcome distinctions;
- rebuild and hash-verify one main-turn request after restart and source-file
  deletion.

This is the first integrated milestone that honestly proves all four rules.
Acceptance also requires repeated identical prompt/Tool-schema content to grow
storage incrementally rather than duplicating one monolithic payload per
request, and no individual encoded record to exceed the declared Store limit.

### PR7: Extension And Resource Generations

- separate Extension declaration/admission from live binding;
- define staged generation refresh/unload semantics before claiming atomic
  reload;
- attach owner/generation to live contributions and restore prior winners after
  exact unload;
- preserve current hook-failure containment unless a separate compatibility
  decision changes it; and
- retain canonical historical prompt/skill/Tool-schema content, using inline
  materialization until a separately accepted Artifact protocol exists.

Acceptance requires failed/cancelled refresh to leave the old generation and
context usable, successful publication to dispose the old generation exactly
once, and historical Model Inputs to rebuild after Extension removal.

### PR8: Session And All-Model-Call Closure

The implementation contract is frozen in
[Session And Model-Call Closure Boundary](session-model-call-closure-boundary.md).
PR8 and the PR9 effective-runtime diagnostics slice are implemented on the
Harness lane. Evidence-gated DOT, multi-Product aggregation, and long-running
operational measurements remain explicit follow-up work rather than implicit
convergence-closure requirements.

- define the nesting contract between candidate graph commit and current
  Session publication before integrating Session switch;
- route main turns, continuations, Tool loops, retries, compaction, branch
  summary, side question, and other Harness-managed AI calls through the
  prepared-request barrier;
- make committed Tool results eligible for sampling only after transcript
  commit; and
- add compaction-v2 lineage while preserving v1 resume as
  derivation-unverifiable.

Acceptance covers durable kill/restart, resume/fork/branch, concurrent revision
conflicts, retry attempts, source deletion, Extension unload, and refusal to
send when a required durable commit is unavailable.

### PR9: Product Projection And Operational Diagnostics

The implementation contract is frozen in
[Effective Runtime Diagnostics Boundary](effective-runtime-diagnostics-boundary.md).

- extend the existing Projector with composed effective views, explain, JSON,
  and diff;
- let Product adapters own CLI, RPC, TUI, and Web presentation;
- add DOT and multi-Product read-only aggregation only when operational
  evidence justifies them; and
- measure leaked registrations, failed cleanup, reconstruction mismatch, and
  projection latency in long-running tests.

Acceptance requires every composed view and diff to expose the Profile,
Mount-generation, registration-revision, and Model-Input clocks it compared.
Legitimate skew, such as a refreshed private facet beside an unchanged Mount
generation, is labeled explicitly rather than presented as an atomic snapshot
or a consistency failure.

## Non-Goals

- no Cordis-style global context or string-keyed service lookup;
- no second Agent loop, AI Provider registry, transcript authority, or Product
  framework inside Harness;
- no generic Fact Store, Blob/Artifact Store, or Product-level ephemeral
  persistence profile without a separate accepted boundary decision;
- no automatic persistence of credentials or arbitrary runtime objects;
- no conversion of every facet, tool, hook, or resource into a top-level graph
  node;
- no hot replacement claim until dependent-closure rebind, rollback, and
  authority tests prove it; and
- no claim that a non-persistent Session can be reconstructed after process
  termination.

## Completion Gate

The convergence is complete only when:

- all live registrations are attributable and reversibly disposed;
- Workspace, Resources, and Session follow the Definition/Provider/Consumer
  boundary;
- the existing graph Projector can compose a final effective runtime view from
  authoritative Profile, Mount Graph, registration, and Model Input facts;
- every durable model input can be reconstructed and hash-verified after
  restart;
- approval, Sandbox, limits, audit, and cleanup remain non-bypassable;
- Product behavior and supported public entrypoints remain compatible; and
- focused, architecture-boundary, rollback, restart, and reconstruction tests
  pass.

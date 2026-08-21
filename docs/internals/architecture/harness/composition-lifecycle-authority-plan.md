# Capability Composition Lifecycle Authority Plan

## Status

Implemented delivery plan. CLA0-CLA8 are complete for issue
[#453](https://github.com/zhnt/loushang/issues/453). This document records the
delivery sequence; it does not authorize a second composition framework.
Source, executable architecture gates, the generated catalog, and implemented
boundary documents remain authoritative for present behavior.

The completed [Capability Runtime Convergence Plan](capability-runtime-convergence-plan.md)
established owned registrations, Capability Definition / Provider / Consumer
seams, Mount Graph mechanics, effective-runtime diagnostics, and model-input
reconstruction. The generated
[Harness Capability Catalog](capability-catalog.md) is the source-backed seam
inventory. This plan addressed the next problem exposed by that work: several
owners constructed or published adjacent parts of one Product runtime.

The accepted boundaries remain:

- [Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md);
- [Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md);
- [Extension And Resource Generation Lifecycle](extension-generation-lifecycle-boundary.md);
- [Session And Model-Call Closure Boundary](session-model-call-closure-boundary.md); and
- [Effective Runtime Diagnostics Boundary](effective-runtime-diagnostics-boundary.md).

Delivery did not silently amend those implemented contracts. CLA2 revised the
Session/model-call boundary when Model Input began receiving the current
Profile fingerprint independently of the Mount snapshot. CLA4 revised the
effective-runtime diagnostics boundary when the view gained a scoped
source-publication reference and versioned skew dispositions. Each revision
shipped with its corresponding JSON compatibility and regression tests.

## Decision Summary

The completed stage converges **one publication authority per owned live object**.
It does not create one global publication point for Profile, Mount,
Registration, Extension, Resource, and Model Input facts.

The implemented rules are:

1. `RuntimeProfileResolver` remains the authority for deterministic fine-grained
   selection facts.
2. `RuntimeCapabilityGraphBinder` remains the only transaction that publishes
   top-level Mounted Capability generations.
3. `RegistrationScope` remains the only owner-scoped container for live,
   reversible side effects; immutable declarations do not become registrations.
4. Extension generation and Resource snapshot-publication owners retain
   discovery, provenance, candidate admission, and private publication. They do
   not independently publish a graph-owned Provider or Bundle.
5. A Product/session composition root owns one graph runtime. A focused runtime
   such as model-call preparation does not create a private peer graph.
6. Consumers receive declared `CapabilityFacetSet` views or focused typed
   wrappers, never a graph runtime or a string-keyed service locator.
7. Profile, Mount, registration, and Model Input clocks remain distinct.
   Extension/resource provenance is linked into those facts rather than being
   promoted automatically to a redundant fifth global clock.

Delivery began with `harness.resources`, after moving existing
`harness.model_input` graph ownership to the Session composition root. Later
slices production-mounted `harness.session` and optional `harness.workspace`
through declared dependencies without turning fine-grained Profile slots into
top-level graph nodes.

## Why Another Layer Is Not The Answer

Most proposed common composition concepts already have an implemented owner:

| Concept | Existing owner |
| --- | --- |
| pure graph plan | `RuntimeCapabilityGraphPlan` |
| deterministic binding identity | mounted node `binding_signature` |
| construction transaction | `RuntimeCapabilityGraphBinder.bind()` |
| live side-effect scope | `RegistrationScope` |
| bind result and attempt facts | `CapabilityGraphBindResult` and `CapabilityGraphBindingAttempt` |
| generation-scoped Consumer view | `CapabilityFacetSet` backed by `RuntimeBindingLease` |
| runtime projection | `RuntimeCapabilityGraphProjector` and `EffectiveRuntimeView` |

This stage extends and relocates ownership of those primitives. It must not add
parallel public `CompositionPlan`, `CompositionTransaction`, `FacetLease`, or
`EffectiveRuntimeProjection` abstractions with equivalent semantics.

A small private adapter is permitted only where the synchronous Product
construction API must transfer an already staged candidate into the existing
asynchronous graph transaction. Such an adapter is a one-use ownership handoff,
not a new registry, graph, or transaction API.

## Current Source-Backed Baseline

### Runtime Profile

`RuntimeProfileResolver` selects fine-grained slots and produces immutable
profile facts. `RuntimeProfileBinder` additionally constructs, replaces, and
disposes live values. It remains useful for unmigrated slots and for private
facet mechanics, but it must stop being a peer live-binding owner for a
migrated top-level Bundle.

### Capability Composition Runtime

`CapabilityCompositionRuntime` creates its own `RuntimeProfileBinder` and
currently exposes:

- resource activation;
- prompt section composition;
- skill activation;
- Tool-pack composition;
- Command-pack composition; and
- the Session side-question Provider factory.

Bootstrap construction may create one capability runtime before Extension
discovery and another after final Extension admission. Session composition then
passes the concrete runtime through broad composition ports. Those normal
success and failure paths already dispose their owned runtimes; the remaining
problem is repeated construction and parallel binding ownership, not a general
cleanup leak.

There is also a separate direct path: `coding.session.AgentSession` constructs a
`CapabilityCompositionRuntime` itself when the caller does not inject one. That
entrypoint sits outside `AgentProductConstructionBinding`'s normal bootstrap/
final handoff and is therefore an explicit CLA0 inventory and CLA4 cutover
target.

`interaction.side_question` belongs to the future `harness.session` Bundle. It
must not be retained inside `harness.resources` merely because the compatibility
facade currently groups them together.

### Mount Graph

`RuntimeCapabilityGraphBinder` already:

- validates Provider bindings against a pure plan;
- computes binding signatures and reuses unchanged nodes;
- stages Provider values and owner-scoped Registration scopes;
- rolls back construction failure and cancellation;
- publishes the new graph in a no-`await` window;
- invalidates replaced Consumer leases; and
- retires old nodes with retryable cleanup facts.

It is the transaction foundation. This plan does not introduce another binder.

### Model Input

At the CLA0 baseline, `SessionModelCallRuntime` created and bound a private
graph containing only `harness.model_input`. That graph proved the Capability
lifecycle, but a private model-call graph could not become the Session-wide
composition authority. CLA2 moves that graph to the Session composition root
and injects the declared model-input Consumer into the model-call runtime.

### Workspace

`harness.workspace` has a role-complete Definition / Provider / Consumer seam.
The generated catalog records that source seam, but production Product/session
composition does not yet mount it. The resource slice must not claim production
closure merely because source symbols and isolated tests exist.

### Extension And Resource Generations

`ExtensionRunner` stages a candidate generation, commits generation-scoped
registrations, publishes its private composition state, and retains failed
retirements for later cleanup. `SessionResourceRefreshRuntime` coordinates the
resource bundle view with that source generation.

Those are legitimate local source/private-composition publication facts, even
though the current Resource snapshot is not yet a versioned clock. The defect
is not that they publish anything; it would be a defect if they also selected
and published a graph-owned Bundle independently of the Graph Binder.

## Authority Invariant

Authority is assigned by the identity of the object being published:

| Published object | Sole authority |
| --- | --- |
| resolved fine-grained selection | `RuntimeProfileResolver` and immutable Profile snapshot |
| top-level Mounted Capability graph | Session/Product-owned `RuntimeCapabilityGraphRuntime`, mutated only by `RuntimeCapabilityGraphBinder` |
| live registration entry | the owning `RegistrationScope`; typed Registry retains only conflict/effective-view policy |
| Extension source/private composition generation | `ExtensionRunner` |
| Resource bundle/snapshot publication | resource refresh owner |
| per-call model-visible input | transcript Model Input commit path |
| composed diagnosis | existing Projector plus `EffectiveRuntimeView`; never an authority |

“One final publication point” therefore means one publication point for one
Mount generation. It does not mean Profile resolution, an Extension source
refresh, a registration retirement retry, and a model call share a fabricated
global generation.

## Target Control Flow

### Initial Session Admission

```text
Product / OEM / Package declarations
  -> Runtime Profile resolution                 # immutable selection facts
  -> bootstrap-only source discovery            # no final Bundle publication
  -> Extension discovery and admission          # immutable candidate facts
  -> final CapabilityGraphPlan
  -> existing RuntimeCapabilityGraphBinder
       stage Provider values
       stage RegistrationScopes
       validate signatures and authority
       publish one Mount generation
       retire replaced nodes
  -> capture typed Consumer facet views
  -> activate the Session
```

Bootstrap discovery must not construct every final-only slot. Each mechanism is
classified as one of:

- **bootstrap infrastructure**: fixed, non-Extension-replaceable mechanics
  required to obtain declarations;
- **final-only Provider**: constructed only after final admission; or
- **reusable staged candidate**: constructed once, fingerprinted completely,
  and transferred exactly once into the final graph transaction.

Incidental construction before and after discovery is not a reuse policy.

### Synchronous Construction And Asynchronous Publication

The supported Product session construction API is synchronous while Graph
binding is asynchronous. This plan preserves that public API.

The synchronous phase may create immutable outputs and private staged candidate
values needed to construct the Product session, but it must not:

- publish a graph generation;
- expose a graph Consumer lease;
- commit live registration scopes; or
- leave ownership ambiguous if Session preparation fails.

The existing asynchronous Session `prepare_session` hook performs final Graph
binding before the transition host publishes the Session as current. The
current-Session pointer remains the only external Session availability
publication point.

A staged value used to preserve synchronous compatibility has one private
ownership cell with exactly four states:

```text
root_owned -> graph_constructing -> graph_owned -> disposed
     |                |
     +----------------+-------------------------> disposed
```

Provider `create()` may move `root_owned -> graph_constructing`. Ownership
becomes Graph-owned only after `create()` returns a complete, valid Bundle
value. An exception before return restores root ownership or disposes the
candidate. After return, Binder rollback/retirement is the sole disposer.
Session rollback and every compatibility facade consult the same ownership
cell and never dispose a Graph-owned value.

Graph-wide assembly reuse and per-node signature reuse are decided before the
corresponding Provider `create()` call. If the Graph reuses the existing Mount,
the new candidate remains `root_owned`; the construction root disposes it. CLA0
freezes this validation/reuse-before-construction ordering, and CLA4 tests that
the reuse path neither transfers nor leaks the rejected candidate.

The two terminal paths are therefore:

```text
candidate -> transferred once to Graph Binder -> Graph owns retirement
candidate -> preparation/transfer fails         -> construction root disposes it
```

There is no synchronous variant of the Graph Binder. Standard lifecycle
preparation and the direct model-call path call the same idempotent
`ensure_session_graph_prepared()` port. The model-call runtime may invoke that
focused port, but it cannot enumerate, plan, or bind the graph. Failure is
closed; successful direct callers retain the current lazy-prepare behavior.

### Runtime Extension Refresh

```text
Extension source refresh
  -> stage/admit candidate declarations
  -> if only contribution/resource content changes:
       publish Extension generation and Resource snapshot/bundle
       update exact registrations/resource facts
       keep Mount generation unchanged
  -> if a graph-owned Provider binding signature would change:
       fail closed as restart-required in this stage
```

Hot replacement of a graph-owned Provider is deferred until dependent-closure
rebind and cross-authority rollback have a separately accepted contract. This
stage must not fake atomicity by publishing Extension state and Mount state in
two unrelated transactions.

## Runtime Profile After Migration

For a migrated top-level Bundle, the Profile remains authoritative for its
private selection facts. It may still select `resource.runtime`,
`prompt.sections`, `skill.activation`, `tool.packs`, and `command.packs`.

The Bundle Provider may temporarily use the existing Profile Binder as an
internal construction engine, subject to all of these constraints:

- the binder is owned and disposed by that Provider;
- no other Session owner exposes the same live values;
- the Profile binding cannot publish a peer effective-runtime identity;
- the Bundle binding signature fingerprints all selection and construction
  inputs; and
- Consumer code receives Bundle facets, not the private Profile binding.

This is a migration seam, not the final public architecture. Once each private
facet has an explicit construction owner, the compatibility facade can shrink
without requiring a flag-day rewrite.

Unmigrated Profiles and focused runtimes such as transcript or continuity may
continue to use `RuntimeProfileBinder`. Architecture gates prohibit only new
peer ownership for the explicitly migrated slot set.

## `harness.resources` Bundle

The accepted top-level Bundle has these internal facets:

| Facet | Shape and lifecycle | Publication rule |
| --- | --- | --- |
| `resource.runtime` | single, workspace-scoped, sealed | selected before final Session activation; backend replacement requires restart |
| `prompt.sections` | single mechanism with aggregate section inputs, Session/turn facts | pure declaration/composition changes do not become registrations |
| `skill.activation` | single policy with resource inputs | active model-visible result is committed through Model Input facts |
| `tool.packs` | single composer with ordered aggregate packs | only live Tool registrations receive Registration leases |
| `command.packs` | single composer with ordered aggregate packs | only live Command registrations receive Registration leases |

The Bundle Provider depends only on declared workspace facets where live
filesystem/process access is required by an accepted Consumer. The current
Resource Loader reads through its own filesystem owner, so this first slice
does not invent a `harness.resources -> harness.workspace` edge. The Provider
must not capture a graph runtime, raw authorization gateway, policy engine,
credential, or a shorter-lived concrete value.

`harness.resources` does not absorb:

- `interaction.side_question`;
- the Product's prompt text or disabled-skill defaults;
- Extension source discovery policy;
- Tool/Command Registry conflict semantics; or
- Model Input persistence.

Those remain separate owners connected through typed facts and ports.

## Declaration Versus Live Registration

`RegistrationScope` applies only to a change that must be undone from a live
surface.

| Item | Registration lease? | Reason |
| --- | --- | --- |
| immutable Provider or Extension declaration | no | no live side effect exists |
| prompt/skill/resource descriptor | no | committed or immutable data |
| resolved pack composition value | no | pure derived value |
| Tool or Command installed in a live Registry | yes | exact removal and winner restoration are required |
| hook/listener/interceptor attachment | yes | ordered live behavior must be detached |
| activated resource overlay with live host state | yes | host mutation must be reversed |
| Capability facet exposure | no | `RuntimeBindingLease` and Mount-node lifetime own the facet view |

Only a live mutation that can survive independently outside its owning object
uses a Registration lease. A Tool or Command needs one only when actually
installed in an independent mutable Registry. A hook/listener needs one only
when attached to a live bus; an immutable route plan does not. A pure resource
bundle/overlay does not need one; mutation of an external host does.

Every leased item carries an owner with generation, exact registration
identity, and disposer state. A surface may project separate redacted source
provenance, but the current base `RegistrationIdentity` is not widened into a
generic source record. Typed registries continue to determine duplicate,
ordering, overlay, and winner semantics; they do not decide owner lifetime.

## Consumer Boundary

The Graph Runtime is a composition-root implementation detail. A Consumer gets:

- a declared `CapabilityRequirement`;
- a generation-scoped `CapabilityFacetSet`; or
- a focused wrapper such as `WorkspaceToolCapabilityConsumer`.

A Consumer cannot:

- capture an undeclared facet;
- enumerate arbitrary nodes;
- query a service by string;
- retain a stale facet after generation retirement; or
- reach raw workspace/process/approval internals outside its authority ceiling.

Existing controllers that currently receive `CapabilityCompositionRuntime`
move to focused typed ports. Compatibility properties may remain temporarily,
but they delegate to the mounted Consumer and do not construct or own another
runtime.

## Binding Signature Discipline

No new public `BindingSignature` type is required for the first slice. Current
node signatures already cover planned Definition/Provider metadata,
scope-instance identity, dependency signatures, and an owner-supplied
`binding_input_fingerprint`; the Profile fingerprint currently participates in
the graph assembly fingerprint rather than each node signature. Stable-reference
binding is currently rejected rather than supported.

CLA3 and CLA4 make the resource Provider's fingerprint obligation executable.
Its `binding_input_fingerprint` must cover:

- every fine-grained Profile selection that chooses a resource mechanism;
- the selected mechanism/factory identity and implementation version;
- deterministic mechanism configuration;
- resource Capability scope-instance identity; and
- every supported managed dependency signature that changes construction.

It excludes credentials, callbacks, arbitrary objects, and environment values.
For `harness.resources`, it also excludes resource-bundle content,
Extension/resource content generation, disabled-skill call data, and current
registrations: those change derived content, not the selected mechanism. If a
Provider cannot fingerprint every input that can change the constructed live
mechanism, it is not reusable. The Binder cannot infer completeness from a
hash, so tests vary each declared construction input and prove that the
fingerprint changes while content-only inputs do not.

A named value object may be introduced later only if two independent owners
must exchange or explain the exact signature contract. It must replace the
current private representation rather than coexist with it.

## Failure, Cancellation, And Disposal

The following invariants apply to every migration PR:

- a failed or cancelled candidate never replaces the previous Mount;
- no live registration is visible before its owner Scope commits;
- candidate cleanup is reverse ordered and cancellation shielded;
- cleanup failure is retained as redacted, retryable retirement state;
- pending-retirement projection retains the latest redacted cleanup diagnostic
  code while retry history remains in binding-attempt facts;
- failed Session preparation disposes every untransferred staged value;
- ownership transfer is exactly once and double disposal is impossible;
- publication invalidates replaced Consumer leases before old values can be
  reused as current; and
- shutdown joins pending Extension/resource work before disposing the graph.

The first slice does not create a distributed transaction across Extension and
Graph owners. Unsupported graph-owned hot replacement is rejected before either
authority publishes.

## Fact Clocks And Projection

The current four top-level references remain:

```text
Profile fingerprint
Mount generation
Registration revision
per-call Model Input snapshot
```

Extension generation and Resource snapshot/bundle publication are local source
facts. They are not promoted into `EffectiveRuntimeClocks`, but current
Registration inventory alone is insufficient: immutable Command, hook, flag,
shortcut, renderer, prompt, and Resource declaration changes may publish
without an independent Registration lease.

The resource slice therefore adds one scoped source-publication reference to
the effective view. Its exact public name is chosen during CLA4, but its
versioned data is at least:

```text
schema_version
owner_capability_id
source_runtime_id
extension_generation
declaration_revision
resource_revision
```

The reference enters the effective-view fingerprint and diff. It is a focused
reference owned by `harness.resources`, not a fifth top-level authority clock.
An unpublished candidate never appears. Until canonical Resource revisions
exist, the plan must not describe the current `ResourceSnapshot` as a durable
or versioned clock.

Examples of legitimate skew include:

- a resource contribution refresh with an unchanged Mount signature;
- a failed old-generation registration retirement beside a newer Mount;
- a turn-refreshable private selection beside an unchanged top-level Bundle.

`EffectiveRuntimeView` must label these states, not synthesize a global
generation or classify all skew as corruption. Skew gains a versioned
disposition when evidence is sufficient:

```text
expected_history
expected_refresh
transitional_retirement
invariant_violation
unclassified
```

For example, an old `pending_retirement` entry is transitional; an effective
registration incorrectly attached to an old authoritative source generation is
an invariant violation. Different runtime domains are never compared merely by
numeric generation.

Every model call continues to commit the exact Profile, Mount, registration,
and model-surface references it used. The composition root passes the current
Profile fingerprint explicitly; it is not inferred from the Mount snapshot.
Profile/Mount skew may be legitimate, but Mount and registration must refer to
one committed graph generation before transcript write or transport.

Reconstruction guarantees are deliberately split:

| Fact | Current guarantee |
| --- | --- |
| Runtime Profile snapshot | persisted and available for resume validation |
| Model Input components and snapshot | persisted and exactly rebuildable after source deletion/restart |
| Mount and Registration inventory | committed in-process read models, not historical durable records |
| Extension/resource declaration projection | re-projectable during the current source generation, not executable replay |
| callbacks, Providers, leases, and disposers | never persisted or reconstructed |

Live `explain()` attributes the current effective declarations and
registrations. Restart reconstructs exact model-visible input; it does not
claim to restore historical live registrations. Durable redacted runtime
observation records require a separate boundary decision.

## Delivery Sequence

The sequence uses `CLA` identifiers to avoid confusing this work with the
completed PR0-PR9 convergence series.

### CLA0: Authority And Compatibility Baseline

Zero production behavior change.

Tracking issue: [#453](https://github.com/zhnt/loushang/issues/453). The
executable pre-migration inventory is [Composition Lifecycle Authority CLA0
Baseline](composition-lifecycle-authority-cla0-baseline.md).

- create or identify the new lifecycle-convergence tracking issue before
  production implementation begins;
- enumerate every construction, publication, capture, and disposal site for
  `CapabilityCompositionRuntime`, Graph Runtime, and Extension generations;
- include the bootstrap/final construction binding and the direct
  `AgentSession` fallback constructor as separate entrypoint families;
- classify every resource/session Profile slot as bootstrap infrastructure,
  final-only, or reusable staged candidate;
- freeze supported synchronous construction and asynchronous activation paths;
- record current construction counts and failure behavior; and
- add architecture gates preventing another graph runtime/projector or broad
  service-locator context; and
- freeze the Graph Binder's validation and assembly/node-reuse decisions before
  Provider construction, because staged-candidate ownership depends on it.

Acceptance:

- the baseline fails if a publication owner or `RuntimeProfileBinder` use for
  the target slot set is added silently;
- architecture allowlists fail when a Graph Runtime/Binder/Projector
  construction site appears outside its named composition owner;
- direct and runtime-managed Product entrypoints are both represented;
- per-entrypoint construction-count baselines distinguish repeated construction
  from cleanup leakage;
- no source behavior changes, and the sandbox-safe full-suite baseline passes;
- generated capability catalog status distinguishes a source-complete seam
  from a production-mounted Capability.

### CLA1: Extension Candidate Cleanup Closure

Before moving another owner into the Session graph, close one source-backed
failure window in the current lifecycle.

If synchronous Extension/resource publication fails, publication already rolls
back candidate visibility to staged state. The lifecycle operation nevertheless
remains in flight until asynchronous candidate disposal completes. That
ownership is expressed either by retaining the existing generation gate or by
an explicit host-owned cleanup task joined by the same gate. Session shutdown
must join it rather than dispose only the authoritative generation and report
completion while staged candidate entries remain undisposed. CLA1 closes this
disposal/join window; it does not treat those entries as effective registrations.

Acceptance:

- publication failure racing shutdown leaves no staged candidate registration;
- previous Extension/resource state remains authoritative;
- rollback and shutdown are cancellation-atomic and exactly once;
- no generic transaction manager or new lifecycle lock hierarchy is added; and
- successful publish/retire behavior is unchanged.

Status: implemented. The disposal/join window is closed by the Extension
runner generation gate; no production API or behavior contract beyond that
window changed.

Implemented evidence:

- `src/loushang/harness/extensions/runner.py` retains the generation gate
  until staged-candidate rollback has disposed its registrations, so Session
  shutdown joins in-flight candidate cleanup instead of reporting completion
  early;
- `tests/harness/extensions/test_generation.py::test_cancelled_failed_publication_holds_gate_and_retries_candidate_cleanup`
  covers publication failure racing cancellation with retryable candidate
  cleanup;
- cancellation-atomic shutdown, retired-generation cleanup join, and
  shutdown/retry behavior remain covered by the existing generation tests
  (`test_cancelled_retirement_joins_cleanup_and_keeps_new_generation`,
  `test_candidate_cannot_publish_after_runtime_shutdown_begins`,
  `test_cancelled_shutdown_finishes_retired_and_current_generation_cleanup`,
  `test_shutdown_retains_retryable_retired_generation_cleanup`); and
- no generic transaction manager or new lifecycle lock hierarchy was added.

### CLA2: Session-Owned Graph Runtime

Move graph ownership from `SessionModelCallRuntime` to the Session composition
root without adding another wrapper framework.

- the composition root creates one `RuntimeCapabilityGraphRuntime` and one
  existing Binder;
- the current `harness.model_input` plan and Provider bind through it;
- `SessionModelCallRuntime` receives its typed Consumer and projection ports;
- standard async preparation and direct lazy preparation use one idempotent
  ensure port, evolved from the current idempotent `SessionModelCallRuntime.bind()`
  seed; and
- disposal remains Session-owned and invalidates captured facets.

Acceptance:

- there is one graph runtime per Session/runtime ID;
- all PR6-PR9 model-input reconstruction and diagnostics tests remain valid;
- model-call runtime cannot enumerate or bind the graph;
- a preparation failure leaves no installed Agent preparer or live Mount; and
- Model Input records the explicit current Profile fingerprint while retaining
  separate Mount and Registration references;
- Mount/Registration mismatch causes zero transcript write and zero transport;
- `session-model-call-closure-boundary.md` is revised with the explicit Profile
  source and compatibility contract;
- standalone AI/Agent dependency direction remains unchanged.

### CLA3: Resources Seam And Legacy Side-Question Extraction

Add the source-complete `harness.resources` top-level seam and pure adapters.
This PR does not mount it in the production Session graph and does not create a
peer live runtime. It does include one behavior-preserving production ownership
refactor: `interaction.side_question` is extracted from the mixed compatibility
runtime into a separate legacy Session-owned binding.

- exclude `interaction.side_question` from the Resources Definition/Provider
  and preserve its current bootstrap/final Extension selection through that
  separate legacy binding until the Session Bundle migration;
- keep fine-grained Profile selections as internal facts;
- define how the current standard composition implementations map into one
  Bundle Provider without production construction;
- represent only live external mutations with Registration leases; and
- preserve Product content and policy as injected data/ports.

Acceptance:

- Definition, Provider, requirements, and Consumers are source-complete;
- Profile selection cannot independently publish the Bundle;
- one complete binding-input fingerprint covers all Provider inputs;
- Provider failure/cancellation leaks no registration or staged value; and
- private turn/resource refresh does not create a false Mount generation;
- top-level metadata is Session-scoped, bootstrap-phase, and sealed while the
  private `resource.runtime` slot retains its workspace/sealed semantics; and
- Extension side-question replacement behavior remains covered and unchanged.

### CLA4: Resource Production Mount And Consumer Cutover

Complete the ownership change in one PR. No preceding PR may production-mount
`harness.resources` while a peer-owning resource Profile binding remains live.

- bind one complete target graph containing both `harness.model_input` and
  `harness.resources`; a resources-only plan must not evict model input;
- prompt, Tool, Command, resource-refresh, and skill consumers use focused
  ports or declared facet views;
- synchronous construction uses only an internal staged candidate and immutable
  derived outputs before async activation; bootstrap-only use of the five
  mechanisms goes through private `root_owned` handles rather than a public
  compatibility facade;
- final Graph bind takes ownership exactly once; and
- `CapabilityCompositionRuntime` either becomes a non-owning compatibility
  view or is removed from the supported Product composition path;
- publish the scoped source-publication reference and skew disposition without
  adding another authority; and
- revise `effective-runtime-diagnostics-boundary.md`, its canonical JSON, and
  compatibility tests for those additive/versioned diagnostic values; and
- retain the separate legacy side-question binding until the Session Bundle.

Acceptance:

- the graph snapshot contains exactly the accepted target nodes, including
  model input and resources;
- each of the five resource mechanisms is constructed once across bootstrap and
  final admission for one unchanged signature;
- supported synchronous creation remains API-compatible;
- standard and direct lazy preparation invoke the same idempotent ensure port;
- first turn cannot run before successful Graph preparation;
- cancellation in `root_owned`, `graph_constructing`, and pre-publication states
  disposes exactly once;
- graph-wide or node-level signature reuse skips `create()` and leaves the new
  rejected candidate root-owned for exact disposal;
- prompt/context/skill/Tool/Command ordering, disabled-skill behavior, and
  Extension Tool adoption remain compatible;
- content-only refresh and rollback leave Mount generation unchanged;
- graph disposal invalidates all Resource Consumer leases;
- current live explain attributes effective source/registration facts, while
  restart tests reconstruct exact Model Input without current source files; and
- no production Session field owns a peer resource Profile Binder;
- the architecture gate prohibiting peer Profile Binder ownership for the
  migrated resource slot set becomes active in this PR, not CLA8.

Status: implemented. The Resources production mount and Consumer cutover
landed first; the residual compatibility-surface closure renamed the staged
construction vehicle so the supported Product composition path no longer
exposes a peer-owning runtime type.

Implemented evidence:

- the synchronous construction vehicle is `StagedResourceCompositionCandidate`
  (`src/loushang/harness/capabilities/composition_runtime.py`), a staged
  candidate with exactly-once transferable ownership
  (`root_owned` / `graph_constructing` / `graph_owned` / `disposed`), not a
  peer live runtime; after the graph claim it is a non-owning compatibility
  view and the graph owns release;
- all supported Product construction families pass that narrow candidate:
  managed bootstrap (`coding/bootstrap.py::_CODING_AGENT_PRODUCT_CONSTRUCTION`
  via `bind_capabilities`), which late-selects the final Extension profile
  onto that same staged candidate through `resolve_session_capability_profile`
  and `StagedResourceCompositionCandidate.select_final_profile`, so the five
  resource mechanisms are constructed exactly once; and the direct
  `AgentSession` fallback (`coding/session/agent_session.py::AgentSession.__init__`),
  which stages one candidate via `stage_resource_composition_candidate`
  directly or via `CodingCapabilityProfileResolution.bind`;
- bootstrap-only mechanism use goes through the private
  `_RootOwnedResourceCapabilityHandles` and the focused
  `SessionResourceCapabilityPorts`, never a public compatibility facade;
- the architecture gates remain active and renamed with the source:
  `tests/architecture/test_composition_lifecycle_authority_cla0.py::test_cla4_session_has_no_peer_resource_profile_owner`,
  `test_cla4_resources_provider_has_one_production_mount_owner`,
  `test_current_entrypoint_construction_counts_are_frozen`, and
  `test_graph_and_profile_construction_sites_match_cla0_allowlist`; and
- the generated catalog records `harness.resources` as `production-mounted`
  with one Provider construction owner and no direct production Resource
  Consumer construction.

CLA0 through CLA4 form the next-stage completion milestone.

### CLA5: Workspace Production Mount

Wire the existing, source-complete `harness.workspace` seam into the
Session-owned graph as an independent follow-up.

- Product composition supplies already authorized workspace operations and
  process launcher through the existing Provider binding;
- Tool and process consumers receive only declared facet views;
- raw gateways and Product services remain outside the Bundle; and
- the catalog records production-mounted status only after this cutover.

A future `harness.resources -> harness.workspace` dependency requires a concrete
Resource Consumer and a separate accepted loader cutover; it is not implied by
co-location in one graph.

Implemented evidence:

- Coding supplies a root-bounded filesystem adapter and one authorized process
  launcher under a deterministic workspace-scope fingerprint;
- generic Products without a workspace binding retain the two-root
  model-input/resources graph, while Coding mounts Workspace as the third
  independent root;
- Session Tool and process callers route through typed, lease-aware Consumers;
  each Tool receives only its explicitly declared operation binding;
- LSP shares the graph-backed process port without binding another launcher;
- raw Sandbox, approval, policy, and process-host services remain outside the
  Bundle and retain their existing Product cleanup owner; and
- Provider-owned derived cleanup failures remain visible and retryable through
  the Session Graph retirement path.

### CLA6: Extension Declaration Bridge

After the resource milestone is stable:

- initial Extension declarations participate in final pure plan/admission;
- content-only runtime refresh retains the existing Extension/Resource
  generation transaction and leaves Mount unchanged;
- an attempted graph-owned Provider replacement fails with a typed
  restart-required diagnostic; and
- exact Extension registrations continue to expose pending retirement facts.

This PR does not implement graph hot replacement. It adds failure-evidence tests
for the typed restart-required diagnostic rather than silently replacing the
whole Extension generation.

Implemented evidence:

- each prepared generation freezes a canonical, redacted declaration snapshot;
- Coding reuses its pure admission and Profile resolver to compare effective
  graph-owned resource inputs; CLA7a extends the same preflight to the admitted
  Session side-question input without comparing callback identity or content;
  losing or content-only declarations are not compared as Provider inputs;
- the Product-injected preflight runs before resource discovery, candidate
  activation, registration publication, or another Graph bind;
- content-only refresh advances Extension and Resource publication facts while
  preserving the current Mount generation and Consumer leases;
- graph-owned Resource or Session input changes fail with the typed
  `extension_graph_provider_restart_required` diagnostic exactly once, retain
  the old Extension/Resource/Session/Mount authorities, and join candidate
  rollback;
  and
- the bridge contains values and a narrow validation port only; it adds no
  Provider registry, graph manager, projector, or hot-replacement transaction.

### CLA7: `harness.session` Bundle

Migrate the Session facets in lifecycle-honest slices. Reuse the Session-owned
graph established by CLA2; do not create a second graph or a broad Session
facade. Each slice moves only after its scope, refresh boundary, restart
behavior, and stable-reference requirement are explicit.

1. **CLA7a — side question (implemented).** Contract version 1 defines the
   sealed `interaction.side_question` facet. The already-focused legacy binding
   becomes a staged candidate, transfers to the Graph exactly once, and is
   consumed through a generation-scoped lease. Active work is cancelled and
   joined before Provider disposal. Extension selection remains sealed and
   restart-required rather than hot-replaced.
2. **CLA7b — transcript lifecycle trio (implemented).** `conversation.store`,
   `agent.transcript_profile`, and `context.compaction` share one existing
   `AgentTranscriptProfileRuntime` binding and must transfer together. The
   slice must preserve session-header/resume compatibility, index publication
   before release, turn-boundary compaction behavior, and cleanup retry. It may
   not reconstruct the store or split one disposer across logical owners.
3. **CLA7c-resources — Resources dependency cutover (implemented).** One
   focused Session Consumer now uses the admitted Resource composition through
   `harness.session -> harness.resources`; Resources is no longer a peer root.
4. **CLA7c-workspace — Workspace dependency cutover (implemented).** Two
   least-authority Session Consumers use the optional admitted Workspace
   dependency; Coding no longer keeps Workspace as a co-root.
5. **CLA7d — continuity stable reference (implemented).** `continuity.provider_packs` remains
   Process-scoped. It requires a process-owned typed stable lease/reference and
   shutdown order before a Session Consumer can observe it. The Session Graph
   never owns the concrete ContinuityHub. The accepted design boundary is
   [Continuity Stable Reference Boundary](continuity-stable-reference-boundary.md).

Implemented CLA7a evidence:

- one source-backed Definition / Provider / Consumer seam is production
  mounted by the existing `AgentProductSession` graph;
- Product bootstrap and direct construction pass one root-owned candidate;
- construction failure restores root ownership, graph publication transfers
  ownership, graph/node reuse leaves a rejected candidate root-owned, and
  release retries retain the exact graph owner;
- the Consumer revalidates its facet lease on each call and cached access is
  stale after Graph retirement; and
- the generated catalog and architecture gates identify exactly one Provider
  construction owner and one Consumer capture owner.

Implemented CLA7b evidence:

- contract version 2 adds the Store/Profile/Compaction facets to the same
  `harness.session` Provider; no second Provider, Binder, graph, or host-hidden
  dependency is introduced;
- the existing `AgentTranscriptProfileRuntime` binding transfers as one
  root-owned candidate, so Store/Profile/Compaction identity and the persisted
  Runtime Profile header remain unchanged;
- `harness.model_input` declares its direct transcript requirement on
  `harness.session`, so Session is in the dependency closure rather than a
  peer root or hidden host closure;
- Model Input and compaction use a stable narrow port that switches to one
  generation-scoped transcript Consumer in the Graph publication window;
- shutdown joins active work, attempts index publication, then retires the
  transcript binding; failed async disposers retain only failed entries for a
  real Graph retirement retry; and
- durable create/load/open/continue/fork, Model Input restart/rebuild, and
  compaction commit-point regressions remain the acceptance gates.

Implemented CLA7c-resources evidence:

- Session contract version 3 adds one bounded `resource.composition` facet and
  the combined Provider declares one aggregate Resources requirement;
- the Provider keeps the raw dependency binding private and exposes only
  method-shaped operations through a generation-scoped Session Consumer;
- existing stable resource ports use the root-owned candidate before Mount and
  switch once to that Session Consumer after Graph publication;
- production no longer constructs the four direct Resources Consumers;
- generic roots are exactly `harness.model_input`; during this slice Coding
  still kept `harness.workspace` as a deferred co-root; and
- content-only Resource/Extension refresh changes source-publication facts but
  does not rebind the Graph or change Mount generation.

Implemented CLA7c-workspace evidence:

- Session contract version 4 adds separate Tool-operation and process-launch
  facets backed by one optional aggregate Workspace dependency;
- generic Products without a Workspace Provider omit that node, while Coding
  realizes `harness.session -> harness.workspace` without a placeholder;
- both generic and Coding production roots are exactly `harness.model_input`;
- production constructs no direct Workspace Consumers; stable Workspace ports
  switch to two Session Consumers only after the single Graph publication;
- cached operation and launcher proxies revalidate the Session generation on
  every call and become stale after Session retirement, including when the
  Workspace node is reused; and
- authority ceilings, raw policy/approval/Sandbox internals, the single process
  launcher binding, and Workspace cleanup ownership remain unchanged.

Implemented CLA7d evidence:

- the accepted design boundary is [Continuity Stable Reference
  Boundary](continuity-stable-reference-boundary.md), revised through a
  three-reviewer pass before implementation;
- `StableContinuityReference` and the frozen `ContinuityObservationDescriptor`
  live in `src/loushang/harness/continuity/reference.py` and are issued only
  through `ContinuityHub.reference()`; every verb revalidates liveness through
  a synchronous admit-and-register step with no intervening `await`;
- `ContinuityHub.close()` is one idempotent, cancellation-atomic operation
  that stales outstanding references, aborts every issued-but-unconsumed
  `PreparedActivationLease` with its existing idempotent abort semantics, and
  joins in-flight reference-guarded operations exactly once; a cancelled close
  leaves the hub closing and unclosed so a retry converges;
- `CodingContinuityComposition.shutdown()` is restructured close-then-record:
  the hub closes before the Profile binding is disposed, and shutdown is
  recorded only after both succeed, so a failed close remains retryable;
- all five former raw-hub consumers (the CLI resume flow,
  `coding/ui/screen_surfaces.py`, `harnesstui/conversation/agent_surfaces.py`,
  `harnesstui/continuity/runner.py`, and `harnesstui/continuity/surface.py`)
  now thread the typed reference; surface domain/sort options flow through the
  frozen issuance-time observation descriptor;
- the architecture gate
  `tests/architecture/test_composition_lifecycle_authority_cla0.py::test_cla7d_continuity_has_one_process_authority_and_typed_reference`
  freezes `ContinuityHub` construction to `coding/continuity.py`, reference
  issuance to `ContinuityHub.reference()`, and prohibits the `ContinuityHub`
  name across `harness/session/`, `harnesstui/`, `coding/cli/`, and
  `coding/ui/` sources;
- the graph `stable_reference` requirement binding remains fail-closed
  (`tests/harness/capabilities/test_graph_binding.py`);
- reference lifecycle, admit protocol, close join/cancellation, activation
  lease abort, and synthetic Session-holder release/force-stale paths are
  covered by `tests/harness/continuity/test_stable_reference.py`, and
  close-then-record ordering and retryability by
  `tests/coding/test_continuity.py`; and
- continuity remains Process-owned with no graph node, so the generated
  catalog and current owner map are unchanged.

### CLA8: Legacy Authority Closure

Status: implemented.

- removed the unused `stage_coding_resource_composition_candidate` factory and
  the `AgentProductConstructionBinding.bind_session_capabilities` callback;
- reduced managed Product construction to one root-owned
  `StagedResourceCompositionCandidate`: admitted Extension facts are selected
  in place through `resolve_session_capability_profile` and
  `select_final_profile`, then the candidate transfers to the Session Graph;
- extended the executable authority gate to reject the removed factory,
  callback, and peer composition-runtime symbol while retaining an exact
  allowlist for every `RuntimeProfileBinder` construction site;
- revised the CLA0 AUTH/ENTRY/SLOT/ORDER inventory, current owner map, and
  Harness index to describe the implemented post-CLA8 topology;
- verified the generated catalog still reports the four production-mounted
  Session graph seams without introducing a duplicate authority; and
- covered successful single-candidate handoff, construction-failure cleanup,
  source-generation restart/rollback, projection, and reconstruction through
  focused lifecycle tests and the Harness integration gate.

## Non-Normative Workload Estimate

The initial planning range, including focused tests and the required boundary
document revisions, is:

| Slice | Estimate |
| --- | --- |
| CLA0 | 2-3 person-days |
| CLA1 | 3-5 person-days |
| CLA2 | 5-8 person-days |
| CLA3 | 5-8 person-days, including side-question extraction |
| CLA4 | 8-13 person-days |

CLA0 through CLA4 therefore have a rough `25-40` person-day integration range
after contingency. These numbers are scheduling heuristics, not acceptance
criteria or justification for combining ownership changes into a giant PR.

## Cross-PR Acceptance Gates

Every implementation PR must prove, in proportion to its scope:

- one Provider construction for one unchanged binding signature;
- one graph publication point for one Mount generation;
- previous runtime remains usable after candidate failure or cancellation;
- no leaked Tool, Command, hook, listener, resource, or Capability registration;
- exact restoration of the previous winner where the typed Registry supports
  replacement;
- no undeclared Consumer facet or graph/service-locator access;
- sync construction and async activation retain their documented ownership;
- shutdown joins pending source-generation work before graph disposal;
- live `explain()` attributes current effective Tool, prompt source, Provider,
  declaration, and registration facts without credentials or callbacks;
- restart/source-deletion tests reconstruct exact committed model-visible input
  without claiming historical live registration recovery; and
- clock-skew diagnostics name every compared component clock.

The integration gate includes focused lifecycle tests, architecture tests,
Product smoke behavior, `git diff --check`, Ruff for changed Python, and
`make check-harness` before lane integration.

## Explicit Non-Goals

- no global mutable plugin context or service locator;
- no generic `Contribution[Any]` or `Registry[str, Any]`;
- no second graph Binder, Runtime, Projector, or composition transaction;
- no conversion of every Profile slot or contribution into a graph node;
- no registration lease for immutable declarations;
- no forced Mount generation for a private facet or content-only Extension
  refresh;
- no graph-owned Provider hot replacement in the first milestone;
- no breaking conversion of the public synchronous Session constructor to
  async; and
- no new Product policy, storage authority, Agent loop, or AI transport seam.

## Completion Criteria And Expected Architectural Effect

The CLA stage is complete: `harness.model_input`, `harness.resources`,
`harness.session`, and optional `harness.workspace` share one Session-owned
graph lifecycle; the standard Product path has no peer-owning composition
runtime or late second-candidate binder; Extension content refresh retains an
independent source clock; and effective model-visible facts remain
reconstructible.

As a non-normative planning heuristic, that milestone may move the overall
Harness architecture from the current high-eight range to roughly `9.1-9.3`,
chiefly through reduced duplicate construction, clearer replacement boundaries,
and a smaller compatibility surface. This estimate is not an acceptance gate.
Reaching `9.4+` additionally requires broader Extension bridge evidence, a
second Product composition, and long-running operational proof. Lifecycle
convergence alone does not justify a `9.6` claim.

# Composition Lifecycle Authority CLA0 Baseline

Status: implemented CLA0 evidence baseline, revised through CLA8 closure for issue
[#453](https://github.com/zhnt/loushang/issues/453).

This document originally froze the pre-migration construction and publication
topology for the accepted [Capability Composition Lifecycle Authority
Plan](composition-lifecycle-authority-plan.md). It now records the implemented
topology after CLA8. Each later CLA revision changed a row only together with
its source, tests, and architecture allowlist.

The inventory is deliberately about lifecycle authority. It is not another
runtime registry, service locator, graph, or effective-state projection.

## Lifecycle Authority Inventory

Each row identifies one current authority transition or supported call-site
family. Repeated call sites within tests are not separate authorities.

| ID | Object / phase | Current owner and exact site | Frozen behavior and evidence |
| --- | --- | --- | --- |
| AUTH-01 | Profile-backed composition construction | `src/loushang/harness/capabilities/composition_runtime.py::stage_resource_composition_candidate` | Creates the only `RuntimeProfileBinder` that binds the resource/composition target slots, then returns one owning `StagedResourceCompositionCandidate`. |
| AUTH-02 | Managed bootstrap construction | `src/loushang/coding/bootstrap.py::_CODING_AGENT_PRODUCT_CONSTRUCTION` -> `src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct` | Calls `bind_capabilities` once before Extension discovery. |
| AUTH-03 | Managed final selection | `src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct` -> `StagedResourceCompositionCandidate.select_final_profile` | Resolves admitted Extension selection facts once and attaches them to the same bootstrap candidate without constructing a late peer runtime. `tests/harness/test_agent_bootstrap.py::test_agent_product_construction_resolves_final_profile_without_rebinding_resources` |
| AUTH-04 | Direct Session fallback construction | `src/loushang/coding/session/agent_session.py::AgentSession.__init__` | With no injected runtime, constructs exactly one composition runtime, using the admitted Extension profile when a runner exists and the Product profile otherwise. |
| AUTH-05 | Composition capture | `src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct`, `src/loushang/harness/session/agent_product.py::AgentProductSession._ensure_session_graph_prepared`, and `src/loushang/coding/session/agent_session.py::AgentSession.__init__` | Bootstrap receives focused root-owned handles. The Session Graph claims the same staged Resource candidate and publishes declared Resources, Session, and Workspace Consumers; callers do not receive a Graph Runtime or string-keyed locator. |
| AUTH-06 | Composition disposal | `src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct`, `src/loushang/harness/session/agent_product.py::AgentProductSession._dispose_owned_model_call_runtime`, and `src/loushang/harness/session/operations_runtime.py::AgentSessionOperationsRuntime._dispose_runtime_cancellation_atomic` | Construction failure disposes the one root-owned candidate once. Successful Graph transfer moves cleanup to the Provider/Graph owner; shutdown joins work and retires graph-owned bindings in owner order. `tests/harness/test_agent_bootstrap.py::test_agent_product_construction_disposes_single_candidate_on_failure` |
| AUTH-07 | Graph construction | `src/loushang/harness/session/agent_product.py::AgentProductSession.__init__` | The sole production construction site creates one Session-owned `RuntimeCapabilityGraphRuntime`, one `RuntimeCapabilityGraphBinder`, and one read-only Projector for `harness.model_input`, `harness.resources`, `harness.session`, and optional `harness.workspace`. `tests/harness/session/test_agent_product_contract.py::test_agent_product_sessions_keep_compaction_strategy_and_state_isolated` |
| AUTH-08 | Graph publication | `src/loushang/harness/capabilities/graph_binding.py::RuntimeCapabilityGraphBinder.bind` | Commits staged registration scopes and assigns nodes, generation, and snapshot in one no-`await` publication window. |
| AUTH-09 | Graph capture | `src/loushang/harness/session/agent_product.py::AgentProductSession._ensure_session_graph_prepared` | Only after successful bind, the Session root captures declared generation-scoped Model Input, Session, Resources, and Workspace Consumers. Focused runtimes receive typed Consumers or stable narrow ports rather than the Graph Runtime. `tests/harness/session/test_agent_product_contract.py::test_agent_product_sessions_keep_compaction_strategy_and_state_isolated` |
| AUTH-10 | Graph disposal | `src/loushang/harness/session/agent_product.py::AgentProductSession._dispose_owned_model_call_runtime` -> `src/loushang/harness/capabilities/graph_binding.py::RuntimeCapabilityGraphBinder.dispose` | Session-owned disposal clears captured Consumers, invalidates graph leases, and retires current plus retained Provider cleanup state, including transferred candidates. `tests/harness/capabilities/test_graph_binding.py::test_graph_dispose_retries_retryable_provider_cleanup` |
| AUTH-11 | Extension candidate construction | `src/loushang/harness/extensions/runner.py::ExtensionRunner.prepare_generation` | Creates exactly one unpublished candidate runner for the next source generation; active `LoadedExtension` and API identities cannot be reused. `tests/harness/extensions/test_generation.py::test_prepare_generation_rejects_active_extension_or_api_identity_reuse` |
| AUTH-12 | Extension registration staging | `src/loushang/harness/extensions/runner.py::PreparedExtensionGeneration.activate` | Holds the host lifecycle gate while the candidate activates generation-scoped entries in staged state. |
| AUTH-13 | Extension/private composition publication | `src/loushang/harness/extensions/runner.py::PreparedExtensionGeneration.publish` -> `src/loushang/harness/extensions/runner.py::ExtensionRunner._publish_generation` | Commits candidate registration scopes, swaps private composition state and generation, and invokes the Resource publication callback synchronously. `tests/harness/extensions/test_generation.py::test_failed_generation_publication_restores_old_runtime_and_context` |
| AUTH-14 | Extension/resource refresh orchestration | `src/loushang/harness/session/resource_refresh.py::SessionResourceRefreshRuntime.reload_extension_generation` | Discovers, activates, publishes, then retires a candidate; failure restores the prior Resource view before awaiting candidate rollback. `tests/harness/session/test_resource_refresh.py::test_failed_publication_restores_old_resource_before_async_candidate_cleanup` |
| AUTH-15 | Extension rollback and retirement | `src/loushang/harness/extensions/runner.py::PreparedExtensionGeneration.rollback`, `ExtensionGenerationRetirement.retire`, and `ExtensionRunner.dispose_runtime_generation` | Candidate rollback, old-generation retirement, and shutdown cleanup remain Extension-owned. Retryable old entries remain explicit retirement facts. |

## Supported Entrypoints And Current Counts

Counts are per attempted Session construction unless the row says otherwise.
They record current post-CLA8 behavior.

| ID | Entrypoint family | Current composition count | Current Graph / Extension count | Failure behavior |
| --- | --- | --- | --- | --- |
| ENTRY-01 | Runtime-managed Product with final Extension profile resolution | one `StagedResourceCompositionCandidate`, built before discovery and final-selected in place | one Session-owned Capability Graph; one stable Extension runner | Construction failure disposes the single root candidate; successful graph claim transfers it exactly once. |
| ENTRY-02 | Runtime-managed Product without final profile resolution | one staged candidate, reused by the Session | one Session-owned Capability Graph | The single candidate transfers to Session Graph ownership; root cleanup is idempotent after transfer. |
| ENTRY-03 | Direct `AgentSession` with injected staged candidate | zero new staged candidates | one Session-owned Capability Graph when normal AgentProduct composition is installed | The injected candidate follows the same final-selection and graph-transfer contract. |
| ENTRY-04 | Direct `AgentSession` without an injected staged candidate | one fallback staged candidate | one Session-owned Capability Graph when normal AgentProduct composition is installed | Constructor failure remains responsible for the one locally created candidate. |
| ENTRY-05 | One Extension reload attempt with a Resource bundle | no new Profile composition candidate | one unpublished candidate runner in addition to the stable host runner | Publish failure restores old Extension/Resource visibility, then the joined reload/shutdown lifecycle retires staged candidate entries. |

The removed two-candidate late-binder path is not a supported entrypoint. The
CLA8 architecture gate forbids both its factory and construction callback from
returning to production source.

## Standard Profile Slot Classification

The class is the required ownership shape for this migration stage:

- `bootstrap-infrastructure`: fixed mechanics required to load/resume or obtain
  declarations, not reconstructed after Extension admission;
- `final-only`: constructed only after final admission; or
- `reusable-staged-candidate`: constructed once before final publication,
  fingerprinted completely, and transferred or disposed exactly once.

The table covers every slot returned by
`src/loushang/harness/runtime/_profile_standard.py::standard_runtime_capability_slots`.

| ID | Slot | CLA class | Reason and current owner boundary |
| --- | --- | --- | --- |
| SLOT-01 | `conversation.store` | `bootstrap-infrastructure` | Session/sealed Product/OEM store mechanics are required to open or resume durable conversation state; the focused transcript candidate is transferred through the combined Session Provider. |
| SLOT-02 | `agent.transcript_profile` | `bootstrap-infrastructure` | Session/sealed Product/OEM codec/profile mechanics remain part of the same indivisible transcript candidate transferred through the Session Provider. |
| SLOT-03 | `context.compaction` | `final-only` | The final-selected compaction mechanism is carried in that indivisible transcript candidate; Model Input receives a stable narrow Session Consumer. |
| SLOT-04 | `resource.runtime` | `bootstrap-infrastructure` | Workspace/sealed Product/OEM activation mechanics are required while loading and activating Resource declarations; backend replacement is restart-only. |
| SLOT-05 | `prompt.sections` | `reusable-staged-candidate` | The mechanism is used during bootstrap prompt assembly, final-selected in place, then transferred once through the Resources Provider. |
| SLOT-06 | `skill.activation` | `reusable-staged-candidate` | The mechanism participates in bootstrap Resource admission, while its Session/turn selection admits final layers. |
| SLOT-07 | `tool.packs` | `reusable-staged-candidate` | Bootstrap and admitted Extension Tool packs must be composed without constructing a peer final owner. Only installed live Tools receive registration leases. |
| SLOT-08 | `command.packs` | `reusable-staged-candidate` | The composer follows the same staged ownership rule as Tool packs; immutable pack declarations do not receive leases. |
| SLOT-09 | `interaction.side_question` | `final-only` | The optional Session/sealed Extension-replaceable binding is admitted after discovery and transferred through the combined `harness.session` Provider. |
| SLOT-10 | `continuity.provider_packs` | `bootstrap-infrastructure` | Optional Process/sealed Product/OEM packs bind once in the focused continuity owner and are exposed only through `StableContinuityReference`; continuity remains outside the Session Graph. |

These classes do not change slot scope, refresh boundary, source ceiling, or
variation semantics. They classify construction ownership only.

## Ordering And Failure Invariants

| ID | Frozen invariant | Source/evidence |
| --- | --- | --- |
| ORDER-01 | Plan/type validation and Provider indexing occur before any Provider `construct()` call. | `src/loushang/harness/capabilities/graph_binding.py::RuntimeCapabilityGraphBinder.bind`; `tests/harness/capabilities/test_graph_binding.py::test_binder_fails_closed_before_constructing_stable_reference_plan` |
| ORDER-02 | Graph-wide assembly reuse is decided before the node loop and before any Provider `construct()` call. | `src/loushang/harness/capabilities/graph_binding.py::RuntimeCapabilityGraphBinder.bind`; `tests/harness/capabilities/test_graph_binding.py::test_bootstrap_to_final_bind_reuses_unchanged_workspace_mount` |
| ORDER-03 | Per-node binding-signature reuse is decided before creating a registration scope or calling Provider `construct()`. | `src/loushang/harness/capabilities/graph_binding.py::RuntimeCapabilityGraphBinder.bind` |
| ORDER-04 | A failed or cancelled Graph bind preserves the prior authoritative Mount and reverses staged work. | `tests/harness/capabilities/test_graph_binding.py::test_failed_binding_rolls_back_registrations_and_keeps_old_graph`; `tests/harness/capabilities/test_graph_binding.py::test_cancelled_binding_rolls_back_before_preserving_old_authority` |
| ORDER-05 | Extension publication rollback makes candidate registrations staged/invisible synchronously; asynchronous disposal follows in the same reload operation. | `src/loushang/harness/extensions/runner.py::ExtensionRunner._publish_generation`; `tests/harness/session/test_resource_refresh.py::test_staged_extension_reload_rolls_back_failed_candidate_without_commit` |
| ORDER-06 | Session shutdown joins in-flight source generations, Graph, task, Extension generation, Profile, and composition cleanup in owner order; retryable retirement remains explicit. | `src/loushang/harness/session/operations_runtime.py::AgentSessionOperationsRuntime._dispose_runtime_cancellation_atomic` |

The validation/reuse-before-construction ordering is an ownership dependency,
not an incidental optimization. A future staged candidate rejected by Graph
reuse must remain root-owned and be disposed by that root.

## Architecture Allowlist

The executable authority gates freeze these production construction sites:

- `RuntimeCapabilityGraphRuntime`, `RuntimeCapabilityGraphBinder`, and
  `RuntimeCapabilityGraphProjector`: `AgentProductSession.__init__` only;
- `RuntimeProfileBinder`: focused construction in `bind_coding_continuity`,
  `stage_resource_composition_candidate`,
  `resources_capability_provider_binding.create`, `bind_legacy_side_question`,
  and `AgentTranscriptProfileRuntime.__init__` only; and
- `StagedResourceCompositionCandidate`: constructed only by
  `stage_resource_composition_candidate`.

These sites are focused Process owners, staged-candidate factories, or
Provider-owned transfers. No Session peer Profile owner remains. CLA8 also
forbids the removed late-binder factory, its construction callback, and the old
peer composition runtime symbol across production source.

The gate intentionally rejects renamed imports, assignment aliases, and
subclasses of guarded constructors, even when an alias is not invoked. Lambda
bodies receive their own scope so lazy construction cannot inherit an
allowlisted outer owner accidentally. This is a reviewability constraint, not
a claim to prove arbitrary reflective or dynamic Python data flow.

## Capability Catalog Status

The generated catalog uses two statuses:

- `source-complete`: Definition, Provider, requirement, and Consumer exist, but
  no production composition reference is declared; and
- `production-mounted`: the generator declares a production composition
  reference and verifies that it resolves to a callable source symbol. The
  construction allowlist independently verifies the current mount owner.

At CLA8 closure, `harness.model_input`, `harness.resources`, `harness.session`
v4, and `harness.workspace` are production-mounted in the one Session-owned
graph. Catalog status is documentation metadata only and is never consulted by
runtime composition.

## CLA8 Closure

CLA0 remains the executable inventory shape; CLA8 closes its migration. The
inventory, exact construction allowlists, forbidden legacy symbols, ordering
gate, generated catalog, focused lifecycle tests, and Harness integration gate
must now pass together. Any future authority change must revise all of those
artifacts in the same change.

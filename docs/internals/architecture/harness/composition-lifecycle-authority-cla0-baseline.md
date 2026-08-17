# Composition Lifecycle Authority CLA0 Baseline

Status: implemented CLA0 evidence baseline for issue
[#453](https://github.com/zhnt/loushang/issues/453).

This document freezes the pre-migration construction and publication topology
for the accepted [Capability Composition Lifecycle Authority
Plan](composition-lifecycle-authority-plan.md). CLA0 changes no production
behavior.
Later CLA work may revise a row only together with its source, tests, and
architecture allowlist.

The inventory is deliberately about lifecycle authority. It is not another
runtime registry, service locator, graph, or effective-state projection.

## Lifecycle Authority Inventory

Each row identifies one current authority transition or supported call-site
family. Repeated call sites within tests are not separate authorities.

| ID | Object / phase | Current owner and exact site | Frozen behavior and evidence |
| --- | --- | --- | --- |
| AUTH-01 | Profile-backed composition construction | `src/loushang/harness/capabilities/composition_runtime.py::bind_capability_composition_runtime` | Creates the only `RuntimeProfileBinder` that binds the resource/composition target slots, then returns one owning `CapabilityCompositionRuntime`. |
| AUTH-02 | Managed bootstrap construction | `src/loushang/coding/bootstrap.py::_CODING_AGENT_PRODUCT_CONSTRUCTION` -> `src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct` | Calls `bind_capabilities` once before Extension discovery. |
| AUTH-03 | Managed final construction | `src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct` -> `src/loushang/coding/runtime_capability_admission.py::bind_coding_capability_composition_runtime` | When a late binder is configured, calls it once after final Extension admission and gives the final runtime to the Session. `tests/harness/test_agent_bootstrap.py::test_agent_product_construction_late_binds_session_capabilities_and_disposes_bootstrap` |
| AUTH-04 | Direct Session fallback construction | `src/loushang/coding/session/agent_session.py::AgentSession.__init__` | With no injected runtime, constructs exactly one composition runtime, using the admitted Extension profile when a runner exists and the Product profile otherwise. |
| AUTH-05 | Composition capture | `src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct` and `src/loushang/coding/session/agent_session.py::AgentSession.__init__` | Broad compatibility ports and the Session retain the concrete composition runtime; no typed Bundle lease exists yet. |
| AUTH-06 | Composition disposal | `src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct` and `src/loushang/harness/session/operations_runtime.py::AgentSessionOperationsRuntime._dispose_runtime_cancellation_atomic` | Bootstrap/final failure paths and Session shutdown dispose every owned runtime. Repeated construction is not classified as a cleanup leak. `tests/harness/test_agent_bootstrap.py::test_agent_product_construction_disposes_late_bound_capabilities_on_failure` |
| AUTH-07 | Graph construction | `src/loushang/harness/session/agent_product.py::AgentProductSession.__init__` | The sole production construction site creates one Session-owned `RuntimeCapabilityGraphRuntime`, one `RuntimeCapabilityGraphBinder`, and one read-only Projector for `harness.model_input`. `tests/harness/session/test_agent_product_contract.py::test_agent_product_sessions_keep_compaction_strategy_and_state_isolated` |
| AUTH-08 | Graph publication | `src/loushang/harness/capabilities/graph_binding.py::RuntimeCapabilityGraphBinder.bind` | Commits staged registration scopes and assigns nodes, generation, and snapshot in one no-`await` publication window. |
| AUTH-09 | Graph capture | `src/loushang/harness/session/agent_product.py::AgentProductSession._ensure_session_graph_prepared` | The Session root captures the declared model-input requirement only after a successful bind. Standard preparation and direct lazy sampling share this idempotent port; `SessionModelCallRuntime` receives the typed Consumer rather than the Graph Runtime. `tests/harness/session/test_agent_product_contract.py::test_agent_product_sessions_keep_compaction_strategy_and_state_isolated` |
| AUTH-10 | Graph disposal | `src/loushang/harness/session/agent_product.py::AgentProductSession._dispose_owned_model_call_runtime` -> `src/loushang/harness/capabilities/graph_binding.py::RuntimeCapabilityGraphBinder.dispose` | Session-owned disposal clears its captured Consumer, invalidates graph leases, and retires current plus retained cleanup state. `tests/harness/capabilities/test_graph_binding.py::test_graph_dispose_retries_retryable_provider_cleanup` |
| AUTH-11 | Extension candidate construction | `src/loushang/harness/extensions/runner.py::ExtensionRunner.prepare_generation` | Creates exactly one unpublished candidate runner for the next source generation; active `LoadedExtension` and API identities cannot be reused. `tests/harness/extensions/test_generation.py::test_prepare_generation_rejects_active_extension_or_api_identity_reuse` |
| AUTH-12 | Extension registration staging | `src/loushang/harness/extensions/runner.py::PreparedExtensionGeneration.activate` | Holds the host lifecycle gate while the candidate activates generation-scoped entries in staged state. |
| AUTH-13 | Extension/private composition publication | `src/loushang/harness/extensions/runner.py::PreparedExtensionGeneration.publish` -> `src/loushang/harness/extensions/runner.py::ExtensionRunner._publish_generation` | Commits candidate registration scopes, swaps private composition state and generation, and invokes the Resource publication callback synchronously. `tests/harness/extensions/test_generation.py::test_failed_generation_publication_restores_old_runtime_and_context` |
| AUTH-14 | Extension/resource refresh orchestration | `src/loushang/harness/session/resource_refresh.py::SessionResourceRefreshRuntime.reload_extension_generation` | Discovers, activates, publishes, then retires a candidate; failure restores the prior Resource view before awaiting candidate rollback. `tests/harness/session/test_resource_refresh.py::test_failed_publication_restores_old_resource_before_async_candidate_cleanup` |
| AUTH-15 | Extension rollback and retirement | `src/loushang/harness/extensions/runner.py::PreparedExtensionGeneration.rollback`, `ExtensionGenerationRetirement.retire`, and `ExtensionRunner.dispose_runtime_generation` | Candidate rollback, old-generation retirement, and shutdown cleanup remain Extension-owned. Retryable old entries remain explicit retirement facts. |

## Supported Entrypoints And Current Counts

Counts are per attempted Session construction unless the row says otherwise.
They record current behavior, not the CLA4 target.

| ID | Entrypoint family | Current composition count | Current Graph / Extension count | Failure behavior |
| --- | --- | --- | --- | --- |
| ENTRY-01 | Runtime-managed Product with final Extension binder | two `CapabilityCompositionRuntime` instances: one bootstrap and one final | one model-call Graph per constructed Session; one stable Extension runner | Final construction failure disposes final then bootstrap; successful handoff disposes bootstrap and Session owns final. |
| ENTRY-02 | Runtime-managed Product without a late binder | one composition runtime, reused by the Session | one model-call Graph per constructed Session | The single runtime transfers to Session ownership; root cleanup skips the transferred instance. |
| ENTRY-03 | Direct `AgentSession` with injected composition runtime | zero new composition runtimes | one model-call Graph when normal AgentProduct composition is installed | Caller/Session ownership follows the injected runtime contract. |
| ENTRY-04 | Direct `AgentSession` without injected composition runtime | one fallback composition runtime | one model-call Graph when normal AgentProduct composition is installed | Constructor failure remains responsible for the one locally created runtime. |
| ENTRY-05 | One Extension reload attempt with a Resource bundle | no new Profile composition runtime | one unpublished candidate runner in addition to the stable host runner | Publish failure restores old Extension/Resource visibility, then asynchronously disposes staged candidate entries. CLA1 closes the shutdown/join window. |

`ENTRY-01` is the duplicated construction path to remove. Existing failure tests
show that it is not a general cleanup leak:
`tests/harness/test_agent_bootstrap.py::test_agent_product_construction_disposes_session_if_bootstrap_cleanup_fails`.

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
| SLOT-01 | `conversation.store` | `bootstrap-infrastructure` | Session/sealed Product/OEM store mechanics are required to open or resume durable conversation state; the focused transcript runtime remains its current owner. |
| SLOT-02 | `agent.transcript_profile` | `bootstrap-infrastructure` | Session/sealed Product/OEM codec/profile mechanics are required to interpret transcript state and remain owned by the focused transcript runtime. |
| SLOT-03 | `context.compaction` | `final-only` | Session/turn selection may vary by admitted Product/OEM/Extension/session layer and is not required to discover Extensions. |
| SLOT-04 | `resource.runtime` | `bootstrap-infrastructure` | Workspace/sealed Product/OEM activation mechanics are required while loading and activating Resource declarations; backend replacement is restart-only. |
| SLOT-05 | `prompt.sections` | `reusable-staged-candidate` | The mechanism is used during bootstrap prompt assembly, while its Session/turn selection admits final layers; CLA4 must construct or transfer it once. |
| SLOT-06 | `skill.activation` | `reusable-staged-candidate` | The mechanism participates in bootstrap Resource admission, while its Session/turn selection admits final layers. |
| SLOT-07 | `tool.packs` | `reusable-staged-candidate` | Bootstrap and admitted Extension Tool packs must be composed without constructing a peer final owner. Only installed live Tools receive registration leases. |
| SLOT-08 | `command.packs` | `reusable-staged-candidate` | The composer follows the same staged ownership rule as Tool packs; immutable pack declarations do not receive leases. |
| SLOT-09 | `interaction.side_question` | `final-only` | Optional Session/sealed Extension-replaceable Provider factory is admitted after discovery and remains a legacy Session-owned binding until the `harness.session` slice. |
| SLOT-10 | `continuity.provider_packs` | `bootstrap-infrastructure` | Optional Process/sealed Product/OEM packs bind once in the focused continuity owner; they are outside the first `harness.resources` cutover. |

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
| ORDER-06 | Session shutdown joins Graph, task, Extension generation, Profile, and composition cleanup in owner order; CLA1 must additionally join in-flight candidate disposal. | `src/loushang/harness/session/operations_runtime.py::AgentSessionOperationsRuntime._dispose_runtime_cancellation_atomic` |

The validation/reuse-before-construction ordering is an ownership dependency,
not an incidental optimization. A future staged candidate rejected by Graph
reuse must remain root-owned and be disposed by that root.

## Architecture Allowlist

CLA0 executable gates freeze these production construction sites:

- `RuntimeCapabilityGraphRuntime`, `RuntimeCapabilityGraphBinder`, and
  `RuntimeCapabilityGraphProjector`: `AgentProductSession.__init__` only;
- `RuntimeProfileBinder` for the Resource/composition target slots:
  `bind_capability_composition_runtime` only; and
- `CapabilityCompositionRuntime`: constructed only by
  `bind_capability_composition_runtime`.

Focused transcript and continuity Profile binders remain legitimate unmigrated
owners. CLA2 and CLA4 intentionally update the corresponding allowlist in the
same change that moves authority; adding a peer site without updating this
baseline fails.

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

At this baseline, `harness.workspace` is `source-complete` and
`harness.model_input` is `production-mounted`. Catalog status is documentation
metadata only and is never consulted by runtime composition.

## CLA0 Closure

CLA0 is complete when the inventory, architecture allowlists, ordering gate,
catalog status, focused tests, and sandbox-safe full-suite baseline pass with no
`src/` change. CLA1 may then close the Extension candidate cleanup/join window;
CLA2 may move Graph ownership to the Session composition root.

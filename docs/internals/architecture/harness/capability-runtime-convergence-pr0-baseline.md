# Capability Runtime Convergence PR0 Baseline

## Status

Implementation baseline for PR0, tracked by GitHub issue `#450`. This document
freezes current behavior and package ownership before lifecycle, Tool, graph,
or Model Input implementation begins. It is evidence for later PRs, not a
claim that the target convergence runtime exists.

PR0 changes no Product behavior. Source and accepted boundary documents remain
authoritative when this inventory is incomplete or stale.

## Scope

PR0 records five kinds of evidence:

1. mutable contribution and subscription surfaces;
2. compatibility behavior that later migrations must preserve or explicitly
   replace;
3. Harness-managed model invocation paths and their current authority;
4. package ownership for the contracts introduced by later PRs; and
5. lifecycle failure/cancellation points and the required pre-change tests.

The inventory covers mutable and registry-like surfaces owned by Harness, plus
the AI, Agent, and TUI seams that Harness invokes or uses as lifecycle
precedents. Ordinary domain collection methods such as a data grid's
`add_row()` are not registration surfaces.

The machine gate is
`tests/architecture/test_capability_runtime_convergence_pr0.py`. It prevents a
second graph runtime/projector, pins the four accepted Graph contract owners,
rejects broad service-locator parameters on those target contracts, and checks
that the inventory retains its required rows. Package decisions for later
Registration and Model Input contracts remain documentary until their owning
implementation PR can gate the real symbols and imports.

## Surface Classification

The classifications are:

- **declaration**: data or a build-time descriptor; no live disposer is
  required after the builder is frozen;
- **live registration**: mutates a runtime-visible registry or effective
  provider view; owner and exact disposal are target requirements;
- **subscription**: attaches a listener to a live owner and should return an
  idempotent exact unsubscribe handle;
- **persistent configuration**: changes authoritative settings rather than a
  live registry; transaction/revision semantics apply instead of a
  RegistrationLease; and
- **orchestration helper**: calls another classified surface but is not itself
  a registry.

Names such as `register_*` and `add_*` do not determine the classification.

## Mutable Surface Baseline

| ID | Current owner and API | Class | Current duplicate/removal behavior | Current evidence | Target wave |
| --- | --- | --- | --- | --- | --- |
| SUR-01 | `harness.tools.core.ToolRegistry.register_tool` | live registration | public tool name is identity; same name overwrites in place and preserves original order; returns `ToolDefinition`; no removal API or owner | `tests/harness/tools/test_core.py::test_tool_registry_duplicate_registration_compatibility_baseline`; `tests/coding/test_session_tool_controller.py::test_tool_controller_runtime_registration_preserves_duplicate_overwrite_behavior` | PR2 |
| SUR-02 | `harness.tools.workspace.WorkspaceToolRegistry.register_tool` | live registration facade | delegates to SUR-01, preserves return value, and additionally validates workspace Tool binding | `tests/coding/test_tool_registry.py::test_registry_register_tool_accepts_explicitly_bound_decorated_tool` | PR2 |
| SUR-03 | `harness.session.tool_runtime` and `tool_controller` runtime Tool registration | live registration adapter | registers through SUR-01, returns the selected definition, may activate/rebind same-name Tool and prompt state, exposes no disposer | `tests/coding/test_session_tool_controller.py::test_tool_controller_registers_selected_runtime_resolver_contribution`; `tests/coding/test_session_tool_controller.py::test_tool_controller_rebinds_active_same_name_runtime_replacement` | PR2 |
| SUR-04 | `harness.extensions.api.ExtensionContributionAPI.register_tool` | mixed declaration plus live registration | appends a data declaration, then calls a live runtime callback when bound; returns `None`; repeated names remain in declarations while the live Tool path follows SUR-01 | `tests/harness/extensions/test_runtime.py::test_loader_executes_register_api_without_coding_runtime`; `tests/coding/test_agent_session_tools.py::test_agent_session_extension_api_register_tool_after_runtime_bind_updates_session_tools` | PR2 then PR7 |
| SUR-05 | `ExtensionContributionAPI.on/register_policy/register_approval` | declaration builder | ordered/aggregate list entries are retained; conflicts are resolved during routing/admission; no live disposer at declaration time | `tests/harness/extensions/test_routing.py::test_contribution_api_records_ordering_metadata_and_preserves_hooks`; `tests/harness/extensions/test_control.py::test_approval_conflict_survives_duplicate_extension_and_contribution_ids` | PR7 |
| SUR-06 | `ExtensionContributionAPI.register_command/register_flag/register_shortcut/register_message_renderer` | declaration builder | dictionaries silently replace the same public key and return `None`; loaded Extension owns the frozen copy; no unload token exists | `tests/harness/extensions/test_runtime.py::test_extension_runtime_validates_and_applies_flag_values`; `tests/harness/extensions/test_commands.py::test_extension_command_descriptors_preserve_conflict_and_provenance` | PR7 |
| SUR-07 | `extensions.agent.ExtensionAgentAPI.register_side_question_provider` | declaration | appends a `RegisteredRuntimeCapabilityReplacement`; factory is not invoked until final profile binding | `tests/harness/extensions/test_agent_profile.py::test_agent_extension_api_declares_side_question_replacement_as_data` | PR3/PR7 adapter |
| SUR-08 | `harness.runtime.RuntimeCapabilityRegistry.register` | binder-local declaration | exact `(slot, implementation, version)` duplicates fail closed; returns `None`; not a live side effect | `tests/harness/runtime/test_profile.py::test_runtime_capability_registry_duplicate_compatibility_baseline` | retain; PR3 consumes |
| SUR-09 | Conversation/transcript codec and profile registration | build-time declaration | duplicate codec/profile identities fail closed; builders return no live disposer | `tests/harness/conversation/test_jsonl_codec.py::test_payload_registry_rejects_duplicate_keys_and_unregistered_known_values`; `tests/harness/transcript/test_profile.py::test_profile_rejects_duplicate_record_profile_registration` | retain |
| SUR-10 | `ai.APIRegistry.register_api_adapter` | lower-layer live registry | exact API duplicates fail closed; optional `source_id` supports bulk removal; returns `None`; AI owns the token vocabulary | `tests/ai/test_bootstrap.py::test_api_registry_duplicate_and_source_scope_compatibility_baseline` | PR5-compatible AI follow-up, not Harness-owned |
| SUR-11 | `ai.ProviderRegistry.register_provider_adapter` | lower-layer live registry | exact provider/API route duplicates fail closed; optional `source_id` bulk removal; returns `None` | `tests/ai/test_bootstrap.py::test_provider_registry_duplicate_and_source_scope_compatibility_baseline` | PR5-compatible AI follow-up, not Harness-owned |
| SUR-12 | `harness.model_catalog.ModelCatalog.register_model/register_provider/unregister_provider` | live Product-neutral catalog facade | model/provider IDs replace existing values; unregister removes the entire provider by public ID and returns `None` | `tests/harness/test_model_catalog.py::test_model_catalog_registration_compatibility_baseline` | PR7; surface-specific policy |
| SUR-13 | `harness.extensions.ExtensionProviderRuntime.register_provider/unregister_provider` | live registration adapter | merges provider configuration into the existing provider; unregister removes the public provider and all `provider:{name}` API adapters | `tests/coding/test_session_extension_provider_controller.py::test_extension_provider_controller_registers_native_provider_against_existing_provider`; `tests/coding/test_session_extension_provider_controller.py::test_extension_provider_controller_unregisters_provider_and_source_registrations` | PR7 |
| SUR-14 | `harness.config.ScopedConfigRuntime.subscribe/subscribe_change` and `SettingsRuntime` facades | subscription | returns idempotent listener-specific removal closure; listener failure is post-commit and contained by the runtime's error contract | `tests/harness/config/test_runtime.py::test_scoped_config_runtime_listener_failure_is_post_commit` | retain/adapt primitive only |
| SUR-15 | `harness.runtime.SessionTransitionHost.subscribe_before_invalidate/subscribe_after_invalidate` | subscription | returns idempotent exact observer removal; Session replacement still uses dispose-previous then publish-candidate ordering | `tests/harness/runtime/test_transition.py::test_transition_host_subscription_unsubscribe_has_token_identity`; `tests/harness/runtime/test_transition.py::test_transition_host_orders_release_activation_and_rebind` | retain; separate PR8 nesting decision |
| SUR-16 | Session runtime-event, footer, and multi-agent fact/notice consumers | subscription | returns callback-specific removal where exposed; observer failures do not roll back committed state | `tests/harness/multiagent/test_control.py::test_failing_fact_and_notice_consumers_do_not_rollback_state`; `tests/harness/session/test_footer.py::test_footer_data_provider_set_cwd_invalidates_branch_and_notifies` | inventory; migrate only if live ownership requires it |
| SUR-17 | `tui.Tui.add_child/add_input_listener` | subscription/live UI contribution precedent | `ExtensionHandle` is idempotent and captures the registered object/listener; removal is object-specific | source inspection of `src/loushang/tui/tui.py` | reference only; TUI lane owns migration |
| SUR-18 | `tui.ExtensionHost.set_widget/set_status/set_footer/open_surface` | keyed live UI contribution precedent | returns an idempotent handle, but the disposer captures the public key; an old handle may remove a same-key replacement, so this is not exact registration identity | source inspection of `src/loushang/tui/extensions.py` | reference only; do not copy as exact lease |
| SUR-19 | Agent settings `add/remove_package_source` and `add/remove_plugin_source` | persistent configuration | updates scoped authoritative configuration with existing persistence and identity rules; it is not a live registry lease | `tests/harness/config/test_agent_settings.py::test_settings_manager_package_source_add_remove_uses_package_identity` | outside Rule 1 unless a later live binding is produced |
| SUR-20 | `WorkspaceToolRegistry.register_profile` | build-time declaration | profile ID maps to an immutable selection description; profile construction copies Tool definitions without changing source registry order | `tests/harness/tools/test_workspace_profile.py::test_profile_builds_product_copy_without_changing_tool_order` | retain |
| SUR-21 | CLI/parser `register_*` functions and bootstrap `register_extension_tools` helpers | orchestration/build helper | mutate an argparse/build object or call SUR-01; they are not independent runtime registries | current source inspection | classify through the surface they invoke |
| SUR-22 | `BuiltInResourceRegistry` and `resources.plugins.PluginRegistry` | live resource/package catalog | the public package/plugin name silently replaces an earlier value; exact public-name unregister returns the removed value or `None`; register returns the input value; no owner/token exists | `tests/harness/resources/test_runtime.py::test_resource_registries_public_key_compatibility_baseline` | PR7; surface-specific policy |
| SUR-23 | `ai.auth.AuthRegistry` and OAuth Provider registration | lower-layer live registry | process-global default registries exist; duplicates fail closed by default, callers may request explicit replacement, and no owner token or unregister exists; tests must isolate global replacement | `tests/ai/test_auth_api.py::test_auth_registry_explicit_replace_compatibility_baseline`; `tests/ai/test_auth_oauth.py::test_oauth_registry_and_status_cover_lifecycle_states` | AI-owned follow-up; no Harness token vocabulary |
| SUR-24 | Agent custom-message codec, `AgentTypeRegistry`, and `SandboxBackendRegistry` | build-time declaration/catalog | duplicate identities fail closed during construction/registration; values are fixed before the consuming runtime is created and expose no live mutation/removal | `tests/agent/test_json_codec.py::test_agent_message_codec_rejects_conflicting_registrations`; `tests/harness/sandbox/test_registry.py::test_registry_rejects_duplicate_ids` | retain |
| SUR-25 | `harness.multiagent.AgentRegistry` | authoritative entity-state registry | reserve/commit/rollback owns Agent path and incarnation state; open-name conflict fails closed and close permits a later incarnation; this is not a plugin contribution registry | `tests/harness/multiagent/test_registry.py::test_pending_reservation_is_hidden_and_rollback_releases_the_name`; `tests/harness/multiagent/test_registry.py::test_open_name_conflicts_but_close_allows_a_new_incarnation` | outside Rule 1; retain transaction authority |
| SUR-26 | `OrderedEventBus.subscribe` and Session/runtime/RPC subscription facades | subscription | the callback removal closure is idempotent only while no equal listener remains; repeated equal subscriptions let a stale closure remove another registration because the base bus removes the first equal listener rather than an opaque identity; facades preserve the returned hook | `tests/harness/events/test_bus.py::test_ordered_event_bus_subscribes_and_unsubscribes` | retain compatibility; adopt exact token only when ownership requires it |
| SUR-27 | Remote/Extension UI `set_status/set_widget` state and context facades | keyed live presentation contribution | public key overwrites the value, `None` removes it, and the remote UI returns no handle; Extension/TUI adapters may add their own handle semantics | `tests/harness/host/test_remote_ui.py::test_remote_ui_context_records_state_and_emits_requests` | PR7/presentation; do not infer Tool winner restoration |
| SUR-28 | multi-agent/delegate Tool pack `register`, runtime-context `register_tool`, and other forwarding facades | orchestration helper | returns/delegates according to SUR-01 or SUR-04 and owns no independent registry identity | current source inspection | migrate with the underlying Tool surface |

## Compatibility Matrix

| ID | Behavior frozen by PR0 | Evidence | Later change rule |
| --- | --- | --- | --- |
| COMP-01 | Tool registration returns the exact input `ToolDefinition`. | SUR-01 test | PR2 adds `bind_tool`; legacy facade retains return value during migration. |
| COMP-02 | Same-name Tool registration replaces content without adding another order entry. | SUR-01 and SUR-03 tests | PR2 must characterize explicit Tool layering/conflict policy before changing it. |
| COMP-03 | At PR0, `ProductRuntimeBindings.register_tool` defaulted to a silent no-op. PR2 keeps default binding construction compatible but makes an attempted live Tool registration fail closed. | `tests/harness/runtime/test_bindings.py::test_product_runtime_bindings_default_tool_registration_fails_closed` | PR2 changes only the attempted live mutation; unrelated unbound contexts remain compatible. |
| COMP-04 | Runtime Capability and codec declaration registries fail closed on duplicate exact identities. | SUR-08 and SUR-09 tests | No migration may loosen these registries to replacement semantics. |
| COMP-05 | AI API/provider adapter registries fail closed but remove in bulk by `source_id`. | SUR-10 and SUR-11 tests | AI-local token evolution preserves `AI -X-> Harness`. |
| COMP-06 | Session switch disposes the previous Session before publishing and activating/rebinding the candidate. | SUR-15 tests | PR1 does not alter this; PR8 requires an explicit nested-commit decision. |
| COMP-07 | Runtime and Capability Profile snapshots are schema-versioned, persisted in Session metadata, and checked on resume. | `tests/coding/test_runtime_profile.py::test_persistent_session_resumes_the_snapshotted_file_profile`; `tests/coding/test_capability_profile.py::test_coding_capability_snapshot_is_separate_from_other_header_metadata` | Graph/effective views use additive records and do not replace Profile authority. |
| COMP-08 | Extension reload invalidates context, refreshes resources, binds, emits `session_start`, and contains hook failures under current policy. | `tests/harness/extensions/test_lifecycle.py::test_extension_runtime_coordinator_owns_reload_and_refresh_order`; `tests/harness/extensions/test_lifecycle.py::test_extension_runtime_coordinator_contains_hook_failure_and_syncs` | PR7 stages a new generation before changing this order or failure policy. |
| COMP-09 | ModelCatalog public-ID replacement and removal are not the same semantics as Tool winner restoration. | SUR-12/SUR-13 tests | Each surface declares its own conflict and fallback policy. |
| COMP-10 | Resource package/plugin registries replace and remove by public name and return the registered/removed value. | SUR-22 test | PR7 must provide an explicit compatibility facade if it introduces exact live identities. |
| COMP-11 | AI auth registries fail closed unless replacement is explicit, and currently provide no removal/owner token. | SUR-23 tests | Any AI-local token evolution must preserve standalone AI use and `AI -X-> Harness`. |

## Harness-Managed Model Invocation Inventory

| ID | Invocation path | Current finalization boundary | Current committed authority | Required follow-up |
| --- | --- | --- | --- | --- |
| CALL-01 | `agent.agent_loop._collect_assistant_response` through configured `stream_fn` or `ai.stream` | Agent transforms messages and builds `ai.Context`; AI later resolves auth/model, normalizes context, resolves adapter, and materializes provider fields | transcript commits user/tool/assistant messages around the loop, but no prepared-request fact exists | PR5 prepared-request seam; PR6 main-turn commit |
| CALL-02 | `agent.Agent` default `_default_stream` | thin call into `ai.stream` | same as CALL-01 | must remain standalone when no committer is injected |
| CALL-03 | Harness transcript summarization `_complete_summary` | calls `ai.stream` or `ai.complete` directly after summary context construction | committed compaction checkpoint stores summary output but not complete prepared input lineage | PR8 routes through PR5 seam and compaction-v2 facts |
| CALL-04 | Session side question | creates a child `Agent` with the parent `stream_fn`, then follows CALL-01 | child logical context is transient; transcript handling depends on the Session adapter | PR8 invocation purpose and attempt facts |
| CALL-05 | Agent loop Tool continuation and Product retry | re-enters CALL-01; AI provider runtime may invoke adapter `raw_parts()` again for transport retry | message/tool-result commits exist; request-attempt facts do not | PR5 defines payload-change retry semantics; PR8 covers all paths |
| CALL-06 | injected/custom `stream_fn` in Harness Session bootstrap | can replace the default AI entrypoint after Agent logical assembly | test/product-specific; no common prepared-request guarantee | PR0 marks it explicit; a durable Harness guarantee requires a conforming barrier or fail-closed profile decision |

The current source proves why a host-only commit is insufficient:
`agent_loop.py` calls `stream_fn`/`ai.stream` with provider-neutral values, while
`ai/api/streaming.py` performs request/model normalization and provider adapter
resolution afterward. PR5 therefore belongs to AI and exposes a neutral
pre-transport port; Harness supplies an implementation without creating an
`AI -> Harness` import.

## Contract And Package Ownership

| ID | Future contract/mechanism | Owning package boundary | Forbidden dependency/authority |
| --- | --- | --- | --- |
| OWN-01 | Harness `RegistrationOwner`, exact identity, disposal result, and `RegistrationScope` | `loushang.harness.runtime.registration` | must not enter `loushang.ai`; not a global registry |
| OWN-02 | AI-local opaque API/provider/auth registration token | `loushang.ai` registry owner | no Product/Extension/Harness vocabulary |
| OWN-03 | top-level Capability Definition/Requirement, plan values, and pure planner | `loushang.harness.capabilities` | no Product, Agent, AI, provider, broad runtime bindings, or discovery side effects |
| OWN-04 | graph binder/runtime and Mount lifecycle | `loushang.harness.capabilities` using PR1 lifecycle primitives | no second `CapabilityCompositionRuntime`, global DAG manager, or service locator |
| OWN-05 | graph projector, `MountGraphSnapshot`, and composed `EffectiveRuntimeView` | `loushang.harness.capabilities` | read-only; references Profile/registration/Model Input authorities rather than copying selection |
| OWN-06 | Tool live bind and compatibility facade | `loushang.harness.tools` | no Product conflict policy in shared primitive |
| OWN-07 | `PreparedModelRequest` and async pre-transport commit port | `loushang.ai` | no `AI -> Harness`; standalone calls remain valid without a committer |
| OWN-08 | `ModelInputSnapshot`, transcript record/codec, and reconstruction | `loushang.harness.transcript`; Session only orchestrates calls and assembles the committer | existing ConversationStore is the sole writable authority; no parallel Fact Store |
| OWN-09 | CLI/RPC/TUI/Web presentation of effective views | Product/Channel presentation adapters | presentation does not become lifecycle or selection authority |

Concrete filenames may be refined in the owning package, but moving a contract
to another layer requires updating this matrix and the architecture gate in the
same PR.

## Lifecycle Fault Matrix

| ID | Await/failure point | Current risk or compatibility fact | Required result before broad migration | Owner PR |
| --- | --- | --- | --- | --- |
| FAULT-01 | declaration/admission | mixed Extension Tool API can perform a live callback during declaration | discovery/admission has no untracked live side effect | PR2/PR7 |
| FAULT-02 | Provider/facet create | profile binder rolls back values created before a later factory exception | reverse cleanup records every outcome and survives cancellation | PR1 |
| FAULT-03 | registration after create | current Tool registration cannot produce an exact token | failed later binding removes only the new registration | PR1/PR2 |
| FAULT-04 | validation before graph publish | top-level graph is not implemented | candidate delta is disposed and previous graph/objects remain usable | PR4 |
| FAULT-05 | cancellation during create/register | binder catches `Exception`, not a complete shielded cleanup protocol | cleanup runs to completion and cancellation is reported after owned cleanup | PR1 |
| FAULT-06 | disposer failure within one slot/scope | current `_dispose_entries` stops at first failure and rollback suppresses errors | continue cleanup, aggregate results, and expose retryable/terminal outcome | PR1 |
| FAULT-07 | rebind old-value disposal | current profile rebind disposes old values before `_replace` publication | no nominally authoritative partially disposed old generation | PR1/PR4 |
| FAULT-08 | Session switch dispose failure | current Session is cleared before disposal and candidate is not published after failure | behavior remains characterized until PR8 nested transaction decision | PR0/PR8 |
| FAULT-09 | Extension resource refresh/runtime bind/session hook | current reload invalidates context before refresh and contains selected hook failures | PR7 staged generation defines rollback and compatibility policy first | PR7 |
| FAULT-10 | AI prepare/adapter normalization | provider-visible fields can be added after Agent/host logical projection | freeze after final model-visible preparation | PR5 |
| FAULT-11 | Model Input commit | no prepared-input record exists | required durable commit failure causes zero transport calls | PR6 |
| FAULT-12 | transport retry | AI runtime may prepare/invoke the adapter again | changed payload gets a new snapshot; identical payload may reuse snapshot but records another attempt | PR5/PR8 |
| FAULT-13 | old-generation retirement after graph publish | no graph runtime exists; disposer failures can currently abort a cleanup loop | published generation remains authoritative; retirement is degraded/diagnosed, not rolled back | PR1/PR4 |
| FAULT-14 | shutdown/quiescence | independent callbacks/scopes have different cleanup conventions | lifecycle owner joins all permitted concurrent cleanup before reporting shutdown complete | PR1/PR8 |

PR1 fault injection must cover every create/register/dispose await point before
PR2 uses the lifecycle foundation in a production registry.

## Architecture Gates

PR0 adds the following executable restrictions:

- the four accepted named Graph symbols have one owner under
  `loushang.harness.capabilities`; target Registration and Model Input package
  decisions are recorded in OWN-01 and OWN-08, with concrete symbol gates
  deferred to their implementation PRs;
- `EffectiveRuntimeSnapshot`, global Capability registry/graph/container/context
  symbols, and duplicate graph manager classes are forbidden;
- target Graph Planner/Binder/Runtime/Projector APIs may not accept
  syntactically broad parameters named `context`, `runtime`, `bindings`,
  `services`, or `container`, including unannotated, `Any`, `object`, and broad
  mapping forms; this is a regression tripwire rather than whole-program
  type-alias analysis;
- existing `AI -X-> Harness` and `Agent -X-> Harness` import gates remain
  mandatory; and
- the surface, call-path, ownership, compatibility, and fault IDs in this
  document may not silently disappear. Later PRs update a row rather than
  deleting historical baseline evidence.

Legacy `ProductRuntimeBindings` and binder `context: object` remain explicit
compatibility debt at composition roots. PR0 does not relabel them as target
graph contracts or authorize new consumers.

Two additional specialized leases are implementation precedents, not new
surface rows or a proposed hierarchy:

- Session approval presentation uses a generation-aware, idempotent lease so a
  superseded presenter cannot close its replacement, covered by
  `tests/coding/test_agent_session.py::test_agent_session_superseded_approval_lease_cannot_close_replacement`;
- continuity activation keeps an unpublished candidate private until consume
  and makes unconsumed cleanup idempotent, covered by
  `tests/harness/continuity/test_activation.py::test_cross_domain_relaunch_lease_cleanup_is_idempotent`.

PR1 should reuse their proven state transitions where applicable without
forcing either specialized lease to inherit a common base class.

## PR0 Completion Gate

PR0 is complete when:

- all rows above are present and machine-checked;
- characterization tests pass without source behavior changes;
- the target package/no-second-runtime/service-locator gates pass;
- `make check-harness` passes;
- the focused Coding Profile/Tool and AI registry compatibility tests pass; and
- the resulting commit/PR references issue `#450`.

Implementation of leases, graph values, AI request barriers, or Model Input
records is explicitly deferred to PR1 and later.

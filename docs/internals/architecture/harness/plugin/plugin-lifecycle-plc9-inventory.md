# Plugin Lifecycle PLC9.0 Owner And Peer Inventory

## Status

- Source baseline: `1c104ce5`.
- Scope: source-backed starting inventory for PLC9.0.
- Effect: descriptive and test-frozen only; it grants no new runtime authority.
- Companion decision:
  [Plugin Lifecycle PLC9.0 Baseline](plugin-lifecycle-plc9-baseline.md).

This inventory distinguishes accepted reusable owners, Product adapters,
parallel compatibility paths, and missing target boundaries. “Migrate” or
“delete” below is a delivery obligation, not a claim that the work is already
implemented.

## Durable Control And Lifecycle Owners

| Current seam | Exact source owner or symbol | Current fact | PLC9 disposition and deletion gate |
| --- | --- | --- | --- |
| Desired-state journal | `src/loushang/harness/plugin_management/ledger.py::PluginDesiredStateLedger` | Durable desired installation snapshots and transitions | Retain as state authority behind the management service; transports never import it to mutate state |
| Management command journal | `src/loushang/harness/plugin_management/service.py::PluginManagementService` | Sole PLC2-2/PLC2-3 command authority over inert desired state; handles install/enable/disable/remove and the v2 update command | Retain and compose behind one application boundary; revise only through an accepted command contract |
| Retirement intent | `src/loushang/harness/plugin_management/retirement.py::PluginRetirementIntentLedger` | Durable intent opened by lifecycle transitions | Retain; removal cannot bypass it when retirement is required |
| Retirement-set coordination | `src/loushang/harness/plugin_management/retirement_sets.py::PluginRetirementSetLedger` | Correlates exact covered Instance revisions and owner completion | Retain; completion must remain evidence-backed |
| Instance runtime | `src/loushang/harness/plugin_management/instance_runtime.py::PluginInstanceRuntimeLedger` | Durable Instance activation, lease-family, drain, revocation, and retirement state | Retain; do not replace with Worker/process state |
| Security retirement acceptance | `src/loushang/harness/plugin_management/security_acceptance.py::PluginInstanceSecurityRetirementJournal` | Durable acceptance evidence for security retirement | Retain; keep distinct from graceful retirement and generic management auth |
| Package retention and cleanup | `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageLifecycleLedger` | Durable pins, cleanup leases/attempts/repair decisions, recovery barrier, retention snapshots, and GC candidates | Retain as lifecycle evidence; PLC9D must add deletion execution/result without weakening candidate recheck |
| Coding Product composition | `src/loushang/coding/_plugin_lifecycle.py::CodingPluginLifecycle` | Product adapter composes the generic ledgers under one workspace identity and coordination lock | Retain as an outer Product adapter until common application ports replace Product-specific call sites; it must not become a second generic owner |
| Management application command adapter | `src/loushang/harness/plugin_management/application.py::PluginManagementCommandApplication` | A1-1 preserves correlation around the durable operation identity and delegates every mutation to `PluginManagementService` | Retain as the transport-neutral command boundary; transports cannot import the service or desired-state ledger directly |
| Management query projector | `src/loushang/harness/plugin_management/application.py::PluginManagementReadModelProjector` | A1-1 joins independently revisioned desired, operation, Source, Instance, Package, and retirement snapshots without persisting another clock | Retain as the common read boundary; optional owners remain explicitly unsupported/unknown and skew remains observable |
| Source projection snapshot | `src/loushang/harness/plugin_management/application.py::PluginManagementSourceSnapshotV1` | A1-1 describes source identity, availability, version, and manifest install default as inert input facts | Retain behind a Product Source adapter; availability and install default never become live desired-selection writers |
| Enablement migration receipt | `src/loushang/harness/plugin_management/enablement_migration.py::PluginEnablementMigrationJournal` | A1-2 owns strict append-only `accepted -> desired_committed -> compatibility_window -> finalized` evidence per Installation and rejects changed accepted input | Retain through the downgrade window; finalization evidence is a later deletion gate, not automatic permission to remove compatibility fields |
| Enablement migration coordinator | `src/loushang/harness/plugin_management/enablement_migration.py::PluginEnablementMigrationCoordinator` | A1-2 seeds only never-seen desired state through the common command port with deterministic retry identities; any desired history wins | Retain until all legacy inputs are receipted; it cannot acquire Packages, infer Source availability as selection, or call a desired ledger commit |
| Legacy compatibility projection | `src/loushang/harness/plugin_management/enablement_migration.py::PluginEnablementCompatibilityProjector` | A1-2 derives legacy disabled ids from canonical desired snapshots plus migration receipts | Temporary retain; callers may consume it for downgrade compatibility but cannot mutate it as peer state |
| Coding migration composition | `src/loushang/coding/_plugin_lifecycle.py::build_coding_plugin_lifecycle` | A1-2 binds the generic journal under the private workspace lifecycle root and checks the epoch fence before management recovery; A1-3 base, Capability, and Continuity paths import exact legacy inputs before mount | Retain as Product composition; `build_coding_plugin_management_application` and `project_coding_plugin_enablement_compatibility` keep durable owner construction out of transport adapters |
| Coding management CLI binding | `src/loushang/coding/plugin_management_cli.py::CodingConfiguredPluginSourceProjection` | A1-3 projects configured Source facts relative to the workspace and composes the common command/query binding plus derived downgrade publication | Retain as a Product adapter; it may inspect configured Sources but cannot construct or mutate a durable lifecycle ledger |
| Coding base migration caller | `src/loushang/coding/_base_plugin.py::prepare_managed_coding_base_plugin_assembly` | A1-3 imports the base manifest default and legacy disable input before mount; an existing desired history wins | Retain during migration; delete the legacy input only after PLC9E finalization evidence |
| Coding Capability migration caller | `src/loushang/coding/_capability_plugin_composition.py::_resolve_managed_capability_plugins` | A1-3 imports exact checked-in Capability revisions before mount and leaves legacy-disabled Installations unmounted | Retain during migration; canonical desired state is the only post-migration selection input |
| Coding session migration input | `src/loushang/coding/bootstrap.py::_create_agent_session` | Captures the legacy disabled-id snapshot once and passes it to base/Capability migration callers | Temporary compatibility input; it cannot veto a receipted desired-state replay |

The `PluginManagementAction` v1 union in
`src/loushang/harness/plugin_management/operations.py` is exactly `install`,
`enable`, `disable`, and `remove`. Update is the separately versioned
`PluginManagementUpdateCommandV2` in
`src/loushang/harness/plugin_management/updates.py`. PLC9 must preserve replay
compatibility rather than silently widening the v1 wire union.

## Current Management And Enablement Peers

| Peer seam | Exact source site | Current fact | PLC9 migration/deletion gate |
| --- | --- | --- | --- |
| Shared CLI mutation | `src/loushang/harness/cli/resource_toggles.py::apply_resource_toggles` | A1-3 routes Plugin enable/disable through `PluginManagementCliBinding`; Skill and source configuration retain their settings owner and compatibility aliases retain source meaning | Retain the transport-only split; Plugin commands cannot call settings enable/disable mutators or materialize an unmigrated Installation |
| Shared CLI listing | `src/loushang/harness/cli/plugin_listing.py::list_plugin_records` | A1-3 maps the correlated common management projection into legacy TSV/JSON fields without inspecting Sources or constructing an authority | Retain as pure formatting/projection adaptation; Product Source inspection stays behind the injected query owner |
| Mutable helper manager | `src/loushang/harness/resources/plugins/manager.py::PluginManager` | Owns a registry and `_disabled_plugins`; exposes add/remove/enable/disable helpers | No new production construction; delete or reduce to inert compatibility/tests after all callers use management ports |
| Config persistence | `src/loushang/harness/config/agent/types.py`, `src/loushang/harness/config/agent/_settings_patch.py`, `src/loushang/harness/config/agent/_settings_codec.py`, and `src/loushang/harness/config/agent/manager.py` | Defines, decodes, patches, and mutates the legacy `disabled_plugins` setting | PLC9A1 records a durable migration receipt and retains a derived compatibility projection until the minimum-version/downgrade gate passes; only then delete the Plugin field/mutators |
| Session activation dependency | `src/loushang/harness/session/bootstrap_activation.py::standard_agent_session_activation_plan` | Treats `disabled_plugins` as a Resource-root and Extension activation input | Delete this dependency after those consumers read the desired-state projection |
| Package/Resource projection chain | `src/loushang/harness/resources/packages/roots.py`, `src/loushang/harness/resources/packages/catalog.py`, `src/loushang/harness/resources/packages/projection.py`, and `src/loushang/harness/resources/packages/session.py` | Threads `disabled_plugins` through package catalog/root resolution and derives enabled mounts/entries | PLC9A migrates selection to exact desired revisions; retain Package/Resource projection while deleting the legacy veto input |
| Coding continuity bootstrap | `src/loushang/coding/continuity_bootstrap.py::bind_coding_configured_continuity` | A1-3 reads legacy `disabled_plugins` only as one-time migration input, then selects solely from durable desired state and exact revision replay | Retain the migration input through the compatibility window; delete it only at PLC9E after finalization evidence |
| Coding package-list fallback | `src/loushang/coding/cli/__main__.py::_run_list_packages` | Passes settings `disabled_plugins` into legacy catalog projection when the session query is unavailable | Delete the fallback after the common query port is mandatory and covered by startup diagnostics |
| Settings disable list | `src/loushang/harness/resources/plugins/authority.py::PluginResolutionAuthority.project_package` | Combines `source.enabled` with settings `disabled_plugins` | One-time migration to desired state; delete as runtime-selection input only after replay-safe migration proves explicit disabled/removed state is preserved |
| Resolver projection veto | `src/loushang/harness/resources/plugins/resolver.py::PluginResolver.project_package` | Computes effective enabled from source and manifest flags | Retain inert descriptor projection only after it stops deciding runtime selection |
| Preflight veto | `src/loushang/harness/resources/plugins/selection.py::PluginSelectionResolver.preflight` | Rejects selected packages when either `source.enabled` or `manifest.enabled` is false | Delete after desired state is the sole selection writer and Source Authority availability has a distinct diagnostic |
| Manifest author default | `src/loushang/harness/resources/plugins/manifest.py::PluginManifestParser` | Parses the inert manifest; the manifest currently carries `enabled` | `manifest.enabled` may seed install desired state once; it cannot remain a live veto |

The settings manager and Product configuration remain valid owners of settings
that are not Plugin lifecycle facts. PLC9A changes only Plugin lifecycle routes;
it must not absorb Skill, theme, model, or unrelated Product settings.

## Existing Command And Adapter Surfaces

| Surface | Exact source site | Current semantics and risk | PLC9 disposition and gate |
| --- | --- | --- | --- |
| Standard CLI grammar | `src/loushang/harness/cli/profile.py` and `src/loushang/harness/cli/parser.py::build_parser` | Exposes Package materialize/install/update/remove/uninstall and Plugin source/list/enable/disable flags; `--add-plugin`/`--remove-plugin` are compatibility aliases for source mutation | Preserve alias meaning, deprecate rather than reinterpret, and add distinct desired-state commands through a versioned CLI contract |
| CLI Package startup arguments | `src/loushang/harness/cli/agent_args.py::agent_cli_argument_values` | Projects startup `update_packages` and `check_package_updates` flags into normalized launch values | Retain as inert argument projection; execution remains behind the same PLC9B Package route/refusal gate |
| CLI Package dispatcher | `src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle` | Dynamically invokes Package methods on the Session | PLC9B routes Plugin-bound artifacts to the canonical Package/Plugin port or rejects before mutation; PLC9A must not mislabel these as desired commands |
| Shared CLI composition | `src/loushang/harness/cli/host_operations.py::run_standard_cli_operations` | Composes Plugin listing/toggles and Package lifecycle operations as separate early operations | PLC9A1 migrates list/enable/disable; PLC9B migrates artifact operations; retain unrelated Skill/Package behavior |
| RPC Package commands | `src/loushang/harness/host/rpc/commands/packages.py::RpcPackageCommands` | Resolves runtime first, then Session, for materialize/install/update/remove/uninstall; this is already an RPC surface but not a Plugin management projection | PLC9A2 applies versioned common-port conformance; Plugin-bound artifact commands remain disabled/refused until PLC9B |
| Session lifecycle facade | `src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter` | Passes Package lifecycle calls to the current Session by dynamic method lookup | Replace Plugin-bound fallback with typed application ports; no concrete ledger/store mutation in the adapter |
| Public Session optional forwarding | `src/loushang/harness/session/facade_optional.py::SessionPackagePort` and `src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations` | Defines and forwards the public optional Package methods to the Product-bound Package port | Keep as a forwarding-only public seam; apply the same PLC9B route/refusal and PLC9A2 conformance contract without importing concrete lifecycle owners |
| Session Package controller | `src/loushang/harness/resources/packages/session.py::SessionPackageController` | Owns current Package list/materialize/install/update/remove/uninstall Product composition | Retain for non-Plugin Packages; route or reject Plugin-bound operations at the canonical lifecycle seam |
| Package operation coordinator | `src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime` | Coordinates materialization, settings publication, update, remove, async uninstall, and legacy sync uninstall | PLC9B owns artifact transaction migration; PLC9E removes the sync compatibility path after the async caller/conformance gate |
| Startup source resolver | `src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver.resolve_configured_sources_sync` | Defaults missing configured remote sources to synchronous auto-materialization | PLC9B covers this entrypoint; Plugin-bound sources cannot auto-publish outside the bounded Package sink |

Source operations and desired operations are never synonyms:

| Command family | Sole meaning |
| --- | --- |
| source add/remove | change Source Authority configuration/availability only; never install, enable, retire, or delete a published revision |
| Package materialize/remove/uninstall | manage acquisition cache/source registration; a Plugin-bound target must route to canonical lifecycle or fail without mutation |
| Plugin install/enable/disable/update/remove | consume an exact verified revision where required and mutate desired state only through `PluginManagementService`; removal opens retirement but does not delete data/artifacts |

Every CLI alias, RPC binding, Session method, and future UI/SDK operation is
included in the common conformance matrix. Dynamic runtime/Session fallback is
not an authority boundary.

## Package Acquisition And Publication Seams

| Current seam | Exact source owner or symbol | Current fact | PLC9 disposition and gate |
| --- | --- | --- | --- |
| General package materializer | `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer` | Owns install roots, lockfile mutation, source materialization, Plugin revision publication, and bindings | Split/compose behind one Package lifecycle transaction without duplicating lock or publication authority |
| Existing source policy port | `src/loushang/harness/resources/packages/materializer.py::PackageSourcePolicy` | Allows/denies a source string before materialization | Retain as one policy input only; it is not authenticated provenance, a bounded sink, or the complete Source Authority |
| Python installer backend | `src/loushang/harness/resources/packages/materializer.py::PythonPackageInstallerBackend` | Calls `uv pip install` and falls back to `python -m pip install` into a temporary target; the command does not enforce verified wheel-only input | Must not publish untrusted Plugin packages after PLC9B; replace with verified wheel acquisition/extraction or a separately accepted contained build service |
| Git materializer backend | `src/loushang/harness/resources/packages/materializer.py::GitPackageMaterializerBackend` | Shells out to fetch/clone/checkout Git sources as a source adapter/backend | Limit to authenticated fetch plus provenance/bytes; it must not choose final quarantine, publication, binding, or runtime authority |
| Startup auto-materializer | `src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver.resolve_configured_sources_sync` | Missing configured remote sources default to `install` and call synchronous materialization | Route Plugin-bound input through PLC9B or fail closed; startup cannot be a second safe-publication owner |
| Package operation runtime | `src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime` | Coordinates current materialize/install/update/remove/uninstall and settings refresh | Retain non-Plugin behavior; all Plugin-bound paths pass the Package owner and management boundaries |
| Direct mutable removal | `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.remove_remote_source` | Directly `shutil.rmtree()`s the mutable materialized target and updates the lockfile without Package lifecycle GC evidence | Never use as immutable Plugin revision GC; route/refuse Plugin-bound targets and narrow/delete at PLC9E after replay/pin/rollback proof |
| Binding/history forgetting | `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.forget_remote_source` and `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.forget_plugin_binding` | Removes current source records/bindings and can remove replay binding history | Preserve history required by desired revisions and pinned Sessions; mutation needs canonical lifecycle evidence or must refuse |
| Verified revision store | `src/loushang/harness/resources/plugins/revisions.py::PluginRevisionStore` | Copies a resolved local tree into owner-created quarantine, rejects unsafe filesystem entries, computes content identity, freezes, and atomically renames an immutable revision | Retain as a safe publication primitive; integrate only after bounded archive/wheel extraction and dependency closure verification |
| Verified revision handle | `src/loushang/harness/resources/plugins/revisions.py::VerifiedRevisionHandle` | Provides no-follow/stability-checked access to a published revision | Retain; consumers use exact handles rather than mutable source paths |
| Dependency lock v1 | `src/loushang/harness/resources/plugins/dependencies.py::PluginDependencyClosureLock` | Binds the final package content digest plus canonical installed `name==version` facts | Retain for replay compatibility; PLC9B adds a new version for recursive verified-artifact digests and never reinterprets v1 |
| Package lifecycle evidence | `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageLifecycleLedger` | Determines conservative retention and recheckable GC candidates from desired/Instance/family/pin/cleanup evidence | Retain; it does not yet perform complete safe acquisition or artifact deletion |

No current single symbol owns the complete PLC9 target transaction from bounded
source bytes through safe extraction and dependency verification to immutable
publication. PLC9B must create that composition without claiming that
`PluginRevisionStore` validates archives or that `PluginPackageLifecycleLedger`
materializes packages.

## Execution And Containment Seams

| Current seam | Exact source owner or symbol | Current fact | PLC9 disposition and gate |
| --- | --- | --- | --- |
| Declaration source union | `src/loushang/harness/resources/plugins/declarations.py::PluginDeclarationSourceKind` | Exactly `document` or `in_process`; this describes how the inert declaration is acquired | Retain as an independent axis; a document may declare Worker execution, so PLC9 does not invent a Worker source kind |
| Contribution execution model | `src/loushang/harness/resources/plugins/declarations.py::PluginContributionExecutionModel` | Exactly `data_only` or `in_process`; this is the current execution-topology axis | Add `local_worker` only through a new versioned IR/codec and compatibility fixtures; `remote_service` remains separately deferred |
| Author SDK | `src/loushang/plugin/__init__.py` | Exposes declarative authoring/validation and the narrow Provider runtime ABI; no management, Worker, Process Host, or Sandbox owner objects | Preserve the authority firewall; any future Worker authoring surface is data-only and versioned |
| Raw process owner | `src/loushang/harness/workspace/process/host.py::ProcessHost` | Owns bounded child count, I/O limits, process lifetime, termination, and an optional containment-planner hook | Reuse only behind the authorized launcher; raw construction/start is not Worker admission |
| Generic authorized process launcher | `src/loushang/harness/tools/process_hosting.py::ScopeBoundProcessLauncher` | Its public `start` runs Policy/Approval/Authorization and permits the configured best-effort or required containment mode; it rejects private managed requests | Retain for general process Tools, but explicitly forbid this generic public method for managed Worker admission |
| Private managed-process substrate | `src/loushang/harness/tools/process_hosting.py::_managed_process_launch_request`, `src/loushang/harness/tools/process_hosting.py::ScopeBoundProcessLauncher._start_managed`, and `src/loushang/harness/tools/process_hosting.py::ScopeBoundProcessLauncher._verify_managed_start_authority` | Existing private mechanics require an owner-minted request/launcher, mandatory Approval, required containment, and verification of a Sandbox-owner-bound plan | Reuse behind a new owner-only `ManagedWorkerLaunchPort`; neither the private symbols nor the generic launcher become a Worker-facing API |
| Existing managed caller precedent | `src/loushang/harness/tools/skill_actions.py::execute_managed_skill_action` | Managed Skill actions privately construct the sealed request and call the managed start path after verifying authority | Retain as proof of the current owner-only chain, not as a Worker port or declaration contract |
| Long-lived containment planner | `src/loushang/harness/sandbox/process.py::HostedProcessContainmentPlanner` | Plans/tracks hosted-process containment; required mode fails closed and verifies Sandbox-owned managed plans | Retain as the Worker containment owner; degraded/best-effort plans never satisfy managed Worker admission |
| Process/Sandbox composition root | `src/loushang/harness/sandbox/runtime.py::SandboxExecutionRuntime.bind_process_launcher` | Mints the current generic launcher over its owned Process Host and containment planner and privately binds managed-owner authority when available; its return type alone does not prove Worker-grade admission | PLC9C adds the separate owner-only managed Worker port at this owner composition boundary; Worker hosts do not construct Process Host/Sandbox directly |
| Exec-scope Sandbox service | `src/loushang/harness/sandbox/service.py::LocalSandboxService` | Owns selected backend Exec scopes and fail-closed behavior when containment is required | Retain for Exec; do not misidentify it as the complete hosted-Worker chain |
| Capability domain hosts | `src/loushang/harness/capabilities/component_host.py::CapabilityComponentHost` and `src/loushang/harness/capabilities/owner_component_host.py::CapabilityOwnerComponentHost` | Own Capability semantic admission/binding and exact owner composition | Retain; a Capability Worker protocol terminates here, not in Plugin management |
| Resource owner generation | `src/loushang/harness/resource_catalog/generation.py::PreparedResourceOwnerGeneration` | Owns prepared Resource/Skill Catalog generation publication/rollback/retirement | Retain; Worker-derived Resource facts still publish through this owner path |
| Continuity domain host | `src/loushang/harness/continuity/plugin_provider.py::PluginContinuityProvider` | Owns Continuity provider generation calls, mutation preparation, and domain deletion candidates | Retain; a Worker transport cannot become the Continuity owner |

There is no implemented Plugin `local_worker` declaration or supervised Worker
envelope on this baseline. There is also no accepted `remote_service`
declaration/client topology. Process Host and Sandbox substrate existence does
not imply either feature is implemented.

## Cleanup, Data, And Compatibility Seams

| Current seam | Exact source owner or symbol | Current fact | PLC9 disposition and gate |
| --- | --- | --- | --- |
| Cleanup attempts and repair | `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageLifecycleLedger` | Derives `pending`, `retryable_failure`, `terminal_failure`, `retry_permitted`, `succeeded`, and `safe_abandoned` from durable attempts/decisions | Retain; PLC9D adds operator projection and exact deletion execution without releasing debt implicitly |
| GC candidate | `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageGcCandidateV1` | Binds desired, Instance, package-journal, and recovery-barrier revisions | Retain and recheck immediately before exact revision deletion; desired absence alone is insufficient |
| Coding private roots | `src/loushang/coding/_plugin_lifecycle.py::CodingPluginLifecycleStateLayout` | Separates private lifecycle state and package data bases and prepares private directory permissions | Retain path containment; path ownership is not deletion authorization |
| Continuity deletion authorization | `src/loushang/harness/plugin_management/continuity_mutation.py::PluginContinuityDeletionAuthority` | Serializes one exact deletion, durably authorizes it, and settles terminal receipt/cancel evidence; it does not perform the source mutation | Retain as Product authorization/settlement precedent; never elevate it into a generic destructive executor |
| Continuity destructive commit | `src/loushang/harness/continuity/mutation.py::AuthorizedContinuityDeletionLease._commit_complete_and_release` over the source-owned `PreparedContinuityDeletion.commit` port, prepared by `src/loushang/harness/continuity/plugin_provider.py::PluginContinuityProvider._prepare_delete` | Calls the source/data-domain candidate commit first, validates its receipt, then asks the Product authority to settle | Retain the plan -> authorization -> source commit -> receipt settlement order for any future domain deletion contract |
| Continuity lifecycle adapter | `src/loushang/harness/plugin_management/continuity_adapter.py::PluginInstanceLedgerContinuityFamilyAuthority` | Adapts Continuity provider family lifetime to generic Instance/package ledgers | Retain until the same exact domain contract has another accepted composition; never delete merely because its filename says adapter |
| Generic private-data deletion | no common owner/contract on this baseline | Plugin removal does not generically delete private mutable data | PLC9D requires separate confirmation, domain-owned plan/receipt, and tests proving remove/GC cannot invoke it |
| Backup retention/expiry | no common Plugin projection on this baseline | Local deletion has no authority to claim backup expiry | PLC9D projects the exact backup owner or reports unsupported/unknown; it never guesses completion |

## Compatibility Candidate Ledger

PLC9.0 classifies current candidates now; PLC9E may update this ledger but may
not discover an unnamed deletion target in the deletion change itself.

| Candidate | Current caller/authority risk | Disposition | Named deletion or retention gate |
| --- | --- | --- | --- |
| `src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime.uninstall_sync` | `SessionPackageController.uninstall_package` preserves a synchronous fallback that can reach mutable Package deletion | migrate/delete | async Session/RPC/CLI conformance passes, no production sync caller remains, and rollback does not need the sync mutation |
| `src/loushang/harness/resources/plugins/manager.py::PluginManager` | owns peer registry and enable/disable/source mutation | delete | production and supported test/client callers use management/query/Source ports; architecture guard forbids reconstruction |
| `src/loushang/harness/resources/plugins/resolver.py::PluginResolver.resolve_resources` | deny-only compatibility entrypoint; direct callers could mistake it for runtime Resource authority | delete | all supported callers use `PluginResolutionAuthority.resolve_resources`; route-exclusivity tests move to the canonical port |
| `src/loushang/harness/resources/plugins/safe_files.py` compatibility import | Plugin manifest and public validation currently import the Plugin-local alias of the neutral safe-file capture | migrate/delete shim | a supported neutral import surface exists for both internal parser and public SDK validation; callers migrate in one compatibility-reviewed change |
| `src/loushang/harness/resources/plugins/import_realm.py::PluginImportRealm` | named “compatibility” but is the active fail-closed gate for verified in-process imports | retain | retain until in-process topology is removed by a separate architecture decision; never delete or bypass based on naming alone |
| `src/loushang/harness/extensions/loader.py::_adapt_legacy_extension_object` | synthesizes legacy Extension handlers/Tools during load | decision-required, then migrate/delete | exact Product caller inventory, parity through canonical Extension declarations/owners, and rollback fixture are accepted |
| `src/loushang/coding/_plugin_lifecycle.py::CodingPluginLifecycle.publish_session_owner_generations` | preserves direct publish for legacy/public callers and synthesizes prepare evidence | migrate/delete compatibility branch | every publisher calls prepare before publication, historical journal replay passes, and the direct method has no caller |
| `src/loushang/harness/plugin_management/continuity_adapter.py::PluginInstanceLedgerContinuityFamilyAuthority` | Product/domain adapter binds Continuity family lifetime to generic Instance/Package ledgers without peer state | retain | retain while Continuity uses this exact contract; replacement requires equivalent domain conformance and recovery evidence |
| `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.remove_remote_source`, `forget_remote_source`, and `forget_plugin_binding` | mutable cache/source-binding compatibility deletion can bypass Plugin retirement/GC/replay evidence | narrow for non-Plugin; route/refuse Plugin-bound targets | exact Plugin-bound caller inventory is empty, replay/pin/rollback tests pass, and architecture guard rejects future bypass |

Each candidate records whether it is retained, migrated, deleted, narrowed, or
requires a decision. A filename or “legacy” comment is never deletion evidence.

## Missing Target Boundaries

These remain deliberately absent and therefore cannot be imported or exercised
by PLC9A1 tests. The former missing common management query snapshot/projector
and transport-neutral query port is now implemented by
`src/loushang/harness/plugin_management/application.py` and frozen by the
PLC9A1 contract:

- RPC/UI/management-SDK transport conformance fixture (CLI is bound in A1-3);
- complete bounded byte/archive/wheel materialization transaction;
- versioned `local_worker` execution-topology IR, handshake, semantic protocol, and
  supervised domain-host envelope;
- owner-only managed Worker launch port minted by Process/Sandbox composition;
- `remote_service` topology contract and client;
- executable artifact-GC owner/receipt;
- generic Plugin-private data deletion command/receipt; and
- correlated backup-retention projection.

Later slices must first add a focused contract and negative tests for the
relevant boundary, then revise this inventory in the same change. Absence is a
guardrail, not an invitation to infer an API shape.

## Dependency Direction

The accepted direction is:

```text
CLI / RPC / UI / management SDK
  -> management application command/query ports
     -> durable desired/operation owner
     -> read-only joins over Package, Instance, domain-owner, Process Host,
        Sandbox, cleanup, private-data, and backup snapshots

Source Authority -> bounded Package lifecycle sink -> immutable revision
exact domain Worker host -> authorized Process Host + Sandbox
exact domain Worker host -> exact domain publication owner
```

Forbidden reverse edges include management ledgers importing CLI/UI/RPC,
Process Host importing Plugin declarations, Sandbox importing management,
Package materialization importing Product UI, and the author SDK importing any
concrete owner implementation.

## Inventory Change Protocol

Any PLC9 change that adds, migrates, or deletes a row must include:

1. the exact qualified source site and authority classification;
2. the old and new caller inventory;
3. positive behavioral evidence at the canonical port;
4. a negative architecture guard against restoring the peer path;
5. recovery, replay, idempotency, and partial-failure evidence when durable
   state changes; and
6. an explicit deletion gate for every compatibility bridge.

Directory-wide exemptions and prose-only claims are not acceptable inventory
updates.

# Coding package component migration

## Scope and ownership

The first internal componentization batch relocates all 187 root `package*.py`
implementations from main `5b0c18d096c751a92aeb9200c411d879d23c0bef` into
`loushang.coding.package`. Each basename loses its redundant `package_` prefix.
The implementations remain in Coding. This batch does not extract Harness
capabilities or claim deletion of the relocated implementation.

The component contains product package selection/materialization, installation
and epoch bindings, private-data lifecycle integration, and product Worker
payload, approval, launch, receipt, history and retirement integration. Existing
Harness and Hosting mechanisms remain their owners; their implementations are
not copied into the component. CLI, UI and session composition remain consumers
outside it. This directory is the first cohesive boundary, not a claim that all
remaining root responsibilities or its internal sub-capabilities are finished.

Real first-party imports, dynamic module references and source inventories use
the new paths. Source-relative locations are rebased for the built-in plugin
wheel and native launcher source. Hosting's source-attestation member path now
names the relocated provisioning source; identity/hash validation is retained.
Source locations and hashes change with this release. Historical inventory
hashes remain evidence of their named historical revision, not the new source.

## Compatibility edge

`package/__init__.py` has no eager implementation exports. Three files provide
the bounded compatibility edge: this initializer, `_legacy_names.py` (the exact
187-name inventory), and `_imports.py`. Coding installs the finder once during
initialization. It handles only those old and canonical leaf names and delegates
source loading to Python's ordinary loader and import locks.

Old and new imports resolve to the same module and definitions; root legacy
module attributes, historical class/function module identities and pickle lookup
remain available. The implementation spec and physical source filename point to
the canonical component. Loader source/code/filename lookup accepts either name.
This avoids 187 root forwarding modules and does not create a second business
implementation. The compatibility code owns import identity only, with no
package policy, transaction, resource or Worker lifecycle decisions.

Retain these aliases while supported external imports or stored pickle references
need them. Removal requires evidence that supported consumers and retained data
no longer require the old names, followed by an explicit compatibility decision.
Runtime aliases do not provide old leaf-module source stubs to static type
checkers; first-party static probes import the canonical modules. The existing
public Coding facade and its explicit static exports remain unchanged.

## Evidence and limitations

The frozen pre-move inventory has 187 files and 31,606 physical Python lines.
The batch's inert reflection comparison covers 187 imports and 609 public
entries; the original 1,118 protocol-4/5 class/function pickle references load to
the same objects and reserialize identically. These checks do not establish
native platform behavior or complete historical instance-data recovery.

The source-body audit found no implementation AST changes after normalization of
declared import/path relocations and the two source-relative locations, and no
lost original source comments. Existing CI selection tests pass (150 tests).
All 190 component Python files pass mypy; Coding passes Ruff. The real SDK
session/tools/diagnostics smoke passes with the authorized private test runtime.
Full batch regression and remote platform checks are still pending; these local
results are not delivery acceptance.

The ordinary machine test-runtime directory failed the unchanged SDK runtime
baseline with `transcript_writer:unsafe`. The user authorized a private test
runtime for this task. The pre-move full SDK rerun there also recorded four
60-second cold-subprocess timeouts and was interrupted. Those baseline failures
are retained separately from candidate results; no Product timeout or safety
check is weakened.

At this snapshot Coding root Python files fall from 299 to 112. Coding and the
system each grow by 366 physical production Python lines; Harness and Hosting
line totals are unchanged. The compatibility files total 337 lines, the root
loader installation adds lines, and import rebasing/formatting changes the
remaining physical-line count. These are compatibility and organization costs,
not system simplification. Tests and documentation are excluded from production
counts. These counts use `src/**/*.py`; they do not count native or frontend
sources.

A normalized AST import-edge audit adds no edges between original Coding modules
(1,656 before, 1,652 after). Four old root-package imports now resolve directly
to component children. Thus the original-module static graph gains no cycles;
the new import-only compatibility edge and dynamic imports require separate
review and runtime coverage. This does not claim to remove pre-existing cycles.

CI scope globs and workflow source arguments are relocated with their original
coverage. The equivalence audit matches every changed glob's old file set to its
new paths. No new test case, gate, trigger, platform or required check is added.

## Exact implementation mapping

All paths below are relative to `src/loushang/coding/`. Line counts refer to the
frozen original files; movement and import formatting are not deletion credit.

| Original root file | Component file | Baseline lines |
| --- | --- | ---: |
| `package_arch_private_cache.py` | `package/arch_private_cache.py` | 20 |
| `package_builtin_wheel.py` | `package/builtin_wheel.py` | 389 |
| `package_cutover_backup.py` | `package/cutover_backup.py` | 73 |
| `package_epoch_layout.py` | `package/epoch_layout.py` | 301 |
| `package_external_data_wheel.py` | `package/external_data_wheel.py` | 229 |
| `package_external_dependency_wheel.py` | `package/external_dependency_wheel.py` | 308 |
| `package_external_worker_wheel.py` | `package/external_worker_wheel.py` | 436 |
| `package_installation_private_data.py` | `package/installation_private_data.py` | 328 |
| `package_legacy_binding_catalog.py` | `package/legacy_binding_catalog.py` | 391 |
| `package_legacy_builtin_acceptance.py` | `package/legacy_builtin_acceptance.py` | 179 |
| `package_legacy_builtin_adoption.py` | `package/legacy_builtin_adoption.py` | 131 |
| `package_legacy_builtin_review.py` | `package/legacy_builtin_review.py` | 436 |
| `package_legacy_classification.py` | `package/legacy_classification.py` | 203 |
| `package_legacy_configured_source.py` | `package/legacy_configured_source.py` | 93 |
| `package_legacy_data_trust.py` | `package/legacy_data_trust.py` | 40 |
| `package_legacy_desired_evidence.py` | `package/legacy_desired_evidence.py` | 105 |
| `package_legacy_disabled_acceptance.py` | `package/legacy_disabled_acceptance.py` | 164 |
| `package_legacy_disabled_review.py` | `package/legacy_disabled_review.py` | 184 |
| `package_legacy_installation_inventory.py` | `package/legacy_installation_inventory.py` | 455 |
| `package_legacy_instance_evidence.py` | `package/legacy_instance_evidence.py` | 59 |
| `package_legacy_local_acceptance.py` | `package/legacy_local_acceptance.py` | 427 |
| `package_legacy_local_adoption.py` | `package/legacy_local_adoption.py` | 338 |
| `package_legacy_local_adoption_read.py` | `package/legacy_local_adoption_read.py` | 176 |
| `package_legacy_local_binding_owner.py` | `package/legacy_local_binding_owner.py` | 120 |
| `package_legacy_local_installation.py` | `package/legacy_local_installation.py` | 289 |
| `package_legacy_local_wheel.py` | `package/legacy_local_wheel.py` | 95 |
| `package_legacy_lock_evidence.py` | `package/legacy_lock_evidence.py` | 183 |
| `package_legacy_operation_evidence.py` | `package/legacy_operation_evidence.py` | 149 |
| `package_legacy_reacquisition.py` | `package/legacy_reacquisition.py` | 90 |
| `package_legacy_removed_acceptance.py` | `package/legacy_removed_acceptance.py` | 153 |
| `package_legacy_removed_adoption.py` | `package/legacy_removed_adoption.py` | 127 |
| `package_legacy_removed_review.py` | `package/legacy_removed_review.py` | 788 |
| `package_legacy_review.py` | `package/legacy_review.py` | 409 |
| `package_legacy_skill_cutover_admission.py` | `package/legacy_skill_cutover_admission.py` | 451 |
| `package_legacy_snapshot_member.py` | `package/legacy_snapshot_member.py` | 133 |
| `package_legacy_source_consumption.py` | `package/legacy_source_consumption.py` | 172 |
| `package_legacy_source_evidence.py` | `package/legacy_source_evidence.py` | 140 |
| `package_legacy_windows_receipt.py` | `package/legacy_windows_receipt.py` | 71 |
| `package_pre_b_snapshot.py` | `package/pre_b_snapshot.py` | 380 |
| `package_private_data_backup.py` | `package/private_data_backup.py` | 275 |
| `package_private_data_backup_expiry.py` | `package/private_data_backup_expiry.py` | 275 |
| `package_private_data_backup_expiry_journal.py` | `package/private_data_backup_expiry_journal.py` | 190 |
| `package_private_data_backup_expiry_records.py` | `package/private_data_backup_expiry_records.py` | 274 |
| `package_private_data_backup_records.py` | `package/private_data_backup_records.py` | 223 |
| `package_private_data_backup_sdk.py` | `package/private_data_backup_sdk.py` | 326 |
| `package_private_data_deletion_journal.py` | `package/private_data_deletion_journal.py` | 132 |
| `package_private_data_deletion_owner.py` | `package/private_data_deletion_owner.py` | 167 |
| `package_private_data_deletion_preview.py` | `package/private_data_deletion_preview.py` | 158 |
| `package_private_data_read_owner.py` | `package/private_data_read_owner.py` | 278 |
| `package_private_data_restore.py` | `package/private_data_restore.py` | 366 |
| `package_private_data_restore_confirmation.py` | `package/private_data_restore_confirmation.py` | 249 |
| `package_private_data_restore_journal.py` | `package/private_data_restore_journal.py` | 192 |
| `package_private_data_restore_records.py` | `package/private_data_restore_records.py` | 81 |
| `package_private_data_windows_archive_snapshot.py` | `package/private_data_windows_archive_snapshot.py` | 123 |
| `package_private_data_windows_backup.py` | `package/private_data_windows_backup.py` | 231 |
| `package_private_data_windows_backup_client.py` | `package/private_data_windows_backup_client.py` | 344 |
| `package_private_data_windows_backup_expiry_journal.py` | `package/private_data_windows_backup_expiry_journal.py` | 314 |
| `package_private_data_windows_backup_expiry_owner.py` | `package/private_data_windows_backup_expiry_owner.py` | 81 |
| `package_private_data_windows_backup_expiry_preview.py` | `package/private_data_windows_backup_expiry_preview.py` | 164 |
| `package_private_data_windows_backup_expiry_recovery.py` | `package/private_data_windows_backup_expiry_recovery.py` | 140 |
| `package_private_data_windows_confirmation.py` | `package/private_data_windows_confirmation.py` | 216 |
| `package_private_data_windows_deletion_journal.py` | `package/private_data_windows_deletion_journal.py` | 337 |
| `package_private_data_windows_deletion_owner.py` | `package/private_data_windows_deletion_owner.py` | 156 |
| `package_private_data_windows_preview.py` | `package/private_data_windows_preview.py` | 171 |
| `package_private_data_windows_restore_journal.py` | `package/private_data_windows_restore_journal.py` | 353 |
| `package_private_data_windows_restore_owner.py` | `package/private_data_windows_restore_owner.py` | 79 |
| `package_private_data_windows_restore_preview.py` | `package/private_data_windows_restore_preview.py` | 143 |
| `package_product_backup_types.py` | `package/product_backup_types.py` | 207 |
| `package_product_cli.py` | `package/product_cli.py` | 467 |
| `package_product_management_cli.py` | `package/product_management_cli.py` | 539 |
| `package_product_preview.py` | `package/product_preview.py` | 585 |
| `package_product_repair.py` | `package/product_repair.py` | 228 |
| `package_product_repair_rpc.py` | `package/product_repair_rpc.py` | 49 |
| `package_product_repair_ui.py` | `package/product_repair_ui.py` | 86 |
| `package_product_revisions.py` | `package/product_revisions.py` | 219 |
| `package_product_runtime.py` | `package/product_runtime.py` | 1,650 |
| `package_product_worker_activation_base_v2.py` | `package/product_worker_activation_base_v2.py` | 32 |
| `package_product_worker_activation_history.py` | `package/product_worker_activation_history.py` | 50 |
| `package_product_worker_activation_state.py` | `package/product_worker_activation_state.py` | 98 |
| `package_product_worker_activation_state_journal.py` | `package/product_worker_activation_state_journal.py` | 88 |
| `package_product_worker_capability.py` | `package/product_worker_capability.py` | 78 |
| `package_product_worker_cleanup_evidence.py` | `package/product_worker_cleanup_evidence.py` | 44 |
| `package_product_worker_crash_c5_settlement.py` | `package/product_worker_crash_c5_settlement.py` | 98 |
| `package_product_worker_discovery.py` | `package/product_worker_discovery.py` | 61 |
| `package_product_worker_gc_references.py` | `package/product_worker_gc_references.py` | 25 |
| `package_product_worker_history_checkpoint.py` | `package/product_worker_history_checkpoint.py` | 240 |
| `package_product_worker_history_checkpoint_anchor.py` | `package/product_worker_history_checkpoint_anchor.py` | 66 |
| `package_product_worker_history_commit_v2.py` | `package/product_worker_history_commit_v2.py` | 105 |
| `package_product_worker_history_cutover_v2.py` | `package/product_worker_history_cutover_v2.py` | 99 |
| `package_product_worker_history_deletion_v2.py` | `package/product_worker_history_deletion_v2.py` | 34 |
| `package_product_worker_history_preflight_v2.py` | `package/product_worker_history_preflight_v2.py` | 78 |
| `package_product_worker_history_prepared_v2.py` | `package/product_worker_history_prepared_v2.py` | 98 |
| `package_product_worker_history_read_v2.py` | `package/product_worker_history_read_v2.py` | 87 |
| `package_product_worker_history_retention.py` | `package/product_worker_history_retention.py` | 306 |
| `package_product_worker_history_retire_v2.py` | `package/product_worker_history_retire_v2.py` | 82 |
| `package_product_worker_history_retirement_preview.py` | `package/product_worker_history_retirement_preview.py` | 59 |
| `package_product_worker_history_rotate_v2.py` | `package/product_worker_history_rotate_v2.py` | 51 |
| `package_product_worker_history_segments.py` | `package/product_worker_history_segments.py` | 18 |
| `package_product_worker_history_stage_v2.py` | `package/product_worker_history_stage_v2.py` | 158 |
| `package_product_worker_history_stream_snapshot.py` | `package/product_worker_history_stream_snapshot.py` | 120 |
| `package_product_worker_history_v2_names.py` | `package/product_worker_history_v2_names.py` | 4 |
| `package_product_worker_installed_native.py` | `package/product_worker_installed_native.py` | 154 |
| `package_product_worker_native_approval.py` | `package/product_worker_native_approval.py` | 155 |
| `package_product_worker_native_install.py` | `package/product_worker_native_install.py` | 74 |
| `package_product_worker_native_release.py` | `package/product_worker_native_release.py` | 77 |
| `package_product_worker_no_effect_archive_v2.py` | `package/product_worker_no_effect_archive_v2.py` | 74 |
| `package_product_worker_no_effect_closure.py` | `package/product_worker_no_effect_closure.py` | 31 |
| `package_product_worker_operator_query.py` | `package/product_worker_operator_query.py` | 295 |
| `package_product_worker_opt_in.py` | `package/product_worker_opt_in.py` | 182 |
| `package_product_worker_opt_in_base_v2.py` | `package/product_worker_opt_in_base_v2.py` | 49 |
| `package_product_worker_opt_in_owner.py` | `package/product_worker_opt_in_owner.py` | 72 |
| `package_product_worker_ordinary_bootstrap.py` | `package/product_worker_ordinary_bootstrap.py` | 265 |
| `package_product_worker_ordinary_error.py` | `package/product_worker_ordinary_error.py` | 12 |
| `package_product_worker_payload.py` | `package/product_worker_payload.py` | 319 |
| `package_product_worker_pending_host.py` | `package/product_worker_pending_host.py` | 175 |
| `package_product_worker_policy.py` | `package/product_worker_policy.py` | 194 |
| `package_product_worker_posix_gc_history.py` | `package/product_worker_posix_gc_history.py` | 60 |
| `package_product_worker_provider.py` | `package/product_worker_provider.py` | 165 |
| `package_product_worker_provider_host.py` | `package/product_worker_provider_host.py` | 90 |
| `package_product_worker_query_consumer.py` | `package/product_worker_query_consumer.py` | 159 |
| `package_product_worker_receipt.py` | `package/product_worker_receipt.py` | 473 |
| `package_product_worker_receipt_base_v2.py` | `package/product_worker_receipt_base_v2.py` | 44 |
| `package_product_worker_registered_c5_settlement.py` | `package/product_worker_registered_c5_settlement.py` | 102 |
| `package_product_worker_registered_payload_repair.py` | `package/product_worker_registered_payload_repair.py` | 170 |
| `package_product_worker_registered_recovery.py` | `package/product_worker_registered_recovery.py` | 147 |
| `package_product_worker_resume.py` | `package/product_worker_resume.py` | 151 |
| `package_product_worker_session_composition.py` | `package/product_worker_session_composition.py` | 208 |
| `package_product_worker_start_gate.py` | `package/product_worker_start_gate.py` | 58 |
| `package_product_worker_start_gate_base_v2.py` | `package/product_worker_start_gate_base_v2.py` | 53 |
| `package_product_worker_start_gate_journal.py` | `package/product_worker_start_gate_journal.py` | 216 |
| `package_product_worker_start_gate_recovery.py` | `package/product_worker_start_gate_recovery.py` | 195 |
| `package_product_worker_supervisor_base_v2.py` | `package/product_worker_supervisor_base_v2.py` | 57 |
| `package_product_worker_supervisor_journal.py` | `package/product_worker_supervisor_journal.py` | 42 |
| `package_product_worker_turn_tool.py` | `package/product_worker_turn_tool.py` | 73 |
| `package_product_worker_windows_activation_state_journal.py` | `package/product_worker_windows_activation_state_journal.py` | 54 |
| `package_product_worker_windows_backend_release.py` | `package/product_worker_windows_backend_release.py` | 129 |
| `package_product_worker_windows_base_files.py` | `package/product_worker_windows_base_files.py` | 22 |
| `package_product_worker_windows_c5_base.py` | `package/product_worker_windows_c5_base.py` | 80 |
| `package_product_worker_windows_checkpoint.py` | `package/product_worker_windows_checkpoint.py` | 212 |
| `package_product_worker_windows_cleanup_evidence.py` | `package/product_worker_windows_cleanup_evidence.py` | 96 |
| `package_product_worker_windows_crash_c5_settlement.py` | `package/product_worker_windows_crash_c5_settlement.py` | 28 |
| `package_product_worker_windows_crash_cleanup_review.py` | `package/product_worker_windows_crash_cleanup_review.py` | 84 |
| `package_product_worker_windows_crash_lease_repair.py` | `package/product_worker_windows_crash_lease_repair.py` | 60 |
| `package_product_worker_windows_crash_native_settlement.py` | `package/product_worker_windows_crash_native_settlement.py` | 46 |
| `package_product_worker_windows_crash_recovery.py` | `package/product_worker_windows_crash_recovery.py` | 90 |
| `package_product_worker_windows_crash_stage_retirement.py` | `package/product_worker_windows_crash_stage_retirement.py` | 90 |
| `package_product_worker_windows_crash_stage_review.py` | `package/product_worker_windows_crash_stage_review.py` | 103 |
| `package_product_worker_windows_crash_supervisor_settlement.py` | `package/product_worker_windows_crash_supervisor_settlement.py` | 38 |
| `package_product_worker_windows_desired_references.py` | `package/product_worker_windows_desired_references.py` | 56 |
| `package_product_worker_windows_gc_history.py` | `package/product_worker_windows_gc_history.py` | 89 |
| `package_product_worker_windows_history_bases.py` | `package/product_worker_windows_history_bases.py` | 79 |
| `package_product_worker_windows_history_cutover_preflight.py` | `package/product_worker_windows_history_cutover_preflight.py` | 48 |
| `package_product_worker_windows_history_cutover_record.py` | `package/product_worker_windows_history_cutover_record.py` | 80 |
| `package_product_worker_windows_history_join.py` | `package/product_worker_windows_history_join.py` | 70 |
| `package_product_worker_windows_history_preparation.py` | `package/product_worker_windows_history_preparation.py` | 111 |
| `package_product_worker_windows_history_sources.py` | `package/product_worker_windows_history_sources.py` | 165 |
| `package_product_worker_windows_installed_backend.py` | `package/product_worker_windows_installed_backend.py` | 148 |
| `package_product_worker_windows_launch_intent.py` | `package/product_worker_windows_launch_intent.py` | 215 |
| `package_product_worker_windows_launch_intent_base.py` | `package/product_worker_windows_launch_intent_base.py` | 102 |
| `package_product_worker_windows_native_approval_journal.py` | `package/product_worker_windows_native_approval_journal.py` | 92 |
| `package_product_worker_windows_native_approval_owner.py` | `package/product_worker_windows_native_approval_owner.py` | 81 |
| `package_product_worker_windows_opt_in_base.py` | `package/product_worker_windows_opt_in_base.py` | 87 |
| `package_product_worker_windows_opt_in_journal.py` | `package/product_worker_windows_opt_in_journal.py` | 66 |
| `package_product_worker_windows_opt_in_owner.py` | `package/product_worker_windows_opt_in_owner.py` | 66 |
| `package_product_worker_windows_orphan_review.py` | `package/product_worker_windows_orphan_review.py` | 112 |
| `package_product_worker_windows_package_references.py` | `package/product_worker_windows_package_references.py` | 129 |
| `package_product_worker_windows_partial_stage_retirement.py` | `package/product_worker_windows_partial_stage_retirement.py` | 86 |
| `package_product_worker_windows_partial_stage_review.py` | `package/product_worker_windows_partial_stage_review.py` | 146 |
| `package_product_worker_windows_payload.py` | `package/product_worker_windows_payload.py` | 170 |
| `package_product_worker_windows_payload_inventory.py` | `package/product_worker_windows_payload_inventory.py` | 86 |
| `package_product_worker_windows_pending_host.py` | `package/product_worker_windows_pending_host.py` | 203 |
| `package_product_worker_windows_persisted_bases.py` | `package/product_worker_windows_persisted_bases.py` | 195 |
| `package_product_worker_windows_provisioning.py` | `package/product_worker_windows_provisioning.py` | 116 |
| `package_product_worker_windows_provisioning_base.py` | `package/product_worker_windows_provisioning_base.py` | 93 |
| `package_product_worker_windows_provisioning_journal.py` | `package/product_worker_windows_provisioning_journal.py` | 37 |
| `package_product_worker_windows_receipt.py` | `package/product_worker_windows_receipt.py` | 141 |
| `package_product_worker_windows_receipt_base.py` | `package/product_worker_windows_receipt_base.py` | 82 |
| `package_product_worker_windows_receipt_journal.py` | `package/product_worker_windows_receipt_journal.py` | 47 |
| `package_product_worker_windows_recovery_inventory.py` | `package/product_worker_windows_recovery_inventory.py` | 263 |
| `package_product_worker_windows_reserved_review.py` | `package/product_worker_windows_reserved_review.py` | 211 |
| `package_product_worker_windows_reserved_settlement.py` | `package/product_worker_windows_reserved_settlement.py` | 73 |
| `package_product_worker_windows_stage_retirement.py` | `package/product_worker_windows_stage_retirement.py` | 143 |
| `package_product_worker_windows_stage_review.py` | `package/product_worker_windows_stage_review.py` | 183 |
| `package_product_worker_windows_supervisor_base.py` | `package/product_worker_windows_supervisor_base.py` | 84 |
| `package_product_worker_windows_supervisor_journal.py` | `package/product_worker_windows_supervisor_journal.py` | 50 |
| `package_product_worker_windows_unlaunched_stage_retirement.py` | `package/product_worker_windows_unlaunched_stage_retirement.py` | 93 |
| `package_source_snapshot.py` | `package/source_snapshot.py` | 123 |

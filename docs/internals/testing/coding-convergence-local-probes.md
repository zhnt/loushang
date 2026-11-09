# Coding Convergence Local Probes

These carried compatibility and ownership probes are explicit local validation.
They are excluded from default directory collection by the `probe_*.py` filename.
The original main test inventory, classification catalog, CI routes and platforms
are unchanged. Existing historical run records retain their original paths; the
mapping below identifies the current executable sources. Fixtures remain in place.

Run explicit paths through `scripts/dev/run_pytest.py`, with the task worktree src
on PYTHONPATH, private disk runtime, outside the sandbox and with the existing
`not live` / `--skip-host-runtime` selectors. Passing these probes does not claim
that existing PR gates executed them.

| Historical path | Current explicit local path |
| --- | --- |
| `tests/coding/test_arch_private_cache_stream_ownership.py` | [tests/coding/probe_arch_private_cache_stream_ownership.py](../../../tests/coding/probe_arch_private_cache_stream_ownership.py) |
| `tests/coding/test_external_wheel_io_compatibility.py` | [tests/coding/probe_external_wheel_io_compatibility.py](../../../tests/coding/probe_external_wheel_io_compatibility.py) |
| `tests/coding/test_legacy_receipt_publication_compatibility.py` | [tests/coding/probe_legacy_receipt_publication_compatibility.py](../../../tests/coding/probe_legacy_receipt_publication_compatibility.py) |
| `tests/coding/test_posix_expiry_action_compatibility.py` | [tests/coding/probe_posix_expiry_action_compatibility.py](../../../tests/coding/probe_posix_expiry_action_compatibility.py) |
| `tests/coding/test_posix_expiry_journal_compatibility.py` | [tests/coding/probe_posix_expiry_journal_compatibility.py](../../../tests/coding/probe_posix_expiry_journal_compatibility.py) |
| `tests/coding/test_posix_restore_action_compatibility.py` | [tests/coding/probe_posix_restore_action_compatibility.py](../../../tests/coding/probe_posix_restore_action_compatibility.py) |
| `tests/coding/test_private_archive_inventory_compatibility.py` | [tests/coding/probe_private_archive_inventory_compatibility.py](../../../tests/coding/probe_private_archive_inventory_compatibility.py) |
| `tests/coding/test_private_data_journal_compatibility.py` | [tests/coding/probe_private_data_journal_compatibility.py](../../../tests/coding/probe_private_data_journal_compatibility.py) |
| `tests/coding/test_private_data_record_compatibility.py` | [tests/coding/probe_private_data_record_compatibility.py](../../../tests/coding/probe_private_data_record_compatibility.py) |
| `tests/coding/test_private_journal_binding_compatibility.py` | [tests/coding/probe_private_journal_binding_compatibility.py](../../../tests/coding/probe_private_journal_binding_compatibility.py) |
| `tests/coding/test_private_restore_history_compatibility.py` | [tests/coding/probe_private_restore_history_compatibility.py](../../../tests/coding/probe_private_restore_history_compatibility.py) |
| `tests/coding/test_private_windows_receipt_compatibility.py` | [tests/coding/probe_private_windows_receipt_compatibility.py](../../../tests/coding/probe_private_windows_receipt_compatibility.py) |
| `tests/coding/test_private_windows_tree_io_compatibility.py` | [tests/coding/probe_private_windows_tree_io_compatibility.py](../../../tests/coding/probe_private_windows_tree_io_compatibility.py) |
| `tests/coding/test_rooted_supervisor_execution.py` | [tests/coding/probe_rooted_supervisor_execution.py](../../../tests/coding/probe_rooted_supervisor_execution.py) |
| `tests/coding/test_tool_pack_binding_compatibility.py` | [tests/coding/probe_tool_pack_binding_compatibility.py](../../../tests/coding/probe_tool_pack_binding_compatibility.py) |
| `tests/coding/test_windows_archive_action_compatibility.py` | [tests/coding/probe_windows_archive_action_compatibility.py](../../../tests/coding/probe_windows_archive_action_compatibility.py) |
| `tests/coding/test_windows_archive_snapshot_compatibility.py` | [tests/coding/probe_windows_archive_snapshot_compatibility.py](../../../tests/coding/probe_windows_archive_snapshot_compatibility.py) |
| `tests/coding/test_windows_base_wire_compatibility.py` | [tests/coding/probe_windows_base_wire_compatibility.py](../../../tests/coding/probe_windows_base_wire_compatibility.py) |
| `tests/coding/test_windows_confirmation_storage_compatibility.py` | [tests/coding/probe_windows_confirmation_storage_compatibility.py](../../../tests/coding/probe_windows_confirmation_storage_compatibility.py) |
| `tests/coding/test_windows_deletion_barrier_compatibility.py` | [tests/coding/probe_windows_deletion_barrier_compatibility.py](../../../tests/coding/probe_windows_deletion_barrier_compatibility.py) |
| `tests/coding/test_windows_deletion_effect_compatibility.py` | [tests/coding/probe_windows_deletion_effect_compatibility.py](../../../tests/coding/probe_windows_deletion_effect_compatibility.py) |
| `tests/coding/test_windows_deletion_procedure_compatibility.py` | [tests/coding/probe_windows_deletion_procedure_compatibility.py](../../../tests/coding/probe_windows_deletion_procedure_compatibility.py) |
| `tests/coding/test_windows_expiry_action_compatibility.py` | [tests/coding/probe_windows_expiry_action_compatibility.py](../../../tests/coding/probe_windows_expiry_action_compatibility.py) |
| `tests/coding/test_windows_expiry_journal_compatibility.py` | [tests/coding/probe_windows_expiry_journal_compatibility.py](../../../tests/coding/probe_windows_expiry_journal_compatibility.py) |
| `tests/coding/test_windows_history_source_compatibility.py` | [tests/coding/probe_windows_history_source_compatibility.py](../../../tests/coding/probe_windows_history_source_compatibility.py) |
| `tests/coding/test_windows_preview_parent_compatibility.py` | [tests/coding/probe_windows_preview_parent_compatibility.py](../../../tests/coding/probe_windows_preview_parent_compatibility.py) |
| `tests/coding/test_windows_private_record_sequence_compatibility.py` | [tests/coding/probe_windows_private_record_sequence_compatibility.py](../../../tests/coding/probe_windows_private_record_sequence_compatibility.py) |
| `tests/coding/test_windows_record_file_compatibility.py` | [tests/coding/probe_windows_record_file_compatibility.py](../../../tests/coding/probe_windows_record_file_compatibility.py) |
| `tests/coding/test_windows_recovery_value_compatibility.py` | [tests/coding/probe_windows_recovery_value_compatibility.py](../../../tests/coding/probe_windows_recovery_value_compatibility.py) |
| `tests/coding/test_windows_restore_effect_compatibility.py` | [tests/coding/probe_windows_restore_effect_compatibility.py](../../../tests/coding/probe_windows_restore_effect_compatibility.py) |
| `tests/coding/test_windows_restore_transaction_compatibility.py` | [tests/coding/probe_windows_restore_transaction_compatibility.py](../../../tests/coding/probe_windows_restore_transaction_compatibility.py) |
| `tests/coding/test_windows_stage_io_compatibility.py` | [tests/coding/probe_windows_stage_io_compatibility.py](../../../tests/coding/probe_windows_stage_io_compatibility.py) |
| `tests/coding/test_windows_worker_query_contract.py` | [tests/coding/probe_windows_worker_query_contract.py](../../../tests/coding/probe_windows_worker_query_contract.py) |
| `tests/coding/test_worker_append_tail_compatibility.py` | [tests/coding/probe_worker_append_tail_compatibility.py](../../../tests/coding/probe_worker_append_tail_compatibility.py) |
| `tests/coding/test_worker_checkpoint_command_compatibility.py` | [tests/coding/probe_worker_checkpoint_command_compatibility.py](../../../tests/coding/probe_worker_checkpoint_command_compatibility.py) |
| `tests/coding/test_worker_gate_access_compatibility.py` | [tests/coding/probe_worker_gate_access_compatibility.py](../../../tests/coding/probe_worker_gate_access_compatibility.py) |
| `tests/coding/test_worker_gate_append_compatibility.py` | [tests/coding/probe_worker_gate_append_compatibility.py](../../../tests/coding/probe_worker_gate_append_compatibility.py) |
| `tests/coding/test_worker_history_checkpoint_translation.py` | [tests/coding/probe_worker_history_checkpoint_translation.py](../../../tests/coding/probe_worker_history_checkpoint_translation.py) |
| `tests/coding/test_worker_history_public_values.py` | [tests/coding/probe_worker_history_public_values.py](../../../tests/coding/probe_worker_history_public_values.py) |
| `tests/coding/test_worker_history_publication_compatibility.py` | [tests/coding/probe_worker_history_publication_compatibility.py](../../../tests/coding/probe_worker_history_publication_compatibility.py) |
| `tests/coding/test_worker_history_reconstruction.py` | [tests/coding/probe_worker_history_reconstruction.py](../../../tests/coding/probe_worker_history_reconstruction.py) |
| `tests/coding/test_worker_payload_repair_compatibility.py` | [tests/coding/probe_worker_payload_repair_compatibility.py](../../../tests/coding/probe_worker_payload_repair_compatibility.py) |
| `tests/coding/test_worker_receipt_access_compatibility.py` | [tests/coding/probe_worker_receipt_access_compatibility.py](../../../tests/coding/probe_worker_receipt_access_compatibility.py) |
| `tests/coding/test_worker_segment_owner_compatibility.py` | [tests/coding/probe_worker_segment_owner_compatibility.py](../../../tests/coding/probe_worker_segment_owner_compatibility.py) |
| `tests/coding/test_worker_session_composition_compatibility.py` | [tests/coding/probe_worker_session_composition_compatibility.py](../../../tests/coding/probe_worker_session_composition_compatibility.py) |
| `tests/coding/test_worker_supervisor_access_compatibility.py` | [tests/coding/probe_worker_supervisor_access_compatibility.py](../../../tests/coding/probe_worker_supervisor_access_compatibility.py) |
| `tests/coding/test_worker_windows_journal_io_compatibility.py` | [tests/coding/probe_worker_windows_journal_io_compatibility.py](../../../tests/coding/probe_worker_windows_journal_io_compatibility.py) |
| `tests/coding/test_worker_windows_read_scope_compatibility.py` | [tests/coding/probe_worker_windows_read_scope_compatibility.py](../../../tests/coding/probe_worker_windows_read_scope_compatibility.py) |
| `tests/foundation/test_owned_join_compatibility.py` | [tests/foundation/probe_owned_join_compatibility.py](../../../tests/foundation/probe_owned_join_compatibility.py) |
| `tests/harness/journal/test_rooted_context.py` | [tests/harness/journal/probe_rooted_context.py](../../../tests/harness/journal/probe_rooted_context.py) |
| `tests/harness/plugin_management/test_gc_snapshot_compatibility.py` | [tests/harness/plugin_management/probe_gc_snapshot_compatibility.py](../../../tests/harness/plugin_management/probe_gc_snapshot_compatibility.py) |
| `tests/harness/resources/packages/test_controlled_source_stream_ownership.py` | [tests/harness/resources/packages/probe_controlled_source_stream_ownership.py](../../../tests/harness/resources/packages/probe_controlled_source_stream_ownership.py) |
| `tests/harness/resources/packages/test_file_consumption_error_contract.py` | [tests/harness/resources/packages/probe_file_consumption_error_contract.py](../../../tests/harness/resources/packages/probe_file_consumption_error_contract.py) |
| `tests/harness/resources/packages/test_private_tree_read_policy.py` | [tests/harness/resources/packages/probe_private_tree_read_policy.py](../../../tests/harness/resources/packages/probe_private_tree_read_policy.py) |
| `tests/harness/resources/packages/test_windows_journal_stream_ownership.py` | [tests/harness/resources/packages/probe_windows_journal_stream_ownership.py](../../../tests/harness/resources/packages/probe_windows_journal_stream_ownership.py) |
| `tests/harness/session/test_worker_provider_handoff.py` | [tests/harness/session/probe_worker_provider_handoff.py](../../../tests/harness/session/probe_worker_provider_handoff.py) |
| `tests/harness/transcript/test_continuity_portable_source_contract.py` | [tests/harness/transcript/probe_continuity_portable_source_contract.py](../../../tests/harness/transcript/probe_continuity_portable_source_contract.py) |

The builtin-bootstrap probe was added after the carried-probe rename. It uses
31 fixed original full-function observations captured before implementation;
the fixture is never regenerated by the current tests. Product effects are
controlled while Desired records use their real DTOs. It checks action traces,
record encodings and exception graphs, not native-process or physical IO.

Explicit local path: [probe_builtin_bootstrap_compatibility.py](../../../tests/coding/probe_builtin_bootstrap_compatibility.py).

The Worker candidate-update local probe compares both full CLI paths with 96
immutable original observations. Desired/Management DTOs and journal writes
are real; runtime/native ports and Lifecycle request reads are controlled.
The fixture records original commit/source hashes and exact record-byte hashes.
It is explicit local validation, not default PR coverage.

Explicit local path: [probe_worker_candidate_update_compatibility.py](../../../tests/coding/probe_worker_candidate_update_compatibility.py).

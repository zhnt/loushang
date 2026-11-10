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

A88 adds the complete 61-case Windows stage capture replay at
[probe_windows_stage_capture_compatibility.py](../../../tests/coding/probe_windows_stage_capture_compatibility.py).
The fixed gzip fixture is derived only from frozen original observations. Each
fresh input's identities, injected offsets, bytes and bounded read budgets are
checked before physical-role projection; all event ordering, errors and FD debt
remain compared. Use `-p tests.coding.probe_continuity_payload_custody` for this
machine's private temporary input fixture. Windows ACL/native ports are bridged
to real POSIX files/FDs, and cancellation is synchronous fault injection. This
does not prove native Windows or actual Task.cancel interleavings. See the
[A88 evidence and portability correction](../architecture/harness/key-designs/windows-stage-capture-custody-convergence.md).

A89 adds [probe_windows_reserved_capture_compatibility.py](../../../tests/coding/probe_windows_reserved_capture_compatibility.py),
which reuses the A88 observer and runs 75 Reserved capture cases. Original public
type, all ten fields, canonical bytes and both domain hashes are checked against
independent input/schema formulas before role projection. It includes native
revision late rejection, public constructor/cleanup failures and StopIteration.
Run with the same private input plugin above; no default collection or PR gate
is added. [A89 evidence](../architecture/harness/key-designs/windows-stage-capture-custody-convergence.md#a89完整reserved捕获复用与共同寿命)
records the rejected generator candidate and preserved oracle setup failures.

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

The native-release reader probe replays 105 immutable original observations over
real files, descriptors, canonical catalogs, installed RECORD and Product receipt.
Source bytes/version are fixed inputs; Product admission and approval are controlled.
It covers generated/installed mode asymmetry, eight stat fields, overflow, nested
close failures and public approval/generation projection. It never executes ELF
bytes. Original directory-fstat leakage remains recorded; its independent fix has
one explicit expected cleanup delta. Seven additional local faults check each
directory level, compound close failures and interrupt/cancellation propagation.

Explicit local path: [probe_native_release_readers_compatibility.py](../../../tests/coding/probe_native_release_readers_compatibility.py).

The Continuity payload custody probe compares43 immutable original observations
over real private files/descriptors, identity-checked deletion and barrier-controlled
cancellation. Its fixture has baseline source provenance and no capture path.
The original consumer assertions remain intact; fault hooks follow the shared owner.

Explicit local path: [probe_continuity_payload_custody.py](../../../tests/coding/probe_continuity_payload_custody.py).

For strict path-input tests on this machine, workspace mode0775 is correctly
refused as a writable ancestor. The probe supplies per-test private `/tmp` input
directories; pytest's managed lease/runtime stay unchanged. To apply the same
local input fixture to original Bridge consumers, explicitly add
`-p tests.coding.probe_continuity_payload_custody`, with the worktree root appended
to its `src` PYTHONPATH. Keep the managed wrapper, mandated runtime environment
and original non-live/host-runtime selectors. This plugin is local opt-in and
does not alter default test discovery or Product path-admission rules.

The native-approval probe compares101 immutable original observations: public
dataclass fields/signatures/pickle and wire, history decoding, real Rooted IO,
and both complete platform decision programs. Product authority and Windows
native custody are controlled. It has no capture path; the original asymmetric
version/revoke/byte/error contracts are explicit rather than strengthened.

Explicit local path: [probe_native_approval_compatibility.py](../../../tests/coding/probe_native_approval_compatibility.py).

The existing private-journal parent-scope probe now obtains pure bindings from
the actual journal classes and supplies the migrated instance v2 port. Original
fixture bytes, cases and assertions remain. Three older fake-owner mismatches
were reproduced at89992a383 before this fixture maintenance; no Product fix or
default gate coverage is claimed for that repair.


The Linux Product native release custody probe compares123 immutable original
observations over real inert Wheels, installed RECORD/source/receipt bytes and
file descriptors. Product fencing and ApprovalJournal.current are controlled;
the A67 verifier, actual public DTOs, staging, noreplace and filesystem IO are real.
It covers review/install differences, short/failed/cancelled writes, fsync/close,
stage/root replacement, approval changes, repair debt and six same-disk retries.
Initial random relative stage-name traces remain in external evidence; stable
expectations were recaptured under unchanged original-source guards before any
production replacement. There is no capture path in the durable probe, no ELF
execution and no expansion of default discovery or PR gates.

Explicit local path: [probe_linux_product_native_release_compatibility.py](../../../tests/coding/probe_linux_product_native_release_compatibility.py).


The Windows Installation root-lineage probe compares86 immutable original
observations: full values/error graphs/tree plus exact ordered trace count/SHA.
Raw source-guarded observations and canonical content hashes remain in the
external archive. It runs the real receipt IO and deletion scan/decode/sequence
programs over real disk files; native ACL, directory identity and admitted paths
are emulated. It covers staged debt, predecessor/name fencing, restore publication,
write-or-match retries and getter/enter/constructor/events/close/exit failures.
No current capture path, native Windows proof or default gate expansion is claimed.

Explicit local path: [probe_windows_installation_root_lineage_compatibility.py](../../../tests/coding/probe_windows_installation_root_lineage_compatibility.py).


The Product selected revision probes compare33 immutable values/byte observations
and48 complete input-construction/failure observations captured from original
sources. They retain complete three-Wheel bytes, actual public DTO identities,
handle/path/currentness behavior, real selected/parser/package DTOs, actual
metadata-reader distribution resolution, ordered cleanup and ZIP failures. Product
Store capture/authority and metadata inputs are controlled. Raised cancellation is
synchronous; native Windows and full Store/Session publication are not established.
Expected values and input Wheel bytes are copied from source-guarded originals,
with no current recapture entry or expansion of default discovery/PR coverage.

Explicit local paths: [probe_product_selected_revision_values.py](../../../tests/coding/probe_product_selected_revision_values.py)
and [probe_product_selected_revision_custody.py](../../../tests/coding/probe_product_selected_revision_custody.py).


The canonical hosted Catalog probes compare31 original value/byte observations
and35 complete custody observations. The latter directly invokes the existing five
consumer modules with their original assertions, rather than copying their files.
Actual Writers/Store probes, real task cancellation, source changes and retry run.
Private per-test inputs and a scoped Home avoid shared directories or live state;
the managed RunLease remains on the configured private disk runtime directory.
Input-derived identities and exact title/filename relations use frozen original
formulas. Complete normalized Header bytes and ordered traces remain checked;
only two observed identical-input concurrent completion traces are allowed.
Original raw evidence, conversion and anti-mask proofs remain outside Product.
The full custody JSON fixture is losslessly gzip-compressed; decompression keeps
the exact original bytes and every ordered event. These are explicit local probes,
with no default discovery or PR gate expansion.

Explicit local paths: [probe_hosted_catalog_values.py](../../../tests/coding/probe_hosted_catalog_values.py)
and [probe_hosted_catalog_custody.py](../../../tests/coding/probe_hosted_catalog_custody.py).
The existing opt-in private input plugin described above can be supplied when
running original consumers alongside these probes on this machine.


The delegated Goal Session probes compare28 immutable original API/value/wire
observations and38 full runtime observations. The report cases call the actual
shared publisher and prohibit the former helper. Real Tasks, cancellation,
MultiAgent control/runtime/RunHandle, history codecs and model allowance execute;
parent/SDK/factory/child-driver, reader, Work lookup and Blob ports are controlled.
Ordered traces, exact error chains, ownership/fence state and cleanup retries are
compared without event sorting or candidate recapture. Real SDK consumers are
verified separately. The runtime JSON fixture is losslessly gzip-compressed and
checks its full original content hash after decompression. Fixture provenance,
raw captures and complete source/origin guards remain in the external evidence
archive. These are explicit local probes and add no default discovery or PR gate.

Explicit local paths: [probe_goal_delegation_values.py](../../../tests/coding/probe_goal_delegation_values.py)
and [probe_goal_delegation_runtime.py](../../../tests/coding/probe_goal_delegation_runtime.py).


A90 adds [probe_owner_receipt_publication_compatibility.py](../../../tests/coding/probe_owner_receipt_publication_compatibility.py):
56 frozen-original capture/prepare/publish/retry/qualified-retirement scenarios,
using actual generation and Resource receipt methods with controlled lease,
Graph and admission ports. Ordered trace, exception identity, mapping key order
and all direct original predicates remain compared. The gzip fixture is a
lossless copy of original values; no identity/input projection is applied.
This explicit local probe adds no default discovery or PR gate. SDK storage
smoke on this machine uses the existing private input plugin above; see
[A90 validation and limits](../architecture/harness/key-designs/startup-session-assembly-convergence.md#21-a90原publication直接捕获完整receipt).

A91 adds [probe_windows_partial_stage_capture_compatibility.py](../../../tests/coding/probe_windows_partial_stage_capture_compatibility.py)
(118 original partial observations) and [probe_windows_stage_cleanup_compatibility.py](../../../tests/coding/probe_windows_stage_cleanup_compatibility.py)
(90 original full/reserved cleanup observations from the correct pre-A89 lexical source).
Run both explicit paths through `scripts/dev/run_pytest.py`, keeping the same non-live and
host-runtime selectors, private input plugin and workspace execution/storage rules above.
The combined repository run passed all 208 cases. These probes retain public wire/type
checks, ordered traces, cause/context graphs and first-close-error FD debt; their gzip
fixtures derive from frozen original raw observations, never candidate output. They reuse
existing A88/A89 drivers and do not expand default discovery, PR routes or gates.
[A91 validation and limits](../architecture/harness/key-designs/windows-stage-capture-custody-convergence.md#a91完整partial-capture与原生关闭区域).

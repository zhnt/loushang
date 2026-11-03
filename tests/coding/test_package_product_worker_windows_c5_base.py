"""Windows C5 cutover keeps the last state and compacted attempt tombstones."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.coding.package_product_worker_activation_history import (
    project_coding_worker_retained_attempts,
)
from loushang.coding.package_product_worker_windows_activation_state_journal import (
    _head_bytes,
)
from loushang.coding.package_product_worker_windows_c5_base import (
    CodingWindowsWorkerC5SemanticBaseV1,
)
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceFileV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
)
from loushang.harness.worker.activation_state_journal import (
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.product_activation import (
    WorkerCleanupSettlementV1,
    _AttemptKey,
    _initial_state,
)
from tests.coding.test_package_product_worker_activation_segments import (
    _next_state,
    _registered_attempt,
)

_RECEIPT = "a" * 64
_ATTEMPT = "b" * 32
_KEY = _AttemptKey(_RECEIPT, _ATTEMPT, 1).encoded


def _history() -> tuple[_StateRecord, ...]:
    initial = _initial_state(restart_budget=3)
    registered = _next_state(initial)
    registered["attempts"] = {
        _KEY: _registered_attempt(receipt=_RECEIPT, attempt_id=_ATTEMPT)
    }
    settled = _next_state(registered)
    attempt = dict(registered["attempts"][_KEY])
    attempt.update(
        phase="settled",
        domainRetired=True,
        protocolTerminal=True,
        cleanupSettlement=WorkerCleanupSettlementV1(
            receipt_fingerprint=_RECEIPT,
            attempt_id=_ATTEMPT,
            owner_generation=1,
            host_identity="host-a",
            boot_identity="boot-a",
            protocol_terminal=True,
            domain_retired=True,
            tree_settled=True,
        ).to_dict(),
    )
    settled["attempts"] = {_KEY: attempt}
    compacted = _next_state(settled)
    compacted["attempts"] = {}
    return tuple(
        _StateRecord.create(state)
        for state in (initial, registered, settled, compacted)
    )


def _semantic_read() -> CodingWindowsWorkerHistorySemanticReadV1:
    records = _history()
    lines = tuple(_canonical_json_bytes(item.to_dict()) + b"\n" for item in records)
    files = tuple(
        (
            f"worker-activation-state.h{revision:08d}.json",
            _head_bytes(revision, b"".join(lines[:revision])),
        )
        for revision in range(1, len(records) + 1)
    ) + (("worker-activation-state.jsonl", b"".join(lines)),)
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a",
        store_id="store-a",
        lease_owner_revision=3,
        files=tuple(
            CodingWindowsWorkerHistorySourceFileV1(
                name=name, size=len(raw), sha256_digest=sha256(raw).hexdigest()
            )
            for name, raw in files
        ),
    )
    recovery = CodingWindowsWorkerOfflineRecoverySnapshotV1(
        store_id="store-a",
        lease_owner_revision=3,
        attempts=(),
        opt_in_decisions=(),
        receipt_records=(),
        supervisor_records=(),
        activation_state_owner_present=True,
        activation_state_revision=4,
        retained_activation_attempts=project_coding_worker_retained_attempts(records),
        native_job_absence=(),
        gc_reservation_revision=0,
        gc_revision_refs=frozenset(),
        worker_backup_observations=(),
        activation_state_records=records,
    )
    return CodingWindowsWorkerHistorySemanticReadV1(
        source_snapshot=source, offline_recovery=recovery
    )


def test_windows_c5_base_preserves_compacted_attempt_tombstone() -> None:
    semantic = _semantic_read()
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    base = CodingWindowsWorkerC5SemanticBaseV1.from_semantic_read(prepared, semantic)
    assert base.cutoff_revision == 4
    assert base.last_record == semantic.offline_recovery.activation_state_records[-1]
    assert base.retired_attempt_ids == (_ATTEMPT,)
    assert CodingWindowsWorkerC5SemanticBaseV1.from_bytes(base.to_bytes()) == base
    assert base.replay(()).last_record == base.last_record
    reused = _next_state(dict(base.last_record.document))
    reused["attempts"] = {
        _KEY: _registered_attempt(receipt=_RECEIPT, attempt_id=_ATTEMPT)
    }
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((_StateRecord.create(reused),))


def test_windows_c5_base_knows_settled_attempt_still_in_final_state() -> None:
    records = _history()[:-1]
    lines = tuple(_canonical_json_bytes(item.to_dict()) + b"\n" for item in records)
    files = tuple(
        (
            f"worker-activation-state.h{revision:08d}.json",
            _head_bytes(revision, b"".join(lines[:revision])),
        )
        for revision in range(1, len(records) + 1)
    ) + (("worker-activation-state.jsonl", b"".join(lines)),)
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a",
        store_id="store-a",
        lease_owner_revision=3,
        files=tuple(
            CodingWindowsWorkerHistorySourceFileV1(
                name=name, size=len(raw), sha256_digest=sha256(raw).hexdigest()
            )
            for name, raw in files
        ),
    )
    original = _semantic_read()
    semantic = replace(
        original,
        source_snapshot=source,
        offline_recovery=replace(
            original.offline_recovery,
            activation_state_revision=len(records),
            activation_state_records=records,
            retained_activation_attempts=project_coding_worker_retained_attempts(
                records
            ),
        ),
    )
    base = CodingWindowsWorkerC5SemanticBaseV1.from_semantic_read(
        CodingWindowsWorkerHistoryPreparationV1.create(semantic), semantic
    )
    assert base.retired_attempt_ids == ()
    assert base.known_attempt_ids == frozenset({_ATTEMPT})


def test_windows_c5_base_refuses_missing_journal_source() -> None:
    semantic = _semantic_read()
    changed = replace(
        semantic,
        source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.create(
            scope_id="scope-a",
            store_id="store-a",
            lease_owner_revision=3,
            files=semantic.source_snapshot.files[:-1],
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(changed)
    with pytest.raises(ValueError, match="source is absent"):
        CodingWindowsWorkerC5SemanticBaseV1.from_semantic_read(prepared, changed)


@pytest.mark.parametrize("file_index", [0, -1])
def test_windows_c5_base_refuses_changed_source_bytes(file_index: int) -> None:
    semantic = _semantic_read()
    source_files = semantic.source_snapshot.files
    changed_file = replace(
        source_files[file_index], sha256_digest=sha256(b"other bytes").hexdigest()
    )
    changed_files = list(source_files)
    changed_files[file_index] = changed_file
    changed = replace(
        semantic,
        source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.create(
            scope_id="scope-a",
            store_id="store-a",
            lease_owner_revision=3,
            files=tuple(changed_files),
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(changed)
    with pytest.raises(ValueError, match="source changed"):
        CodingWindowsWorkerC5SemanticBaseV1.from_semantic_read(prepared, changed)


def test_windows_c5_base_supports_absent_owner_before_first_revision() -> None:
    semantic = _semantic_read()
    empty = replace(
        semantic,
        source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.create(
            scope_id="scope-a",
            store_id="store-a",
            lease_owner_revision=3,
            files=(),
        ),
        offline_recovery=replace(
            semantic.offline_recovery,
            activation_state_owner_present=False,
            activation_state_revision=0,
            activation_state_records=(),
            retained_activation_attempts=(),
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(empty)
    base = CodingWindowsWorkerC5SemanticBaseV1.from_semantic_read(prepared, empty)
    assert base.last_record is None
    assert base.cutoff_revision == 0
    assert base.retired_attempt_ids == ()
    assert CodingWindowsWorkerC5SemanticBaseV1.from_bytes(base.to_bytes()) == base
    first = _StateRecord.create(_initial_state(restart_budget=3))
    assert base.replay((first,)).last_record == first

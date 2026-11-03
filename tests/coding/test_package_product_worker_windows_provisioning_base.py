"""Native provisioning cutover binds complete old bytes and retired IDs."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceFileV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from loushang.coding.package_product_worker_windows_provisioning_base import (
    CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
)
from loushang.coding.package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
    WindowsWorkerProvisioningStateJournal,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
    CodingWindowsWorkerRecoveryAttemptV1,
)
from loushang.harness.worker._native_profile_bridge import (
    _bind_windows_lpac_contained_product_worker_profile,
    _document_fingerprint,
    _windows_lpac_provisioning_identity,
)
from tests.harness.worker.test_native_profile_bridge import _windows_profile_context


def _semantic_read(tmp_path: Path) -> CodingWindowsWorkerHistorySemanticReadV1:
    _, receipt, request, plan, _, _, bindings, probe = _windows_profile_context(
        tmp_path
    )
    attempt_id = request.identity.attempt_id
    name = f"worker-native-provisioning-{attempt_id}.jsonl"
    path = tmp_path / name
    identity = _windows_lpac_provisioning_identity(
        receipt=receipt, worker_request=request, plan=plan
    )
    journal = WindowsWorkerProvisioningStateJournal(path, identity=identity)
    profile = _bind_windows_lpac_contained_product_worker_profile(
        receipt=receipt,
        worker_request=request,
        plan=plan,
        platform_imports=("KERNEL32.DLL",),
        provisioning_state_store=journal,
        _platform_probe=probe,
        _runtime_bindings=bindings,
    )
    asyncio.run(profile.close())
    raw = path.read_bytes()
    records, _ = journal._decode_raw(raw)
    current = records[-1].document
    phases = tuple(record.document["phase"] for record in records)
    witnesses = tuple(record.document["witness"] is not None for record in records)
    witness = current["witness"]
    witness_state = None if witness is None else witness["state"]
    fingerprint = _document_fingerprint(
        "loushang.worker.windows-lpac-settlement/v1", current
    )
    native = WindowsWorkerProvisioningAttemptV1(
        attempt_id=attempt_id,
        phase="settled",
        state_revision=len(records),
        identity=identity,
        phase_history=phases,
        witness_present_history=witnesses,
        last_witness_state=witness_state,
        settlement_fingerprint=fingerprint,
        records=records,
    )
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a",
        store_id="store-a",
        lease_owner_revision=1,
        files=tuple(
            CodingWindowsWorkerHistorySourceFileV1(
                name=file_name,
                size=len(file_raw),
                sha256_digest=sha256(file_raw).hexdigest(),
            )
            for file_name, file_raw in ((name, raw), (name + ".lock", b"\1"))
        ),
    )
    observed = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=attempt_id,
        payload_directory_identity=None,
        native_phase="settled",
        native_revision=len(records),
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
        native_phase_history=phases,
        native_witness_present_history=witnesses,
        native_witness_state=witness_state,
        native_worker_request_fingerprint=identity["workerRequestFingerprint"],
        native_receipt_fingerprint=identity["receiptFingerprint"],
        native_job_name=identity["jobObjectName"],
    )
    recovery = CodingWindowsWorkerOfflineRecoverySnapshotV1(
        store_id="store-a",
        lease_owner_revision=1,
        attempts=(observed,),
        opt_in_decisions=(),
        receipt_records=(),
        supervisor_records=(),
        activation_state_owner_present=False,
        activation_state_revision=0,
        retained_activation_attempts=(),
        native_job_absence=(),
        gc_reservation_revision=0,
        gc_revision_refs=frozenset(),
        worker_backup_observations=(),
        native_provisioning_attempts=(native,),
    )
    return CodingWindowsWorkerHistorySemanticReadV1(
        source_snapshot=source, offline_recovery=recovery
    )


def test_native_provisioning_base_binds_old_bytes_and_attempt_ids(
    tmp_path: Path,
) -> None:
    semantic = _semantic_read(tmp_path)
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    base = CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_semantic_read(
        prepared, semantic
    )
    native = semantic.offline_recovery.native_provisioning_attempts[0]
    assert base.attempt_ids == (native.attempt_id,)
    assert base.retained_attempts[0].last_record == native.records[-1]
    assert base.retained_attempts[0].cutoff_revision == len(native.records)
    assert (
        CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_bytes(base.to_bytes())
        == base
    )


def test_native_provisioning_base_refuses_changed_source_and_recovery_join(
    tmp_path: Path,
) -> None:
    semantic = _semantic_read(tmp_path)
    source_file = semantic.source_snapshot.files[0]
    changed_source = replace(
        semantic,
        source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.create(
            scope_id="scope-a",
            store_id="store-a",
            lease_owner_revision=1,
            files=(
                replace(source_file, sha256_digest=sha256(b"changed").hexdigest()),
                semantic.source_snapshot.files[1],
            ),
        ),
    )
    with pytest.raises(ValueError, match="source changed"):
        CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_semantic_read(
            CodingWindowsWorkerHistoryPreparationV1.create(changed_source),
            changed_source,
        )
    missing_join = replace(
        semantic,
        offline_recovery=replace(semantic.offline_recovery, attempts=()),
    )
    with pytest.raises(ValueError, match="recovery join is invalid"):
        CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_semantic_read(
            CodingWindowsWorkerHistoryPreparationV1.create(missing_join),
            missing_join,
        )
    missing_lock = replace(
        semantic,
        source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.create(
            scope_id="scope-a",
            store_id="store-a",
            lease_owner_revision=1,
            files=(semantic.source_snapshot.files[0],),
        ),
    )
    with pytest.raises(ValueError, match="source is absent"):
        CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_semantic_read(
            CodingWindowsWorkerHistoryPreparationV1.create(missing_lock),
            missing_lock,
        )

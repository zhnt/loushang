"""Canonical checkpoint bytes bind guarded Windows Worker reference inputs."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeApprovalDecisionV1,
    CodingWorkerNativeReleaseApprovalV1,
)
from loushang.coding.package_product_worker_windows_checkpoint import (
    CodingWindowsWorkerHistoryCheckpointV1,
)
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySourceFileV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from loushang.coding.package_product_worker_windows_package_references import (
    CodingWindowsWorkerPackageReferenceReviewV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from tests.coding.test_package_product_worker_windows_package_references import (
    _inputs,
)


def _checkpoint(tmp_path: Path) -> CodingWindowsWorkerHistoryCheckpointV1:
    prepared, semantic, quiescence, topology = _inputs(tmp_path)
    review = CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
        prepared, semantic, quiescence=quiescence, backup_topology=topology
    )
    return CodingWindowsWorkerHistoryCheckpointV1.from_guarded_read(
        prepared, semantic, review, ()
    )


def test_windows_checkpoint_roundtrip_keeps_all_six_bases_and_references(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint(tmp_path)
    assert (
        CodingWindowsWorkerHistoryCheckpointV1.from_bytes(checkpoint.to_bytes())
        == checkpoint
    )
    assert tuple(name for name, _ in checkpoint.base_digests) == (
        "optIn",
        "receipt",
        "supervisor",
        "c5",
        "launchIntent",
        "nativeProvisioning",
    )
    assert checkpoint.receipt_fingerprints
    assert checkpoint.opt_in_operation_ids
    assert checkpoint.source_snapshot.files


def test_windows_checkpoint_refuses_changed_reference_digest(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    with pytest.raises(ValueError, match="checkpoint is invalid"):
        replace(checkpoint, package_reference_digest="0" * 64)


def test_windows_checkpoint_refuses_noncanonical_or_unknown_bytes(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint(tmp_path)
    document = checkpoint.to_dict()
    document["unknown"] = 1
    with pytest.raises(ValueError, match="checkpoint is invalid"):
        CodingWindowsWorkerHistoryCheckpointV1.from_bytes(
            canonical_json_bytes(document)
        )
    with pytest.raises(ValueError, match="checkpoint is invalid"):
        CodingWindowsWorkerHistoryCheckpointV1.from_bytes(
            json.dumps(checkpoint.to_dict()).encode()
        )


def test_windows_checkpoint_retains_native_approval_before_revoke(
    tmp_path: Path,
) -> None:
    _, semantic, quiescence, topology = _inputs(tmp_path)
    approval = CodingWorkerNativeReleaseApprovalV1(
        wheel_sha256="a" * 64,
        catalog_sha256="b" * 64,
        launcher_sha256="c" * 64,
        profile_sha256="d" * 64,
    )
    approved = CodingWorkerNativeApprovalDecisionV1.create(
        journal_revision=1,
        scope_id=semantic.source_snapshot.scope_id,
        operation_id="operator:approve",
        generation=1,
        action="approve",
        approval=approval,
    )
    revoked = CodingWorkerNativeApprovalDecisionV1.create(
        journal_revision=2,
        scope_id=semantic.source_snapshot.scope_id,
        operation_id="operator:revoke",
        generation=2,
        action="revoke",
        approval=None,
    )
    events = (approved, revoked)
    raw = b"".join(canonical_json_bytes(item.to_dict()) + b"\n" for item in events)
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id=semantic.source_snapshot.scope_id,
        store_id=semantic.source_snapshot.store_id,
        lease_owner_revision=semantic.source_snapshot.lease_owner_revision,
        files=tuple(
            sorted(
                (
                    *semantic.source_snapshot.files,
                    CodingWindowsWorkerHistorySourceFileV1(
                        name="worker-native-release-approvals.jsonl",
                        size=len(raw),
                        sha256_digest=sha256(raw).hexdigest(),
                    ),
                ),
                key=lambda item: item.name,
            )
        ),
    )
    semantic = replace(semantic, source_snapshot=source)
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    review = CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
        prepared, semantic, quiescence=quiescence, backup_topology=topology
    )
    checkpoint = CodingWindowsWorkerHistoryCheckpointV1.from_guarded_read(
        prepared, semantic, review, events
    )
    assert checkpoint.native_approval_record_digests == (
        approved.record_digest,
        revoked.record_digest,
    )
    assert checkpoint.native_approval_generation == 2
    assert (
        CodingWindowsWorkerHistoryCheckpointV1.from_bytes(checkpoint.to_bytes())
        == checkpoint
    )
    with pytest.raises(ValueError, match="checkpoint references changed"):
        CodingWindowsWorkerHistoryCheckpointV1.from_guarded_read(
            prepared, semantic, review, (revoked,)
        )

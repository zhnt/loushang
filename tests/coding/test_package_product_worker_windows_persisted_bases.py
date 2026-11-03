"""Persisted Windows bases must retain one checkpoint and cross-ledger ID set."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_windows_checkpoint import (
    CodingWindowsWorkerHistoryCheckpointV1,
)
from loushang.coding.package_product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_opt_in_base import (
    CodingWindowsWorkerOptInSemanticBaseV1,
)
from loushang.coding.package_product_worker_windows_package_references import (
    CodingWindowsWorkerPackageReferenceReviewV1,
)
from loushang.coding.package_product_worker_windows_persisted_bases import (
    CodingWindowsWorkerPersistedBasesV1,
)
from tests.coding.test_package_product_worker_windows_history_join import _empty_read
from tests.coding.test_package_product_worker_windows_package_references import _inputs


def _persisted(tmp_path: Path) -> CodingWindowsWorkerPersistedBasesV1:
    prepared, semantic, quiescence, topology = _inputs(tmp_path)
    review = CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
        prepared, semantic, quiescence=quiescence, backup_topology=topology
    )
    checkpoint = CodingWindowsWorkerHistoryCheckpointV1.from_guarded_read(
        prepared, semantic, review, ()
    )
    joined = CodingWindowsWorkerHistorySemanticJoinV1.from_semantic_read(
        prepared, semantic
    )
    return CodingWindowsWorkerPersistedBasesV1(
        checkpoint=checkpoint,
        opt_in=joined.opt_in,
        receipt=joined.receipt,
        supervisor=joined.supervisor,
        c5=joined.c5,
        launch_intent=joined.launch_intent,
        native_provisioning=joined.native_provisioning,
    )


def test_windows_persisted_bases_join_checkpoint_and_high_water_marks(
    tmp_path: Path,
) -> None:
    persisted = _persisted(tmp_path)
    assert persisted.checkpoint.base_digests == (
        ("optIn", persisted.opt_in.record_digest),
        ("receipt", persisted.receipt.record_digest),
        ("supervisor", persisted.supervisor.record_digest),
        ("c5", persisted.c5.record_digest),
        ("launchIntent", persisted.launch_intent.record_digest),
        ("nativeProvisioning", persisted.native_provisioning.record_digest),
    )
    assert persisted.checkpoint.opt_in_operation_ids == (
        persisted.opt_in.retired_operation_ids
    )
    assert persisted.checkpoint.receipt_fingerprints == (
        persisted.receipt.retired_receipt_fingerprints
    )


def test_windows_persisted_bases_refuse_valid_base_from_other_snapshot(
    tmp_path: Path,
) -> None:
    persisted = _persisted(tmp_path)
    other = _empty_read()
    other_opt_in = CodingWindowsWorkerOptInSemanticBaseV1.from_semantic_read(
        CodingWindowsWorkerHistoryPreparationV1.create(other), other
    )
    assert other_opt_in.source_snapshot_digest != (
        persisted.checkpoint.source_snapshot.snapshot_digest
    )
    with pytest.raises(ValueError, match="persisted bases are invalid"):
        replace(persisted, opt_in=other_opt_in)

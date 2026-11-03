"""A receipt writer must retain the checkpoint's exact source prefix."""

from __future__ import annotations

import pytest

from loushang.coding.package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
)
from loushang.coding.package_product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    CodingWorkerReceiptError,
)


def test_receipt_checkpoint_source_requires_exact_old_bytes() -> None:
    original = b'{"journalRevision":1}\n'
    appended = b'{"journalRevision":2}\n'
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=0,
            last_sealed_revision=0,
            segments=(original if stem == "worker-activation-receipts" else b"",),
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="scope",
        store_id="store",
        attempt_id="a" * 32,
        receipt_fingerprint="b" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=("a" * 32,),
        new_receipt_fingerprints=("b" * 64,),
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=(),
    )
    history = CodingWorkerSegmentedHistoryV1(
        manifest=None, segments=(original + appended,)
    )
    assert (
        CodingWorkerProductReceiptOwner._assert_checkpoint_source(
            (checkpoint,), history
        )
        == 1
    )

    rewritten = CodingWorkerSegmentedHistoryV1(
        manifest=None,
        segments=(b'{"journalRevision":9}\n' + appended,),
    )
    with pytest.raises(CodingWorkerReceiptError) as changed:
        CodingWorkerProductReceiptOwner._assert_checkpoint_source(
            (checkpoint,), rewritten
        )
    assert changed.value.code == "coding_worker_receipt_checkpoint_source_changed"

    with pytest.raises(CodingWorkerReceiptError) as retired:
        CodingWorkerProductReceiptOwner._assert_checkpoint_fingerprint_fresh(
            (checkpoint,), "b" * 64
        )
    assert retired.value.code == "coding_worker_receipt_fingerprint_retired"

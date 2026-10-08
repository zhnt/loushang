"""A V2 receipt base preserves the global issue sequence and tombstones."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.coding.package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from loushang.coding.package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
)
from loushang.coding.package_product_worker_history_cutover_v2 import (
    CodingWorkerStreamCutoverV2,
)
from loushang.coding.package_product_worker_history_retirement_preview import (
    preview_first_coding_worker_stream_retirement_v2,
)
from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerSealedSegmentV1,
    CodingWorkerSegmentedHistoryV1,
    CodingWorkerSegmentManifestV1,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
)
from loushang.coding.package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
    _linux_receipt_line,
)
from loushang.coding.package_product_worker_receipt_base_v2 import (
    CodingWorkerReceiptSemanticBaseV2,
)
from tests.harness.worker.test_product_activation import _receipt


def _record(sequence: int) -> CodingWorkerReceiptRecordV1:
    receipt = replace(
        _receipt(), issue_sequence=sequence, issue_nonce=f"receipt-nonce-{sequence}"
    )
    return CodingWorkerReceiptRecordV1.create(
        journal_revision=sequence,
        scope_id=receipt.policy.product_scope_id,
        opt_in_decision_digest="a" * 64,
        receipt=receipt,
    )


def _history() -> tuple[
    CodingWorkerSegmentedHistoryV1, tuple[CodingWorkerReceiptRecordV1, ...]
]:
    records = (_record(1), _record(2), _record(3))
    old = b"".join(_linux_receipt_line(item) for item in records[:2])
    active = _linux_receipt_line(records[2])
    seal = CodingWorkerSealedSegmentV1(
        generation=0,
        first_revision=1,
        last_revision=2,
        byte_count=len(old),
        digest=sha256(old).hexdigest(),
    )
    return (
        CodingWorkerSegmentedHistoryV1(
            manifest=CodingWorkerSegmentManifestV1(
                stream_id="worker-activation-receipts",
                active_generation=1,
                sealed=(seal,),
            ),
            segments=(old, active),
        ),
        records,
    )


def test_receipt_base_replays_sequence_and_binds_exact_cutover() -> None:
    history, records = _history()
    base = CodingWorkerReceiptSemanticBaseV2.from_v1_history(
        history=history, scope_id="scope-1", first_retained_generation=1
    )
    assert base.last_issue_sequence == 2
    assert base.retired_receipt_fingerprints == tuple(
        sorted((records[0].receipt.fingerprint, records[1].receipt.fingerprint))
    )
    assert CodingWorkerReceiptSemanticBaseV2.from_bytes(base.to_bytes()) == base
    replay = base.replay_retained((history.active_raw,))
    assert replay.last_issue_sequence == 3
    assert replay.retained_records == (records[2],)
    assert replay.receipt_fingerprints == frozenset(
        item.receipt.fingerprint for item in records
    )

    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=1,
            last_sealed_revision=2,
            segments=history.segments,
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="scope-1",
        store_id="store",
        attempt_id="a" * 32,
        receipt_fingerprint="b" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=("a" * 32,),
        new_receipt_fingerprints=base.retired_receipt_fingerprints,
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=(),
    )
    anchor = CodingWorkerCheckpointAnchorV1.create(
        scope_id="scope-1",
        store_id="store",
        latest_revision=1,
        latest_digest=checkpoint.record_digest,
    )
    preview = preview_first_coding_worker_stream_retirement_v2(
        checkpoint=checkpoint,
        anchor=anchor,
        history=history,
        stem="worker-activation-receipts",
        first_retained_generation=1,
    )
    stream = CodingWorkerStreamCutoverV2.from_receipt_base(
        checkpoint=checkpoint, preview=preview, history=history, semantic_base=base
    )
    assert stream.semantic_base_digest == sha256(base.to_bytes()).hexdigest()

    forged = replace(
        base,
        retired_receipt_fingerprints=tuple(
            sorted((records[1].receipt.fingerprint, records[2].receipt.fingerprint))
        ),
    )
    with pytest.raises(ValueError, match="semantic base differs"):
        CodingWorkerStreamCutoverV2.from_receipt_base(
            checkpoint=checkpoint,
            preview=preview,
            history=history,
            semantic_base=forged,
        )
    with pytest.raises(ValueError, match="fingerprint repeated"):
        forged.replay_retained((history.active_raw,))


def test_receipt_base_rejects_source_change_sequence_gap_and_noncanonical_bytes() -> (
    None
):
    history, _records = _history()
    base = CodingWorkerReceiptSemanticBaseV2.from_v1_history(
        history=history, scope_id="scope-1", first_retained_generation=1
    )
    changed = CodingWorkerSegmentedHistoryV1(
        manifest=history.manifest,
        segments=(history.segments[0] + b" ", history.active_raw),
    )
    with pytest.raises(ValueError, match="source changed"):
        CodingWorkerReceiptSemanticBaseV2.from_v1_history(
            history=changed, scope_id="scope-1", first_retained_generation=1
        )
    with pytest.raises(ValueError, match="segment is invalid"):
        base.replay_retained((_linux_receipt_line(_record(4)),))
    with pytest.raises(ValueError, match="bytes are invalid"):
        CodingWorkerReceiptSemanticBaseV2.from_bytes(base.to_bytes() + b" ")

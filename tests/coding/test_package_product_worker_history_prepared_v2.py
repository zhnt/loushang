"""The five typed Worker sources form one prepared Product index."""

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
from loushang.coding.package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from loushang.coding.package_product_worker_history_retirement_preview import (
    CodingWorkerRetirementPreviewError,
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
from tests.coding.test_package_product_worker_activation_base_v2 import (
    _history as _activation_history,
)
from tests.coding.test_package_product_worker_opt_in_base_v2 import (
    _history as _opt_in_history,
)
from tests.coding.test_package_product_worker_start_gate_base_v2 import (
    _history as _start_gate_history,
)
from tests.coding.test_package_product_worker_supervisor_base_v2 import (
    _history as _supervisor_history,
)
from tests.harness.worker.test_product_activation import _policy, _receipt


def _sources() -> tuple[
    tuple[CodingWorkerHistoryCheckpointV1, ...],
    CodingWorkerCheckpointAnchorV1,
    tuple[CodingWorkerSegmentedHistoryV1, ...],
]:
    receipt = replace(
        _receipt(policy=replace(_policy(), product_scope_id="scope")),
        issue_sequence=1,
        issue_nonce="cutover-receipt",
    )
    receipt_record = CodingWorkerReceiptRecordV1.create(
        journal_revision=1,
        scope_id="scope",
        opt_in_decision_digest="a" * 64,
        receipt=receipt,
    )
    receipt_raw = _linux_receipt_line(receipt_record)
    receipt_history = CodingWorkerSegmentedHistoryV1(
        manifest=CodingWorkerSegmentManifestV1(
            stream_id="worker-activation-receipts",
            active_generation=1,
            sealed=(
                CodingWorkerSealedSegmentV1(
                    generation=0,
                    first_revision=1,
                    last_revision=1,
                    byte_count=len(receipt_raw),
                    digest=sha256(receipt_raw).hexdigest(),
                ),
            ),
        ),
        segments=(receipt_raw, b""),
    )
    histories = (
        _opt_in_history()[0],
        receipt_history,
        _activation_history(2)[0],
        _start_gate_history()[0],
        _supervisor_history()[0],
    )
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=history.active_generation,
            last_sealed_revision=history.last_sealed_revision,
            segments=history.segments,
        )
        for stem, history in zip(
            CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
        )
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="scope",
        store_id="store",
        attempt_id="a" * 32,
        receipt_fingerprint=receipt.fingerprint,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=("allow-a1",),
        new_attempt_ids=("a" * 32,),
        new_receipt_fingerprints=(receipt.fingerprint,),
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=(("c" * 64, 2),),
    )
    anchor = CodingWorkerCheckpointAnchorV1.create(
        scope_id="scope",
        store_id="store",
        latest_revision=1,
        latest_digest=checkpoint.record_digest,
    )
    return (checkpoint,), anchor, histories


def test_prepared_product_cutover_reprojects_every_typed_stream() -> None:
    checkpoints, anchor, histories = _sources()
    prepared = CodingWorkerPreparedProductCutoverV2.from_v1_histories(
        checkpoints=checkpoints,
        anchor=anchor,
        histories=histories,
        first_retained_generations=(1, 1, 1, 1, 1),
    )
    assert tuple(item.stem for item in prepared.streams) == (
        CODING_WORKER_HISTORY_STREAM_STEMS
    )
    assert prepared.index.checkpoint_digest == checkpoints[-1].record_digest
    assert all(
        stream.semantic_base_digest == sha256(base.to_bytes()).hexdigest()
        for stream, base in zip(prepared.streams, prepared.semantic_bases, strict=True)
    )

    with pytest.raises(ValueError, match="typed Product cutover differs"):
        replace(
            prepared,
            semantic_bases=(
                prepared.semantic_bases[1],
                prepared.semantic_bases[0],
                *prepared.semantic_bases[2:],
            ),
        )
    with pytest.raises(ValueError, match="typed Product sources are invalid"):
        CodingWorkerPreparedProductCutoverV2.from_v1_histories(
            checkpoints=checkpoints,
            anchor=anchor,
            histories=histories[:-1],
            first_retained_generations=(1, 1, 1, 1),
        )


def test_prepared_product_cutover_refuses_changed_source_and_anchor() -> None:
    checkpoints, anchor, histories = _sources()
    changed = replace(
        histories[0],
        segments=(histories[0].segments[0], histories[0].active_raw + b" "),
    )
    with pytest.raises(
        CodingWorkerRetirementPreviewError,
        match="coding_worker_retirement_source_unproven",
    ):
        CodingWorkerPreparedProductCutoverV2.from_v1_histories(
            checkpoints=checkpoints,
            anchor=anchor,
            histories=(changed, *histories[1:]),
            first_retained_generations=(1, 1, 1, 1, 1),
        )
    with pytest.raises(ValueError, match="checkpoint chain differs"):
        CodingWorkerPreparedProductCutoverV2.from_v1_histories(
            checkpoints=checkpoints,
            anchor=CodingWorkerCheckpointAnchorV1.create(
                scope_id="scope", store_id="store", latest_revision=0, latest_digest=""
            ),
            histories=histories,
            first_retained_generations=(1, 1, 1, 1, 1),
        )


def test_prepared_product_cutover_refuses_repeated_checkpoint_ids() -> None:
    checkpoints, _anchor, histories = _sources()
    first = checkpoints[0]
    repeated = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=2,
        scope_id=first.scope_id,
        store_id=first.store_id,
        attempt_id=first.attempt_id,
        receipt_fingerprint=first.receipt_fingerprint,
        previous_digest=first.record_digest,
        gc_reservation_revision=first.gc_reservation_revision,
        backup_topology_revision=first.backup_topology_revision,
        stream_snapshots=first.stream_snapshots,
        new_opt_in_operation_ids=first.new_opt_in_operation_ids,
        new_attempt_ids=first.new_attempt_ids,
        new_receipt_fingerprints=first.new_receipt_fingerprints,
        opt_in_generation_high_water=first.opt_in_generation_high_water,
        supervisor_epoch_high_water=first.supervisor_epoch_high_water,
    )
    anchor = CodingWorkerCheckpointAnchorV1.create(
        scope_id="scope",
        store_id="store",
        latest_revision=2,
        latest_digest=repeated.record_digest,
    )
    with pytest.raises(ValueError, match="checkpoint IDs repeat"):
        CodingWorkerPreparedProductCutoverV2.from_v1_histories(
            checkpoints=(first, repeated),
            anchor=anchor,
            histories=histories,
            first_retained_generations=(1, 1, 1, 1, 1),
        )

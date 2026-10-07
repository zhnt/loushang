"""V2 candidates bind all five exact V1 streams before any authority switch."""

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
    CodingWorkerProductCutoverIndexV2,
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


def _prepared_cutover() -> tuple[
    CodingWorkerHistoryCheckpointV1,
    CodingWorkerCheckpointAnchorV1,
    tuple[CodingWorkerStreamCutoverV2, ...],
    CodingWorkerSegmentedHistoryV1,
]:
    old = b'{"journalRevision":1}\n'
    active = b'{"journalRevision":2}\n'
    seal = CodingWorkerSealedSegmentV1(
        generation=0,
        first_revision=1,
        last_revision=1,
        byte_count=len(old),
        digest=sha256(old).hexdigest(),
    )
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=1,
            last_sealed_revision=1,
            segments=(old, active),
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
        new_opt_in_operation_ids=("operation-1",),
        new_attempt_ids=("a" * 32,),
        new_receipt_fingerprints=("b" * 64,),
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=(),
    )
    anchor = CodingWorkerCheckpointAnchorV1.create(
        scope_id="scope",
        store_id="store",
        latest_revision=1,
        latest_digest=checkpoint.record_digest,
    )
    histories = tuple(
        CodingWorkerSegmentedHistoryV1(
            manifest=CodingWorkerSegmentManifestV1(
                stream_id=stem, active_generation=1, sealed=(seal,)
            ),
            segments=(old, active),
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    streams = tuple(
        CodingWorkerStreamCutoverV2.from_preview(
            preview=preview_first_coding_worker_stream_retirement_v2(
                checkpoint=checkpoint,
                anchor=anchor,
                history=history,
                stem=stem,
                first_retained_generation=1,
            ),
            history=history,
            semantic_base_digest=sha256(stem.encode()).hexdigest(),
        )
        for stem, history in zip(
            CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
        )
    )
    return checkpoint, anchor, streams, histories[0]


def test_cutover_candidates_bind_canonical_five_stream_index() -> None:
    checkpoint, anchor, streams, history = _prepared_cutover()
    assert streams[0].first_retained_revision == 2
    assert streams[0].retired_sealed[0].generation == 0
    assert streams[0].retained_sealed == ()
    assert CodingWorkerStreamCutoverV2.from_bytes(streams[0].to_bytes()) == streams[0]
    index = CodingWorkerProductCutoverIndexV2.from_streams(
        checkpoint=checkpoint, anchor=anchor, streams=streams
    )
    assert CodingWorkerProductCutoverIndexV2.from_bytes(index.to_bytes()) == index
    assert tuple(stem for stem, _digest in index.stream_digests) == (
        CODING_WORKER_HISTORY_STREAM_STEMS
    )

    with pytest.raises(ValueError, match="sources differ"):
        CodingWorkerProductCutoverIndexV2.from_streams(
            checkpoint=checkpoint, anchor=anchor, streams=streams[:-1]
        )
    with pytest.raises(ValueError, match="sources differ"):
        CodingWorkerProductCutoverIndexV2.from_streams(
            checkpoint=checkpoint,
            anchor=anchor,
            streams=(replace(streams[0], checkpoint_revision=2), *streams[1:]),
        )
    with pytest.raises(ValueError, match="revision boundary"):
        replace(streams[0], first_retained_revision=3)
    with pytest.raises(ValueError, match="snapshot"):
        replace(streams[0], active_digest="f" * 64)
    with pytest.raises(ValueError, match="bytes are invalid"):
        CodingWorkerStreamCutoverV2.from_bytes(streams[0].to_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes are invalid"):
        CodingWorkerProductCutoverIndexV2.from_bytes(index.to_bytes() + b" ")

    changed = CodingWorkerSegmentedHistoryV1(
        manifest=history.manifest,
        segments=(history.segments[0], history.active_raw.replace(b"2", b"8")),
    )
    preview = preview_first_coding_worker_stream_retirement_v2(
        checkpoint=checkpoint,
        anchor=anchor,
        history=history,
        stem="worker-opt-in",
        first_retained_generation=1,
    )
    with pytest.raises(ValueError, match="source changed"):
        CodingWorkerStreamCutoverV2.from_preview(
            preview=preview,
            history=changed,
            semantic_base_digest="d" * 64,
        )

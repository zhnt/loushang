"""A first retirement preview must bind exact sealed bytes and stay inert."""

from __future__ import annotations

from hashlib import sha256

import pytest

from loushang.coding.package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from loushang.coding.package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
)
from loushang.coding.package_product_worker_history_retirement_preview import (
    CodingWorkerRetirementPreviewError,
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


def test_first_retirement_preview_requires_anchored_exact_sealed_prefix() -> None:
    old = b'{"journalRevision":1}\n'
    active = b'{"journalRevision":2}\n'
    seal = CodingWorkerSealedSegmentV1(
        generation=0,
        first_revision=1,
        last_revision=1,
        byte_count=len(old),
        digest=sha256(old).hexdigest(),
    )
    manifest = CodingWorkerSegmentManifestV1(
        stream_id="worker-opt-in", active_generation=1, sealed=(seal,)
    )
    history = CodingWorkerSegmentedHistoryV1(manifest=manifest, segments=(old, active))
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=1 if stem == "worker-opt-in" else 0,
            last_sealed_revision=1 if stem == "worker-opt-in" else 0,
            segments=(old, active) if stem == "worker-opt-in" else (b"",),
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
    preview = preview_first_coding_worker_stream_retirement_v2(
        checkpoint=checkpoint,
        anchor=anchor,
        history=history,
        stem="worker-opt-in",
        first_retained_generation=1,
    )
    assert preview.first_retained_revision == 2
    assert preview.retired_generations == (0,)
    assert preview.retained_generations == (1,)
    assert preview.deletion_authorized is False

    changed_history = CodingWorkerSegmentedHistoryV1(
        manifest=manifest,
        segments=(old.replace(b"1", b"9"), active),
    )
    with pytest.raises(CodingWorkerRetirementPreviewError) as changed:
        preview_first_coding_worker_stream_retirement_v2(
            checkpoint=checkpoint,
            anchor=anchor,
            history=changed_history,
            stem="worker-opt-in",
            first_retained_generation=1,
        )
    assert changed.value.code == "coding_worker_retirement_source_unproven"

    changed_active = CodingWorkerSegmentedHistoryV1(
        manifest=manifest,
        segments=(old, active.replace(b"2", b"8")),
    )
    with pytest.raises(CodingWorkerRetirementPreviewError) as active_mismatch:
        preview_first_coding_worker_stream_retirement_v2(
            checkpoint=checkpoint,
            anchor=anchor,
            history=changed_active,
            stem="worker-opt-in",
            first_retained_generation=1,
        )
    assert active_mismatch.value.code == "coding_worker_retirement_source_unproven"

    unanchored = CodingWorkerCheckpointAnchorV1.create(
        scope_id="scope", store_id="store", latest_revision=0, latest_digest=""
    )
    with pytest.raises(CodingWorkerRetirementPreviewError) as missing_anchor:
        preview_first_coding_worker_stream_retirement_v2(
            checkpoint=checkpoint,
            anchor=unanchored,
            history=history,
            stem="worker-opt-in",
            first_retained_generation=1,
        )
    assert missing_anchor.value.code == "coding_worker_retirement_checkpoint_unanchored"

    with pytest.raises(CodingWorkerRetirementPreviewError) as unsealed:
        preview_first_coding_worker_stream_retirement_v2(
            checkpoint=checkpoint,
            anchor=anchor,
            history=history,
            stem="worker-opt-in",
            first_retained_generation=2,
        )
    assert unsealed.value.code == "coding_worker_retirement_cutoff_unavailable"

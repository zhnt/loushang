"""A typed opt-in base replays the same decisions after sealed V1 retirement."""

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
from loushang.coding.package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    _fold_opt_in_events,
    _opt_in_line,
)
from loushang.coding.package_product_worker_opt_in_base_v2 import (
    CodingWorkerOptInSemanticBaseV2,
)
from loushang.coding.package_product_worker_policy import CodingWorkerOptInV1


def _allow(
    *, plugin_id: str, revision: int, generation: int, kill: int, operation: str
) -> CodingWorkerOptInDecisionV1:
    return CodingWorkerOptInDecisionV1.create(
        journal_revision=revision,
        scope_id="scope",
        plugin_id=plugin_id,
        operation_id=operation,
        generation=generation,
        kill_switch_generation=kill,
        action="allow",
        opt_in=CodingWorkerOptInV1(
            plugin_id=plugin_id,
            contribution_id="query-provider",
            owner_id="coding",
            artifact_digest="d" * 64,
            native_platform="linux-x86_64",
            owner_selection_generation=generation,
            kill_switch_generation=kill,
            require_worker=True,
        ),
    )


def _history() -> tuple[
    CodingWorkerSegmentedHistoryV1, tuple[CodingWorkerOptInDecisionV1, ...]
]:
    events = (
        _allow(
            plugin_id="plugin-a", revision=1, generation=1, kill=0, operation="allow-a1"
        ),
        CodingWorkerOptInDecisionV1.create(
            journal_revision=2,
            scope_id="scope",
            plugin_id="plugin-a",
            operation_id="revoke-a2",
            generation=2,
            kill_switch_generation=1,
            action="revoke",
            opt_in=None,
        ),
        _allow(
            plugin_id="plugin-a", revision=3, generation=3, kill=1, operation="allow-a3"
        ),
        _allow(
            plugin_id="plugin-b", revision=4, generation=1, kill=0, operation="allow-b1"
        ),
    )
    old = b"".join(_opt_in_line(event) for event in events[:2])
    active = b"".join(_opt_in_line(event) for event in events[2:])
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
                stream_id="worker-opt-in", active_generation=1, sealed=(seal,)
            ),
            segments=(old, active),
        ),
        events,
    )


def test_opt_in_base_replays_retained_events_and_binds_cutover() -> None:
    history, events = _history()
    base = CodingWorkerOptInSemanticBaseV2.from_v1_history(
        history=history, scope_id="scope", first_retained_generation=1
    )
    assert base.cutoff_revision == 2
    assert base.retired_operation_ids == ("allow-a1", "revoke-a2")
    assert base.latest_decisions == (events[1],)
    assert CodingWorkerOptInSemanticBaseV2.from_bytes(base.to_bytes()) == base

    full_latest, full_operations = _fold_opt_in_events(events, scope_id="scope")
    replay = base.replay_retained((history.active_raw,))
    assert replay.last_revision == len(events)
    assert replay.latest_decisions == tuple(
        full_latest[key] for key in sorted(full_latest)
    )
    assert replay.operation_ids == full_operations
    assert replay.latest_decisions[0].opt_in == events[2].opt_in

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
        scope_id="scope",
        store_id="store",
        attempt_id="a" * 32,
        receipt_fingerprint="b" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=base.retired_operation_ids,
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
    stream = CodingWorkerStreamCutoverV2.from_opt_in_base(
        checkpoint=checkpoint, preview=preview, history=history, semantic_base=base
    )
    assert stream.semantic_base_digest == sha256(base.to_bytes()).hexdigest()
    with pytest.raises(ValueError, match="semantic base differs"):
        CodingWorkerStreamCutoverV2.from_opt_in_base(
            checkpoint=checkpoint,
            preview=preview,
            history=history,
            semantic_base=replace(base, retired_sealed_digest="f" * 64),
        )
    with pytest.raises(ValueError, match="semantic base differs"):
        CodingWorkerStreamCutoverV2.from_opt_in_base(
            checkpoint=checkpoint,
            preview=preview,
            history=history,
            semantic_base=replace(base, latest_decisions=(events[0],)),
        )


def test_opt_in_base_rejects_changed_prefix_and_retained_identity_reuse() -> None:
    history, _events = _history()
    base = CodingWorkerOptInSemanticBaseV2.from_v1_history(
        history=history, scope_id="scope", first_retained_generation=1
    )
    changed = CodingWorkerSegmentedHistoryV1(
        manifest=history.manifest,
        segments=(
            history.segments[0].replace(b"allow-a1", b"allow-x1"),
            history.active_raw,
        ),
    )
    with pytest.raises(ValueError, match="source changed"):
        CodingWorkerOptInSemanticBaseV2.from_v1_history(
            history=changed, scope_id="scope", first_retained_generation=1
        )

    reused = _allow(
        plugin_id="plugin-a",
        revision=3,
        generation=3,
        kill=1,
        operation="revoke-a2",
    )
    with pytest.raises(ValueError, match="retained replay"):
        base.replay_retained((_opt_in_line(reused),))

    stale_generation = _allow(
        plugin_id="plugin-a",
        revision=3,
        generation=2,
        kill=1,
        operation="allow-a3",
    )
    with pytest.raises(ValueError, match="retained replay"):
        base.replay_retained((_opt_in_line(stale_generation),))
    with pytest.raises(ValueError, match="bytes are invalid"):
        CodingWorkerOptInSemanticBaseV2.from_bytes(base.to_bytes() + b" ")

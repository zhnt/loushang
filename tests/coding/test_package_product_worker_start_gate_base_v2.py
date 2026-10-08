"""Start Gate V2 base keeps live intent and checkpoint retired IDs."""

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
from loushang.coding.package_product_worker_start_gate_base_v2 import (
    CodingWorkerStartGateSemanticBaseV2,
)
from loushang.coding.package_product_worker_start_gate_journal import (
    CodingWorkerStartGateRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.gated_start import WorkerNativeProcessIdentityV1


def _record(
    revision: int, *, attempt_id: str, bound: bool, scope_id: str = "scope"
) -> CodingWorkerStartGateRecordV1:
    return CodingWorkerStartGateRecordV1.create(
        journal_revision=revision,
        phase="bound" if bound else "intent",
        attempt_id=attempt_id,
        worker_identity_fingerprint="c" * 64,
        receipt_fingerprint="d" * 64,
        policy_fingerprint="e" * 64,
        scope_id=scope_id,
        native_closure_digest="f" * 64,
        identity=(
            WorkerNativeProcessIdentityV1(
                pid=123,
                start_ticks=456,
                boot_id="00000000-0000-0000-0000-000000000001",
                user_id=1000,
                pid_namespace_device=1,
                pid_namespace_inode=2,
            )
            if bound
            else None
        ),
    )


def _line(record: CodingWorkerStartGateRecordV1) -> bytes:
    return canonical_json_bytes(record.to_dict()) + b"\n"


def _history(
    *, scope_a: str = "scope", scope_b: str = "scope"
) -> tuple[
    CodingWorkerSegmentedHistoryV1, tuple[CodingWorkerStartGateRecordV1, ...]
]:
    records = (
        _record(1, attempt_id="a" * 32, bound=False, scope_id=scope_a),
        _record(2, attempt_id="a" * 32, bound=True, scope_id=scope_a),
        _record(3, attempt_id="b" * 32, bound=False, scope_id=scope_b),
        _record(4, attempt_id="b" * 32, bound=True, scope_id=scope_b),
    )
    old = b"".join(_line(item) for item in records[:3])
    active = _line(records[3])
    seal = CodingWorkerSealedSegmentV1(
        generation=0,
        first_revision=1,
        last_revision=3,
        byte_count=len(old),
        digest=sha256(old).hexdigest(),
    )
    return (
        CodingWorkerSegmentedHistoryV1(
            manifest=CodingWorkerSegmentManifestV1(
                stream_id="worker-start-gates", active_generation=1, sealed=(seal,)
            ),
            segments=(old, active),
        ),
        records,
    )


def test_start_gate_base_replays_live_bound_and_binds_tombstone_chain() -> None:
    history, records = _history()
    base = CodingWorkerStartGateSemanticBaseV2.from_v1_history(
        history=history,
        scope_id="scope",
        first_retained_generation=1,
        retired_attempt_ids=("a" * 32,),
    )
    assert base.cutoff_revision == 3
    assert base.current_records == (records[2],)
    assert base.retired_attempt_ids == ("a" * 32,)
    assert CodingWorkerStartGateSemanticBaseV2.from_bytes(base.to_bytes()) == base
    replay = base.replay_retained((history.active_raw,))
    assert replay.last_revision == 4
    assert replay.current_records == (records[3],)

    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=1,
            last_sealed_revision=3,
            segments=history.segments,
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="scope",
        store_id="store",
        attempt_id="a" * 32,
        receipt_fingerprint="d" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=("a" * 32,),
        new_receipt_fingerprints=("d" * 64,),
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
        stem="worker-start-gates",
        first_retained_generation=1,
    )
    stream = CodingWorkerStreamCutoverV2.from_start_gate_base(
        checkpoints=(checkpoint,), preview=preview, history=history, semantic_base=base
    )
    assert stream.semantic_base_digest == sha256(base.to_bytes()).hexdigest()
    with pytest.raises(ValueError, match="semantic base differs"):
        CodingWorkerStreamCutoverV2.from_start_gate_base(
            checkpoints=(checkpoint,),
            preview=preview,
            history=history,
            semantic_base=replace(base, retired_attempt_ids=()),
        )

    premature = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="scope",
        store_id="store",
        attempt_id="a" * 32,
        receipt_fingerprint="d" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=("a" * 32, "b" * 32),
        new_receipt_fingerprints=("d" * 64,),
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=(),
    )
    premature_preview = preview_first_coding_worker_stream_retirement_v2(
        checkpoint=premature,
        anchor=CodingWorkerCheckpointAnchorV1.create(
            scope_id="scope",
            store_id="store",
            latest_revision=1,
            latest_digest=premature.record_digest,
        ),
        history=history,
        stem="worker-start-gates",
        first_retained_generation=1,
    )
    premature_base = CodingWorkerStartGateSemanticBaseV2.from_v1_history(
        history=history,
        scope_id="scope",
        first_retained_generation=1,
        retired_attempt_ids=("a" * 32, "b" * 32),
    )
    with pytest.raises(ValueError, match="retained replay"):
        CodingWorkerStreamCutoverV2.from_start_gate_base(
            checkpoints=(premature,),
            preview=premature_preview,
            history=history,
            semantic_base=premature_base,
        )


def test_start_gate_base_preserves_distinct_session_scopes_under_product_owner() -> None:
    history, records = _history(scope_a="session-a", scope_b="session-b")
    base = CodingWorkerStartGateSemanticBaseV2.from_v1_history(
        history=history,
        scope_id="product-scope",
        first_retained_generation=1,
        retired_attempt_ids=("a" * 32,),
    )
    assert base.scope_id == "product-scope"
    assert base.current_records == (records[2],)
    assert base.replay_retained((history.active_raw,)).current_records == (records[3],)
    assert CodingWorkerStartGateSemanticBaseV2.from_bytes(base.to_bytes()) == base


def test_start_gate_base_refuses_retired_reuse_and_changed_binding() -> None:
    history, _records = _history()
    base = CodingWorkerStartGateSemanticBaseV2.from_v1_history(
        history=history,
        scope_id="scope",
        first_retained_generation=1,
        retired_attempt_ids=("a" * 32,),
    )
    with pytest.raises(ValueError, match="retained replay"):
        base.replay_retained((_line(_record(4, attempt_id="a" * 32, bound=False)),))
    with pytest.raises(ValueError, match="retained replay"):
        base.replay_retained((_line(_record(4, attempt_id="b" * 32, bound=False)),))
    changed_binding = CodingWorkerStartGateRecordV1.create(
        journal_revision=4,
        phase="bound",
        attempt_id="b" * 32,
        worker_identity_fingerprint="c" * 64,
        receipt_fingerprint="0" * 64,
        policy_fingerprint="e" * 64,
        scope_id="scope",
        native_closure_digest="f" * 64,
        identity=_record(4, attempt_id="b" * 32, bound=True).identity,
    )
    with pytest.raises(ValueError, match="retained replay"):
        base.replay_retained((_line(changed_binding),))
    with pytest.raises(ValueError, match="base bytes are invalid"):
        CodingWorkerStartGateSemanticBaseV2.from_bytes(base.to_bytes() + b" ")

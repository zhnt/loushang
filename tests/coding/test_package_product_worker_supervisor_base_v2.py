"""Supervisor V2 base preserves attempts, epochs, and retry-window state."""

from __future__ import annotations

import json
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
    CodingWorkerStreamRetirementPreviewV2,
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
from loushang.coding.package_product_worker_supervisor_base_v2 import (
    CodingWorkerSupervisorSemanticBaseV2,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1, _validate_history

_KEY = "c" * 64
_OLD = "a" * 32
_NEW = "e" * 32


def _record(
    revision: int,
    *,
    attempt_id: str,
    epoch: int,
    phase: str,
    prior_revision: int,
    ordinal: int,
    failure_code: str | None = None,
) -> WorkerAttemptRecordV1:
    return WorkerAttemptRecordV1(
        supervisor_key=_KEY,
        identity_fingerprint="d" * 64 if attempt_id == _OLD else "f" * 64,
        attempt_id=attempt_id,
        supervisor_epoch=epoch,
        phase=phase,  # type: ignore[arg-type]
        record_revision=revision,
        prior_attempt_revision=prior_revision,
        restart_ordinal=ordinal,
        failure_code=failure_code,
    )


def _line(record: WorkerAttemptRecordV1) -> bytes:
    return (
        json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _history() -> tuple[
    CodingWorkerSegmentedHistoryV1, tuple[WorkerAttemptRecordV1, ...]
]:
    records = (
        _record(
            1, attempt_id=_OLD, epoch=1, phase="claimed", prior_revision=0, ordinal=1
        ),
        _record(
            2,
            attempt_id=_OLD,
            epoch=1,
            phase="failed",
            prior_revision=1,
            ordinal=1,
            failure_code="test_failure",
        ),
        _record(
            3,
            attempt_id=_OLD,
            epoch=1,
            phase="process_settled",
            prior_revision=2,
            ordinal=1,
            failure_code="test_failure",
        ),
        _record(
            4, attempt_id=_NEW, epoch=2, phase="claimed", prior_revision=0, ordinal=2
        ),
        _record(
            5, attempt_id=_NEW, epoch=2, phase="launching", prior_revision=4, ordinal=2
        ),
    )
    old = b"".join(_line(item) for item in records[:3])
    active = b"".join(_line(item) for item in records[3:])
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
                stream_id="worker-supervisor", active_generation=1, sealed=(seal,)
            ),
            segments=(old, active),
        ),
        records,
    )


def test_supervisor_base_replays_an_explicit_zero_record_cutover() -> None:
    manifest = CodingWorkerSegmentManifestV1(
        stream_id="worker-supervisor", active_generation=0, sealed=()
    )
    assert CodingWorkerSegmentManifestV1.from_bytes(
        manifest.to_bytes(), stream_id="worker-supervisor"
    ) == manifest
    history = CodingWorkerSegmentedHistoryV1(manifest=manifest, segments=(b"",))
    base = CodingWorkerSupervisorSemanticBaseV2.from_v1_history(
        history=history,
        scope_id="scope",
        first_retained_generation=0,
        retired_attempt_ids=(),
    )
    assert base.cutoff_revision == 0
    assert base.current_attempts == base.key_states == base.retired_attempt_ids == ()
    assert CodingWorkerSupervisorSemanticBaseV2.from_bytes(base.to_bytes()) == base
    assert base.replay_retained((b"",)).last_revision == 0
    snapshot = CodingWorkerHistoryStreamSnapshotV1.capture(
        stem="worker-supervisor",
        active_generation=0,
        last_sealed_revision=0,
        segments=history.segments,
    )
    preview = CodingWorkerStreamRetirementPreviewV2(
        stem="worker-supervisor",
        checkpoint_revision=1,
        checkpoint_digest="a" * 64,
        source_fingerprint=snapshot.fingerprint,
        first_retained_generation=0,
        first_retained_revision=1,
        retired_sealed_digest=sha256(b"[]").hexdigest(),
        retired_generations=(),
        retained_generations=(0,),
    )
    stream = CodingWorkerStreamCutoverV2.from_preview(
        preview=preview,
        history=history,
        semantic_base_digest=sha256(base.to_bytes()).hexdigest(),
    )
    assert stream.first_retained_generation == stream.total_revision == 0
    assert CodingWorkerStreamCutoverV2.from_bytes(stream.to_bytes()) == stream
    with pytest.raises(ValueError, match="manifest is invalid"):
        CodingWorkerSegmentManifestV1(
            stream_id="worker-start-gates", active_generation=0, sealed=()
        )


def test_supervisor_base_replays_epoch_and_binds_checkpoint_waterline() -> None:
    history, records = _history()
    _validate_history(records)
    base = CodingWorkerSupervisorSemanticBaseV2.from_v1_history(
        history=history,
        scope_id="scope",
        first_retained_generation=1,
        retired_attempt_ids=(_OLD,),
    )
    assert base.cutoff_revision == 3
    assert base.current_attempts == ()
    assert base.key_states[0].last_record == records[2]
    assert base.key_states[0].claims_since_stop == 1
    assert CodingWorkerSupervisorSemanticBaseV2.from_bytes(base.to_bytes()) == base
    replay = base.replay_retained((history.active_raw,))
    assert replay.last_revision == 5
    assert replay.current_attempts == (records[4],)
    assert replay.key_states[0].last_record == records[4]
    assert replay.key_states[0].claims_since_stop == 2

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
        attempt_id=_OLD,
        receipt_fingerprint="b" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=(_OLD,),
        new_receipt_fingerprints=("b" * 64,),
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=((_KEY, 2),),
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
        stem="worker-supervisor",
        first_retained_generation=1,
    )
    stream = CodingWorkerStreamCutoverV2.from_supervisor_base(
        checkpoints=(checkpoint,), preview=preview, history=history, semantic_base=base
    )
    assert stream.semantic_base_digest == sha256(base.to_bytes()).hexdigest()
    forged = replace(
        base,
        key_states=(replace(base.key_states[0], last_clean_stop_revision=1),),
    )
    with pytest.raises(ValueError, match="semantic base differs"):
        CodingWorkerStreamCutoverV2.from_supervisor_base(
            checkpoints=(checkpoint,),
            preview=preview,
            history=history,
            semantic_base=forged,
        )


def test_supervisor_base_refuses_retired_reuse_and_stale_epoch() -> None:
    history, _records = _history()
    base = CodingWorkerSupervisorSemanticBaseV2.from_v1_history(
        history=history,
        scope_id="scope",
        first_retained_generation=1,
        retired_attempt_ids=(_OLD,),
    )
    with pytest.raises(ValueError, match="retired"):
        base.replay_retained(
            (
                _line(
                    _record(
                        4,
                        attempt_id=_OLD,
                        epoch=2,
                        phase="claimed",
                        prior_revision=0,
                        ordinal=2,
                    )
                ),
            )
        )
    with pytest.raises(ValueError, match="claim is invalid"):
        base.replay_retained(
            (
                _line(
                    _record(
                        4,
                        attempt_id=_NEW,
                        epoch=1,
                        phase="claimed",
                        prior_revision=0,
                        ordinal=2,
                    )
                ),
            )
        )
    with pytest.raises(ValueError, match="base bytes are invalid"):
        CodingWorkerSupervisorSemanticBaseV2.from_bytes(base.to_bytes() + b" ")


def test_supervisor_base_resets_retry_ordinal_after_clean_stop() -> None:
    phases = (
        "claimed",
        "launching",
        "handshaking",
        "healthy",
        "draining",
        "stopped",
    )
    old_records = tuple(
        _record(
            revision,
            attempt_id=_OLD,
            epoch=1,
            phase=phase,
            prior_revision=revision - 1,
            ordinal=1,
        )
        for revision, phase in enumerate(phases, 1)
    )
    old_raw = b"".join(_line(item) for item in old_records)
    seal = CodingWorkerSealedSegmentV1(
        generation=0,
        first_revision=1,
        last_revision=len(old_records),
        byte_count=len(old_raw),
        digest=sha256(old_raw).hexdigest(),
    )
    history = CodingWorkerSegmentedHistoryV1(
        manifest=CodingWorkerSegmentManifestV1(
            stream_id="worker-supervisor", active_generation=1, sealed=(seal,)
        ),
        segments=(old_raw, b""),
    )
    base = CodingWorkerSupervisorSemanticBaseV2.from_v1_history(
        history=history,
        scope_id="scope",
        first_retained_generation=1,
        retired_attempt_ids=(_OLD,),
    )
    assert base.key_states[0].last_clean_stop_revision == 6
    assert base.key_states[0].claims_since_stop == 0
    next_claim = _record(
        7, attempt_id=_NEW, epoch=2, phase="claimed", prior_revision=0, ordinal=1
    )
    assert (
        base.replay_retained((_line(next_claim),)).key_states[0].claims_since_stop == 1
    )
    with pytest.raises(ValueError, match="claim is invalid"):
        base.replay_retained((_line(replace(next_claim, restart_ordinal=2)),))


def test_supervisor_base_refuses_unsettled_retired_attempt() -> None:
    history, _ = _history()
    with pytest.raises(ValueError, match="retired attempt is not settled"):
        CodingWorkerSupervisorSemanticBaseV2.from_v1_history(
            history=history,
            scope_id="scope",
            first_retained_generation=1,
            retired_attempt_ids=(_NEW,),
        )

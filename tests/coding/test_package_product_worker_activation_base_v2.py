"""C5 V2 state keeps current attempts and refuses compacted ID reuse."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.coding.package_product_worker_activation_base_v2 import (
    CodingWorkerActivationSemanticBaseV2,
)
from loushang.coding.package_product_worker_activation_history import (
    project_coding_worker_retained_attempts,
    validate_coding_worker_activation_attempt_history,
)
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
from loushang.harness.worker.activation_state_journal import (
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.product_activation import (
    WorkerCleanupSettlementV1,
    _AttemptKey,
    _initial_state,
)
from tests.coding.test_package_product_worker_activation_segments import (
    _next_state,
    _registered_attempt,
)


def _states() -> tuple[dict[str, object], ...]:
    receipt = "a" * 64
    attempt_id = "b" * 32
    key = _AttemptKey(receipt, attempt_id, 1).encoded
    attempt = _registered_attempt(receipt=receipt, attempt_id=attempt_id)
    initial = _initial_state(restart_budget=3)
    registered = _next_state(initial)
    registered["attempts"] = {key: attempt}
    settled = _next_state(registered)
    settled_attempt = dict(attempt)
    settled_attempt.update(
        phase="settled",
        domainRetired=True,
        protocolTerminal=True,
        cleanupSettlement=WorkerCleanupSettlementV1(
            receipt_fingerprint=receipt,
            attempt_id=attempt_id,
            owner_generation=1,
            host_identity="host-a",
            boot_identity="boot-a",
            protocol_terminal=True,
            domain_retired=True,
            tree_settled=True,
            no_effect=True,
        ).to_dict(),
    )
    settled["attempts"] = {key: settled_attempt}
    compacted = _next_state(settled)
    compacted["attempts"] = {}
    unchanged = _next_state(compacted)
    return initial, registered, settled, compacted, unchanged


def _line(state: dict[str, object]) -> bytes:
    return _canonical_json_bytes(_StateRecord.create(state).to_dict()) + b"\n"


def _history(
    cutoff: int,
) -> tuple[CodingWorkerSegmentedHistoryV1, tuple[_StateRecord, ...]]:
    states = _states()
    records = tuple(_StateRecord.create(state) for state in states)
    old = b"".join(_line(state) for state in states[:cutoff])
    active = b"".join(_line(state) for state in states[cutoff:])
    seal = CodingWorkerSealedSegmentV1(
        generation=0,
        first_revision=1,
        last_revision=cutoff,
        byte_count=len(old),
        digest=sha256(old).hexdigest(),
    )
    return (
        CodingWorkerSegmentedHistoryV1(
            manifest=CodingWorkerSegmentManifestV1(
                stream_id="worker-activation-state",
                active_generation=1,
                sealed=(seal,),
            ),
            segments=(old, active),
        ),
        records,
    )


def test_c5_base_replays_live_transition_and_compaction() -> None:
    history, records = _history(2)
    validate_coding_worker_activation_attempt_history(records)
    base = CodingWorkerActivationSemanticBaseV2.from_v1_history(
        history=history, scope_id="scope", first_retained_generation=1
    )
    assert base.last_record == records[1]
    assert base.retired_attempt_ids == ()
    assert CodingWorkerActivationSemanticBaseV2.from_bytes(base.to_bytes()) == base
    replay = base.replay_retained((history.active_raw,))
    assert replay.last_record == records[-1]
    assert replay.retired_attempt_ids == frozenset({"b" * 32})

    changed_identity = _states()[2]
    key = _AttemptKey("a" * 64, "b" * 32, 1).encoded
    attempt = dict(changed_identity["attempts"][key])
    attempt["evidenceAuthorityId"] = "different-evidence"
    changed_identity["attempts"] = {key: attempt}
    with pytest.raises(ValueError, match="retained replay"):
        base.replay_retained((_line(changed_identity),))


def test_c5_v2_base_retains_no_effect_settlement_after_v1_retirement() -> None:
    history, _ = _history(3)
    base = CodingWorkerActivationSemanticBaseV2.from_v1_history(
        history=history, scope_id="scope", first_retained_generation=1
    )
    reopened = CodingWorkerActivationSemanticBaseV2.from_bytes(base.to_bytes())
    [attempt] = project_coding_worker_retained_attempts((reopened.last_record,))
    assert attempt.no_effect
    assert attempt.phase == "settled"
    assert reopened.replay_retained((history.active_raw,)).retired_attempt_ids == (
        frozenset({"b" * 32})
    )


def test_c5_base_refuses_retired_id_and_binds_exact_cutover() -> None:
    history, records = _history(4)
    base = CodingWorkerActivationSemanticBaseV2.from_v1_history(
        history=history, scope_id="scope", first_retained_generation=1
    )
    assert base.last_record == records[3]
    assert base.retired_attempt_ids == ("b" * 32,)
    assert base.replay_retained((history.active_raw,)).last_record == records[4]

    reused = _next_state(_states()[3])
    key = _AttemptKey("a" * 64, "b" * 32, 1).encoded
    reused["attempts"] = {
        key: _registered_attempt(receipt="a" * 64, attempt_id="b" * 32)
    }
    with pytest.raises(ValueError, match="retained replay"):
        base.replay_retained((_line(reused),))

    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=1,
            last_sealed_revision=4,
            segments=history.segments,
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="scope",
        store_id="store",
        attempt_id="b" * 32,
        receipt_fingerprint="a" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=("b" * 32,),
        new_receipt_fingerprints=("a" * 64,),
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
        stem="worker-activation-state",
        first_retained_generation=1,
    )
    stream = CodingWorkerStreamCutoverV2.from_activation_base(
        checkpoint=checkpoint, preview=preview, history=history, semantic_base=base
    )
    assert stream.semantic_base_digest == sha256(base.to_bytes()).hexdigest()
    with pytest.raises(ValueError, match="semantic base differs"):
        CodingWorkerStreamCutoverV2.from_activation_base(
            checkpoint=checkpoint,
            preview=preview,
            history=history,
            semantic_base=replace(base, retired_attempt_ids=()),
        )


def test_c5_base_refuses_changed_prefix_and_noncanonical_bytes() -> None:
    history, _records = _history(4)
    base = CodingWorkerActivationSemanticBaseV2.from_v1_history(
        history=history, scope_id="scope", first_retained_generation=1
    )
    changed = CodingWorkerSegmentedHistoryV1(
        manifest=history.manifest,
        segments=(history.segments[0] + b" ", history.active_raw),
    )
    with pytest.raises(ValueError, match="source changed"):
        CodingWorkerActivationSemanticBaseV2.from_v1_history(
            history=changed, scope_id="scope", first_retained_generation=1
        )
    with pytest.raises(ValueError, match="bytes are invalid"):
        CodingWorkerActivationSemanticBaseV2.from_bytes(base.to_bytes() + b" ")

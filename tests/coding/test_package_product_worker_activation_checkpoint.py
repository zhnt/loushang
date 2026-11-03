"""C5 writes respect checkpointed source bytes and retired attempt identities."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from loushang.coding.package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from loushang.coding.package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
    write_coding_worker_checkpoint_anchor,
)
from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
    commit_coding_worker_active_segment,
    initialize_coding_worker_active_head,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
)
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError,
    _StateRecord,
)
from loushang.harness.worker.product_activation import _AttemptKey, _initial_state
from tests.coding.test_package_product_worker_activation_segments import (
    _next_state,
    _registered_attempt,
)


def test_activation_checkpoint_preserves_source_and_retired_attempt_id() -> None:
    attempt_id = "a" * 32
    receipt = "b" * 64
    original = b'{"journalRevision":1}\n'
    appended = b'{"journalRevision":2}\n'
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=0,
            last_sealed_revision=0,
            segments=(original if stem == "worker-activation-state" else b"",),
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="scope",
        store_id="store",
        attempt_id=attempt_id,
        receipt_fingerprint=receipt,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=(attempt_id,),
        new_receipt_fingerprints=(receipt,),
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=(),
    )
    history = CodingWorkerSegmentedHistoryV1(
        manifest=None, segments=(original + appended,)
    )
    assert (
        CodingProductWorkerActivationStateJournal._assert_checkpoint_source(
            (checkpoint,), history
        )
        == 1
    )

    rewritten = CodingWorkerSegmentedHistoryV1(
        manifest=None, segments=(b'{"journalRevision":9}\n' + appended,)
    )
    with pytest.raises(WorkerActivationStateJournalError) as changed:
        CodingProductWorkerActivationStateJournal._assert_checkpoint_source(
            (checkpoint,), rewritten
        )
    assert changed.value.code == "worker_activation_state_checkpoint_source_changed"

    initial = _initial_state(restart_budget=3)
    registered = _next_state(initial)
    key = _AttemptKey(receipt, attempt_id, 1).encoded
    registered["attempts"] = {
        key: _registered_attempt(receipt=receipt, attempt_id=attempt_id)
    }
    candidate = _StateRecord.create(registered)
    with pytest.raises(WorkerActivationStateJournalError) as retired:
        CodingProductWorkerActivationStateJournal._assert_checkpoint_attempts_fresh(
            (checkpoint,), (_StateRecord.create(initial),), candidate
        )
    assert retired.value.code == "worker_activation_state_attempt_retired"

    # An existing retained attempt may progress across a CAS revision.
    CodingProductWorkerActivationStateJournal._assert_checkpoint_attempts_fresh(
        (checkpoint,), (candidate,), _StateRecord.create(_next_state(registered))
    )


@pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted Product journal")
def test_activation_writer_reads_anchored_checkpoint_before_cas(tmp_path: Path) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    journal = CodingProductWorkerActivationStateJournal(
        root / "worker-activation-state.jsonl", scope_id="scope", store_id="store"
    )
    initial = _initial_state(restart_budget=3)
    assert journal.compare_and_swap(expected_revision=0, document=initial)

    attempt_id = "a" * 32
    receipt = "b" * 64
    c5_source = journal.path.read_bytes()
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=0,
            last_sealed_revision=0,
            segments=(c5_source if stem == "worker-activation-state" else b"",),
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="scope",
        store_id="store",
        attempt_id=attempt_id,
        receipt_fingerprint=receipt,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=(attempt_id,),
        new_receipt_fingerprints=(receipt,),
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=(),
    )
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    io = RootedFileIO(root, root_fd)
    try:
        with io.bind(root / "worker-history-checkpoints.jsonl", durable=True) as rooted:
            assert rooted.acquire_lock(
                exclusive=True,
                suffix=".lock",
                initialize_empty_target_if_new=True,
            )
            initialize_coding_worker_active_head(
                rooted,
                stem="worker-history-checkpoints",
                stream_id="worker-history-checkpoints",
            )
            line = canonical_json_bytes(checkpoint.to_dict()) + b"\n"
            rooted.append_bytes(line)
            commit_coding_worker_active_segment(
                rooted,
                stem="worker-history-checkpoints",
                stream_id="worker-history-checkpoints",
                generation=0,
                previous_raw=b"",
                appended_line=line,
            )
            write_coding_worker_checkpoint_anchor(
                rooted,
                expected=None,
                current=CodingWorkerCheckpointAnchorV1.create(
                    scope_id="scope",
                    store_id="store",
                    latest_revision=1,
                    latest_digest=checkpoint.record_digest,
                ),
            )
    finally:
        io.cleanup()
        os.close(root_fd)

    registered = _next_state(initial)
    key = _AttemptKey(receipt, attempt_id, 1).encoded
    registered["attempts"] = {
        key: _registered_attempt(receipt=receipt, attempt_id=attempt_id)
    }
    before = journal.path.read_bytes()
    with pytest.raises(WorkerActivationStateJournalError) as retired:
        journal.compare_and_swap(expected_revision=1, document=registered)
    assert retired.value.code == "worker_activation_state_attempt_retired"
    assert journal.path.read_bytes() == before

    ownerless = CodingProductWorkerActivationStateJournal(journal.path)
    with pytest.raises(WorkerActivationStateJournalError) as missing_owner:
        ownerless.compare_and_swap(expected_revision=1, document=_next_state(initial))
    assert (
        missing_owner.value.code == "worker_activation_state_checkpoint_owner_required"
    )
    assert journal.path.read_bytes() == before

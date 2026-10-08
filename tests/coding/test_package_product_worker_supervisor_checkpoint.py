"""Supervisor writes keep checkpointed bytes, attempt IDs, and epochs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

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
from loushang.coding.package_product_worker_payload import (
    open_coding_product_worker_supervisor_journal,
)
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
    WorkerSupervisorJournalError,
)
from tests.coding.test_package_product_worker_supervisor_segments import (
    _identity,
    _product,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Product journal")


def _checkpoint(
    source: bytes,
    *,
    scope_id: str,
    store_id: str,
    supervisor_key: str,
    attempt_ids: tuple[str, ...],
    epoch_high_water: int,
) -> CodingWorkerHistoryCheckpointV1:
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=0,
            last_sealed_revision=0,
            segments=(source if stem == "worker-supervisor" else b"",),
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    return CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id=scope_id,
        store_id=store_id,
        attempt_id=attempt_ids[0],
        receipt_fingerprint="b" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=(),
        new_attempt_ids=attempt_ids,
        new_receipt_fingerprints=("b" * 64,),
        opt_in_generation_high_water=(),
        supervisor_epoch_high_water=((supervisor_key, epoch_high_water),),
    )


def test_supervisor_writer_reads_anchor_and_refuses_retired_attempt(
    tmp_path: Path,
) -> None:
    owner = _product(tmp_path)
    try:
        product = owner.runtime_owner.product_owner
        journal = open_coding_product_worker_supervisor_journal(product)
        first = _identity(attempt="1", epoch=1)
        claimed = journal.claim(first, max_attempts=3)
        failed = journal.transition(
            first.attempt_id,
            expected_phase="claimed",
            next_phase="failed",
            expected_record_revision=claimed.record_revision,
            expected_supervisor_epoch=1,
            failure_code="test_failure",
        )
        journal.transition(
            first.attempt_id,
            expected_phase="failed",
            next_phase="process_settled",
            expected_record_revision=failed.record_revision,
            expected_supervisor_epoch=1,
            failure_code="test_failure",
        )
        second = _identity(attempt="2", epoch=2)
        scope_id = product.policy.project_scope_id
        store_id = product.epoch_runtime.registry.store_id
        checkpoint = _checkpoint(
            journal.path.read_bytes(),
            scope_id=scope_id,
            store_id=store_id,
            supervisor_key=claimed.supervisor_key,
            attempt_ids=(first.attempt_id, second.attempt_id),
            epoch_high_water=1,
        )
        root = product.state_root
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        io = RootedFileIO(root, root_fd)
        try:
            with io.bind(
                root / "worker-history-checkpoints.jsonl", durable=True
            ) as rooted:
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
                        scope_id=scope_id,
                        store_id=store_id,
                        latest_revision=1,
                        latest_digest=checkpoint.record_digest,
                    ),
                )
        finally:
            io.cleanup()
            os.close(root_fd)

        before = journal.path.read_bytes()
        with pytest.raises(WorkerSupervisorJournalError) as retired:
            journal.claim(second, max_attempts=3)
        assert retired.value.code == "worker_supervisor_checkpoint_attempt_retired"
        assert journal.path.read_bytes() == before

        third = _identity(attempt="3", epoch=2)
        assert journal.next_supervisor_epoch(third) == 2
        successor = journal.claim(third, max_attempts=3)
        assert successor.record_revision == 4
        assert successor.supervisor_epoch == 2
    finally:
        owner.close()


def test_supervisor_checkpoint_rejects_source_fork_and_epoch_reuse(
    tmp_path: Path,
) -> None:
    owner = _product(tmp_path)
    try:
        product = owner.runtime_owner.product_owner
        journal = open_coding_product_worker_supervisor_journal(product)
        first = _identity(attempt="1", epoch=1)
        claimed = journal.claim(first, max_attempts=3)
        source = journal.path.read_bytes()
        checkpoint = _checkpoint(
            source,
            scope_id=product.policy.project_scope_id,
            store_id=product.epoch_runtime.registry.store_id,
            supervisor_key=claimed.supervisor_key,
            attempt_ids=(first.attempt_id,),
            epoch_high_water=2,
        )
        candidate = WorkerAttemptRecordV1(
            supervisor_key=claimed.supervisor_key,
            identity_fingerprint="d" * 64,
            attempt_id="2" * 32,
            supervisor_epoch=2,
            phase="claimed",
            record_revision=4,
            prior_attempt_revision=0,
            restart_ordinal=2,
        )
        history = CodingWorkerSegmentedHistoryV1(manifest=None, segments=(source,))
        with pytest.raises(WorkerSupervisorJournalError) as stale:
            journal._assert_checkpoint_write((checkpoint,), history, candidate)
        assert stale.value.code == "worker_supervisor_checkpoint_epoch_retired"

        forked = CodingWorkerSegmentedHistoryV1(
            manifest=None, segments=(source.replace(b'"claimed"', b'"failed"'),)
        )
        with pytest.raises(WorkerSupervisorJournalError) as changed:
            journal._assert_checkpoint_write((checkpoint,), forked, candidate)
        assert changed.value.code == "worker_supervisor_checkpoint_source_changed"
    finally:
        owner.close()

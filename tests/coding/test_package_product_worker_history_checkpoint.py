"""Fail-closed durable checkpoint record and active-head regression."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointError,
    CodingWorkerHistoryCheckpointV1,
    _anchor_for_records,
    _is_empty_seal_successor,
    _read_records,
    _read_records_or_repair_empty_bootstrap,
)
from loushang.coding.package_product_worker_history_checkpoint_anchor import (
    ANCHOR_NAME,
    CodingWorkerCheckpointAnchorError,
    CodingWorkerCheckpointAnchorV1,
    read_coding_worker_checkpoint_anchor,
    write_coding_worker_checkpoint_anchor,
)
from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    commit_coding_worker_active_segment,
    initialize_coding_worker_active_head,
    rollback_coding_worker_uncommitted_active_tail,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
)
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)


def test_worker_checkpoint_stream_requires_exact_old_bytes_before_new_revision() -> None:
    first = b'{"journalRevision":1}\n'
    next_record = b'{"journalRevision":2}\n'
    prior = CodingWorkerHistoryStreamSnapshotV1.capture(
        stem="worker-start-gates",
        active_generation=0,
        last_sealed_revision=0,
        segments=(first,),
    )
    appended = (first + next_record,)
    appended_snapshot = CodingWorkerHistoryStreamSnapshotV1.capture(
        stem="worker-start-gates",
        active_generation=0,
        last_sealed_revision=0,
        segments=appended,
    )
    assert prior.is_exact_prefix_of(
        appended_snapshot, current_segments=appended
    )

    rewritten = (b'{"journalRevision":9}\n' + next_record,)
    rewritten_snapshot = CodingWorkerHistoryStreamSnapshotV1.capture(
        stem="worker-start-gates",
        active_generation=0,
        last_sealed_revision=0,
        segments=rewritten,
    )
    assert rewritten_snapshot.total_revision > prior.total_revision
    assert not prior.is_exact_prefix_of(
        rewritten_snapshot, current_segments=rewritten
    )

    rotated = (first + next_record, b"")
    rotated_snapshot = CodingWorkerHistoryStreamSnapshotV1.capture(
        stem="worker-start-gates",
        active_generation=1,
        last_sealed_revision=2,
        segments=rotated,
    )
    assert prior.is_exact_prefix_of(
        rotated_snapshot, current_segments=rotated
    )
    assert _is_empty_seal_successor(appended_snapshot, rotated_snapshot)
    rewritten_rotated = CodingWorkerHistoryStreamSnapshotV1.capture(
        stem="worker-start-gates",
        active_generation=1,
        last_sealed_revision=2,
        segments=(rewritten[0], b""),
    )
    assert not _is_empty_seal_successor(appended_snapshot, rewritten_rotated)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted Product journal")
def test_worker_checkpoint_reopens_complete_record_and_refuses_uncommitted_append(
    tmp_path: Path,
) -> None:
    snapshots = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=0,
            last_sealed_revision=0,
            segments=(b"",),
        )
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    checkpoint = CodingWorkerHistoryCheckpointV1.create(
        journal_revision=1,
        scope_id="project",
        store_id="store",
        attempt_id="a" * 32,
        receipt_fingerprint="b" * 64,
        previous_digest="",
        gc_reservation_revision=0,
        backup_topology_revision="coding-product-backup-types:" + "c" * 64,
        stream_snapshots=snapshots,
        new_opt_in_operation_ids=("allow-1",),
        new_attempt_ids=("a" * 32,),
        new_receipt_fingerprints=("b" * 64,),
        opt_in_generation_high_water=(("worker", 1, 0, "allow", "d" * 64),),
        supervisor_epoch_high_water=(("worker-key", 1),),
    )
    assert CodingWorkerHistoryCheckpointV1.from_dict(checkpoint.to_dict()) == checkpoint
    changed = checkpoint.to_dict()
    changed["gcReservationRevision"] = 1
    with pytest.raises(ValueError, match="checkpoint is invalid"):
        CodingWorkerHistoryCheckpointV1.from_dict(changed)

    tmp_path.chmod(0o700)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        io = RootedFileIO(tmp_path, root_fd)
        try:
            with io.bind(
                tmp_path / "worker-history-checkpoints.jsonl", durable=True
            ) as rooted:
                rooted.create_new(b"")
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
                records, _history = _read_records(
                    rooted, scope_id="project", store_id="store"
                )
                assert records == (checkpoint,)
                with pytest.raises(CodingWorkerHistoryCheckpointError) as missing:
                    _anchor_for_records(
                        rooted,
                        scope_id="project",
                        store_id="store",
                        records=records,
                        settle_lag=False,
                    )
                assert missing.value.code == "coding_worker_checkpoint_anchor_missing"
                anchor = CodingWorkerCheckpointAnchorV1.create(
                    scope_id="project",
                    store_id="store",
                    latest_revision=0,
                    latest_digest="",
                )
                write_coding_worker_checkpoint_anchor(
                    rooted, expected=None, current=anchor
                )
                with pytest.raises(CodingWorkerHistoryCheckpointError) as lagging:
                    _anchor_for_records(
                        rooted,
                        scope_id="project",
                        store_id="store",
                        records=records,
                        settle_lag=False,
                    )
                assert lagging.value.code == "coding_worker_checkpoint_anchor_lagging"
                settled = _anchor_for_records(
                    rooted,
                    scope_id="project",
                    store_id="store",
                    records=records,
                    settle_lag=True,
                )
                assert settled is not None
                assert settled.latest_revision == 1
                assert settled.latest_digest == checkpoint.record_digest
                assert read_coding_worker_checkpoint_anchor(
                    rooted, scope_id="project", store_id="store"
                ) == settled
                rooted.append_bytes(b"{}\n")
                with pytest.raises(
                    CodingWorkerHistorySegmentError,
                    match="coding_worker_segment_head_changed",
                ):
                    _read_records(rooted, scope_id="project", store_id="store")
        finally:
            io.cleanup()
    finally:
        os.close(root_fd)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted Product journal")
def test_worker_checkpoint_bootstrap_requires_anchor_before_head_recovery(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        io = RootedFileIO(tmp_path, root_fd)
        try:
            with io.bind(
                tmp_path / "worker-history-checkpoints.jsonl", durable=True
            ) as rooted:
                rooted.create_new(b"")
                with pytest.raises(
                    CodingWorkerHistorySegmentError,
                    match="coding_worker_segment_head_missing",
                ):
                    _read_records(rooted, scope_id="project", store_id="store")
                with pytest.raises(
                    CodingWorkerHistorySegmentError,
                    match="coding_worker_segment_head_missing",
                ):
                    rollback_coding_worker_uncommitted_active_tail(
                        rooted,
                        stem="worker-history-checkpoints",
                        stream_id="worker-history-checkpoints",
                        max_segment_bytes=32 * 1024 * 1024,
                    )
                assert rooted.read_bytes(max_bytes=1) == b""
                anchor = CodingWorkerCheckpointAnchorV1.create(
                    scope_id="project",
                    store_id="store",
                    latest_revision=0,
                    latest_digest="",
                )
                write_coding_worker_checkpoint_anchor(
                    rooted, expected=None, current=anchor
                )
                records, history = _read_records_or_repair_empty_bootstrap(
                    rooted, scope_id="project", store_id="store"
                )
                assert records == ()
                assert history.active_raw == b""
                assert _read_records(
                    rooted, scope_id="project", store_id="store"
                )[0] == ()
        finally:
            io.cleanup()
    finally:
        os.close(root_fd)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted Product journal")
def test_worker_checkpoint_anchor_rejects_changed_tip_bytes(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        io = RootedFileIO(tmp_path, root_fd)
        try:
            with io.bind(
                tmp_path / "worker-history-checkpoints.jsonl", durable=True
            ) as rooted:
                anchor = CodingWorkerCheckpointAnchorV1.create(
                    scope_id="project",
                    store_id="store",
                    latest_revision=0,
                    latest_digest="",
                )
                write_coding_worker_checkpoint_anchor(
                    rooted, expected=None, current=anchor
                )
                changed = anchor.to_bytes().replace(
                    b'"latestRevision":0', b'"latestRevision":1'
                )
                rooted.sibling(ANCHOR_NAME).atomic_write(changed)
                with pytest.raises(
                    CodingWorkerCheckpointAnchorError,
                    match="coding_worker_checkpoint_anchor_corrupt",
                ):
                    read_coding_worker_checkpoint_anchor(
                        rooted, scope_id="project", store_id="store"
                    )
        finally:
            io.cleanup()
    finally:
        os.close(root_fd)

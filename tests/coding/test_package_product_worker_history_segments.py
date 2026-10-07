"""A published Worker history must survive reopen and reject forked bytes."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    commit_coding_worker_active_segment,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
    read_coding_worker_uncommitted_active_append,
    read_coding_worker_uncommitted_active_tail,
    rollback_coding_worker_uncommitted_active_tail,
    seal_coding_worker_active_segment,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted journal")


@contextmanager
def _bound(root: Path):
    root.mkdir(mode=0o700, exist_ok=True)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    io = RootedFileIO(root, root_fd)
    try:
        with io.bind(root / "worker-start-gates.jsonl", durable=True) as rooted:
            created = rooted.acquire_lock(
                exclusive=True,
                suffix=".lock",
                initialize_empty_target_if_new=True,
            )
            if created:
                initialize_coding_worker_active_head(
                    rooted, stem="worker-start-gates", stream_id="worker-start-gates"
                )
            yield rooted
    finally:
        io.cleanup()
        os.close(root_fd)


def _read(rooted):
    return read_coding_worker_segmented_history(
        rooted,
        stem="worker-start-gates",
        stream_id="worker-start-gates",
        max_segment_bytes=1024,
    )


def _seal(rooted, history, revision):
    return seal_coding_worker_active_segment(
        rooted,
        stem="worker-start-gates",
        stream_id="worker-start-gates",
        history=history,
        last_revision=revision,
    )


def _append(rooted, generation: int, line: bytes) -> None:
    history = _read(rooted)
    assert history.active_generation == generation
    target = rooted.sibling(
        "worker-start-gates.jsonl"
        if generation == 0
        else f"worker-start-gates.g{generation:08d}.jsonl"
    )
    target.append_bytes(line)
    commit_coding_worker_active_segment(
        rooted,
        stem="worker-start-gates",
        stream_id="worker-start-gates",
        generation=generation,
        previous_raw=history.active_raw,
        appended_line=line,
    )


def test_sealed_history_reopens_across_generations_and_refuses_changed_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    with _bound(root) as rooted:
        _append(rooted, 0, b'{"journalRevision":1}\n')
        _seal(rooted, _read(rooted), 1)

    # A crash after manifest publication leaves a durable empty successor.
    with _bound(root) as rooted:
        history = _read(rooted)
        assert history.active_generation == 1
        assert history.segments == (b'{"journalRevision":1}\n', b"")
        assert (root / "worker-start-gates.g00000001.jsonl").is_file()
        _append(rooted, 1, b'{"journalRevision":2}\n')
        _seal(rooted, _read(rooted), 2)

    with _bound(root) as rooted:
        history = _read(rooted)
        assert history.active_generation == 2
        assert history.last_sealed_revision == 2
        assert history.active_raw == b""
        rooted.sibling("worker-start-gates.g00000001.jsonl").append_bytes(b"changed")
        with pytest.raises(CodingWorkerHistorySegmentError) as error:
            _read(rooted)
        assert error.value.code == "coding_worker_sealed_segment_changed"


@pytest.mark.parametrize("stem", ("worker-start-gates", "worker-activation-receipts"))
def test_first_writer_creates_durable_empty_history_and_refuses_its_loss(
    tmp_path: Path, stem: str
) -> None:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    io = RootedFileIO(root, root_fd)
    try:
        with io.bind(root / f"{stem}.jsonl", durable=True) as rooted:
            with pytest.raises(ValueError, match="separate new exclusive lock"):
                rooted.acquire_lock(exclusive=True, initialize_empty_target_if_new=True)
            created = rooted.acquire_lock(
                exclusive=True,
                suffix=".lock",
                initialize_empty_target_if_new=True,
            )
            assert created
            initialize_coding_worker_active_head(rooted, stem=stem, stream_id=stem)
            assert rooted.read_bytes(max_bytes=1024) == b""
            assert read_coding_worker_segmented_history(
                rooted, stem=stem, stream_id=stem, max_segment_bytes=1024
            ).segments == (b"",)
        (root / f"{stem}.jsonl").unlink()
        with io.bind(root / f"{stem}.jsonl", durable=True) as rooted:
            rooted.acquire_lock(
                exclusive=True,
                suffix=".lock",
                initialize_empty_target_if_new=True,
            )
            with pytest.raises(CodingWorkerHistorySegmentError) as lost:
                read_coding_worker_segmented_history(
                    rooted, stem=stem, stream_id=stem, max_segment_bytes=1024
                )
            assert lost.value.code == "coding_worker_segment_initial_missing"
    finally:
        io.cleanup()
        os.close(root_fd)


def test_interrupted_first_writer_leaves_refused_orphan_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    io = RootedFileIO(root, root_fd)
    original_create = RootedFile.create_new

    def interrupt_create(_target: RootedFile, _data: bytes) -> tuple[int, int]:
        raise OSError("interrupted before first history publication")

    try:
        with io.bind(root / "worker-start-gates.jsonl", durable=True) as rooted:
            monkeypatch.setattr(RootedFile, "create_new", interrupt_create)
            with pytest.raises(OSError, match="interrupted before first history"):
                rooted.acquire_lock(
                    exclusive=True,
                    suffix=".lock",
                    initialize_empty_target_if_new=True,
                )
        monkeypatch.setattr(RootedFile, "create_new", original_create)
        with io.bind(root / "worker-start-gates.jsonl", durable=True) as rooted:
            rooted.acquire_lock(exclusive=True, suffix=".lock", create=False)
            with pytest.raises(CodingWorkerHistorySegmentError) as orphan:
                _read(rooted)
            assert orphan.value.code == "coding_worker_segment_initial_missing"
    finally:
        monkeypatch.setattr(RootedFile, "create_new", original_create)
        io.cleanup()
        os.close(root_fd)


def test_orphan_and_stale_seal_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "state"
    with _bound(root) as rooted:
        _append(rooted, 0, b'{"journalRevision":1}\n')
        history = _read(rooted)
        rooted.sibling("worker-start-gates.g00000001.jsonl").append_bytes(b"orphan")
        with pytest.raises(CodingWorkerHistorySegmentError) as error:
            _read(rooted)
        assert error.value.code == "coding_worker_segment_orphan"

    (root / "worker-start-gates.g00000001.jsonl").unlink()
    with _bound(root) as rooted:
        _append(rooted, 0, b'{"journalRevision":2}\n')
        with pytest.raises(CodingWorkerHistorySegmentError) as error:
            _seal(rooted, history, 1)
        assert error.value.code == "coding_worker_segment_active_changed"
        _seal(rooted, _read(rooted), 2)

    manifest = root / "worker-start-gates.segments.json"
    manifest.write_bytes(
        manifest.read_bytes().replace(b'"activeGeneration":1', b'"activeGeneration":2')
    )
    with _bound(root) as rooted:
        with pytest.raises(CodingWorkerHistorySegmentError) as error:
            _read(rooted)
        assert error.value.code == "coding_worker_segment_manifest_invalid"


def test_reopen_after_publication_interruption_has_one_complete_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "state"
    original_write = RootedFile.atomic_write

    def interrupt_after_publish(
        target: RootedFile,
        data: bytes,
        *,
        fsync: bool = True,
        exclusive: bool = False,
    ) -> None:
        original_write(target, data, fsync=fsync, exclusive=exclusive)
        raise OSError("interrupted after durable manifest publication")

    with _bound(root) as rooted:
        _append(rooted, 0, b'{"journalRevision":1}\n')
        monkeypatch.setattr(RootedFile, "atomic_write", interrupt_after_publish)
        with pytest.raises(OSError, match="interrupted after"):
            _seal(rooted, _read(rooted), 1)

    with _bound(root) as rooted:
        history = _read(rooted)
        assert history.active_generation == 1
        assert history.last_sealed_revision == 1
        assert history.segments == (b'{"journalRevision":1}\n', b"")


def test_active_head_refuses_complete_record_truncation_and_missing_witness(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    first = b'{"journalRevision":1}\n'
    with _bound(root) as rooted:
        _append(rooted, 0, first)
        _append(rooted, 0, b'{"journalRevision":2}\n')

    (root / "worker-start-gates.jsonl").write_bytes(first)
    with _bound(root) as rooted:
        with pytest.raises(CodingWorkerHistorySegmentError) as truncated:
            _read(rooted)
        assert truncated.value.code == "coding_worker_segment_head_changed"

    (root / "worker-start-gates.head.json").unlink()
    with _bound(root) as rooted:
        with pytest.raises(CodingWorkerHistorySegmentError) as missing:
            _read(rooted)
        assert missing.value.code == "coding_worker_segment_head_missing"


def test_uncommitted_append_and_empty_successor_head_loss_refuse_reopen(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    with _bound(root) as rooted:
        rooted.append_bytes(b'{"journalRevision":1}\n')
        with pytest.raises(CodingWorkerHistorySegmentError) as uncommitted:
            _read(rooted)
        assert uncommitted.value.code == "coding_worker_segment_head_changed"
        pending = read_coding_worker_uncommitted_active_append(
            rooted,
            stem="worker-start-gates",
            stream_id="worker-start-gates",
            max_segment_bytes=1024,
        )
        assert pending.committed_history.active_raw == b""
        assert pending.appended_line == b'{"journalRevision":1}\n'

        rooted.append_bytes(b'{"journalRevision":2}\n')
        with pytest.raises(CodingWorkerHistorySegmentError) as multiple:
            read_coding_worker_uncommitted_active_append(
                rooted,
                stem="worker-start-gates",
                stream_id="worker-start-gates",
                max_segment_bytes=1024,
            )
        assert multiple.value.code == "coding_worker_segment_head_changed"

    root2 = tmp_path / "sealed"
    with _bound(root2) as rooted:
        _append(rooted, 0, b'{"journalRevision":1}\n')
        _seal(rooted, _read(rooted), 1)
    (root2 / "worker-start-gates.g00000001.head.json").unlink()
    with _bound(root2) as rooted:
        with pytest.raises(CodingWorkerHistorySegmentError) as missing:
            _read(rooted)
        assert missing.value.code == "coding_worker_segment_head_missing"


def test_head_anchored_rollback_discards_partial_tail_only(tmp_path: Path) -> None:
    root = tmp_path / "state"
    committed = b'{"journalRevision":1}\n'
    with _bound(root) as rooted:
        _append(rooted, 0, committed)
        rooted.append_bytes(b'{"journalRevision":2')
        with pytest.raises(CodingWorkerHistorySegmentError) as blocked:
            _read(rooted)
        assert blocked.value.code == "coding_worker_segment_head_changed"
        history, tail = read_coding_worker_uncommitted_active_tail(
            rooted,
            stem="worker-start-gates",
            stream_id="worker-start-gates",
            max_segment_bytes=1024,
        )
        assert history.active_raw == committed
        assert tail == b'{"journalRevision":2'
        with pytest.raises(OSError, match="source changed"):
            rooted.truncate_exact_prefix(
                expected=committed + b'{"journalRevision":9',
                keep_bytes=len(committed),
            )
        assert rollback_coding_worker_uncommitted_active_tail(
            rooted,
            stem="worker-start-gates",
            stream_id="worker-start-gates",
            max_segment_bytes=1024,
        ) == history
        assert _read(rooted) == history
        with pytest.raises(CodingWorkerHistorySegmentError) as absent:
            rollback_coding_worker_uncommitted_active_tail(
                rooted,
                stem="worker-start-gates",
                stream_id="worker-start-gates",
                max_segment_bytes=1024,
            )
        assert absent.value.code == "coding_worker_segment_repair_absent"

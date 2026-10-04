"""A published Worker history must survive reopen and reject forked bytes."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    read_coding_worker_segmented_history,
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
            rooted.acquire_lock(exclusive=True, suffix=".lock")
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


def test_sealed_history_reopens_across_generations_and_refuses_changed_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    with _bound(root) as rooted:
        rooted.append_bytes(b'{"journalRevision":1}\n')
        _seal(rooted, _read(rooted), 1)

    # A crash after manifest publication leaves an empty active generation.
    with _bound(root) as rooted:
        history = _read(rooted)
        assert history.active_generation == 1
        assert history.segments == (b'{"journalRevision":1}\n', b"")
        rooted.sibling("worker-start-gates.g00000001.jsonl").append_bytes(
            b'{"journalRevision":2}\n'
        )
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


def test_orphan_and_stale_seal_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "state"
    with _bound(root) as rooted:
        rooted.append_bytes(b'{"journalRevision":1}\n')
        history = _read(rooted)
        rooted.sibling("worker-start-gates.g00000001.jsonl").append_bytes(b"orphan")
        with pytest.raises(CodingWorkerHistorySegmentError) as error:
            _read(rooted)
        assert error.value.code == "coding_worker_segment_orphan"

    (root / "worker-start-gates.g00000001.jsonl").unlink()
    with _bound(root) as rooted:
        rooted.append_bytes(b'{"journalRevision":2}\n')
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
        rooted.append_bytes(b'{"journalRevision":1}\n')
        monkeypatch.setattr(RootedFile, "atomic_write", interrupt_after_publish)
        with pytest.raises(OSError, match="interrupted after"):
            _seal(rooted, _read(rooted), 1)

    with _bound(root) as rooted:
        history = _read(rooted)
        assert history.active_generation == 1
        assert history.last_sealed_revision == 1
        assert history.segments == (b'{"journalRevision":1}\n', b"")

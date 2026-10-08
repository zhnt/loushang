from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory
from loushang.apphost.managed.event_log import ManagedLifecycleLogV1
from tests.apphost.test_managed_namespace_admission import tree

from . import test_managed_event_log as fixtures

log = fixtures.log
registry = fixtures.registry
namespace = fixtures.namespace
pytestmark = fixtures.pytestmark


def test_rotated_tail_is_ordered_bounded_and_readonly(log):
    writer, directory, service_id = log
    for _ in range(25):
        writer.write(fixtures.event())
    before = tree(directory._root)
    reader = ManagedLifecycleLogV1(directory, writer._budget, service_id, segment_bytes=256)
    result = reader.read_tail(limit=5)
    assert [item.sequence for item in result] == [21, 22, 23, 24, 25]
    assert all(item.event == fixtures.event() for item in result)
    assert tree(directory._root) == before


def test_missing_log_lock_is_not_created(log):
    writer, directory, _ = log
    before = tree(directory._root)
    with pytest.raises(ManagedStorageError, match="not_found"):
        writer.read_tail(limit=5)
    assert tree(directory._root) == before


@pytest.mark.parametrize("limit", [True, 0, 101, -1, "5"])
def test_bad_read_limit_has_no_io(log, limit):
    writer, directory, _ = log
    with pytest.raises(ValueError):
        writer.read_tail(limit=limit)
    assert not tuple(directory._root.iterdir())


def test_bad_earlier_visible_frame_is_not_printed_or_repaired(log):
    writer, directory, _ = log
    writer.write(fixtures.event())
    writer.write(fixtures.event())
    path = directory._root / "lifecycle-0.jsonl"
    last = path.read_bytes().splitlines(keepends=True)[-1]
    path.write_bytes(b'{"message":"secret arbitrary text"}\n' + last)
    before = tree(directory._root)
    with pytest.raises(ManagedStorageError, match="invalid_record") as error:
        writer.read_tail(limit=1)
    assert "secret" not in str(error.value)
    assert tree(directory._root) == before


def test_reader_limits_actual_pread_and_handles_cut_first_frame(log, monkeypatch):
    writer, directory, service_id = log
    # Use the production cap for this same charged slot.
    writer = ManagedLifecycleLogV1(directory, writer._budget, service_id)
    for _ in range(220):
        writer.write(fixtures.event())
    content = (directory._root / "lifecycle-0.jsonl").read_bytes()
    assert len(content) > 16384
    assert content[-16385:-16384] != b"\n"
    native = os.pread
    requested = []

    def read(fd, size, offset):
        requested.append(size)
        return native(fd, size, offset)

    with monkeypatch.context() as patch:
        patch.setattr(os, "pread", read)
        result = writer.read_tail(limit=100)
    assert [item.sequence for item in result] == list(range(121, 221))
    assert sum(requested) <= 5 * 16384 and max(requested) <= 16384


def test_writer_lock_contention_is_bounded_and_readonly(log):
    writer, directory, service_id = log
    writer.write(fixtures.event())
    other = PrivateManagedDirectory(directory._root)
    reader = ManagedLifecycleLogV1(other, writer._budget, service_id, segment_bytes=256)
    entered, release = Event(), Event()

    def hold():
        with directory.lock("lifecycle.lock"):
            entered.set()
            assert release.wait(5)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(hold)
            assert entered.wait(5)
            before = tree(directory._root)
            try:
                with pytest.raises(ManagedStorageError, match="busy"):
                    reader.read_tail(limit=1, deadline=monotonic() + 0.05)
                assert tree(directory._root) == before
            finally:
                release.set()
                future.result(timeout=5)
        assert reader.read_tail(limit=1, deadline=monotonic() + 2)[0].sequence == 1
    finally:
        other.close()


def test_reader_contention_drops_only_current_writer_event(log, monkeypatch):
    writer, directory, service_id = log
    assert writer.write(fixtures.event()) == 1
    other = PrivateManagedDirectory(directory._root)
    reader = ManagedLifecycleLogV1(other, writer._budget, service_id, segment_bytes=256)
    entered, release = Event(), Event()
    native = reader._snapshots

    def snapshots(**kwargs):
        entered.set()
        assert release.wait(5)
        return native(**kwargs)

    monkeypatch.setattr(reader, "_snapshots", snapshots)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(reader.read_tail)
            assert entered.wait(5)
            try:
                assert writer.write(fixtures.event()) is None
                assert not writer._failed
            finally:
                release.set()
                assert future.result(timeout=5)[0].sequence == 1
        assert writer.write(fixtures.event()) == 2
    finally:
        other.close()


def test_reader_checks_deadline_after_lock_release(log, monkeypatch):
    from loushang.apphost.managed import _files

    writer, directory, _ = log
    writer.write(fixtures.event())
    native = directory.lock
    expired = False

    @contextmanager
    def lock(*args, **kwargs):
        nonlocal expired
        with native(*args, **kwargs):
            yield
        expired = True

    monkeypatch.setattr(directory, "lock", lock)
    monkeypatch.setattr(_files, "monotonic", lambda: 11.0 if expired else 1.0)
    with pytest.raises(ManagedStorageError, match="busy"):
        writer.read_tail(deadline=10.0)
    assert expired and not directory._locks

from __future__ import annotations

import os
import stat
import sys

import pytest

from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed storage")


@pytest.fixture
def directory(tmp_path):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True)
    try:
        yield root, owner
    finally:
        owner.close()


def test_append_and_same_inode_rotation_have_no_copy_peak(directory):
    root, owner = directory
    with owner.lock("events.lock", create=True):
        empty = owner.append_data("events", b"", expected=None, capacity=64)
        full = owner.append_data("events", b"x" * 64, expected=empty, capacity=64)
        with pytest.raises(ManagedStorageError, match="capacity"):
            owner.append_data("events", b"y", expected=full, capacity=64)
        rotated = owner.append_data("events", b"next\n", expected=full, capacity=64, truncate=True)
        assert empty.identity == full.identity == rotated.identity
        assert rotated.size == 5 and rotated.tail == b"next\n"
        assert {p.name for p in root.iterdir()} == {"events.lock", "events"}
        assert (root / "events").read_bytes() == b"next\n"
    assert not owner.cleanup_pending


@pytest.mark.parametrize("change", ["append", "truncate", "replace", "symlink"])
def test_stale_snapshot_never_changes_replaced_or_modified_target(directory, change):
    root, owner = directory
    with owner.lock("events.lock", create=True):
        original = owner.append_data("events", b"old\n", expected=None, capacity=64)
        target = root / "events"
        if change == "append":
            with target.open("ab") as stream:
                stream.write(b"external\n")
        elif change == "truncate":
            with target.open("wb"):
                pass
        else:
            target.rename(root / "old")
            if change == "replace":
                target.touch(mode=0o600)
            else:
                target.symlink_to(root / "old")
        before = target.read_bytes()
        with pytest.raises(ManagedStorageError):
            owner.append_data("events", b"new\n", expected=original, capacity=64)
        assert target.read_bytes() == before


@pytest.mark.parametrize("fault", ["partial", "zero", "interrupt", "truncate", "sync"])
def test_unknown_effect_is_not_replayed_and_close_only_syncs(directory, monkeypatch, fault):
    root, owner = directory
    with owner.lock("events.lock", create=True):
        original = owner.append_data("events", b"old\n", expected=None, capacity=64)
        native_write, native_sync, native_truncate = os.write, os.fsync, os.ftruncate
        writes = []

        def write(fd, value):
            writes.append(bytes(value))
            if fault == "partial":
                if len(writes) == 1:
                    return native_write(fd, value[:3])
                raise OSError("private native failure")
            if fault == "zero":
                return 0
            if fault == "interrupt":
                raise InterruptedError("private native failure")
            return native_write(fd, value)

        def sync(fd):
            if fault == "sync" and stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("private native failure")
            return native_sync(fd)

        def truncate(fd, size):
            native_truncate(fd, size)
            if fault == "truncate":
                raise OSError("lost truncate receipt")

        with monkeypatch.context() as patch:
            patch.setattr(os, "write", write)
            patch.setattr(os, "fsync", sync)
            patch.setattr(os, "ftruncate", truncate)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.append_data("events", b"new-event\n", expected=original,
                                  capacity=64, truncate=fault == "truncate")
            assert owner.cleanup_pending and len(owner._data_sync_pending) == 1
            with pytest.raises(ManagedStorageError, match="busy"):
                owner.append_data("events", b"new-event\n", expected=original, capacity=64)
        before = (root / "events").read_bytes()
        count = len(writes)
        failed_fd, = owner._data_sync_pending
    settled = []
    native_close = os.close

    def settle_sync(fd):
        native_sync(fd)
        if fd == failed_fd:
            settled.append("sync")

    def settle_close(fd):
        if fd == failed_fd:
            assert settled == ["sync"]
            settled.append("close")
        native_close(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda *args: pytest.fail("cleanup replayed body"))
        patch.setattr(os, "ftruncate", lambda *args: pytest.fail("cleanup replayed truncate"))
        patch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("retry sync")))
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.close()
        assert owner._data_sync_pending == {failed_fd} and owner.cleanup_pending
        assert os.fstat(failed_fd).st_ino == original.identity[1]
        patch.setattr(os, "fsync", settle_sync)
        patch.setattr(os, "close", settle_close)
        owner.close()
    assert settled == ["sync", "close"]
    assert len(writes) == count and not owner.cleanup_pending
    assert (root / "events").read_bytes() == before
    assert before == {"partial": b"old\nnew", "zero": b"old\n", "interrupt": b"old\n",
                      "truncate": b"", "sync": b"old\nnew-event\n"}[fault]


def test_snapshot_reads_only_bounded_tail(directory):
    root, owner = directory
    with owner.lock("events.lock", create=True):
        current = owner.append_data("events", b"a" * 16384, expected=None, capacity=65536)
        current = owner.append_data("events", b"b" * 16384, expected=current, capacity=65536)
        assert current.size == 32768 and current.tail == b"b" * 16384
        assert owner.data_snapshot("events", capacity=65536) == current


@pytest.mark.parametrize("capacity,payload", [(True, b"x"), (0, b"x"),
                                              (128 * 1024**2 + 1, b"x"),
                                              (65536, b"x" * 16385)],
                         ids=["bool", "zero", "too-large-cap", "too-large-record"])
def test_invalid_values_rejected_before_file_creation(directory, capacity, payload):
    root, owner = directory
    with owner.lock("events.lock", create=True):
        with pytest.raises(ManagedStorageError):
            owner.append_data("events", payload, expected=None, capacity=capacity)
    assert not (root / "events").exists()


def test_rotation_validates_encoded_bytes_before_truncating(directory):
    root, owner = directory
    with owner.lock("events.lock", create=True):
        original = owner.append_data("events", b"old\n", expected=None, capacity=8)
        with pytest.raises(ManagedStorageError, match="capacity"):
            owner.append_data("events", "你好啊".encode(), expected=original,
                              capacity=8, truncate=True)
        assert (root / "events").read_bytes() == b"old\n"


def test_snapshot_rejects_change_during_bounded_read(directory, monkeypatch):
    root, owner = directory
    with owner.lock("events.lock", create=True):
        owner.append_data("events", b"old\n", expected=None, capacity=64)
        native = os.pread

        def changed(fd, size, offset):
            result = native(fd, size, offset)
            with (root / "events").open("ab") as stream:
                stream.write(b"external\n")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(os, "pread", changed)
            with pytest.raises(ManagedStorageError, match="conflict"):
                owner.data_snapshot("events", capacity=64)
        assert (root / "events").read_bytes() == b"old\nexternal\n"


@pytest.mark.parametrize("operation", ["append", "snapshot"])
def test_unknown_close_never_touches_reused_fd(tmp_path, monkeypatch, operation):
    owner = PrivateManagedDirectory(tmp_path / "private", create=True)
    reused = []
    native_close = os.close

    def close(fd):
        if fd in owner._close_pending and fd != owner._fd and not reused:
            native_close(fd)
            replacement = os.open("/dev/null", os.O_RDONLY)
            reused.append(replacement)
            assert replacement == fd
            raise OSError("lost close receipt")
        assert fd not in reused, "retried close on reused fd"
        return native_close(fd)

    try:
        with owner.lock("events.lock", create=True):
            original = owner.append_data("events", b"old\n", expected=None, capacity=64)
            with monkeypatch.context() as patch:
                patch.setattr(os, "close", close)
                try:
                    raise RuntimeError("unrelated caller exception")
                except RuntimeError:
                    with pytest.raises(ManagedStorageError, match="unavailable"):
                        if operation == "append":
                            owner.append_data("events", b"event\n", expected=original, capacity=64)
                        else:
                            owner.data_snapshot("events", capacity=64)
            assert reused and owner.cleanup_pending and not owner._data_sync_pending
        for _ in range(2):
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.close()
            assert stat.S_ISCHR(os.fstat(reused[0]).st_mode)
    finally:
        for fd in reused:
            native_close(fd)


def test_no_lock_means_no_data_creation(directory):
    root, owner = directory
    with pytest.raises(ManagedStorageError, match="busy"):
        owner.append_data("events", b"event\n", expected=None, capacity=64)
    assert not tuple(root.iterdir())

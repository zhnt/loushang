import os
from contextlib import suppress
from dataclasses import replace

import pytest

from loushang.apphost.managed import _files
from loushang.apphost.managed._files import ManagedStorageError

from .test_managed_files import directory as directory
from .test_managed_files import pytestmark as pytestmark


def create(owner):
    with owner.lock("data.lock", create=True):
        return owner.append_data("stdout", b"original", expected=None, capacity=4096)


def test_isolation_keeps_original_inode_and_bytes(directory):
    root, owner = directory
    snapshot = create(owner)
    with owner.lock("data.lock"):
        isolated = owner.isolate_data("stdout", "removed-first", expected=snapshot, capacity=4096)
    assert isolated.identity == snapshot.identity and isolated.tail == b"original"
    assert not (root / "stdout").exists()
    assert (root / "removed-first").read_bytes() == b"original"
    assert not owner.cleanup_pending


def test_isolation_never_overwrites_existing_target(directory):
    root, owner = directory
    snapshot = create(owner)
    target = root / "removed-first"
    target.write_bytes(b"keep")
    target.chmod(0o600)
    with owner.lock("data.lock"):
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.isolate_data("stdout", "removed-first", expected=snapshot, capacity=4096)
    assert target.read_bytes() == b"keep" and (root / "stdout").read_bytes() == b"original"


@pytest.mark.parametrize("change", ["missing", "snapshot", "symlink", "hardlink"])
def test_bad_identity_does_not_move_file(directory, change):
    root, owner = directory
    snapshot = create(owner)
    if change == "missing":
        (root / "stdout").unlink()
    elif change == "snapshot":
        snapshot = replace(snapshot, size=snapshot.size + 1)
    elif change == "symlink":
        (root / "stdout").rename(root / "held")
        (root / "stdout").symlink_to(root / "held")
    else:
        os.link(root / "stdout", root / "held")
    with owner.lock("data.lock"):
        with pytest.raises(ManagedStorageError):
            owner.isolate_data("stdout", "removed-first", expected=snapshot, capacity=4096)
    assert not (root / "removed-first").exists()


def test_unknown_rename_is_not_replayed_by_close(directory, monkeypatch):
    root, owner = directory
    snapshot = create(owner)
    original = _files._rename_data_noreplace
    calls = []

    def rename(*args):
        calls.append(args)
        original(*args)
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(_files, "_rename_data_noreplace", rename)
    with owner.lock("data.lock"):
        with pytest.raises(ManagedStorageError):
            owner.isolate_data("stdout", "removed-first", expected=snapshot, capacity=4096)
    (root / "stdout").write_bytes(b"replacement")
    owner.close()
    assert len(calls) == 1
    assert (root / "stdout").read_bytes() == b"replacement"
    assert (root / "removed-first").read_bytes() == b"original"


def test_sync_failure_close_only_retries_sync(directory, monkeypatch):
    root, owner = directory
    snapshot = create(owner)
    with owner.lock("data.lock"):
        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("injected sync")))
            with pytest.raises(ManagedStorageError):
                owner.isolate_data("stdout", "removed-first", expected=snapshot, capacity=4096)
    assert owner.cleanup_pending
    (root / "stdout").write_bytes(b"replacement")
    owner.close()
    assert (root / "stdout").read_bytes() == b"replacement"
    assert (root / "removed-first").read_bytes() == b"original"


@pytest.mark.parametrize("change", ["replace", "modify"])
def test_sync_boundary_mutation_cannot_return_success(directory, monkeypatch, change):
    root, owner = directory
    snapshot = create(owner)
    original = os.fsync
    target = root / "removed-first"

    def sync(fd):
        original(fd)
        if change == "replace":
            target.rename(root / "held-original")
        target.write_bytes(b"changed")
        target.chmod(0o600)

    with owner.lock("data.lock"):
        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", sync)
            with pytest.raises(ManagedStorageError, match="conflict"):
                owner.isolate_data("stdout", "removed-first", expected=snapshot, capacity=4096)
    assert owner._data_failed
    owner.close()
    assert target.read_bytes() == b"changed"
    if change == "replace":
        assert (root / "held-original").read_bytes() == b"original"


def test_source_replacement_before_rename_preserves_both_files(directory, monkeypatch):
    root, owner = directory
    snapshot = create(owner)
    original = _files._rename_data_noreplace

    def rename(*args):
        (root / "stdout").rename(root / "held-original")
        (root / "stdout").write_bytes(b"replacement")
        (root / "stdout").chmod(0o600)
        original(*args)

    with owner.lock("data.lock"):
        with monkeypatch.context() as patch:
            patch.setattr(_files, "_rename_data_noreplace", rename)
            with pytest.raises(ManagedStorageError, match="conflict"):
                owner.isolate_data("stdout", "removed-first", expected=snapshot, capacity=4096)
    owner.close()
    assert (root / "held-original").read_bytes() == b"original"
    assert (root / "removed-first").read_bytes() == b"replacement"


def test_unknown_data_close_does_not_close_a_reused_descriptor(tmp_path, monkeypatch):
    root = tmp_path / "private"
    owner = _files.PrivateManagedDirectory(root, create=True)
    snapshot = create(owner)
    original_close = os.close
    reused = []
    attempted = []

    def close_then_lose_receipt(fd):
        metadata = os.fstat(fd)
        attempted.append(fd)
        original_close(fd)
        if not reused and (metadata.st_dev, metadata.st_ino) == snapshot.identity:
            # The native close really happened; its numeric descriptor now
            # belongs to a different, test-owned file before the error returns.
            replacement = os.open(root / "unrelated", os.O_CREAT | os.O_RDWR, 0o600)
            reused.append(replacement)
            assert replacement == fd
            raise OSError("injected lost close receipt")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "close", close_then_lose_receipt)
            with owner.lock("data.lock"):
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    owner.isolate_data("stdout", "removed-first", expected=snapshot, capacity=4096)
            assert owner.cleanup_pending and owner._data_failed
            for _ in range(2):
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    owner.close()
            assert attempted.count(reused[0]) == 1
            os.write(reused[0], b"still open")
        assert (root / "unrelated").read_bytes() == b"still open"
        assert (root / "removed-first").read_bytes() == b"original"
        assert not (root / "stdout").exists()
    finally:
        for fd in reused:
            original_close(fd)
        # Unknown receipts remain unknown; only settle the other original fds.
        with suppress(ManagedStorageError):
            owner.close()

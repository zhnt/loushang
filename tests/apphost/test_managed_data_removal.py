import asyncio
import os
from contextlib import suppress
from dataclasses import replace

import pytest

from loushang.apphost.managed import _files
from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory

from .test_managed_data_isolation import create
from .test_managed_files import pytestmark as pytestmark


@pytest.fixture
def directory(tmp_path):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True)
    try:
        yield root, owner
    finally:
        try:
            owner.close()
        except ManagedStorageError:
            # Unknown deletion stays charged, but these tests never inject an
            # unknown close: all originally owned descriptors must be released.
            assert owner._removals and owner._fd is None
            assert not owner._close_pending and not owner._uncertain_closes


def test_original_removal_completes_and_repeated_use_has_no_native_effect(directory, monkeypatch):
    root, owner = directory
    snapshot = create(owner)
    removal = owner.prepare_data_removal("stdout", "removed-first", expected=snapshot, capacity=4096)
    assert owner.cleanup_pending and (root / "stdout").exists()
    with owner.lock("data.lock"):
        owner.remove_data(removal)
    assert removal.phase == "complete" and not owner.cleanup_pending
    assert not (root / "stdout").exists() and not (root / "removed-first").exists()

    def unexpected(*args, **kwargs):
        raise AssertionError("completed removal must not replay native work")
    monkeypatch.setattr(_files.os, "unlink", unexpected)
    owner.remove_data(removal)


def test_sync_retry_never_unlinks_replacement(directory, monkeypatch):
    root, owner = directory
    snapshot = create(owner)
    removal = owner.prepare_data_removal("stdout", "removed-first", expected=snapshot, capacity=4096)
    original_sync = owner._sync_parent
    failed = False

    def fail_once(parent):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("sync unavailable")
        return original_sync(parent)

    monkeypatch.setattr(owner, "_sync_parent", fail_once)
    with owner.lock("data.lock"):
        with pytest.raises(ManagedStorageError):
            owner.remove_data(removal)
        assert removal.phase == "unlinked"
        # Even after releasing the lock, close must preserve retry resources.
    with pytest.raises(ManagedStorageError, match="busy"):
        owner.close()
    assert not owner._closing and removal.fd in owner._close_pending
    with owner.lock("data.lock"):
        (root / "removed-first").write_bytes(b"replacement")
        owner.remove_data(removal)
    assert (root / "removed-first").read_bytes() == b"replacement"
    assert removal.phase == "complete"


def test_unknown_unlink_retains_debt_and_never_replays(directory, monkeypatch):
    root, owner = directory
    snapshot = create(owner)
    removal = owner.prepare_data_removal("stdout", "removed-first", expected=snapshot, capacity=4096)
    original = os.unlink
    calls = []

    def lost_receipt(name, *args, **kwargs):
        calls.append(name)
        original(name, *args, **kwargs)
        raise OSError("lost unlink receipt")

    with owner.lock("data.lock"):
        with monkeypatch.context() as patch:
            patch.setattr(_files.os, "unlink", lost_receipt)
            with pytest.raises(ManagedStorageError):
                owner.remove_data(removal)
        (root / "removed-first").write_bytes(b"replacement")
        with pytest.raises(ManagedStorageError):
            owner.remove_data(removal)
    assert calls == ["removed-first"]
    assert removal.phase == "unlink_unknown" and owner.cleanup_pending
    assert (root / "removed-first").read_bytes() == b"replacement"


def test_event_loop_rejection_precedes_mutex_and_native_effects(directory, monkeypatch):
    root, owner = directory
    snapshot = create(owner)
    removal = owner.prepare_data_removal("stdout", "removed-first", expected=snapshot, capacity=4096)

    class UnavailableMutex:
        def __enter__(self):
            raise AssertionError("event loop must not wait for the native mutex")

        def __exit__(self, *args):
            pass

    async def run():
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.prepare_data_removal("stderr", "removed-second", expected=snapshot, capacity=4096)
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.remove_data(removal)

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_mutex", UnavailableMutex())
        asyncio.run(run())
    assert removal.phase == "new" and (root / "stdout").read_bytes() == b"original"
    assert len(owner._removals) == 1
    with owner.lock("data.lock"):
        owner.remove_data(removal)


@pytest.mark.parametrize("opened", [False, True])
def test_abandon_releases_handles_but_never_completes_removal(directory, opened):
    root, owner = directory
    snapshot = create(owner)
    if opened:
        snapshot = replace(snapshot, size=snapshot.size + 1)
    removal = owner.prepare_data_removal("stdout", "removed-first", expected=snapshot, capacity=4096)
    if opened:
        with owner.lock("data.lock"):
            with pytest.raises(ManagedStorageError, match="conflict"):
                owner.remove_data(removal)
    phase = removal.phase
    owner.abandon_data_removal(removal)
    assert removal.phase == phase and removal.abandoned
    with pytest.raises(ManagedStorageError, match="unavailable"):
        owner.remove_data(removal)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        owner.close()
    assert owner._fd is None and not owner._close_pending
    assert owner.cleanup_pending and removal.phase != "complete"
    assert (root / "stdout").read_bytes() == b"original"


def test_isolated_content_change_is_not_deleted_on_retry(directory, monkeypatch):
    root, owner = directory
    snapshot = create(owner)
    removal = owner.prepare_data_removal("stdout", "removed-first", expected=snapshot, capacity=4096)
    original_snapshot = owner._data_snapshot
    calls = 0

    def transient(*args):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("read temporarily unavailable")
        return original_snapshot(*args)

    with owner.lock("data.lock"):
        with monkeypatch.context() as patch:
            patch.setattr(owner, "_data_snapshot", transient)
            with pytest.raises(ManagedStorageError):
                owner.remove_data(removal)
        assert removal.phase == "isolated"
        (root / "removed-first").write_bytes(b"changed original inode")
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.remove_data(removal)
    owner.abandon_data_removal(removal)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        owner.close()
    assert (root / "removed-first").read_bytes() == b"changed original inode"
    assert removal.phase == "isolated" and owner.cleanup_pending


def test_abandoned_unknown_close_never_closes_reused_fd(tmp_path, monkeypatch):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True)
    snapshot = create(owner)
    removal = owner.prepare_data_removal(
        "stdout", "removed-first", expected=replace(snapshot, size=snapshot.size + 1), capacity=4096,
    )
    with owner.lock("data.lock"):
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.remove_data(removal)
    original_fd = removal.fd
    assert original_fd is not None
    owner.abandon_data_removal(removal)
    original_close = os.close
    reused = []
    attempts = []

    def lost_close(fd):
        attempts.append(fd)
        original_close(fd)
        if fd == original_fd and not reused:
            replacement = os.open(root / "unrelated", os.O_CREAT | os.O_RDWR, 0o600)
            if replacement != fd:
                os.dup2(replacement, fd)
                original_close(replacement)
            reused.append(fd)
            raise OSError("original close succeeded but receipt was lost")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "close", lost_close)
            for _ in range(2):
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    owner.close()
            assert attempts.count(original_fd) == 1
            assert removal.phase == "opened" and removal.abandoned
            assert owner.cleanup_pending and original_fd in owner._uncertain_closes
            os.write(reused[0], b"test-owned descriptor remains open")
        assert (root / "unrelated").read_bytes() == b"test-owned descriptor remains open"
        assert (root / "stdout").read_bytes() == b"original"
    finally:
        for fd in reused:
            original_close(fd)
        with suppress(ManagedStorageError):
            owner.close()

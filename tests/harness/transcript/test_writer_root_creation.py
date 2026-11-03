from __future__ import annotations

import os
import stat
import sys

import pytest

from loushang.harness.journal import _directory_lease as module
from loushang.harness.transcript.writer_lease import (
    TranscriptWriterError,
    TranscriptWriterLease,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux retained writer")


def identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def test_expected_root_and_parent_are_bound_before_writer_namespace_creation(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    owner = TranscriptWriterLease(root, "coding", "one", expected_root_identity=identity(root),
                                   expected_parent_identity=identity(tmp_path))
    try:
        owner.acquire()
        assert set(owner._fds) == {"parent", "root", "directory", "lock"}
        owner.check(product_id="coding", conversation_id="one")
        assert stat.S_IMODE(root.stat().st_mode) == 0o755
    finally:
        owner.close()
    assert not owner.cleanup_pending


@pytest.mark.parametrize("replacement", ["root", "parent", "symlink", "missing"])
def test_expected_identity_rejects_replacement_without_creating_writer_files(tmp_path, replacement):
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    root = data / "sessions"
    root.mkdir(mode=0o700)
    owner = TranscriptWriterLease(root, "coding", "one", expected_root_identity=identity(root),
                                   expected_parent_identity=identity(data))
    moved = tmp_path / "original"
    if replacement == "parent":
        data.rename(moved)
        data.mkdir(mode=0o700)
        (moved / "sessions").rename(root)
    else:
        root.rename(moved)
        if replacement == "root":
            root.mkdir(mode=0o700)
        elif replacement == "symlink":
            root.symlink_to(moved, target_is_directory=True)
    before = {str(p): (p.lstat().st_ino, p.lstat().st_mode) for p in tmp_path.rglob("*")}
    try:
        with pytest.raises(TranscriptWriterError, match="conflict|unavailable"):
            owner.acquire()
    finally:
        owner.close()
    assert before == {str(p): (p.lstat().st_ino, p.lstat().st_mode) for p in tmp_path.rglob("*")}


def test_expected_parent_is_checked_during_held_lifetime(tmp_path):
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    root = data / "sessions"
    root.mkdir(mode=0o700)
    owner = TranscriptWriterLease(root, "coding", "one", expected_root_identity=identity(root),
                                   expected_parent_identity=identity(data))
    try:
        owner.acquire()
        moved = tmp_path / "original"
        data.rename(moved)
        data.mkdir(mode=0o700)
        (moved / "sessions").rename(root)
        with pytest.raises(TranscriptWriterError, match="conflict"):
            owner.check(product_id="coding", conversation_id="one")
    finally:
        owner.close()


@pytest.mark.parametrize("options", [
    {"expected_root_identity": (True, 1)}, {"expected_root_identity": (1, 0)},
    {"expected_root_identity": [1, 2]}, {"expected_root_identity": (1, 2**64)},
    {"expected_parent_identity": (1, 2)},
    {"create_root": True, "expected_root_identity": (1, 2)},
])
def test_expected_identity_cannot_grant_root_creation_or_accept_invalid_shape(tmp_path, options):
    with pytest.raises(TranscriptWriterError, match="invalid"):
        TranscriptWriterLease(tmp_path / "missing", "coding", "one", **options)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("mask", [0, 0o022, 0o077])
def test_explicit_create_private_parents_and_original_three_fds(tmp_path, mask):
    root = tmp_path / "new" / "sessions"
    owner = TranscriptWriterLease(root, "coding", "one", create_root=True)
    old_mask = os.umask(mask)
    try:
        owner.acquire()
        assert set(owner._fds) == {"root", "directory", "lock"}
        assert not owner._sync_pending and not owner._unknown
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(root.parent.stat().st_mode) == 0o700
        owner.check(product_id="coding", conversation_id="one")
    finally:
        os.umask(old_mask)
        owner.close()
    assert not owner.cleanup_pending
    assert root.is_dir()  # Closing a preparation never removes created storage.


def test_existing_safe_root_mode_unchanged(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    owner = TranscriptWriterLease(root, "coding", "one", create_root=True)
    try:
        owner.acquire()
        assert stat.S_IMODE(root.stat().st_mode) == 0o755
    finally:
        owner.close()


@pytest.mark.parametrize("position", ["parent", "root"])
def test_creation_never_follows_symlinks(tmp_path, position):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    root = link / "sessions" if position == "parent" else link
    owner = TranscriptWriterLease(root, "coding", "one", create_root=True)
    try:
        with pytest.raises(TranscriptWriterError, match="unavailable|conflict"):
            owner.acquire()
    finally:
        owner.close()
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("exists", [False, True])
def test_failed_parent_sync_retained_and_close_only_retries_sync(tmp_path, monkeypatch, exists):
    root = tmp_path / "sessions"
    if exists:
        root.mkdir(mode=0o700)
    owner = TranscriptWriterLease(root, "coding", "one", create_root=True)
    sync, mkdir = os.fsync, os.mkdir
    calls, failed = [], []
    parent_identity = tmp_path.stat()

    def fail_sync(fd):
        if os.path.samestat(os.fstat(fd), parent_identity):
            failed.append(fd)
            raise OSError("injected sync failure")
        return sync(fd)

    def record_mkdir(*args, **kwargs):
        calls.append(args[0])
        return mkdir(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fsync", fail_sync)
        patch.setattr(module.os, "mkdir", record_mkdir)
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            owner.acquire()
        count = len(calls)
        assert root.is_dir() and not (root / ".transcript-writers").exists()
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            owner.close()
        assert owner.cleanup_pending and len(calls) == count
        assert len(failed) == 2 and failed[0] == failed[1]
        assert os.path.samestat(os.fstat(failed[0]), parent_identity)
        patch.setattr(module.os, "fsync", sync)
        owner.close()
        assert len(calls) == count and not owner.cleanup_pending
    assert root.is_dir()


def test_replaced_child_at_sync_rejected_before_writer_admission(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    saved = tmp_path / "saved"
    owner = TranscriptWriterLease(root, "coding", "one", create_root=True)
    sync = os.fsync
    parent_identity = tmp_path.stat()

    def replace_at_sync(fd):
        if os.path.samestat(os.fstat(fd), parent_identity) and not saved.exists():
            root.rename(saved)
            root.mkdir(mode=0o700)
        return sync(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "fsync", replace_at_sync)
            with pytest.raises(TranscriptWriterError, match="conflict"):
                owner.acquire()
        with pytest.raises(TranscriptWriterError, match="closed"):
            owner._borrow_file_io(root=root, product_id="coding", conversation_id="one")
        assert list(root.iterdir()) == list(saved.iterdir()) == []
    finally:
        owner.close()


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_ancestor_unknown_close_never_admits_or_retries_reused_fd(tmp_path, monkeypatch, error):
    root = tmp_path / "sessions"
    owner = TranscriptWriterLease(root, "coding", "one", create_root=True)
    close = os.close
    replacement, calls = [], []

    def fail_after_close(fd):
        calls.append(fd)
        close(fd)
        if not replacement:
            reused = os.open("/dev/null", os.O_RDONLY)
            assert reused == fd
            replacement.append(fd)
            raise error("lost close receipt")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "close", fail_after_close)
            with pytest.raises(TranscriptWriterError, match="unavailable"):
                owner.acquire()
            assert not owner._held and not (root / ".transcript-writers").exists()
            with pytest.raises(TranscriptWriterError, match="closed"):
                owner._borrow_file_io(root=root, product_id="coding", conversation_id="one")
            for _ in range(2):
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    owner.close()
            assert calls.count(replacement[0]) == 1
            assert len(owner._fds) == len(owner._unknown) == 1
            os.fstat(replacement[0])
    finally:
        for fd in replacement:
            close(fd)

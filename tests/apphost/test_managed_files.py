from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.apphost.managed._files import (
    MAX_RECORD_BYTES,
    ManagedStorageError,
    PrivateManagedDirectory,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed storage")


@pytest.fixture
def directory(tmp_path):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True)
    try:
        yield root, owner
    finally:
        owner.close()


def test_lookup_missing_root_is_read_only(tmp_path):
    with pytest.raises(ManagedStorageError, match="not_found"):
        PrivateManagedDirectory(tmp_path / "missing")
    assert tuple(tmp_path.iterdir()) == ()


def test_private_modes_bounded_cas_and_stable_lock(directory):
    root, owner = directory
    assert root.stat().st_mode & 0o777 == 0o700
    with owner.lock("lifecycle.lock", create=True):
        assert owner.read("record.json") is None
        owner.write("record.json", b'{"phase":"provisional"}', expected=None)
        before = owner.read("record.json")
        assert before is not None
        owner.write("record.json", b'{"phase":"committed"}', expected=before)
        after = owner.read("record.json")
        assert after is not None and after.identity != before.identity
        assert b"committed" in after.content
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.write("record.json", b"stale", expected=before)
        assert owner.read("record.json") == after
    identity = (root / "lifecycle.lock").stat().st_ino
    with owner.lock("lifecycle.lock"):
        assert (root / "lifecycle.lock").stat().st_ino == identity
    assert (root / "record.json").stat().st_mode & 0o777 == 0o600
    assert (root / "lifecycle.lock").stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in root.iterdir()) == ["lifecycle.lock", "record.json"]


def test_stale_snapshot_detects_in_place_update(directory):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        owner.write("state.json", b"before", expected=None)
        snapshot = owner.read("state.json")
        (root / "state.json").write_bytes(b"changed")
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.write("state.json", b"bad", expected=snapshot)


@pytest.mark.parametrize("name", ["../escape", "/absolute", ".", "..", "x/y",
                                 "x\0y", "x\ny", "a" * 97, 12])
def test_invalid_names_are_rejected_without_side_effect(directory, name):
    root, owner = directory
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        owner.write(name, b"data", expected=None)
    assert tuple(root.iterdir()) == ()


def test_symlink_hardlink_and_nonprivate_file_rejected(directory, tmp_path):
    root, owner = directory
    target = tmp_path / "outside"
    target.write_bytes(b"do not alter")
    target.chmod(0o600)
    (root / "link").symlink_to(target)
    with pytest.raises(ManagedStorageError):
        owner.read("link")
    os.link(target, root / "hardlink")
    with pytest.raises(ManagedStorageError):
        owner.read("hardlink")
    unsafe = root / "unsafe"
    unsafe.write_bytes(b"unsafe")
    unsafe.chmod(0o644)
    with pytest.raises(ManagedStorageError):
        owner.read("unsafe")
    assert target.read_bytes() == b"do not alter"


def test_fifo_does_not_block_file_admission(directory):
    root, owner = directory
    os.mkfifo(root / "fifo", 0o600)
    with pytest.raises(ManagedStorageError):
        owner.read("fifo")


def test_insecure_or_symlink_root_is_not_repaired(tmp_path):
    root = tmp_path / "unsafe"
    root.mkdir(mode=0o755)
    with pytest.raises(ManagedStorageError):
        PrivateManagedDirectory(root, create=True)
    assert root.stat().st_mode & 0o777 == 0o755
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ManagedStorageError):
        PrivateManagedDirectory(link)


def test_root_replacement_fences_later_operations(directory, tmp_path):
    root, owner = directory
    root.rename(tmp_path / "old")
    root.mkdir(mode=0o700)
    with pytest.raises(ManagedStorageError, match="conflict"):
        owner.write("state", b"bad", expected=None)
    assert tuple(root.iterdir()) == ()


def test_locked_file_replacement_is_not_silently_accepted(directory):
    root, owner = directory
    with pytest.raises(ManagedStorageError, match="conflict"):
        with owner.lock("control.lock", create=True):
            replacement = root / "replacement"
            replacement.write_bytes(b"")
            replacement.chmod(0o600)
            os.replace(replacement, root / "control.lock")
    assert (root / "control.lock").exists()


def test_oversize_write_or_read_is_bounded(directory):
    root, owner = directory
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        owner.write("state", b"x" * (MAX_RECORD_BYTES + 1), expected=None)
    assert not (root / "state").exists()
    large = root / "large"
    large.write_bytes(b"x" * (MAX_RECORD_BYTES + 1))
    large.chmod(0o600)
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        owner.read("large")


def test_write_failure_preserves_destination_and_removes_only_owned_temp(directory, monkeypatch):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        owner.write("record", b"original", expected=None)
        before = owner.read("record")
        original_write = os.write

        def fail_write(fd, data):
            original_write(fd, data[:1])
            raise OSError("injected error contains private details")

        monkeypatch.setattr(os, "write", fail_write)
        with pytest.raises(ManagedStorageError, match="^managed_storage_unavailable$"):
            owner.write("record", b"new", expected=before)
        assert owner.read("record") == before
    assert sorted(p.name for p in root.iterdir()) == ["control.lock", "record"]


def test_close_is_idempotent_and_never_deletes_storage(directory):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        owner.write("state", b"retained", expected=None)
    owner.close()
    owner.close()
    with pytest.raises(ManagedStorageError, match="closed"):
        owner.read("state")
    assert (root / "state").read_bytes() == b"retained"
    assert (root / "control.lock").exists()


def test_real_second_process_cannot_acquire_stable_lock(directory):
    root, owner = directory
    script = """
import sys
from pathlib import Path
from loushang.apphost.managed._files import PrivateManagedDirectory, ManagedStorageError
directory = PrivateManagedDirectory(Path(sys.argv[1]))
try:
    with directory.lock('control.lock'):
        print('acquired')
except ManagedStorageError as error:
    print(error.code)
finally:
    directory.close()
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    with owner.lock("control.lock", create=True):
        first = subprocess.run([sys.executable, "-c", script, str(root)], env=env,
                               capture_output=True, text=True, timeout=10)
        assert first.returncode == 0, first.stderr
        assert first.stdout.strip() == "busy"
    second = subprocess.run([sys.executable, "-c", script, str(root)], env=env,
                            capture_output=True, text=True, timeout=10)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "acquired"


def test_ancestor_swap_before_mkdir_never_follows_replacement(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    original_mkdir = os.mkdir

    def swap_then_mkdir(path, mode=0o777, *, dir_fd=None):
        if path == "private":
            parent.rename(tmp_path / "retained-parent")
            parent.symlink_to(outside, target_is_directory=True)
        return original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", swap_then_mkdir)
    with pytest.raises(ManagedStorageError):
        PrivateManagedDirectory(parent / "private", create=True)
    assert tuple(outside.iterdir()) == ()


def test_writes_require_lock_and_cannot_replace_lock(directory):
    root, owner = directory
    with pytest.raises(ManagedStorageError, match="busy"):
        owner.write("record", b"unlocked", expected=None)
    with owner.lock("control.lock", create=True):
        snapshot = owner.read("control.lock")
        with pytest.raises(ManagedStorageError, match="invalid_record"):
            owner.write("control.lock", b"", expected=snapshot)
        assert owner.read("control.lock") == snapshot
    assert not (root / "record").exists()


def test_replaced_lock_fences_write_before_publication(directory):
    root, owner = directory
    with pytest.raises(ManagedStorageError, match="conflict"):
        with owner.lock("control.lock", create=True):
            owner.write("record", b"original", expected=None)
            snapshot = owner.read("record")
            replacement = root / "replacement"
            replacement.write_bytes(b"")
            replacement.chmod(0o600)
            os.replace(replacement, root / "control.lock")
            script = """
import sys
from pathlib import Path
from loushang.apphost.managed._files import PrivateManagedDirectory
owner = PrivateManagedDirectory(Path(sys.argv[1]))
with owner.lock('control.lock'):
    print('acquired', flush=True)
    sys.stdin.readline()
owner.close()
"""
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
            with subprocess.Popen([sys.executable, "-c", script, str(root)], env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as child:
                try:
                    import select

                    assert select.select([child.stdout], [], [], 10)[0]
                    assert child.stdout.readline().strip() == "acquired"
                    with pytest.raises(ManagedStorageError, match="conflict"):
                        owner.write("record", b"stale", expected=snapshot)
                    assert (root / "record").read_bytes() == b"original"
                finally:
                    child.communicate("release\n", timeout=10)
                assert child.returncode == 0


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_fsync_failure_has_explicit_pre_or_post_publication_outcome(directory, monkeypatch, stage):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        owner.write("record", b"original", expected=None)
        before = owner.read("record")
        original_fsync = os.fsync
        count = 0

        def fail_stage(fd):
            nonlocal count
            count += 1
            if count == stage:
                raise OSError("private native details")
            original_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_stage)
            with pytest.raises(ManagedStorageError, match="^managed_storage_unavailable$"):
                owner.write("record", b"new", expected=before)
        assert (root / "record").read_bytes() == (b"new" if stage == 3 else b"original")
        assert not owner.cleanup_pending
        assert sorted(p.name for p in root.iterdir()) == ["control.lock", "record"]


def test_replace_failure_cleans_temporary_and_preserves_record(directory, monkeypatch):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        owner.write("record", b"original", expected=None)
        before = owner.read("record")

        def fail_replace(*args, **kwargs):
            raise OSError("replace failed")

        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.write("record", b"new", expected=before)
        assert owner.read("record") == before
        assert not owner.cleanup_pending
        assert sorted(p.name for p in root.iterdir()) == ["control.lock", "record"]


def test_cancel_and_close_failure_preserve_cancel_and_attempt_unlink(directory, monkeypatch):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        original_close = os.close
        temporary_fd = None
        cancellation = KeyboardInterrupt("original cancellation")

        def cancel_write(fd, content):
            nonlocal temporary_fd
            temporary_fd = fd
            raise cancellation

        def close_then_fail(fd):
            original_close(fd)
            if fd == temporary_fd:
                raise OSError("uncertain close")

        with monkeypatch.context() as patch:
            patch.setattr(os, "write", cancel_write)
            patch.setattr(os, "close", close_then_fail)
            with pytest.raises(KeyboardInterrupt) as caught:
                owner.write("record", b"new", expected=None)
        assert caught.value is cancellation
        assert "managed_record_cleanup_incomplete" in caught.value.__notes__
        assert not owner.cleanup_pending
        assert sorted(p.name for p in root.iterdir()) == ["control.lock"]


def test_failed_cleanup_retains_owned_debt_until_close(directory, monkeypatch):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        def fail_write(fd, content):
            raise OSError("primary private failure")

        def fail_unlink(*args, **kwargs):
            raise OSError("cleanup private failure")

        with monkeypatch.context() as patch:
            patch.setattr(os, "write", fail_write)
            patch.setattr(os, "unlink", fail_unlink)
            with pytest.raises(ManagedStorageError) as caught:
                owner.write("record", b"new", expected=None)
            assert str(caught.value) == "managed_storage_unavailable"
            assert caught.value.__notes__ == ["managed_storage_cleanup_incomplete"]
            assert owner.cleanup_pending
            with pytest.raises(ManagedStorageError, match="busy"):
                owner.write("other", b"new", expected=None)
    owner.close()
    assert not owner.cleanup_pending
    assert sorted(p.name for p in root.iterdir()) == ["control.lock"]


def test_cleanup_sync_debt_blocks_write_and_retry_never_unlinks_replacement(directory, monkeypatch):
    root, owner = directory
    with owner.lock("control.lock", create=True):
        original_fsync = os.fsync
        original_unlink = os.unlink
        unlinked = None

        def fail_write(fd, content):
            raise OSError("primary write failure")

        def record_unlink(name, **kwargs):
            nonlocal unlinked
            original_unlink(name, **kwargs)
            unlinked = name

        def fail_cleanup_sync(fd):
            if unlinked is not None:
                raise OSError("cleanup sync failure")
            original_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "write", fail_write)
            patch.setattr(os, "unlink", record_unlink)
            patch.setattr(os, "fsync", fail_cleanup_sync)
            with pytest.raises(ManagedStorageError) as caught:
                owner.write("record", b"new", expected=None)
            assert str(caught.value) == "managed_storage_unavailable"
            assert owner.cleanup_pending
            assert sorted(p.name for p in root.iterdir()) == ["control.lock"]
            with pytest.raises(ManagedStorageError, match="busy"):
                owner.write("other", b"new", expected=None)
        assert unlinked is not None
        replacement = root / unlinked
        replacement.write_bytes(b"not ours")
        replacement.chmod(0o600)
    synced = []

    def track_sync(fd):
        synced.append(fd)
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", track_sync)
    owner.close()
    assert synced
    assert not owner.cleanup_pending
    assert replacement.read_bytes() == b"not ours"

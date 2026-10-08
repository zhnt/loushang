from __future__ import annotations

import os
import selectors
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


@pytest.mark.parametrize("parents", [False, True])
def test_exclusive_directory_creation_never_adopts_existing_leaf(tmp_path, parents):
    root = tmp_path / "new"
    first = PrivateManagedDirectory(root, create=True, create_parents=parents, exclusive_create=True)
    first.close()
    before = root.stat()
    contender = PrivateManagedDirectory(root, create=True, create_parents=parents,
                                        exclusive_create=True, defer_open=True)
    try:
        with pytest.raises(ManagedStorageError, match="conflict"):
            contender.open()
        assert not contender._opened
        with pytest.raises(ManagedStorageError, match="closed"):
            contender.open()
    finally:
        contender.close()
    assert root.stat() == before and not tuple(root.iterdir())


@pytest.mark.parametrize("value", [True, 1, "yes"])
def test_exclusive_creation_requires_explicit_create_without_io(tmp_path, value):
    with pytest.raises(ManagedStorageError):
        PrivateManagedDirectory(tmp_path / "new", exclusive_create=value)
    assert not tuple(tmp_path.iterdir())


def test_exclusive_lock_creation_preserves_existing_lock(directory):
    root, owner = directory
    with owner.lock("first.lock", create=True, exclusive_create=True):
        original = (root / "first.lock").stat()
    with owner.lock("first.lock"):
        assert (root / "first.lock").stat() == original
    with pytest.raises(ManagedStorageError, match="conflict"):
        with owner.lock("first.lock", create=True, exclusive_create=True):
            pytest.fail("existing lock was adopted")
    assert (root / "first.lock").stat() == original
    assert owner.cleanup_pending
    owner.close()
    assert not owner.cleanup_pending and (root / "first.lock").exists()


@pytest.mark.parametrize("kind", ["directory", "lock"])
def test_exclusive_creation_lost_mkdir_or_open_receipt_never_replays(tmp_path, monkeypatch, kind):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True, exclusive_create=True, defer_open=True)
    if kind == "lock":
        owner.open()
    native_call = os.mkdir if kind == "directory" else os.open
    calls = []

    def lose_receipt(name, *args, **kwargs):
        result = native_call(name, *args, **kwargs)
        if name == (root.name if kind == "directory" else "first.lock"):
            calls.append(name)
            if kind == "lock":
                # Model a syscall wrapper that settles its descriptor but
                # loses publication of the successful file creation.
                os.close(result)
            raise OSError("lost creation receipt")
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "mkdir" if kind == "directory" else "open", lose_receipt)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                if kind == "directory":
                    owner.open()
                else:
                    with owner.lock("first.lock", create=True, exclusive_create=True):
                        pytest.fail("lost receipt was delivered")
        assert owner.cleanup_pending
        target = root if kind == "directory" else root / "first.lock"
        original = target.stat()
        owner.close()
        assert not owner.cleanup_pending and target.stat() == original
        assert calls == [target.name]
    finally:
        owner.close()


@pytest.mark.parametrize("kind", ["directory", "lock"])
def test_exclusive_creation_failed_sync_retains_original_parent(tmp_path, monkeypatch, kind):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True, exclusive_create=True, defer_open=True)
    if kind == "lock":
        owner.open()
    fsync = os.fsync
    retained = []

    def fail(fd):
        retained.append(fd)
        raise OSError("sync unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                if kind == "directory":
                    owner.open()
                else:
                    with owner.lock("first.lock", create=True, exclusive_create=True):
                        pytest.fail("unsynced lock delivered")
            assert owner.cleanup_pending
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.close()
            assert retained[0] == retained[-1]
        synced = []

        def sync(fd):
            synced.append(fd)
            return fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", sync)
            owner.close()
        assert synced == [retained[0]] and not owner.cleanup_pending
        assert root.exists()
        if kind == "lock":
            assert (root / "first.lock").exists()
    finally:
        owner.close()


@pytest.mark.parametrize("kind", ["directory", "lock"])
def test_two_real_processes_cannot_both_claim_exclusive_creation(tmp_path, kind):
    root = tmp_path / "private"
    if kind == "lock":
        root.mkdir(mode=0o700)
    script = """
import os
import sys
from pathlib import Path
from loushang.apphost.managed._files import PrivateManagedDirectory, ManagedStorageError
root, kind, gate = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
owner = PrivateManagedDirectory(root, create=kind == 'directory',
                                exclusive_create=kind == 'directory', defer_open=True)
print('ready', flush=True)
try:
    assert os.read(gate, 1) == b'x'
    os.close(gate)
    owner.open()
    if kind == 'lock':
        with owner.lock('first.lock', create=True, exclusive_create=True):
            pass
    print('created', flush=True)
except ManagedStorageError as error:
    print(error.code, flush=True)
finally:
    owner.close()
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    read_gate, write_gate = os.pipe()
    children = []
    try:
        for _ in range(2):
            children.append(subprocess.Popen(
                [sys.executable, "-c", script, str(root), kind, str(read_gate)],
                env=env, pass_fds=(read_gate,), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            ))
        for child in children:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=10), "child did not reach creation gate"
            assert child.stdout.readline().strip() == "ready"
        assert os.write(write_gate, b"xx") == 2
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 0, stderr
            results.append(stdout.strip())
        assert sorted(results) == ["conflict", "created"]
        target = root if kind == "directory" else root / "first.lock"
        assert target.exists()
        # Even after both contenders exit, a new exclusive claimant cannot
        # adopt the durable object; ordinary reopening remains compatible.
        if kind == "directory":
            with pytest.raises(ManagedStorageError, match="conflict"):
                PrivateManagedDirectory(root, create=True, exclusive_create=True)
        reopened = PrivateManagedDirectory(root)
        try:
            if kind == "lock":
                with reopened.lock("first.lock"):
                    pass
                with pytest.raises(ManagedStorageError, match="conflict"):
                    with reopened.lock("first.lock", create=True, exclusive_create=True):
                        pytest.fail("post-exit exclusive claimant adopted lock")
        finally:
            reopened.close()
    finally:
        os.close(read_gate)
        os.close(write_gate)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)


@pytest.mark.parametrize("kind", ["directory", "lock"])
def test_exclusive_creation_rechecks_identity_after_sync(tmp_path, monkeypatch, kind):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True, exclusive_create=True, defer_open=True)
    if kind == "lock":
        owner.open()
    target = root if kind == "directory" else root / "first.lock"
    moved = target.with_name("displaced")
    fsync = os.fsync
    swapped = False

    def replace_after_sync(fd):
        nonlocal swapped
        fsync(fd)
        if not swapped:
            swapped = True
            target.rename(moved)
            if kind == "directory":
                target.mkdir(mode=0o700)
            else:
                target.touch(mode=0o600)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", replace_after_sync)
            with pytest.raises(ManagedStorageError, match="conflict"):
                if kind == "directory":
                    owner.open()
                else:
                    with owner.lock("first.lock", create=True, exclusive_create=True):
                        pytest.fail("replacement lock was delivered")
        assert swapped
    finally:
        owner.close()
    assert target.exists() and moved.exists()
    assert target.stat().st_ino != moved.stat().st_ino


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
        assert owner.cleanup_pending is (stage == 3)
        assert sorted(p.name for p in root.iterdir()) == ["control.lock", "record"]
    owner.close()
    assert not owner.cleanup_pending
    assert (root / "record").read_bytes() == (b"new" if stage == 3 else b"original")


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


def test_cancel_and_close_failure_preserve_cancel_and_attempt_unlink(tmp_path, monkeypatch):
    root = tmp_path / "private"
    owner = PrivateManagedDirectory(root, create=True)
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
        assert owner.cleanup_pending and not owner._pending
        assert sorted(p.name for p in root.iterdir()) == ["control.lock"]
    for _ in range(2):
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.close()


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

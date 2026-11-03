from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, current_thread

import pytest

from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.artifacts._writer_lease import SessionBlobWriterLease
from loushang.harness.journal import _rooted_io as native

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted attachments")


@pytest.fixture
def owned(tmp_path):
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    owner = SessionBlobWriterLease(root, "coding", "session")
    owner.acquire()
    io = owner.borrow_file_io(data_root=root, owner_id="coding", session_id="session")
    try:
        yield root, io
    finally:
        io.cleanup()
        owner.close()


def put(store, payload=b"image", name="image.png"):
    return store.put_bytes(payload, logical_name=name, kind="image", media_type="image/png")


def tree(root):
    return {
        str(path.relative_to(root)): (path.lstat().st_mode, path.lstat().st_ino,
                                     path.lstat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
        for path in (root, *root.rglob("*"))
    }


@pytest.mark.parametrize("action", ["read", "inspect", "metadata", "put", "import", "rollback", "delete"])
def test_actual_blob_operations_stay_in_original_data_root(owned, monkeypatch, action):
    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    first = put(store)
    source = SessionBlobStore(root, "source", file_io=io)
    added = put(source, b"other", "other.png")
    publication = store.import_blobs([(added, b"other")]) if action == "rollback" else None
    moved = root.with_name("saved")
    root.rename(moved)
    root.mkdir(mode=0o700)
    (root / "sentinel").write_bytes(b"untouched")
    before = tree(root)

    def forbidden(*args, **kwargs):
        raise AssertionError("rooted BlobStore fell back to pathname IO")

    with monkeypatch.context() as patch:
        for method in ("open", "read_bytes", "write_bytes", "exists", "lstat", "stat", "resolve", "mkdir", "unlink"):
            patch.setattr(Path, method, forbidden)
        if action == "read":
            assert store.read_bytes(first) == b"image"
        elif action == "inspect":
            assert store.inspect([first])[0].state == "available"
        elif action == "metadata":
            assert store.inspect_metadata([first])[0].state == "available"
        elif action == "put":
            assert store.read_bytes(put(store, b"new")) == b"new"
        elif action == "import":
            assert store.read_bytes(store.import_blobs([(added, b"other")]).references[0]) == b"other"
        elif action == "rollback":
            assert publication.rollback()
            assert store.records == (first,)
        else:
            assert store.delete()
    assert tree(root) == before
    actual = SessionBlobStore(moved, "session")
    if action == "delete":
        assert actual.records == ()
    else:
        assert actual.read_bytes(first) == b"image"


@pytest.mark.parametrize("level", ["session-assets", "session-assets/session", "session-assets/session/objects"])
def test_swap_nested_directory_after_lock_is_rejected_without_touching_replacement(owned, monkeypatch, level):
    import fcntl

    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    reference = put(store)
    selected = root / level
    original = fcntl.flock
    snapshots = []

    def replace_after_lock(*args, **kwargs):
        result = original(*args, **kwargs)
        if not snapshots:
            selected.rename(selected.with_name(selected.name + ".saved"))
            selected.mkdir(mode=0o700)
            (selected / "sentinel").write_bytes(b"untouched")
            snapshots.append(tree(selected))
        return result

    with monkeypatch.context() as patch:
        patch.setattr(fcntl, "flock", replace_after_lock)
        with pytest.raises(OSError, match="identity changed"):
            store.read_bytes(reference)
    assert tree(selected) == snapshots[0]


def test_rollback_after_session_root_replacement_does_not_delete_new_authority(owned):
    root, io = owned
    source = SessionBlobStore(root, "source", file_io=io)
    reference = put(source)
    target = SessionBlobStore(root, "session", file_io=io)
    publication = target.import_blobs([(reference, b"image")])
    path = root / "session-assets/session"
    path.rename(path.with_name("saved"))
    replacement = SessionBlobStore(root, "session", file_io=io)
    put(replacement)
    before = tree(path)
    assert publication.rollback() is False
    assert tree(path) == before


def test_manifest_published_sync_and_restore_failures_preserve_referenced_objects(owned, monkeypatch):
    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    first = put(store)
    replace = native.os.replace
    fsync = native.os.fsync
    replaced = []

    def track_replace(*args, **kwargs):
        if args[1] == "manifest.json":
            if replaced:
                raise OSError("test restore failed")
            result = replace(*args, **kwargs)
            replaced.append(True)
            return result
        return replace(*args, **kwargs)

    def fail_sync(fd):
        if replaced:
            raise OSError("test manifest sync failed")
        return fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(native.os, "replace", track_replace)
        patch.setattr(native.os, "fsync", fail_sync)
        with pytest.raises(OSError, match="manifest sync"):
            put(store, b"second", "second.png")
    assert io.cleanup_pending
    # Reconcile only known native cleanup debt, not a replay of publication.
    io.cleanup()
    restored = SessionBlobStore(root, "session", file_io=io)
    assert restored.records == (first,)
    assert restored.read_bytes(first) == b"image"
    assert {path.name for path in restored.objects_root.iterdir()} == {first.blob_id}


def test_delete_budget_and_symlink_fail_before_deleting_existing_objects(owned):
    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    reference = put(store)
    authority = root / "session-assets/session"
    (authority / "link").symlink_to(root.parent)
    with pytest.raises(OSError):
        store.delete()
    assert store.read_bytes(reference) == b"image"
    (authority / "link").unlink()
    with io.directory() as data:
        assets = data.child("session-assets")
        selected = assets.child("session")
        with pytest.raises(OSError, match="budget"):
            assets.remove_tree("session", expected=selected, limit=1)
    assert store.read_bytes(reference) == b"image"


def test_exclusive_manifest_publish_never_overwrites_existing_target(owned):
    root, io = owned
    with io.directory() as data:
        target = data.file("manifest")
        target.atomic_write(b"original", exclusive=True)
        with pytest.raises(FileExistsError):
            target.atomic_write(b"replacement", exclusive=True)
        assert target.read_bytes() == b"original"
    assert not io.cleanup_pending


@pytest.mark.parametrize("stage", ["replace", "sync"])
def test_repeated_manifest_failures_restore_without_unaccounted_objects(owned, monkeypatch, stage):
    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    first = put(store)
    replacement = native.os.replace
    fsync = native.os.fsync
    failed = []
    published = []

    def fail_publication(*args, **kwargs):
        if args[1] == "manifest.json" and not failed:
            if stage == "replace":
                failed.append(True)
                raise OSError("test manifest publication failed")
            result = replacement(*args, **kwargs)
            published.append(True)
            return result
        return replacement(*args, **kwargs)

    def fail_sync(fd):
        if published and not failed:
            failed.append(True)
            raise OSError("test manifest publication failed")
        return fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(native.os, "replace", fail_publication)
        patch.setattr(native.os, "fsync", fail_sync)
        for number in range(8):
            failed.clear()
            published.clear()
            with pytest.raises(OSError, match="publication failed"):
                put(store, f"new object {number}".encode())
            assert not io.cleanup_pending
    assert store.read_bytes(first) == b"image"
    assert store.records == (first,)
    assert {path.name for path in (root / "session-assets/session/objects").iterdir()} == {first.blob_id}


def test_partial_delete_retains_exact_plan_without_needing_manifest(owned, monkeypatch):
    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    put(store)
    rmdir = native.os.rmdir

    def unavailable(name, *args, **kwargs):
        if name == "objects":
            raise OSError("test partial delete")
        return rmdir(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(native.os, "rmdir", unavailable)
        with pytest.raises(OSError, match="partial delete"):
            store.delete()
        assert io.cleanup_pending
        assert not (root / "session-assets/session/manifest.json").exists()
        with pytest.raises(OSError, match="partial delete"):
            io.cleanup()
    io.cleanup()
    assert not io.cleanup_pending
    assert not (root / "session-assets/session").exists()
    assert SessionBlobStore(root, "session", file_io=io).delete() is False


def test_delete_sync_retry_does_not_remove_replacement_authority(owned, monkeypatch):
    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    put(store)
    rmdir, fsync = native.os.rmdir, native.os.fsync
    removed = []

    def track_remove(name, *args, **kwargs):
        result = rmdir(name, *args, **kwargs)
        if name == "session":
            removed.append(True)
        return result

    def unavailable(fd):
        if removed:
            raise OSError("test retired directory sync")
        return fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(native.os, "rmdir", track_remove)
        patch.setattr(native.os, "fsync", unavailable)
        with pytest.raises(OSError, match="directory sync"):
            store.delete()
    authority = root / "session-assets/session"
    authority.mkdir(mode=0o700)
    (authority / "sentinel").write_bytes(b"replacement")
    before = tree(authority)
    assert io.cleanup_pending
    io.cleanup()
    assert tree(authority) == before and not io.cleanup_pending


def short_lock_state(root):
    script = """
import sys
from pathlib import Path
from loushang.harness.journal import JournalLockUnavailable, journal_file_lock
try:
    with journal_file_lock(Path(sys.argv[1]), 'shared', blocking=False):
        print('free')
except JournalLockUnavailable:
    print('busy')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(root / "session-assets/.locks/session")],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_double_prepublish_failure_retains_recovery_and_original_short_lock(owned, monkeypatch):
    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    first = put(store)
    replace = native.os.replace

    def unavailable(*args, **kwargs):
        if args[1] == "manifest.json":
            raise OSError("test both publications fail")
        return replace(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(native.os, "replace", unavailable)
        with pytest.raises(OSError, match="both publications"):
            put(store, b"new unreferenced object")
        assert io.cleanup_pending
        assert short_lock_state(root) == "busy"
        for _ in range(2):
            with pytest.raises(OSError, match="both publications"):
                io.cleanup()
            assert io.cleanup_pending
    io.cleanup()
    assert not io.cleanup_pending and short_lock_state(root) == "free"
    assert store.read_bytes(first) == b"image"
    assert {path.name for path in store.objects_root.iterdir()} == {first.blob_id}


def test_contender_exits_before_retained_recovery_cleanup(owned, monkeypatch):
    import fcntl

    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    first = put(store)
    holder_ready, contender_ready, holder_finished = Event(), Event(), Event()
    flock, replace = fcntl.flock, native.os.replace

    def barrier(fd, mode):
        if current_thread().name.endswith("_0"):
            result = flock(fd, mode)
            holder_ready.set()
            assert contender_ready.wait(5)
            return result
        contender_ready.set()
        assert holder_finished.wait(5)
        # Check the flag before issuing the syscall, so a regression fails
        # without leaving the test runner stuck in a native blocking flock.
        assert mode & fcntl.LOCK_NB
        return flock(fd, mode)

    def unavailable(*args, **kwargs):
        if args[1] == "manifest.json":
            raise OSError("test retained publication recovery")
        return replace(*args, **kwargs)

    def holder():
        try:
            with pytest.raises(OSError, match="retained publication recovery"):
                put(store, b"unreferenced")
        finally:
            holder_finished.set()

    def contender():
        with pytest.raises(BlockingIOError):
            put(SessionBlobStore(root, "session", file_io=io), b"contender")

    with monkeypatch.context() as patch:
        patch.setattr(fcntl, "flock", barrier)
        patch.setattr(native.os, "replace", unavailable)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="blob-contention") as executor:
            first_call = executor.submit(holder)
            assert holder_ready.wait(5)
            second_call = executor.submit(contender)
            first_call.result(timeout=10)
            second_call.result(timeout=10)
        assert io.cleanup_pending
        assert not any(operation.active for operation in io._operations)
    io.cleanup()
    assert not io.cleanup_pending and short_lock_state(root) == "free"
    assert store.read_bytes(first) == b"image"
    assert {path.name for path in store.objects_root.iterdir()} == {first.blob_id}


def test_batch_rollback_first_unlink_failure_retains_all_remaining_objects(owned, monkeypatch):
    root, io = owned
    store = SessionBlobStore(root, "session", file_io=io)
    first = put(store)
    source = SessionBlobStore(root, "source", file_io=io)
    blobs = [(put(source, str(number).encode()), str(number).encode()) for number in range(3)]
    replace, unlink = native.os.replace, native.os.unlink
    published = []

    def fail_third(*args, **kwargs):
        if args[1] == "manifest.json":
            published.append(True)
            if len(published) == 3:
                raise OSError("test third publication fails")
        return replace(*args, **kwargs)

    def unavailable(name, *args, **kwargs):
        if name in {reference.blob_id for reference, _ in blobs}:
            raise OSError("test object deletion fails")
        return unlink(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(native.os, "replace", fail_third)
        patch.setattr(native.os, "unlink", unavailable)
        with pytest.raises(OSError, match="third publication"):
            store.import_blobs(blobs)
        assert io.cleanup_pending and short_lock_state(root) == "busy"
        assert sum(len(operation.deletions) for operation in io._operations) == 3
    io.cleanup()
    assert not io.cleanup_pending and short_lock_state(root) == "free"
    assert {path.name for path in store.objects_root.iterdir()} == {first.blob_id}


def test_publication_final_receipt_failure_retains_native_recovery(owned, monkeypatch):
    root, io = owned
    source = SessionBlobStore(root, "source", file_io=io)
    reference = put(source)
    target = SessionBlobStore(root, "session", file_io=io)
    native_stat, rmdir = target._stat, native.os.rmdir

    def final_stat(path):
        if path == target.root:
            raise OSError("test final publication receipt fails")
        return native_stat(path)

    def unavailable(name, *args, **kwargs):
        if name == "session":
            raise OSError("test rollback deletion fails")
        return rmdir(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(target, "_stat", final_stat)
        patch.setattr(native.os, "rmdir", unavailable)
        with pytest.raises(OSError, match="final publication receipt fails"):
            target.import_blobs([(reference, b"image")], require_new_authority=True)
        assert io.cleanup_pending
        assert short_lock_state(root) == "busy"
    io.cleanup()
    assert not io.cleanup_pending and not target.root.exists()
    assert short_lock_state(root) == "free"

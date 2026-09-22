from __future__ import annotations

import os
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from loushang.harness.journal import JournalLoadPolicy, JsonlJournal
from loushang.harness.journal import _rooted_io as module
from loushang.harness.journal._rooted_io import RootedFileIO

from .test_jsonl import _Header, _HeaderCodec, _Record, _RecordCodec

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux retained-root IO")


@contextmanager
def borrowed(root):
    root.mkdir(mode=0o700)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    io = RootedFileIO(root, fd)
    try:
        yield io
        assert not io.cleanup_pending
        assert stat.S_ISDIR(os.fstat(fd).st_mode)  # Never consumes the borrowed fd.
    finally:
        os.close(fd)


def journal(io, *, repair=False):
    return JsonlJournal(
        io.root / "session.jsonl", file_io=io,
        record_codec=_RecordCodec(), header_codec=_HeaderCodec(),
        load_policy=JournalLoadPolicy(header="required", partial_tail="repair" if repair else "raise"),
    )


def tree(root):
    return {
        str(path.relative_to(root)): (path.lstat().st_mode, path.lstat().st_ino,
                                     path.lstat().st_mtime_ns,
                                     path.read_bytes() if path.is_file() else None)
        for path in (root, *root.rglob("*"))
    }


def replace_root(root):
    moved = root.with_name("moved")
    root.rename(moved)
    root.mkdir(mode=0o700)
    (root / "session.jsonl").write_bytes(b"replacement must stay untouched\n")
    (root / "sentinel").mkdir(mode=0o700)
    return moved


@pytest.mark.parametrize("action", ["load", "append", "batch", "rewrite", "repair", "unlink"])
def test_rooted_journal_actions_never_follow_replacement_root(tmp_path, monkeypatch, action):
    with borrowed(tmp_path / "root") as io:
        store = journal(io, repair=action == "repair")
        store.rewrite([_Record("one", "old")], header=_Header("id"))
        if action == "repair":
            io.append_bytes(store.path, b'{"unterminated":')
        moved = replace_root(io.root)
        untouched = tree(io.root)

        def forbidden(*_, **__):
            raise AssertionError("rooted Journal fell back to pathname IO")

        with monkeypatch.context() as patch:
            for name in ("open", "read_text", "read_bytes", "write_text", "write_bytes", "mkdir", "replace", "unlink"):
                patch.setattr(Path, name, forbidden)
            if action == "append":
                store.append(_Record("two", "new"))
            elif action == "batch":
                store.append_batch([_Record("two", "new"), _Record("three", "last")])
            elif action == "rewrite":
                store.rewrite([_Record("rewritten", "new")], header=_Header("id"))
            elif action == "unlink":
                io.unlink(store.path)
            else:
                assert store.load().records == (_Record("one", "old"),)
        assert tree(io.root) == untouched
        if action == "unlink":
            assert not (moved / "session.jsonl").exists()
        elif action in {"append", "batch", "rewrite"}:
            assert b"new" in (moved / "session.jsonl").read_bytes()
        elif action == "repair":
            assert b"unterminated" not in (moved / "session.jsonl").read_bytes()


@pytest.mark.parametrize("stage", ["open", "write", "replace", "unlink", "fsync", "lock"])
def test_replacement_at_native_boundaries_stays_in_original_parent(tmp_path, monkeypatch, stage):
    import fcntl

    with borrowed(tmp_path / "root") as io:
        path = io.root / "session.jsonl"
        io.atomic_write(path, b"old")
        replacement = []
        namespace = fcntl if stage == "lock" else module.os
        name = "flock" if stage == "lock" else stage
        original = getattr(namespace, name)

        def swap(*args, **kwargs):
            if not replacement:
                replacement.append(replace_root(io.root))
                replacement.append(tree(io.root))
            return original(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(namespace, name, swap)
            if stage == "unlink":
                io.unlink(path)
            elif stage == "lock":
                with io.lock(path.with_suffix(".lock"), exclusive=True):
                    pass
            elif stage == "write":
                io.append_bytes(path, b"appended")
            else:
                io.atomic_write(path, b"rewritten")
        assert replacement and tree(io.root) == replacement[1]


@pytest.mark.parametrize("name", ["../outside", "/outside", "bad\\name", "bad\0name"])
def test_lexical_escape_rejected_before_native_io(tmp_path, monkeypatch, name):
    with borrowed(tmp_path / "root") as io:
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "open", lambda *_, **__: pytest.fail("opened invalid path"))
            with pytest.raises(ValueError):
                io.read_bytes(io.root / name)


@pytest.mark.parametrize("kind", ["parent_symlink", "leaf_symlink", "fifo", "hardlink"])
def test_unsafe_parent_or_leaf_cannot_write(tmp_path, kind):
    with borrowed(tmp_path / "root") as io:
        outside = tmp_path / "outside"
        outside.mkdir(mode=0o700)
        original = outside / "value"
        original.write_bytes(b"safe")
        path = io.root / "value"
        if kind == "parent_symlink":
            path.symlink_to(outside, target_is_directory=True)
            path = path / "value"
        elif kind == "leaf_symlink":
            path.symlink_to(original)
        elif kind == "fifo":
            os.mkfifo(path, 0o600)
        else:
            os.link(original, path)
        with pytest.raises(OSError):
            io.append_bytes(path, b"unsafe")
        assert original.read_bytes() == b"safe"


def test_temporary_collision_never_acquires_cleanup_authority(tmp_path, monkeypatch):
    with borrowed(tmp_path / "root") as io:
        collision = io.root / ".value.fixed.tmp"
        collision.write_bytes(b"not ours")
        monkeypatch.setattr(module.secrets, "token_hex", lambda _: "fixed")
        with pytest.raises(FileExistsError):
            io.atomic_write(io.root / "value", b"new")
        assert collision.read_bytes() == b"not ours"


@pytest.mark.parametrize("stage", ["write", "file_fsync", "replace", "directory_fsync"])
def test_atomic_failure_preserves_commit_boundary_and_removes_only_own_temp(tmp_path, monkeypatch, stage):
    with borrowed(tmp_path / "root") as io:
        path = io.root / "value"
        io.atomic_write(path, b"old")
        failure = OSError("test native failure")
        original_fsync = module.os.fsync

        def fail(*_, **__):
            raise failure

        def sync(fd):
            directory = stat.S_ISDIR(os.fstat(fd).st_mode)
            if directory == (stage == "directory_fsync"):
                raise failure
            original_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(module.os, "fsync" if "fsync" in stage else stage, sync if "fsync" in stage else fail)
            with pytest.raises(OSError) as raised:
                io.atomic_write(path, b"new")
            assert raised.value is failure
        assert path.read_bytes() == (b"new" if stage == "directory_fsync" else b"old")
        assert not tuple(io.root.glob("*.tmp"))
        assert io.cleanup_pending == (stage == "directory_fsync")
        io.cleanup()


def test_unlink_cleanup_debt_retains_parent_and_retries_after_root_replacement(tmp_path, monkeypatch):
    with borrowed(tmp_path / "root") as io:
        failure = OSError("test write failure")
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "write", lambda *_: (_ for _ in ()).throw(failure))
            patch.setattr(module.os, "unlink", lambda *_, **__: (_ for _ in ()).throw(OSError("test cleanup")))
            with pytest.raises(OSError) as raised:
                io.atomic_write(io.root / "value", b"new")
            assert raised.value is failure and io.cleanup_pending
        moved = replace_root(io.root)
        untouched = tree(io.root)
        io.cleanup()
        assert not tuple(moved.glob("*.tmp")) and tree(io.root) == untouched


def test_unknown_close_preserves_primary_closes_other_fds_and_never_retries_number(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    io = RootedFileIO(root, fd)
    closed = []
    original_close = os.close
    primary = ValueError("test body")

    def close(descriptor):
        closed.append(descriptor)
        original_close(descriptor)
        if len(closed) == 1:
            raise OSError("test close result lost")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "close", close)
            with pytest.raises(ValueError) as raised:
                with io.lock(root / "guard", exclusive=True):
                    raise primary
            assert raised.value is primary
        assert len(closed) == 2 and fd not in closed and io.cleanup_pending
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "close", lambda *_: pytest.fail("retried unknown close"))
            with pytest.raises(OSError, match="unknown"):
                io.cleanup()
        assert stat.S_ISDIR(os.fstat(fd).st_mode)
    finally:
        original_close(fd)  # Fixture knows both injected closes actually succeeded.


def test_rooted_journal_refuses_path_only_lock_factory(tmp_path):
    with borrowed(tmp_path / "root") as io:
        with pytest.raises(ValueError, match="pathname lock factory"):
            JsonlJournal(io.root / "value", record_codec=_RecordCodec(), file_io=io, lock_factory=lambda *_: None)


@pytest.mark.parametrize("action", ["load", "append", "batch", "rewrite", "repair"])
def test_journal_lock_and_data_keep_same_parent_after_nested_directory_replacement(tmp_path, monkeypatch, action):
    import fcntl

    with borrowed(tmp_path / "root") as io:
        parent = io.root / "sub"
        parent.mkdir(mode=0o700)
        store = JsonlJournal(
            parent / "session.jsonl", file_io=io,
            record_codec=_RecordCodec(), header_codec=_HeaderCodec(),
            load_policy=JournalLoadPolicy(header="required", partial_tail="repair"),
        )
        store.rewrite([_Record("one", "old")], header=_Header("id"))
        if action == "repair":
            io.append_bytes(store.path, b"partial")
        original = fcntl.flock
        snapshots = []

        def flock(fd, mode):
            result = original(fd, mode)
            if not snapshots:
                parent.rename(io.root / "previous-sub")
                parent.mkdir(mode=0o700)
                (parent / "session.jsonl").write_bytes(b"must stay untouched")
                snapshots.append(tree(parent))
            return result

        with monkeypatch.context() as patch:
            patch.setattr(fcntl, "flock", flock)
            if action == "append":
                store.append(_Record("two", "new"))
            elif action == "batch":
                store.append_batch([_Record("two", "new")])
            elif action == "rewrite":
                store.rewrite([_Record("two", "new")], header=_Header("id"))
            else:
                assert store.load().records == (_Record("one", "old"),)
        assert snapshots and tree(parent) == snapshots[0]
        original_bytes = (io.root / "previous-sub" / "session.jsonl").read_bytes()
        if action in {"append", "batch", "rewrite"}:
            assert b"new" in original_bytes
        if action == "repair":
            assert b"partial" not in original_bytes


def test_unlinked_temporary_sync_debt_never_redeletes_replacement(tmp_path, monkeypatch):
    with borrowed(tmp_path / "root") as io:
        primary = ValueError("test write failed")
        monkeypatch.setattr(module.secrets, "token_hex", lambda _: "fixed")
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "write", lambda *_: (_ for _ in ()).throw(primary))
            patch.setattr(module.os, "fsync", lambda *_: (_ for _ in ()).throw(OSError("test sync failed")))
            with pytest.raises(ValueError) as raised:
                io.atomic_write(io.root / "value", b"new")
            assert raised.value is primary and io.cleanup_pending
        assert not (io.root / ".value.fixed.tmp").exists()
        (io.root / ".value.fixed.tmp").write_bytes(b"not our old temp")
        moved = replace_root(io.root)
        untouched = tree(io.root)
        with monkeypatch.context() as patch:
            patch.setattr(module.os, "unlink", lambda *_, **__: pytest.fail("retried settled unlink"))
            io.cleanup()
        assert (moved / ".value.fixed.tmp").read_bytes() == b"not our old temp"
        assert tree(io.root) == untouched


def test_committed_replace_sync_debt_never_deletes_new_same_named_temporary(tmp_path, monkeypatch):
    with borrowed(tmp_path / "root") as io:
        monkeypatch.setattr(module.secrets, "token_hex", lambda _: "fixed")
        original = os.fsync

        def fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                (io.root / ".value.fixed.tmp").write_bytes(b"new unrelated file")
                raise OSError("test commit durability unknown")
            original(fd)

        with monkeypatch.context() as patch:
            patch.setattr(module.os, "fsync", fsync)
            with pytest.raises(OSError, match="durability unknown"):
                io.atomic_write(io.root / "value", b"committed")
        assert (io.root / "value").read_bytes() == b"committed" and io.cleanup_pending
        io.cleanup()
        assert (io.root / ".value.fixed.tmp").read_bytes() == b"new unrelated file"


def test_rooted_lock_excludes_independent_process_and_releases_after_context(tmp_path):
    script = """
import os, sys
from pathlib import Path
from loushang.harness.journal._rooted_io import RootedFileIO
root = Path(sys.argv[1])
fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
io = RootedFileIO(root, fd)
try:
    try:
        with io.lock(root / 'guard', exclusive=True, blocking=False):
            print('acquired')
    except BlockingIOError:
        print('busy')
    assert not io.cleanup_pending
finally:
    os.close(fd)
"""
    with borrowed(tmp_path / "root") as io:
        def child():
            result = subprocess.run(
                [sys.executable, "-c", script, str(io.root)], capture_output=True, text=True,
                timeout=5, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3] / "src")},
            )
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        with io.lock(io.root / "guard", exclusive=True):
            assert child() == "busy"
        assert child() == "acquired"


def test_file_reference_expires_with_its_parent_borrow(tmp_path):
    with borrowed(tmp_path / "root") as io:
        with io.bind(io.root / "value") as target:
            target.atomic_write(b"value")
        with pytest.raises(OSError, match="borrow has ended"):
            target.append_bytes(b"late")


def test_recovery_borrows_do_not_revive_expired_references(tmp_path):
    with borrowed(tmp_path / "root") as io:
        recovered = []
        attempts = []
        with pytest.raises(OSError, match="test retained recovery"):
            with io.directory() as original:
                leaf = original.file("payload")
                leaf.atomic_write(b"before")

                def recover(current):
                    for previous in recovered:
                        with pytest.raises(OSError, match="cleanup borrow has ended"):
                            previous.stat()
                    with pytest.raises(OSError, match="borrow has ended"):
                        original.stat()
                    with pytest.raises(OSError, match="borrow has ended"):
                        leaf.read_bytes()
                    rebound = current.reborrow(original)
                    recovered.extend((current, rebound, rebound.file("payload")))
                    attempts.append(True)
                    if len(attempts) == 1:
                        raise OSError("test retained recovery")
                    rebound.file("payload").atomic_write(b"after")

                original.retain_cleanup(recover)
        assert io.cleanup_pending
        for reference in recovered:
            with pytest.raises(OSError, match="cleanup borrow has ended"):
                reference.stat()
        io.cleanup()
        assert len(attempts) == 2 and not io.cleanup_pending
        for reference in recovered:
            with pytest.raises(OSError, match="cleanup borrow has ended"):
                reference.stat()
        assert io.read_bytes(io.root / "payload") == b"after"


def test_inherited_bound_file_refuses_all_operations_before_native_io(tmp_path, monkeypatch):
    with borrowed(tmp_path / "root") as io:
        with io.bind(io.root / "value") as target:
            target.atomic_write(b"parent")
            pid = os.fork()
            if pid == 0:
                try:
                    def forbidden(*_, **__):
                        raise AssertionError("fork child reached native IO")

                    monkeypatch.setattr(module.os, "open", forbidden)
                    monkeypatch.setattr(module.os, "unlink", forbidden)
                    operations = (
                        target.read_bytes,
                        lambda: target.append_bytes(b"child"),
                        lambda: target.atomic_write(b"child"),
                        target.unlink,
                        lambda: target.acquire_lock(exclusive=True),
                        target._operation.cleanup,
                    )
                    for operation in operations:
                        try:
                            operation()
                        except OSError as exc:
                            assert "after fork" in str(exc)
                        else:
                            raise AssertionError("inherited borrow was accepted")
                except BaseException:
                    os._exit(1)
                os._exit(0)
            waited, status = os.waitpid(pid, 0)
            assert waited == pid and os.waitstatus_to_exitcode(status) == 0
            assert target.read_bytes() == b"parent"
            target.append_bytes(b"-continued")
        assert io.read_bytes(io.root / "value") == b"parent-continued"

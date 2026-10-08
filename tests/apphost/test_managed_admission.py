from __future__ import annotations

import os
import sys
from time import monotonic

import pytest

from loushang.apphost.managed import _database, _files
from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed storage admission")


def test_deferred_containers_do_no_io_and_cannot_reopen_or_revive(tmp_path, monkeypatch):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda *a, **kw: pytest.fail("constructor performed IO"))
        registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True, defer_open=True)
        journal = ManagedServiceJournalV1(
            registry, namespace, service, tmp_path / "fence", create=True, defer_open=True,
        )
    try:
        with pytest.raises(ManagedStorageError, match="closed"):
            registry.resolve("dev")
        with pytest.raises(ManagedStorageError, match="closed"):
            journal.read()
        deadline = monotonic() + 5
        registry.open(deadline=deadline)
        registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
        journal.open(deadline=deadline)
        state = journal.prepare("c" * 32, expected=None)
        for owner in (registry, journal):
            with pytest.raises(ManagedStorageError, match="closed"):
                owner.open(deadline=deadline)
        assert journal.read() == state  # Rejected duplicate open did not close valid owners.
        journal.close()
        registry.close()
        for owner in (registry, journal):
            with pytest.raises(ManagedStorageError, match="closed"):
                owner.open(deadline=deadline)
    finally:
        journal.close()
        registry.close()


def test_unopened_close_permanently_fences_admission(tmp_path):
    directory = PrivateManagedDirectory(tmp_path / "private", create=True, defer_open=True)
    directory.close()
    with pytest.raises(ManagedStorageError, match="closed"):
        directory.open(deadline=monotonic() + 1)
    assert not (tmp_path / "private").exists()


def test_failed_parent_validation_retains_unvalidated_descriptor_until_explicit_close(tmp_path, monkeypatch):
    directory = PrivateManagedDirectory(tmp_path / "private", defer_open=True)

    def fail(info):
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(directory, "_validate_parent", fail)
    with pytest.raises(ManagedStorageError):
        directory.open(deadline=monotonic() + 1)
    fd, anchor = directory._opening_fd, directory._anchor
    assert fd is not None and anchor is not None
    os.fstat(fd)
    os.fstat(anchor)
    directory.close()
    for descriptor in (fd, anchor):
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_directory_admission_deadline_retains_acquired_anchor(tmp_path, monkeypatch):
    directory = PrivateManagedDirectory(tmp_path / "private", defer_open=True)
    now = [1.0]
    original = os.open

    def slow_open(*args, **kwargs):
        fd = original(*args, **kwargs)
        now[0] = 3.0
        return fd

    monkeypatch.setattr(_files, "monotonic", lambda: now[0])
    monkeypatch.setattr(os, "open", slow_open)
    with pytest.raises(ManagedStorageError, match="busy"):
        directory.open(deadline=2.0)
    assert directory._anchor is not None and directory._opening_fd is None
    directory.close()


def test_database_initial_inspection_receives_callers_absolute_deadline(tmp_path, monkeypatch):
    from contextlib import contextmanager

    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True, defer_open=True)
    original = registry._database._connection
    deadlines = []

    @contextmanager
    def inspect(**kwargs):
        deadlines.append(kwargs["deadline"])
        with original(**kwargs) as connection:
            yield connection

    monkeypatch.setattr(registry._database, "_connection", inspect)
    deadline = monotonic() + 5
    try:
        registry.open(deadline=deadline)
        assert deadlines == [deadline]
    finally:
        registry.close()


def test_failed_initial_database_inspection_and_close_keep_retryable_connection(tmp_path, monkeypatch):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True, defer_open=True)
    original = _database.sqlite3.connect
    close_calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            self.inner = original(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def close(self):
            close_calls.append(1)
            if len(close_calls) < 3:
                raise _database.sqlite3.OperationalError("injected close failure")
            self.inner.close()

    def reject(connection):
        raise ManagedStorageError("invalid_record")

    monkeypatch.setattr(_database.sqlite3, "connect", Connection)
    monkeypatch.setattr(registry._database, "_validate_schema", reject)
    try:
        with pytest.raises(ManagedStorageError, match="invalid_record"):
            registry.open(deadline=monotonic() + 5)
        retained = registry._database._cleanup_connection
        assert retained is not None and registry.cleanup_pending
        with pytest.raises(ManagedStorageError, match="unavailable"):
            registry.close()
        assert registry._database._cleanup_connection is retained
        assert registry._database._directory._fd is not None
        with pytest.raises(ManagedStorageError, match="closed"):
            registry.open(deadline=monotonic() + 5)
        registry.close()
        assert not registry.cleanup_pending and len(close_calls) == 3
    finally:
        registry.close()


def test_uncertain_native_close_is_debt_not_permission_to_close_reused_fd(tmp_path, monkeypatch):
    root = tmp_path / "private"
    directory = PrivateManagedDirectory(root, create=True)
    target = directory._fd
    original = os.close
    replacements = []
    attempts = []

    def uncertain_close(fd):
        if fd == target:
            attempts.append(fd)
            original(fd)
            replacements.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY))
            raise OSError("close reported failure after releasing the descriptor")
        original(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "close", uncertain_close)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                directory.close()
            with pytest.raises(ManagedStorageError, match="unavailable"):
                directory.close()
        assert attempts == [target] and directory.cleanup_pending
        os.fstat(replacements[0])  # Retry did not close the unrelated replacement.
        with pytest.raises(ManagedStorageError, match="closed"):
            directory.open(deadline=monotonic() + 1)
    finally:
        for fd in replacements:
            original(fd)


@pytest.mark.parametrize("kind", ["registry", "journal"])
def test_first_lock_release_failure_retains_debt_without_closing_replacement(tmp_path, monkeypatch, kind):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True, defer_open=True)
    if kind == "journal":
        registry.open()
        owner = ManagedServiceJournalV1(registry, namespace, service, tmp_path / "fence", create=True, defer_open=True)
        directory = owner._fence
    else:
        owner, directory = registry, registry._database._directory
    open_file, close_fd = directory._open, os.close
    target, replacement = [], []

    def capture(name, *args, **kwargs):
        fd = open_file(name, *args, **kwargs)
        if name.endswith(".lock"):
            target.append(fd)
        return fd

    def fail(fd):
        close_fd(fd)
        if target and fd == target[0] and not replacement:
            replacement.append(os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY))
            raise OSError("uncertain lock release")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(directory, "_open", capture)
            patch.setattr(os, "close", fail)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.open(deadline=monotonic() + 5)
        assert directory.cleanup_pending
        for _ in range(2):
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.close()
        os.fstat(replacement[0])
    finally:
        for fd in replacement:
            close_fd(fd)
        if kind == "journal":
            registry.close()


@pytest.mark.parametrize("kind", ["open", "read", "write"])
def test_file_operation_close_failure_is_retained_by_owner(tmp_path, monkeypatch, kind):
    directory = PrivateManagedDirectory(tmp_path / "private", create=True)
    open_fd, close_fd = os.open, os.close
    target = []

    def capture(name, *args, **kwargs):
        fd = open_fd(name, *args, **kwargs)
        if (kind == "write" and str(name).startswith("pending-")) or (kind != "write" and name == "record"):
            target.append(fd)
        return fd

    def fail(fd):
        close_fd(fd)
        if target and fd == target[0]:
            raise OSError("uncertain file release")

    with directory.lock("control.lock", create=True):
        if kind != "write":
            directory.write("record", b"text", expected=None)
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", capture)
            patch.setattr(os, "close", fail)
            if kind == "open":
                original = directory._validate
                rejected_inode = (tmp_path / "private" / "record").stat().st_ino

                def reject(info, *, directory=False):
                    if not directory and info.st_ino == rejected_inode:
                        raise ManagedStorageError("invalid_record")
                    return original(info, directory=directory)

                patch.setattr(directory, "_validate", reject)
                with pytest.raises(ManagedStorageError, match="invalid_record"):
                    directory._open("record", os.O_RDONLY)
            elif kind == "read":
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    directory.read("record")
            else:
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    directory.write("record", b"new", expected=None)
    assert directory.cleanup_pending and target
    with pytest.raises(ManagedStorageError, match="busy"):
        directory.read("record")
    for _ in range(2):
        with pytest.raises(ManagedStorageError, match="unavailable"):
            directory.close()


@pytest.mark.parametrize("kind", ["registry", "journal"])
def test_late_admission_cleanup_does_not_publish_open_success(tmp_path, monkeypatch, kind):
    from contextlib import contextmanager

    from loushang.apphost.managed import lifecycle

    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True, defer_open=True)
    now = [1.0]
    if kind == "registry":
        owner = registry
        target, attribute = registry._database, "_connection"
    else:
        registry.open()
        owner = ManagedServiceJournalV1(registry, namespace, service, tmp_path / "fence", create=True, defer_open=True)
        target, attribute = owner._fence, "lock"
    original = getattr(target, attribute)

    @contextmanager
    def late(*args, **kwargs):
        with original(*args, **kwargs) as value:
            yield value
        now[0] = 3.0

    monkeypatch.setattr(_files, "monotonic", lambda: now[0])
    monkeypatch.setattr(_database, "monotonic", lambda: now[0])
    monkeypatch.setattr(lifecycle, "_check_deadline", _files._check_deadline)
    monkeypatch.setattr(target, attribute, late)
    try:
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.open(deadline=2.0)
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.resolve("dev") if kind == "registry" else owner.read()
    finally:
        owner.close()
        registry.close()


def test_partial_close_fences_new_operations_but_allows_cleanup_retry(tmp_path, monkeypatch):
    directory = PrivateManagedDirectory(tmp_path / "private", create=True)
    original_write = os.write

    def fail_write(fd, content):
        original_write(fd, content[:1])
        raise OSError("write failed")

    def fail_unlink(*args, **kwargs):
        raise OSError("cleanup failed")

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", fail_unlink)
        with directory.lock("control.lock", create=True):
            patch.setattr(os, "write", fail_write)
            with pytest.raises(ManagedStorageError):
                directory.write("record", b"new", expected=None)
        with pytest.raises(ManagedStorageError):
            directory.close()
        assert directory.cleanup_pending
        with pytest.raises(ManagedStorageError, match="closed"):
            directory.read("record")
        with pytest.raises(ManagedStorageError, match="closed"):
            with directory.lock("control.lock"):
                pytest.fail("closed directory admitted a new lock")
    directory.close()
    assert not directory.cleanup_pending

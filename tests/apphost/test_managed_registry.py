from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.apphost.managed._database import DATABASE_NAME
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed registry")


@pytest.fixture
def namespace(tmp_path):
    return ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)


@pytest.fixture
def registry(tmp_path, namespace):
    owner = ManagedRegistryV1(tmp_path / "registry", namespace, create=True)
    try:
        yield owner
    finally:
        owner.close()


def intent(name="dev", operation="b" * 32, workspace="/workspace"):
    return ManagedMuxReservationV1(name, ManagedServiceKeyV1("coding", workspace), operation)


def test_missing_lookup_does_not_create_root(tmp_path, namespace):
    with pytest.raises(ManagedStorageError, match="not_found"):
        ManagedRegistryV1(tmp_path / "missing", namespace)
    assert not (tmp_path / "missing").exists()


def test_reopen_from_other_cwd_retains_global_intent(registry, tmp_path, namespace, monkeypatch):
    request = intent()
    assert registry.reserve_mux(request) == request
    registry.close()
    other = tmp_path / "other-workspace"
    other.mkdir()
    monkeypatch.chdir(other)
    reopened = ManagedRegistryV1(tmp_path / "registry", namespace)
    try:
        assert reopened.resolve("dev") == request
        assert reopened.list_muxes() == (request,)
        assert not hasattr(reopened.resolve("dev"), "pid")
    finally:
        reopened.close()


def test_reservations_reuse_service_but_not_names_or_operations(registry, tmp_path):
    first = intent()
    assert registry.reserve_mux(first) == first
    assert registry.reserve_mux(first) == first
    second = intent("review", "c" * 32)
    registry.reserve_mux(second)
    with pytest.raises(ManagedStorageError, match="conflict"):
        registry.reserve_mux(intent(operation="d" * 32))
    with pytest.raises(ManagedStorageError, match="conflict"):
        registry.reserve_mux(intent("other"))
    with pytest.raises(ManagedStorageError, match="conflict"):
        registry.reserve_mux(intent(workspace="/different"))
    with sqlite3.connect(tmp_path / "registry" / DATABASE_NAME) as connection:
        assert connection.execute("SELECT count(*) FROM services").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM muxes").fetchone() == (2,)


def test_pagination_is_bounded_and_case_sensitive(registry):
    for index, name in enumerate(("dev", "Dev", "review")):
        registry.reserve_mux(intent(name, f"{index:032x}"))
    assert [r.name for r in registry.list_muxes(limit=2)] == ["Dev", "dev"]
    assert [r.name for r in registry.list_muxes(after="dev", limit=2)] == ["review"]
    for invalid in (0, 65, True, "2"):
        with pytest.raises(ManagedContractError):
            registry.list_muxes(limit=invalid)


def test_private_files_and_read_only_queries(registry, tmp_path, namespace):
    registry.reserve_mux(intent())
    root = tmp_path / "registry"
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}
    observer = ManagedRegistryV1(root, namespace)
    try:
        assert observer.resolve("absent") is None
        assert observer.resolve("dev") == intent()
        observer.list_muxes()
    finally:
        observer.close()
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}
    assert set(before) == {"registry.lock", DATABASE_NAME}
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir())


def test_namespace_mismatch_and_unknown_schema_are_not_migrated(registry, tmp_path, namespace):
    root = tmp_path / "registry"
    other = ManagedNamespaceV1(namespace.platform_home, namespace.user_id, "c" * 32)
    with pytest.raises(ManagedStorageError, match="conflict"):
        ManagedRegistryV1(root, other)
    with sqlite3.connect(root / DATABASE_NAME) as connection:
        connection.execute("PRAGMA user_version=42")
    before = (root / DATABASE_NAME).read_bytes()
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        ManagedRegistryV1(root, namespace, create=True)
    assert (root / DATABASE_NAME).read_bytes() == before


@pytest.mark.parametrize("change", ["CREATE TABLE unknown (x)", "CREATE INDEX extra ON muxes(service_id)"])
def test_unexpected_schema_is_rejected(registry, tmp_path, change):
    with sqlite3.connect(tmp_path / "registry" / DATABASE_NAME) as connection:
        connection.execute(change)
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        registry.list_muxes()


def test_unadmitted_sidecar_never_touched(registry, tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"do not alter")
    (tmp_path / "registry" / (DATABASE_NAME + "-journal")).symlink_to(outside)
    with pytest.raises(ManagedStorageError):
        registry.reserve_mux(intent())
    assert outside.read_bytes() == b"do not alter"


def test_capacity_failure_keeps_existing_names_resolvable(registry, monkeypatch):
    registry.reserve_mux(intent())
    monkeypatch.setattr(os, "fstatvfs", lambda fd: SimpleNamespace(f_bavail=0, f_frsize=4096))
    assert registry.reserve_mux(intent()) == intent()
    with pytest.raises(ManagedStorageError, match="capacity"):
        registry.reserve_mux(intent("new", "c" * 32))
    assert registry.resolve("dev") == intent()
    assert registry.resolve("new") is None


def test_service_capacity_is_atomic(registry, monkeypatch, tmp_path):
    monkeypatch.setattr("loushang.apphost.managed.registry.MAX_SERVICES", 1)
    registry.reserve_mux(intent())
    with pytest.raises(ManagedStorageError, match="capacity"):
        registry.reserve_mux(intent("other", "c" * 32, "/other"))
    registry.reserve_mux(intent("same-service", "d" * 32))
    assert [r.name for r in registry.list_muxes()] == ["dev", "same-service"]


def test_native_transaction_rollback_preserves_database(registry):
    with pytest.raises(KeyboardInterrupt):
        with registry._database.transaction(write=True) as connection:
            connection.execute("INSERT INTO services VALUES (?, ?, ?, ?)",
                               ("orphan", "coding", "/orphan", "local-managed/v1"))
            raise KeyboardInterrupt
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM services").fetchone() == (0,)


def test_real_process_death_rolls_back_without_releasing_committed_name(registry, tmp_path, namespace):
    registry.reserve_mux(intent())
    for index in range(20):
        registry.reserve_mux(intent(f"seed-{index}", f"{index:032x}", "/" + str(index) + "x" * 1000))
    database = tmp_path / "registry" / DATABASE_NAME
    committed = database.read_bytes()
    script = """
import os, sys
from pathlib import Path
from loushang.apphost.managed.registry import ManagedRegistryV1
from loushang.apphost.managed.contracts import ManagedNamespaceV1
root = Path(sys.argv[1])
owner = ManagedRegistryV1(root, ManagedNamespaceV1(sys.argv[2], os.geteuid(), 'a'*32))
with owner._database.transaction(write=True) as connection:
    connection.execute('PRAGMA cache_size=1')
    connection.execute('PRAGMA cache_spill=1')
    connection.execute('DELETE FROM muxes')
    connection.execute('DELETE FROM services')
    os._exit(23)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    process = subprocess.run([sys.executable, "-c", script, str(tmp_path / "registry"),
                              namespace.platform_home], env=env, capture_output=True, timeout=10)
    assert process.returncode == 23, process.stderr
    journal = database.with_name(DATABASE_NAME + "-journal")
    journal_bytes = journal.read_bytes()
    assert len(journal_bytes) > 512
    assert journal_bytes[:8] != b"\0" * 8
    assert database.read_bytes() != committed  # Uncommitted pages really spilled.
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in database.parent.iterdir()}
    with pytest.raises(ManagedStorageError):
        ManagedRegistryV1(database.parent, namespace)
    with pytest.raises(ManagedStorageError):
        registry.resolve("dev")
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in database.parent.iterdir()}
    # An explicit writable owner can perform SQLite's journal recovery. A plain
    # lookup must not silently mutate a database that requires crash recovery.
    recovery = ManagedRegistryV1(tmp_path / "registry", namespace, create=True)
    try:
        assert recovery.resolve("dev") == intent()
        assert len(recovery.list_muxes()) == 21
        assert database.read_bytes() == committed
        assert not journal.exists()
    finally:
        recovery.close()


def test_real_process_contention_cannot_duplicate_name(registry, tmp_path, namespace):
    script = """
import os, sys
from pathlib import Path
from loushang.apphost.managed.registry import ManagedRegistryV1, ManagedMuxReservationV1
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
from loushang.apphost.managed._files import ManagedStorageError
try:
    owner = ManagedRegistryV1(Path(sys.argv[1]), ManagedNamespaceV1(sys.argv[2], os.geteuid(), 'a'*32))
    try:
        owner.reserve_mux(ManagedMuxReservationV1('dev', ManagedServiceKeyV1('coding', '/workspace'), sys.argv[3]))
        print('reserved')
    finally:
        owner.close()
except ManagedStorageError as error:
    print(error.code)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    with registry._database.transaction(write=True):
        child = subprocess.run([sys.executable, "-c", script, str(tmp_path / "registry"),
                                namespace.platform_home, "c" * 32], env=env,
                               capture_output=True, text=True, timeout=10)
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == "busy"
    registry.reserve_mux(intent())
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path / "registry"),
                            namespace.platform_home, "c" * 32], env=env,
                           capture_output=True, text=True, timeout=10)
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "conflict"
    assert registry.list_muxes() == (intent(),)


def test_failed_connection_close_retains_cleanup_owner(registry, monkeypatch):
    original_connect = sqlite3.connect
    fail = True

    class FailingClose(sqlite3.Connection):
        def close(self):
            if fail:
                raise sqlite3.OperationalError("private cleanup details")
            super().close()

    def connect(*args, **kwargs):
        return original_connect(*args, factory=FailingClose, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(ManagedStorageError, match="unavailable"):
        registry.resolve("dev")
    assert registry.cleanup_pending
    with pytest.raises(ManagedStorageError, match="busy"):
        registry.resolve("dev")
    with pytest.raises(ManagedStorageError, match="unavailable"):
        registry.close()
    assert registry.cleanup_pending
    fail = False
    registry.close()
    assert not registry.cleanup_pending


def test_concurrent_close_cannot_lose_new_connection_debt(registry, monkeypatch):
    original_connect = sqlite3.connect
    directory = registry._database._directory
    original_mutex = directory._mutex
    holding = threading.Event()
    release = threading.Event()
    close_waiting = threading.Event()
    fail_close = True
    failures = []

    class TrackedMutex:
        def __enter__(self):
            if threading.current_thread().name == "registry-closer":
                close_waiting.set()
            original_mutex.acquire()
            return self

        def __exit__(self, *args):
            original_mutex.release()

    class FailingClose(sqlite3.Connection):
        def close(self):
            if fail_close:
                raise sqlite3.OperationalError("injected cleanup failure")
            super().close()

    def connect(*args, **kwargs):
        return original_connect(*args, factory=FailingClose, **kwargs)

    def transact():
        try:
            with registry._database.transaction():
                holding.set()
                assert release.wait(10)
        except BaseException as error:
            failures.append(error)

    def close():
        try:
            registry.close()
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(directory, "_mutex", TrackedMutex())
    transaction = threading.Thread(target=transact)
    closer = threading.Thread(target=close, name="registry-closer")
    transaction.start()
    try:
        assert holding.wait(10)
        closer.start()
        assert close_waiting.wait(10)
    finally:
        release.set()
        transaction.join(10)
        if closer.ident is not None:
            closer.join(10)
    assert not transaction.is_alive() and not closer.is_alive()
    assert len(failures) == 2
    assert all(isinstance(error, ManagedStorageError) for error in failures)
    assert registry.cleanup_pending
    assert directory._fd is not None
    fail_close = False
    registry.close()  # Different thread from creation: still serialized and valid.
    assert not registry.cleanup_pending


def test_name_insert_failure_rolls_back_new_service_too(registry, monkeypatch):
    original_connect = sqlite3.connect

    class FailMuxInsert(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO muxes"):
                raise sqlite3.OperationalError("injected insertion failure")
            return super().execute(sql, parameters)

    def connect(*args, **kwargs):
        return original_connect(*args, factory=FailMuxInsert, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            registry.reserve_mux(intent())
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM services").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM muxes").fetchone() == (0,)


def test_corrupt_orphan_is_not_hidden_by_join(registry, tmp_path):
    with sqlite3.connect(tmp_path / "registry" / DATABASE_NAME) as connection:
        connection.execute("INSERT INTO muxes VALUES (?, ?, ?)", ("dev", "missing", "a" * 32))
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        registry.resolve("dev")


def test_mux_capacity_failure_does_not_allocate_service(registry, monkeypatch):
    registry.reserve_mux(intent())
    monkeypatch.setattr("loushang.apphost.managed.registry.MAX_MUXES", 1)
    with pytest.raises(ManagedStorageError, match="capacity"):
        registry.reserve_mux(intent("other", "c" * 32, "/other"))
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM services").fetchone() == (1,)

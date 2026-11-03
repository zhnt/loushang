from __future__ import annotations

import os
import selectors
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._database import DATABASE_NAME
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.admission_record import (
    ManagedInitializationPhaseV1,
    ManagedServiceAdmissionRecordV1,
)
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    ManagedStopEvidenceV1,
)
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.paths import (
    resolve_managed_registry_root,
    resolve_managed_service_paths,
)
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.hosting.service import LinuxServiceIdentityV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux service-control admission")


@pytest.fixture
def namespace(tmp_path):
    identity = ManagedNamespaceV1(str(tmp_path / "home"), os.geteuid(), "a" * 32)
    owner = ManagedNamespaceAdmissionV1(identity, runtime_root=str(tmp_path / "runtime"), create_if_missing=True)
    try:
        owner.open(deadline=monotonic() + 10)
        yield owner
    finally:
        owner.close()


def service(namespace, name="coding"):
    return ManagedServiceKeyV1(name, str(Path(namespace._namespace.platform_home).parent))


def paths(namespace, key):
    return resolve_managed_service_paths(namespace._namespace, key, runtime_root=namespace._runtime_root)


def tree(root):
    return {str(path.relative_to(root)): (path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None) for path in (root, *root.rglob("*"))}


def stored(namespace, key):
    with namespace.registry._database.transaction() as connection:
        row = connection.execute("SELECT record FROM service_controls WHERE service_id=?", (key.service_id,)).fetchone()
    return None if row is None else ManagedServiceAdmissionRecordV1.from_json(row[0])


def test_new_service_has_control_fact_before_any_instance_and_reopens_read_only(namespace, tmp_path):
    key = service(namespace)
    first = ManagedServiceAdmissionV1(namespace, key)
    try:
        journal = first.open(deadline=monotonic() + 10)
        assert journal is first.journal and journal.read() is None
        control = stored(namespace, key)
        assert control.phase is ManagedInitializationPhaseV1.INITIALIZED
        assert control.root_identity == journal._fence._identity
        assert not (tmp_path / "home/data").exists()
    finally:
        first.close()
    before = tree(tmp_path)
    second = ManagedServiceAdmissionV1(namespace, key)
    try:
        assert second.open(deadline=monotonic() + 10).read() is None
        assert stored(namespace, key) == control
    finally:
        second.close()
    assert tree(tmp_path) == before and not first.cleanup_pending and not second.cleanup_pending


def test_managed_journal_cannot_create_fence_before_control_fact(namespace):
    key = service(namespace)
    root = Path(paths(namespace, key).lifecycle)
    journal = ManagedServiceJournalV1(namespace.registry, namespace._namespace, key, root, create=True, defer_open=True)
    try:
        with pytest.raises(ManagedStorageError, match="conflict"):
            journal.open(deadline=monotonic() + 10)
    finally:
        journal.close()
    assert not root.exists() and stored(namespace, key) is None


@pytest.mark.parametrize("stage", ["intent", "root", "lock", "publish"])
def test_failure_after_control_intent_cannot_reinitialize_even_without_instances(namespace, monkeypatch, stage):
    key = service(namespace)
    owner = ManagedServiceAdmissionV1(namespace, key)
    initialize, opening, locking = owner._initialize, owner._fresh.open, owner._fresh.lock

    def fail(*args, **kwargs):
        raise ManagedStorageError("unavailable")

    def opened(**kwargs):
        opening(**kwargs)
        raise ManagedStorageError("unavailable")

    def after_publish(*args):
        initialize(*args)
        raise ManagedStorageError("unavailable")

    try:
        with monkeypatch.context() as patch:
            if stage == "intent":
                patch.setattr(owner, "_initialize", fail)
            elif stage == "root":
                patch.setattr(owner._fresh, "open", opened)
            elif stage == "lock":
                patch.setattr(owner._fresh, "lock", fail)
            else:
                patch.setattr(owner, "_initialize", after_publish)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.open(deadline=monotonic() + 10)
        assert owner._fresh.lock == locking
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.open(deadline=monotonic() + 10)
    finally:
        owner.close()
    before = tree(Path(namespace._namespace.platform_home))
    other = ManagedServiceAdmissionV1(namespace, key)
    try:
        if stage == "publish":
            assert other.open(deadline=monotonic() + 10).read() is None
        else:
            with pytest.raises(ManagedStorageError, match="unavailable"):
                other.open(deadline=monotonic() + 10)
    finally:
        other.close()
    assert tree(Path(namespace._namespace.platform_home)) == before


@pytest.mark.parametrize("target", ["root", "lock", "record"])
def test_lost_control_never_recreated_when_instance_table_empty(namespace, tmp_path, target):
    key = service(namespace)
    first = ManagedServiceAdmissionV1(namespace, key)
    first.open(deadline=monotonic() + 10)
    first.close()
    root = Path(paths(namespace, key).lifecycle)
    if target == "record":
        with namespace.registry._database.transaction(write=True) as connection:
            connection.execute("DELETE FROM service_controls WHERE service_id=?", (key.service_id,))
    else:
        selected = root if target == "root" else root / "lifecycle.lock"
        selected.rename(tmp_path / "displaced")
    before = tree(tmp_path)
    other = ManagedServiceAdmissionV1(namespace, key)
    try:
        with pytest.raises(ManagedStorageError):
            other.open(deadline=monotonic() + 10)
    finally:
        other.close()
    assert tree(tmp_path) == before


@pytest.mark.parametrize("target", ["root", "lock"])
def test_byte_identical_replacement_fence_is_not_adopted(namespace, tmp_path, target):
    key = service(namespace)
    first = ManagedServiceAdmissionV1(namespace, key)
    first.open(deadline=monotonic() + 10)
    first.close()
    root = Path(paths(namespace, key).lifecycle)
    selected = root if target == "root" else root / "lifecycle.lock"
    displaced = tmp_path / "displaced"
    selected.rename(displaced)
    if target == "root":
        shutil.copytree(displaced, selected)
    else:
        shutil.copy2(displaced, selected)
    before = tree(tmp_path)
    other = ManagedServiceAdmissionV1(namespace, key)
    try:
        with pytest.raises(ManagedStorageError, match="conflict"):
            other.open(deadline=monotonic() + 10)
    finally:
        other.close()
    assert tree(tmp_path) == before


@pytest.mark.parametrize("operation", ["read", "prepare", "abort", "stop", "register", "commit",
                                       "child_stop", "child_cleanup", "evidence"])
def test_original_journal_rechecks_control_in_each_transaction(namespace, operation):
    key = service(namespace)
    owner = ManagedServiceAdmissionV1(namespace, key)
    try:
        journal = owner.open(deadline=monotonic() + 10)
        state = journal.prepare("d" * 32, expected=None)
        with namespace.registry._database.transaction(write=True) as connection:
            connection.execute("DELETE FROM service_controls WHERE service_id=?", (key.service_id,))
        identity = LinuxServiceIdentityV1(12345, 100, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", os.geteuid(), 1, 2)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            if operation == "read":
                journal.read()
            elif operation == "prepare":
                journal.prepare("e" * 32, expected=state)
            elif operation == "abort":
                journal.abort(state.handoff.instance, "d" * 32)
            elif operation == "stop":
                journal.request_stop(state.handoff.instance)
            elif operation == "register":
                journal.register_native(state.handoff.instance, "d" * 32, identity)
            elif operation == "commit":
                journal.commit(state.handoff.instance, "d" * 32, native_identity=identity)
            elif operation == "child_stop":
                journal.request_child_stop(state.handoff.instance, "d" * 32, identity)
            elif operation == "child_cleanup":
                journal.record_child_cleanup(state.handoff.instance, "d" * 32, identity)
            else:
                journal.record_stop_evidence(ManagedStopEvidenceV1(state.handoff.instance, False, False, False))
        with namespace.registry._database.transaction() as connection:
            assert connection.execute("SELECT revision FROM instances").fetchone() == (1,)
    finally:
        owner.close()


def test_namespace_cannot_downgrade_to_manual_service_admission(namespace):
    root = Path(resolve_managed_registry_root(namespace._namespace))
    with sqlite3.connect(root / DATABASE_NAME) as connection:
        connection.execute("UPDATE identity SET service_admission=0")
    with pytest.raises(ManagedStorageError, match="conflict"):
        namespace.registry.list_muxes()
    other = ManagedNamespaceAdmissionV1(namespace._namespace, runtime_root=namespace._runtime_root)
    try:
        with pytest.raises(ManagedStorageError, match="conflict"):
            other.open(deadline=monotonic() + 10)
    finally:
        other.close()


def test_service_record_roundtrip_and_partial_identity_rejected(namespace):
    value = ManagedServiceAdmissionRecordV1(service(namespace).service_id, "d" * 32,
                                           ManagedInitializationPhaseV1.INITIALIZING)
    assert ManagedServiceAdmissionRecordV1.from_json(value.to_json()) == value
    with pytest.raises(ManagedContractError):
        replace(value, root_identity=(1, 2))
    complete = replace(value, phase=ManagedInitializationPhaseV1.INITIALIZED,
                       root_identity=(1, 2), lock_identity=(1, 3))
    assert ManagedServiceAdmissionRecordV1.from_json(complete.to_json()) == complete


def test_initializing_raw_journal_never_steals_new_service_lock(namespace, monkeypatch):
    key = service(namespace)
    creator = ManagedServiceAdmissionV1(namespace, key)
    contender = ManagedServiceJournalV1(namespace.registry, namespace._namespace, key,
                                        Path(paths(namespace, key).lifecycle), defer_open=True)
    opening = creator._fresh._open
    observations = []

    def forbidden(*args, **kwargs):
        raise AssertionError("initializing journal attempted to steal fresh lock")

    def before_flock(name, *args, **kwargs):
        result = opening(name, *args, **kwargs)
        if name == "lifecycle.lock":
            observations.append(name)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                contender.open(deadline=monotonic() + 10)
            assert not contender._fence._attempted
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(creator._fresh, "_open", before_flock)
            patch.setattr(contender._fence, "lock", forbidden)
            assert creator.open(deadline=monotonic() + 10).read() is None
        assert observations == ["lifecycle.lock"]
    finally:
        contender.close()
        creator.close()


def test_failed_journal_close_keeps_original_and_closes_independent_resources(namespace, monkeypatch):
    owner = ManagedServiceAdmissionV1(namespace, service(namespace))
    journal = owner.open(deadline=monotonic() + 10)
    calls = []

    def failed():
        calls.append("close")
        raise ManagedStorageError("unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(journal, "close", failed)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.close()
        assert owner._journal is journal and owner.cleanup_pending
        assert owner._closed == {"fresh", "probe"}
        assert namespace.registry.list_muxes() == ()
    finally:
        owner.close()
    assert calls == ["close"] and not owner.cleanup_pending
    other = ManagedServiceAdmissionV1(namespace, service(namespace, "work"))
    try:
        assert other.open(deadline=monotonic() + 10).read() is None
    finally:
        other.close()


@pytest.mark.parametrize("broken", ["{}", "[]", "{", '{"phase":"initialized","phase":"initializing"}',
                                   '{"version":"unknown"}', "[" * 1100 + "]" * 1100])
def test_corrupt_control_is_fixed_error_and_cannot_mutate_instance(namespace, broken):
    key = service(namespace)
    owner = ManagedServiceAdmissionV1(namespace, key)
    try:
        journal = owner.open(deadline=monotonic() + 10)
        state = journal.prepare("d" * 32, expected=None)
        with namespace.registry._database.transaction(write=True) as connection:
            before = connection.execute("SELECT * FROM instances").fetchall()
            connection.execute("UPDATE service_controls SET record=? WHERE service_id=?", (broken, key.service_id))
        with pytest.raises(ManagedStorageError, match="^managed_storage_invalid_record$"):
            journal.request_stop(state.handoff.instance)
        with namespace.registry._database.transaction() as connection:
            assert connection.execute("SELECT * FROM instances").fetchall() == before
    finally:
        owner.close()


_CHILD = """
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
root, stage, gate = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
ns = ManagedNamespaceV1(str(root / 'home'), os.geteuid(), 'a' * 32)
namespace = ManagedNamespaceAdmissionV1(ns, runtime_root=str(root / 'runtime'))
namespace.open(deadline=monotonic() + 10)
owner = ManagedServiceAdmissionV1(namespace, ManagedServiceKeyV1('coding', str(root)))
claim, initialize, opening, locking = owner._claim, owner._initialize, owner._fresh.open, owner._fresh.lock
created = 0
def claimed(deadline, *, wait_for_lock=False):
    if gate >= 0:
        print('ready', flush=True)
        assert os.read(gate, 1) == b'x'
        os.close(gate)
    result = claim(deadline, wait_for_lock=wait_for_lock)
    if stage == 'intent':
        os._exit(23)
    return result
def opened(**kwargs):
    global created
    created += 1
    result = opening(**kwargs)
    if stage == 'root':
        os._exit(23)
    return result
@contextmanager
def locked(*args, **kwargs):
    with locking(*args, **kwargs):
        if stage == 'lock':
            os._exit(23)
        yield
def initialized(deadline):
    result = initialize(deadline)
    if stage == 'published':
        os._exit(23)
    return result
owner._claim, owner._fresh.open, owner._fresh.lock, owner._initialize = claimed, opened, locked, initialized
try:
    owner.open(deadline=monotonic() + 10)
    print('admitted', created, flush=True)
except ManagedStorageError as error:
    print(error.code, created, flush=True)
finally:
    try:
        owner.close()
    finally:
        namespace.close()
"""


def child_env():
    return dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))


@pytest.mark.parametrize("stage", ["intent", "root", "lock", "published"])
def test_real_service_initializer_exit_never_uses_empty_instances_as_creation_proof(namespace, tmp_path, stage):
    child = subprocess.run([sys.executable, "-c", _CHILD, str(tmp_path), stage, "-1"],
                           env=child_env(), capture_output=True, text=True, timeout=15)
    assert child.returncode == 23, child.stderr
    key = service(namespace)
    control = stored(namespace, key)
    assert control is not None
    root = Path(paths(namespace, key).lifecycle)
    assert root.exists() is (stage != "intent")
    assert (root / "lifecycle.lock").exists() is (stage in {"lock", "published"})
    before = tree(tmp_path)
    other = ManagedServiceAdmissionV1(namespace, key)
    try:
        if stage == "published":
            assert other.open(deadline=monotonic() + 10).read() is None
        else:
            with pytest.raises(ManagedStorageError, match="unavailable"):
                other.open(deadline=monotonic() + 10)
    finally:
        other.close()
    assert stored(namespace, key) == control and tree(tmp_path) == before


def test_two_real_service_initializers_publish_only_one_fence(namespace, tmp_path):
    gate_read, gate_write = os.pipe()
    children = []
    try:
        for _ in range(2):
            children.append(subprocess.Popen(
                [sys.executable, "-c", _CHILD, str(tmp_path), "compete", str(gate_read)],
                env=child_env(), pass_fds=(gate_read,), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            ))
            child = children[-1]
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=10), "service initializer did not reach intent gate"
            assert child.stdout.readline().strip() == "ready"
        assert os.write(gate_write, b"xx") == 2
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr
            result, count = stdout.strip().split()
            results.append((result, int(count)))
        assert sum(count for _, count in results) == 1
        assert any(result == "admitted" for result, _ in results)
        assert {result for result, _ in results} <= {"admitted", "busy", "unavailable"}
    finally:
        os.close(gate_read)
        os.close(gate_write)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
    key = service(namespace)
    control = stored(namespace, key)
    before = tree(tmp_path)
    reopeners = [ManagedServiceAdmissionV1(namespace, key) for _ in range(2)]
    try:
        for owner in reopeners:
            journal = owner.open(deadline=monotonic() + 10)
            assert journal.read() is None
            assert journal._fence._identity == control.root_identity
            assert stored(namespace, key) == control
    finally:
        for owner in reopeners:
            owner.close()
    assert tree(tmp_path) == before


@pytest.mark.parametrize("when", ["before", "after"])
def test_publication_contention_settles_original_fence_without_recreation(namespace, monkeypatch, when):
    owner = ManagedServiceAdmissionV1(namespace, service(namespace))
    transaction = namespace.registry._database.transaction
    opening = owner._fresh.open
    attempts, opens = [], []

    def opened(**kwargs):
        opens.append(1)
        return opening(**kwargs)

    @contextmanager
    def busy(**kwargs):
        publishing = bool(owner._fresh._locks)
        if publishing:
            attempts.append(1)
        fail = publishing and len(attempts) <= 2
        if fail and when == "before":
            raise ManagedStorageError("busy")
        with transaction(**kwargs) as connection:
            yield connection
        if fail and when == "after":
            raise ManagedStorageError("busy")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner._fresh, "open", opened)
            patch.setattr(namespace.registry._database, "transaction", busy)
            assert owner.open(deadline=monotonic() + 10).read() is None
        assert len(attempts) == 3 and len(opens) == 1
        assert stored(namespace, service(namespace)).phase is ManagedInitializationPhaseV1.INITIALIZED
    finally:
        owner.close()

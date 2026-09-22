from __future__ import annotations

import os
import selectors
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._database import DATABASE_NAME
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.admission_record import (
    ManagedInitializationPhaseV1,
    ManagedNamespaceAdmissionRecordV1,
)
from loushang.apphost.managed.contracts import ManagedNamespaceV1
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.paths import (
    resolve_managed_admission_root,
    resolve_managed_registry_root,
)
from loushang.apphost.managed.registry import ManagedRegistryV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux namespace admission")


def namespace(root):
    return ManagedNamespaceV1(str(root / "home"), os.geteuid(), "a" * 32)


def owner(root, *, create=False):
    return ManagedNamespaceAdmissionV1(namespace(root), runtime_root=str(root / "runtime"),
                                        create_if_missing=create)


def tree(root):
    return {str(path.relative_to(root)): (path.stat().st_dev, path.stat().st_ino,
            path.stat().st_mode, path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None) for path in (root, *root.rglob("*"))}


def initialize(root):
    admission = owner(root, create=True)
    try:
        registry = admission.open(deadline=monotonic() + 10)
        assert registry is admission.registry
        assert registry.list_muxes() == ()
    finally:
        admission.close()
    assert not admission.cleanup_pending


@pytest.mark.parametrize("suffix", ["state", "state/session-stores", "state/other-product"])
def test_namespace_runtime_cannot_enter_shared_durable_state(tmp_path, suffix):
    from loushang.apphost.managed.contracts import ManagedContractError

    value = namespace(tmp_path)
    before = tree(tmp_path)
    with pytest.raises(ManagedContractError):
        ManagedNamespaceAdmissionV1(value, runtime_root=str(Path(value.platform_home) / suffix),
                                    create_if_missing=True)
    assert tree(tmp_path) == before


def test_first_home_creates_bound_registry_but_no_sessions_or_service(tmp_path):
    admission = owner(tmp_path, create=True)
    assert set(tree(tmp_path)) == {"."}
    try:
        registry = admission.open(deadline=monotonic() + 10)
        marker = Path(resolve_managed_admission_root(namespace(tmp_path))) / "admission.json"
        record = ManagedNamespaceAdmissionRecordV1.from_json(marker.read_text())
        assert record.phase is ManagedInitializationPhaseV1.INITIALIZED
        assert record.deployment_id == registry._database.deployment_id
        assert record.database_identity == registry._database._file_identity
        assert record.registry_lock_identity == registry._database._lock_identity
        assert not (tmp_path / "home/data").exists()
        assert not (tmp_path / "home/lmux/machines" / ("a" * 32) / "lifecycle").exists()
        with pytest.raises(ManagedStorageError, match="closed"):
            admission.open(deadline=monotonic() + 10)
    finally:
        admission.close()
    assert not admission.cleanup_pending


@pytest.mark.parametrize("create", [False, True])
def test_reopen_is_full_tree_read_only_and_retains_same_deployment(tmp_path, create):
    initialize(tmp_path)
    before = tree(tmp_path)
    admission = owner(tmp_path, create=create)
    try:
        assert admission.open(deadline=monotonic() + 10).list_muxes() == ()
    finally:
        admission.close()
    assert tree(tmp_path) == before


def test_missing_read_only_namespace_never_creates_anything(tmp_path):
    before = tree(tmp_path)
    admission = owner(tmp_path)
    try:
        with pytest.raises(ManagedStorageError, match="not_found"):
            admission.open(deadline=monotonic() + 10)
    finally:
        admission.close()
    assert tree(tmp_path) == before and not admission.cleanup_pending


@pytest.mark.parametrize("residue", ["machine", "runtime"])
def test_missing_admission_with_control_residue_never_creates_witness(tmp_path, residue):
    ns = namespace(tmp_path)
    path = (Path(resolve_managed_registry_root(ns)).parent if residue == "machine"
            else tmp_path / "runtime/lmux" / ns.namespace_key)
    current = tmp_path
    for part in path.relative_to(tmp_path).parts:
        current /= part
        current.mkdir(mode=0o700)
    before = tree(tmp_path)
    admission = owner(tmp_path, create=True)
    try:
        with pytest.raises(ManagedStorageError, match="conflict"):
            admission.open(deadline=monotonic() + 10)
    finally:
        admission.close()
    assert tree(tmp_path) == before
    assert not Path(resolve_managed_admission_root(ns)).exists()


@pytest.mark.parametrize("target", ["witness", "marker", "admission_lock", "registry", "database", "registry_lock"])
@pytest.mark.parametrize("replace", [False, True])
def test_missing_control_replaced_bound_identity_or_corrupt_marker_is_rejected(tmp_path, target, replace):
    initialize(tmp_path)
    witness = Path(resolve_managed_admission_root(namespace(tmp_path)))
    registry = Path(resolve_managed_registry_root(namespace(tmp_path)))
    paths = {"witness": witness, "marker": witness / "admission.json",
             "admission_lock": witness / "admission.lock", "registry": registry,
             "database": registry / DATABASE_NAME, "registry_lock": registry / "registry.lock"}
    selected = paths[target]
    displaced = tmp_path / "displaced"
    selected.rename(displaced)
    if replace:
        if displaced.is_dir():
            shutil.copytree(displaced, selected)
        elif target == "marker":
            selected.write_text("{}")
            selected.chmod(0o600)
        else:
            shutil.copy2(displaced, selected)
    before = tree(tmp_path)
    admission = owner(tmp_path, create=True)
    try:
        with pytest.raises(ManagedStorageError):
            admission.open(deadline=monotonic() + 10)
        with pytest.raises(ManagedStorageError, match="closed"):
            _ = admission.registry
    finally:
        admission.close()
    assert tree(tmp_path) == before


def test_equivalent_atomic_marker_copy_preserves_authority_without_rewriting(tmp_path):
    initialize(tmp_path)
    marker = Path(resolve_managed_admission_root(namespace(tmp_path))) / "admission.json"
    old = marker.stat().st_ino
    copy = tmp_path / "marker-copy"
    shutil.copy2(marker, copy)
    copy.replace(marker)
    assert marker.stat().st_ino != old
    before = tree(tmp_path)
    admission = owner(tmp_path)
    try:
        assert admission.open(deadline=monotonic() + 10).list_muxes() == ()
    finally:
        admission.close()
    assert tree(tmp_path) == before


@pytest.mark.parametrize("phase", ["intent", "database", "publish"])
def test_initialization_failures_leave_unavailable_intent_without_replay(tmp_path, monkeypatch, phase):
    admission = owner(tmp_path, create=True)
    write = admission._fresh.write
    calls = []

    def fail_write(name, content, **kwargs):
        calls.append(content)
        if phase == "intent" or (phase == "publish" and len(calls) == 2):
            raise ManagedStorageError("unavailable")
        return write(name, content, **kwargs)

    def fail_database(self, **kwargs):
        raise ManagedStorageError("unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(admission._fresh, "write", fail_write)
            if phase == "database":
                patch.setattr(ManagedRegistryV1, "open", fail_database)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                admission.open(deadline=monotonic() + 10)
        with pytest.raises(ManagedStorageError, match="closed"):
            admission.open(deadline=monotonic() + 10)
    finally:
        admission.close()
    before = tree(tmp_path)
    other = owner(tmp_path, create=True)
    try:
        with pytest.raises(ManagedStorageError):
            other.open(deadline=monotonic() + 10)
    finally:
        other.close()
    assert tree(tmp_path) == before


def test_database_nonce_cannot_be_adopted(tmp_path):
    initialize(tmp_path)
    database = Path(resolve_managed_registry_root(namespace(tmp_path))) / DATABASE_NAME
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE identity SET deployment=?", ("f" * 32,))
    before = tree(tmp_path)
    admission = owner(tmp_path, create=True)
    try:
        with pytest.raises(ManagedStorageError, match="conflict"):
            admission.open(deadline=monotonic() + 10)
    finally:
        admission.close()
    assert tree(tmp_path) == before


@pytest.mark.parametrize("stage", ["intent", "database", "published"])
def test_lost_success_receipt_retains_original_owner_and_never_replays(tmp_path, monkeypatch, stage):
    admission = owner(tmp_path, create=True)
    write, opened = admission._fresh.write, ManagedRegistryV1.open
    calls = []

    def lost_write(*args, **kwargs):
        result = write(*args, **kwargs)
        calls.append("write")
        if (stage == "intent" and len(calls) == 1) or (stage == "published" and len(calls) == 2):
            raise ManagedStorageError("unavailable")
        return result

    def lost_open(self, **kwargs):
        result = opened(self, **kwargs)
        if stage == "database":
            raise ManagedStorageError("unavailable")
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(admission._fresh, "write", lost_write)
            patch.setattr(ManagedRegistryV1, "open", lost_open)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                admission.open(deadline=monotonic() + 10)
        if stage != "intent":
            assert admission._registry is not None and admission._registry._database._opened
        else:
            assert admission._registry is None
        with pytest.raises(ManagedStorageError, match="closed"):
            admission.open(deadline=monotonic() + 10)
    finally:
        admission.close()
    before = tree(tmp_path)
    reopened = owner(tmp_path, create=True)
    try:
        if stage == "published":
            reopened.open(deadline=monotonic() + 10)
        else:
            with pytest.raises(ManagedStorageError, match="unavailable"):
                reopened.open(deadline=monotonic() + 10)
    finally:
        reopened.close()
    assert tree(tmp_path) == before


def test_registry_close_failure_does_not_skip_independent_directory_cleanup(tmp_path, monkeypatch):
    admission = owner(tmp_path, create=True)
    registry = admission.open(deadline=monotonic() + 10)
    closed = registry.close
    calls = []

    def fail():
        calls.append("failed")
        raise ManagedStorageError("unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(registry, "close", fail)
            with pytest.raises(ManagedStorageError, match="unavailable"):
                admission.close()
        assert admission._registry is registry and not admission._registry_closed
        assert admission._closed == set(range(len(admission._directories)))
        assert admission.cleanup_pending
        assert registry.close == closed
    finally:
        admission.close()
    assert not admission.cleanup_pending and calls == ["failed"]


_CHILD = """
import os
import sys
from pathlib import Path
from time import monotonic
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedNamespaceV1
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.registry import ManagedRegistryV1
root, stage, gate = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
ns = ManagedNamespaceV1(str(root / 'home'), os.geteuid(), 'a' * 32)
owner = ManagedNamespaceAdmissionV1(ns, runtime_root=str(root / 'runtime'), create_if_missing=True)
original_write, original_open = owner._fresh.write, ManagedRegistryV1.open
original_fresh_open = owner._fresh.open
writes = 0
def write(*args, **kwargs):
    global writes
    writes += 1
    if stage == 'before_intent':
        os._exit(23)
    result = original_write(*args, **kwargs)
    if (stage == 'intent' and writes == 1) or (stage == 'published' and writes == 2):
        os._exit(23)
    return result
def opened(self, **kwargs):
    result = original_open(self, **kwargs)
    if stage == 'database':
        os._exit(23)
    return result
owner._fresh.write = write
ManagedRegistryV1.open = opened
def fresh_open(**kwargs):
    print('ready', flush=True)
    assert os.read(gate, 1) == b'x'
    os.close(gate)
    return original_fresh_open(**kwargs)
if stage == 'compete':
    owner._fresh.open = fresh_open
elif gate >= 0:
    print('ready', flush=True)
    assert os.read(gate, 1) == b'x'
    os.close(gate)
try:
    owner.open(deadline=monotonic() + 10)
    print('admitted', flush=True)
except ManagedStorageError as error:
    print(error.code, flush=True)
finally:
    owner.close()
"""


def child_env():
    return dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))


@pytest.mark.parametrize("stage", ["before_intent", "intent", "database", "published"])
def test_real_process_exit_preserves_unknown_or_durable_completion(tmp_path, stage):
    child = subprocess.run([sys.executable, "-c", _CHILD, str(tmp_path), stage, "-1"],
                           env=child_env(), capture_output=True, text=True, timeout=15)
    assert child.returncode == 23, child.stderr
    before = tree(tmp_path)
    admission = owner(tmp_path, create=True)
    try:
        if stage == "published":
            assert admission.open(deadline=monotonic() + 10).list_muxes() == ()
        else:
            with pytest.raises(ManagedStorageError):
                admission.open(deadline=monotonic() + 10)
    finally:
        admission.close()
    assert tree(tmp_path) == before
    registry = Path(resolve_managed_registry_root(namespace(tmp_path)))
    if stage in {"database", "published"}:
        assert (registry / DATABASE_NAME).exists()
    else:
        assert not registry.exists()


def test_two_real_initializers_settle_to_one_reopenable_namespace(tmp_path):
    gate_read, gate_write = os.pipe()
    children = []
    try:
        for _ in range(2):
            children.append(subprocess.Popen(
                [sys.executable, "-c", _CHILD, str(tmp_path), "compete", str(gate_read)],
                env=child_env(), pass_fds=(gate_read,), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            ))
        for child in children:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=10), "initializer did not reach gate"
            assert child.stdout.readline().strip() == "ready"
        assert os.write(gate_write, b"xx") == 2
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr
            results.append(stdout.strip())
        assert sorted(results) == ["admitted", "conflict"]
    finally:
        os.close(gate_read)
        os.close(gate_write)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
    before = tree(tmp_path)
    admission = owner(tmp_path)
    try:
        admission.open(deadline=monotonic() + 10)
    finally:
        admission.close()
    assert tree(tmp_path) == before


def test_markerless_reopener_cannot_steal_new_initializers_lock(tmp_path, monkeypatch):
    creator = owner(tmp_path, create=True)
    contender = owner(tmp_path, create=True)
    opening = creator._fresh._open
    observed = []

    def forbidden(*args, **kwargs):
        raise AssertionError("markerless reader attempted to take initializer lock")

    def at_created_lock(name, *args, **kwargs):
        result = opening(name, *args, **kwargs)
        if name == "admission.lock":
            # The lock file really exists and has synced, but its creator has
            # not flocked it yet. An unfixed reopener can steal it right here.
            observed.append(name)
            with pytest.raises(ManagedStorageError, match="invalid_record"):
                contender.open(deadline=monotonic() + 10)
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(creator._fresh, "_open", at_created_lock)
            patch.setattr(contender._existing, "lock", forbidden)
            creator.open(deadline=monotonic() + 10)
        assert observed == ["admission.lock"]
        assert creator.registry.list_muxes() == ()
        assert contender._registry is None
    finally:
        contender.close()
        creator.close()
    before = tree(tmp_path)
    reopened = owner(tmp_path)
    try:
        reopened.open(deadline=monotonic() + 10)
    finally:
        reopened.close()
    assert tree(tmp_path) == before

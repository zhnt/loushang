from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedServiceKeyV1,
    ManagedStopEvidenceV1,
)
from loushang.apphost.managed.discovery import (
    ManagedDiscoveryV1,
    ManagedMuxObservationV1,
)
from loushang.apphost.managed.paths import resolve_managed_registry_root
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1
from loushang.hosting.service import LinuxServiceObserverV1
from tests.apphost.test_managed_connection import committed
from tests.apphost.test_managed_starter import owners as owners

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed discovery")


@pytest.fixture
def discovery(owners):
    namespace = owners[1]
    registry = ManagedRegistryV1(Path(resolve_managed_registry_root(namespace)), namespace)
    try:
        yield ManagedDiscoveryV1(registry, namespace), registry
    finally:
        registry.close()


def test_global_lookup_from_other_cwd_is_readonly_and_contains_no_native_facts(owners, discovery, tmp_path, monkeypatch):
    state = committed(owners)
    reader, registry = discovery
    other = tmp_path / "other"
    other.mkdir()
    root = Path(resolve_managed_registry_root(owners[1]))
    def snapshot():
        result = {}
        for path in (root, *root.rglob("*")):
            info = path.lstat()
            result[path.relative_to(root)] = (
                info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
        return result

    before = snapshot()
    monkeypatch.chdir(other)

    def forbidden(*args, **kwargs):
        raise AssertionError("discovery must not perform a native liveness check")

    monkeypatch.setattr(LinuxServiceObserverV1, "reopen", forbidden)
    result = reader.resolve("main", deadline=monotonic() + 5)
    assert result.instance == state.handoff.instance
    assert result.recorded_phase is ManagedHandoffPhaseV1.COMMITTED
    assert result.service.workspace == str(tmp_path)
    assert not result.stop_requested and not result.cleanly_stopped
    assert result.reservation == registry.resolve("main")
    assert reader.list_muxes(deadline=monotonic() + 5) == (result,)
    assert reader.resolve("missing", deadline=monotonic() + 5) is None
    assert set(asdict(result)) == {
        "reservation", "instance", "revision", "recorded_phase", "stop_requested", "cleanly_stopped",
    }
    assert not any(hasattr(result, name) for name in ("pid", "native_identity", "endpoint", "record_path", "argv", "key"))
    with pytest.raises(FrozenInstanceError):
        result.revision = 99
    assert before == snapshot()
    assert owners[0].read() == state


def test_reservation_without_instance_does_not_invent_ready_or_start(owners, discovery):
    reader, registry = discovery
    result = reader.resolve("main", deadline=monotonic() + 5)
    assert result.reservation == registry.resolve("main")
    assert result.instance is result.revision is result.recorded_phase is None
    assert not result.stop_requested and not result.cleanly_stopped
    assert owners[0].read() is None


def test_service_snapshot_survives_mux_name_release_without_native_authority(owners, discovery):
    reader, registry = discovery
    service = owners[2]
    initial = reader.inspect_service(service.service_id, deadline=monotonic() + 5)
    assert initial.service == service and initial.instance is None
    state = committed(owners)
    observed = reader.inspect_service(service.service_id, deadline=monotonic() + 5)
    assert observed.instance == state.handoff.instance and observed.recorded_phase is ManagedHandoffPhaseV1.COMMITTED
    assert not hasattr(observed, "native_identity") and not hasattr(observed, "pid")
    assert reader.inspect_service("f" * 64, deadline=monotonic() + 5) is None
    # Storage fixture only: read by service must not require the mux join.
    with registry._database.transaction(write=True) as connection:
        connection.execute("DELETE FROM muxes WHERE service_id=?", (service.service_id,))
    assert reader.list_muxes(deadline=monotonic() + 5) == ()
    assert reader.inspect_service(service.service_id, deadline=monotonic() + 5) == observed


def test_durable_start_stop_observations_do_not_retarget_prior_reference(owners, discovery):
    journal = owners[0]
    reader, _ = discovery
    state = journal.prepare("c" * 32, expected=None)
    first = reader.resolve("main", deadline=monotonic() + 5)
    assert first.recorded_phase is ManagedHandoffPhaseV1.PROVISIONAL
    assert first.instance == state.handoff.instance
    journal.abort(state.handoff.instance, "c" * 32)
    second = reader.resolve("main", deadline=monotonic() + 5)
    assert second.recorded_phase is ManagedHandoffPhaseV1.ABORTING
    assert second.instance == first.instance and second.revision > first.revision
    assert not second.cleanly_stopped
    assert first.recorded_phase is ManagedHandoffPhaseV1.PROVISIONAL


def test_committed_stop_flag_is_visible_without_claiming_exit(owners, discovery):
    state = committed(owners)
    owners[0].request_stop(state.handoff.instance)
    result = discovery[0].resolve("main", deadline=monotonic() + 5)
    assert result.recorded_phase is ManagedHandoffPhaseV1.COMMITTED and result.stop_requested
    assert not result.cleanly_stopped


def test_fully_settled_record_and_new_generation_keep_old_reference_frozen(owners, discovery):
    journal = owners[0]
    reader, _ = discovery
    # Pure durable state transition: no actual service is launched in this test.
    first = journal.prepare("c" * 32, expected=None)
    journal.abort(first.handoff.instance, "c" * 32)
    settled = journal.record_stop_evidence(ManagedStopEvidenceV1(first.handoff.instance, True, True, True))
    old = reader.resolve("main", deadline=monotonic() + 5)
    assert old.cleanly_stopped and old.instance == first.handoff.instance
    second = journal.prepare("d" * 32, expected=settled)
    new = reader.resolve("main", deadline=monotonic() + 5)
    assert new.instance == second.handoff.instance != old.instance
    assert new.revision > old.revision and new.recorded_phase is ManagedHandoffPhaseV1.PROVISIONAL
    assert not new.cleanly_stopped and not new.stop_requested
    assert old.cleanly_stopped and old.instance == first.handoff.instance


def test_default_page_really_stops_at_64_rows(discovery, owners):
    reader, registry = discovery
    for index in range(64):
        registry.reserve_mux(ManagedMuxReservationV1(f"mux-{index:02}", owners[2], f"{index:032x}"))
    first = reader.list_muxes(deadline=monotonic() + 5)
    assert len(first) == 64 and first[0].name == "main" and first[-1].name == "mux-62"
    second = reader.list_muxes(deadline=monotonic() + 5, after=first[-1].name)
    assert [item.name for item in second] == ["mux-63"]


def test_bounded_pagination_includes_other_workspaces_and_products(owners, discovery):
    reader, registry = discovery
    for index, (name, product, workspace) in enumerate((
        ("Alpha", "work", "/other"), ("alpha", "coding", "/third"), ("zzz", "design", "/fourth"),
    )):
        registry.reserve_mux(ManagedMuxReservationV1(name, ManagedServiceKeyV1(product, workspace), f"{index:032x}"))
    first = reader.list_muxes(deadline=monotonic() + 5, limit=2)
    second = reader.list_muxes(deadline=monotonic() + 5, after=first[-1].name, limit=2)
    assert [r.name for r in first + second] == ["Alpha", "alpha", "main", "zzz"]
    assert first[0].service.product_id == "work"
    assert reader.list_muxes(deadline=monotonic() + 5, after="zzz") == ()
    for limit in (0, 65, True, "2"):
        with pytest.raises(ManagedContractError):
            reader.list_muxes(deadline=monotonic() + 5, limit=limit)
    for name in ("../main", "", "a\x1bb"):
        with pytest.raises(ManagedContractError):
            reader.resolve(name, deadline=monotonic() + 5)
        with pytest.raises(ManagedContractError):
            reader.list_muxes(deadline=monotonic() + 5, after=name)


@pytest.mark.parametrize("change", [
    "phase='invalid'", "stop_requested=2", "native_identity='{}'", "instance_id='invalid'",
    "native_identity=NULL", "application_cleanup_completed=1",
])
def test_corrupt_state_is_not_partially_projected(owners, discovery, change):
    committed(owners)
    reader, registry = discovery
    # Deliberate on-disk corruption bypasses the writer's deferred paired FK.
    with sqlite3.connect(registry._database._directory._root / "registry.sqlite3") as connection:
        connection.execute("UPDATE instances SET " + change)
    for operation in (lambda: reader.resolve("main", deadline=monotonic() + 5),
                      lambda: reader.list_muxes(deadline=monotonic() + 5), owners[0].read):
        with pytest.raises(ManagedStorageError, match="invalid_record"):
            operation()


def test_expired_deadline_and_closed_registry_are_not_empty_results(owners, discovery):
    reader, registry = discovery
    for operation in (lambda: reader.resolve("main", deadline=monotonic() - 1),
                      lambda: reader.list_muxes(deadline=monotonic() - 1)):
        with pytest.raises(ManagedStorageError, match="busy"):
            operation()
    registry.close()
    with pytest.raises(ManagedStorageError, match="closed"):
        reader.resolve("main", deadline=monotonic() + 5)


def test_discovery_requires_same_namespace_user_and_canonical_registry(owners, discovery, tmp_path):
    namespace = owners[1]
    for other in (replace(namespace, user_id=os.geteuid() + 1), replace(namespace, machine_id="d" * 32)):
        with pytest.raises(ManagedContractError):
            ManagedDiscoveryV1(discovery[1], other)
    other_registry = ManagedRegistryV1(tmp_path / "other-registry", namespace, create=True)
    try:
        with pytest.raises(ManagedContractError):
            ManagedDiscoveryV1(other_registry, namespace)
    finally:
        other_registry.close()


def test_missing_registry_is_not_initialized_by_discovery(tmp_path, owners):
    namespace = replace(owners[1], platform_home=str(tmp_path / "missing-home"))
    root = Path(resolve_managed_registry_root(namespace))
    registry = ManagedRegistryV1(root, namespace, defer_open=True)
    try:
        reader = ManagedDiscoveryV1(registry, namespace)
        with pytest.raises(ManagedStorageError):
            reader.resolve("main", deadline=monotonic() + 5)
        assert not root.exists() and not Path(namespace.platform_home).exists()
    finally:
        registry.close()


def test_observation_rejects_incoherent_values(owners, discovery):
    value = discovery[0].resolve("main", deadline=monotonic() + 5)
    with pytest.raises(ManagedContractError):
        replace(value, revision=1)
    with pytest.raises(ManagedContractError):
        replace(value, stop_requested=True)
    state = committed(owners)
    value = discovery[0].resolve("main", deadline=monotonic() + 5)
    for invalid in (replace(state.handoff.instance, service_id="f" * 64), None):
        with pytest.raises(ManagedContractError):
            replace(value, instance=invalid)
    with pytest.raises(ManagedContractError):
        replace(value, cleanly_stopped=True)
    assert isinstance(value, ManagedMuxObservationV1)

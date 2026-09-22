from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.connection import ManagedConnectionLeaseV1
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
from loushang.apphost.managed.coordinator import ManagedServiceCoordinatorV1
from loushang.apphost.managed.discovery import ManagedDiscoveryV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.mux_creation import ManagedMuxCreateOperationV1
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.paths import (
    resolve_managed_registry_root,
    resolve_managed_service_paths,
)
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1
from loushang.apphost.managed.service_admission import ManagedServiceAdmissionV1
from loushang.apphost.managed.starter import ManagedServiceStarterV1
from loushang.appserver.local import LocalAppClientConnectionV1, LocalConnectionModeV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1, LocalRecordError
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxCreateV1,
    MuxSelectorV1,
    SessionListV1,
    SessionOpenSpecV1,
)
from loushang.coding.managed_process import (
    APPLICATION_ID,
    ENDPOINT,
    coding_managed_process_request,
)
from loushang.harnesstui.mux import open_hosted_mux_profile
from loushang.hosting.service import LinuxServiceObserverV1
from tests.apphost.test_managed_starter import owners as owners
from tests.hosting._pidfd_signal import send_signal

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed process entry")


async def _same_control_operation(operation, *, deadline):
    """Retry only explicit short native lock contention, on the same intent."""
    while True:
        try:
            return operation()
        except ManagedStorageError as error:
            if error.code != "busy" or monotonic() >= deadline:
                raise
            await asyncio.sleep(min(0.01, max(0, deadline - monotonic())))


def test_production_module_starts_real_service_reconnects_and_stops(owners, tmp_path):
    journal, namespace, service, runtime_root = owners
    sessions = Path(namespace.platform_home) / "data/sessions"
    sessions.mkdir(parents=True, mode=0o700)

    def request(invocation, descriptor):
        return coding_managed_process_request(
            invocation, descriptor, executable=sys.executable, environment=os.environ,
        )

    starter = ManagedServiceStarterV1(journal, namespace, service, runtime_root=runtime_root, request_factory=request)
    observer = None
    process = None

    async def scenario():
        directory = LocalConnectionDirectoryV1(Path(starter._layout.paths.connection))
        registry = ManagedRegistryV1(Path(resolve_managed_registry_root(namespace)), namespace, defer_open=True)
        manager_journal = None
        clients = []
        try:
            deadline = monotonic() + 20
            while True:
                try:
                    record = directory.read(ENDPOINT)
                    break
                except LocalRecordError:
                    assert monotonic() < deadline, "production child did not publish a connection"
                    assert process.poll() is None, "production child exited before connection publication"
                    await asyncio.sleep(0.02)
            await asyncio.to_thread(registry.open, deadline=deadline, wait_for_lock=True)
            discovery = ManagedDiscoveryV1(registry, namespace)
            target = discovery.resolve("main", deadline=deadline)
            assert target is not None and target.instance is not None
            reference = target.instance
            instance = reference.instance_id

            async def prepare_exact(deadline):
                # A published endpoint is not a promise that the short native
                # journal fence is currently free. Settle each failed lease
                # before retrying the same frozen instance and budget.
                while True:
                    candidate = ManagedConnectionLeaseV1(
                        journal, namespace, service, reference, runtime_root=runtime_root, endpoint=ENDPOINT,
                    )
                    clients.append(candidate)
                    try:
                        await candidate.prepare(deadline=deadline)
                        return candidate
                    except ManagedStorageError as error:
                        await candidate.close()
                        assert not candidate.cleanup_pending
                        if error.code != "busy" or monotonic() >= deadline:
                            raise
                        await asyncio.sleep(min(0.01, max(0, deadline - monotonic())))

            stop = LocalAppClientConnectionV1(directory, ENDPOINT, mode=LocalConnectionModeV1.STOP, expected_instance=instance)
            clients.append(stop)
            assert record.application_id == APPLICATION_ID and record.product_id == "coding"
            assert record.instance == instance
            assert record.mux_management, "production managed child must publish managed creation"
            assert record.mux_closure, "production recovery binding must explicitly publish close capability"
            client = await prepare_exact(deadline)
            from loushang.apphost.managed.mux_management import ManagedMuxManagerV1

            manager_journal = ManagedServiceJournalV1(
                registry, namespace, service, Path(starter._layout.paths.lifecycle),
            )
            manager = ManagedMuxManagerV1(registry, manager_journal, namespace, service, reference,
                                          application_id=APPLICATION_ID)
            reservation = registry.resolve(target.name)
            permit = await _same_control_operation(lambda: manager.issue_create(reservation, deadline=deadline), deadline=deadline)
            with pytest.raises(AppServiceError):
                await client.client.create_mux(MuxCreateV1(target.name))
            with pytest.raises(AppServiceError):
                await client.managed_mux_client.create_managed_mux(replace(permit, authority="forged"))
            assert not (await client.client.list_muxes()).mux_spaces
            created = await client.managed_mux_client.create_managed_mux(permit)
            assert await _same_control_operation(
                lambda: manager.record_created(permit, created, deadline=deadline), deadline=deadline,
            ) == created
            before = await client.client.list_muxes()
            assert before.mux_spaces and before.mux_spaces[0].mux_space_id == created.mux_space_id
            assert journal.read().handoff.phase.value == "committed"
            # Close only parent launch/client handles. Real child remains alive
            # and a fresh protocol connection recovers the same Mux metadata.
            starter.close()
            await client.close()
            assert not observer.exited()
            assert discovery.resolve("main", deadline=monotonic() + 5).instance == reference
            fresh = await prepare_exact(monotonic() + 10)
            after = await fresh.client.list_muxes()
            assert after == before
            assert await fresh.managed_mux_client.create_managed_mux(permit) == created
            close_deadline = monotonic() + 10
            close = await _same_control_operation(
                lambda: manager.issue_close(reservation, operation_id="d" * 32, deadline=close_deadline),
                deadline=close_deadline,
            )
            assert fresh.managed_mux_close_client is not None
            assert await fresh.managed_mux_close_client.read_managed_mux_close(close) is None
            closed = await fresh.managed_mux_close_client.close_managed_mux(close)
            assert closed.phase.value == "closed"
            assert await fresh.managed_mux_close_client.read_managed_mux_close(close) == closed
            await _same_control_operation(lambda: manager.record_close(close, closed, deadline=close_deadline),
                                          deadline=close_deadline)
            assert registry.resolve(target.name) is None
            await stop.start()
            assert stop.stop_requested
            assert await asyncio.to_thread(observer.exited, timeout=10)
            assert process.wait(timeout=5) == 0
            events = [json.loads(line) for path in Path(starter._layout.paths.logs).glob("*.jsonl")
                      for line in path.read_bytes().splitlines()]
            # Diagnostics are finite best-effort, not a delivery/exit authority.
            expected_events = ["starting", "ready", "stopping", "stopped"]
            names = [item["event"] for item in events]
            assert len(names) == len(set(names))
            assert names == [name for name in expected_events if name in names]
            assert all(item["instanceId"] == instance for item in events)
            assert all(set(item) == {"v", "event", "instanceId", "code", "sequence"} for item in events)
            evidence = journal.read().evidence
            assert evidence.application_cleanup_completed
            assert not evidence.process_exited and not evidence.process_scope_settled
            assert not tuple(sessions.glob("*.jsonl"))  # No model/Session invocation.
        finally:
            try:
                await asyncio.gather(*(item.close() for item in clients))
            finally:
                try:
                    directory.close()
                finally:
                    if manager_journal is not None:
                        manager_journal.close()
                    registry.close()

    try:
        # A busy durable registration is reconciled on the original process.
        try:
            state = starter.start(expected=None, deadline=monotonic() + 10)
        except ManagedStorageError as error:
            if error.code != "busy":
                raise
            state = starter.register_birth(deadline=monotonic() + 5)
        process = starter._process._process
        observer = LinuxServiceObserverV1.capture(state.native_identity.pid)
        assert observer.identity == state.native_identity
        asyncio.run(scenario())
    finally:
        # Failure teardown signals only the exact retained test-owned pidfd.
        _stop_original(starter, observer)


def _stop_original(starter, observer=None):
    native = starter._process
    process = native._process if native is not None else None
    selected = observer if observer is not None else (native._observer if native is not None else None)
    try:
        if process is not None and process.poll() is None:
            assert selected is not None, "live child lacks its retained native observer"
            if not selected.exited():
                send_signal(selected, signal.SIGTERM)
                assert selected.exited(timeout=20)
        if process is not None:
            process.wait(timeout=5)
    finally:
        starter.close()
        if observer is not None:
            observer.close()


def test_entry_teardown_retains_child_after_lost_registration(owners, monkeypatch):
    journal, namespace, service, runtime_root = owners
    (Path(namespace.platform_home) / "data/sessions").mkdir(parents=True, mode=0o700)
    original = journal.register_native

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(journal, "register_native", lost)
    starter = ManagedServiceStarterV1(
        journal, namespace, service, runtime_root=runtime_root,
        request_factory=lambda invocation, fd: coding_managed_process_request(
            invocation, fd, executable=sys.executable, environment=os.environ,
        ),
    )
    try:
        with pytest.raises(ManagedStorageError, match="unavailable"):
            starter.start(expected=None, deadline=monotonic() + 10)
        assert starter._process._process is not None
    finally:
        _stop_original(starter)
    assert starter._process._process.poll() is not None


@pytest.fixture(params=["manual", "admitted"])
def production_owners(request, tmp_path):
    if request.param == "manual":
        yield request.getfixturevalue("owners")
        return
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    runtime = str(tmp_path / "runtime")
    admission = ManagedNamespaceAdmissionV1(namespace, runtime_root=runtime, create_if_missing=True)
    control = None
    assert not Path(namespace.platform_home).exists()
    try:
        registry = admission.open(deadline=monotonic() + 10)
        registry.reserve_mux(ManagedMuxReservationV1("main", service, "b" * 32))
        control = ManagedServiceAdmissionV1(admission, service)
        journal = control.open(deadline=monotonic() + 10)
        yield journal, namespace, service, runtime
    finally:
        try:
            if control is not None:
                control.close()
        finally:
            admission.close()


@pytest.mark.parametrize("scratch_override", [False, True])
def test_creation_operation_cold_start_and_warm_second_name_use_one_real_child(production_owners, tmp_path, scratch_override):
    _, namespace, service, runtime = production_owners
    paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime)
    registry = ManagedRegistryV1(Path(paths.registry), namespace)
    journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle))
    launches = []
    temporary = str(tmp_path / "explicit-scratch") if scratch_override else None

    def request(invocation, descriptor):
        launches.append(invocation)
        return coding_managed_process_request(invocation, descriptor, executable=sys.executable, environment=os.environ)

    operations = [ManagedMuxCreateOperationV1(
        registry, journal, namespace, ManagedMuxReservationV1(name, service, operation_id),
        runtime_root=runtime, endpoint=ENDPOINT, application_id=APPLICATION_ID, request_factory=request,
        temporary_override=temporary,
    ) for name, operation_id in (("main", "b" * 32), ("second", "d" * 32))]
    observer = None

    async def scenario():
        nonlocal observer
        directory = LocalConnectionDirectoryV1(Path(paths.connection))
        stop = None
        try:
            first = await operations[0].run(deadline=monotonic() + 25)
            native = operations[0]._coordinator._starter._process
            observer = LinuxServiceObserverV1.reopen(native.identity)
            assert launches[0].temporary_override == temporary
            scratch = Path(operations[0]._coordinator._starter._layout.paths.temporary)
            assert scratch.is_dir()
            if temporary is not None:
                assert scratch.is_relative_to(temporary)
                assert not (Path(namespace.platform_home) / "lmux/machines" / namespace.machine_id /
                            "servers" / service.service_id / "tmp").exists()
            assert operations[0].connection.application_id == APPLICATION_ID
            await operations[0].close()
            assert not observer.exited()
            second = await operations[1].run(deadline=monotonic() + 15)
            assert first.instance_id == second.instance_id
            assert first.mux_space_id != second.mux_space_id
            assert len(launches) == 1 and operations[1]._coordinator._starter._process is None
            assert {item.name for item in (await operations[1].connection.client.list_muxes()).mux_spaces} == {"main", "second"}
            assert registry.resolve("main").operation_id == first.operation_id
            assert registry.resolve("second").operation_id == second.operation_id
            stop = LocalAppClientConnectionV1(
                directory, ENDPOINT, mode=LocalConnectionModeV1.STOP, expected_instance=second.instance_id,
            )
            await stop.start()
            assert await asyncio.to_thread(observer.exited, timeout=10)
            assert native._process.wait(timeout=5) == 0
        finally:
            try:
                if stop is not None:
                    await stop.close()
                await asyncio.gather(*(operation.close() for operation in operations))
            finally:
                directory.close()

    try:
        asyncio.run(asyncio.wait_for(scenario(), 50))
    finally:
        try:
            _stop_original(operations[0]._coordinator._starter, observer)
            _stop_original(operations[1]._coordinator._starter)
        finally:
            journal.close()
            registry.close()


@pytest.mark.parametrize("busy_birth", [False, True])
def test_concurrent_start_and_warm_reuse_use_one_production_child(production_owners, monkeypatch, busy_birth):
    journal, namespace, service, runtime = production_owners
    session_root = Path(namespace.platform_home) / "data/sessions"
    lazy_store = journal._database.service_admission_required
    if lazy_store:
        assert not session_root.exists()
    else:
        session_root.mkdir(parents=True, mode=0o700)
    requests = []
    registrations = []
    original_register = journal.register_native

    def register(*args, **kwargs):
        registrations.append(1)
        if busy_birth and len(registrations) <= 2:
            raise ManagedStorageError("busy")
        return original_register(*args, **kwargs)

    monkeypatch.setattr(journal, "register_native", register)

    def request(invocation, descriptor):
        requests.append(invocation)
        return coding_managed_process_request(
            invocation, descriptor, executable=sys.executable, environment=os.environ,
        )

    coordinators = [ManagedServiceCoordinatorV1(
        journal, namespace, service, runtime_root=runtime, endpoint=ENDPOINT, request_factory=request,
    ) for _ in range(3)]
    observers = {}

    async def scenario():
        paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime)
        directory = LocalConnectionDirectoryV1(Path(paths.connection))
        registry = ManagedRegistryV1(Path(paths.registry), namespace, defer_open=True)
        manager_journal = None
        stop = None
        tasks = []
        try:
            cold, release = [], asyncio.Event()
            for item in coordinators[:2]:
                original_read = item._read

                def gated_read(original):
                    first = True

                    async def read(deadline):
                        nonlocal first
                        value = await original(deadline)
                        if first:
                            first = False
                            assert value is None
                            cold.append(1)
                            if len(cold) == 2:
                                release.set()
                            await asyncio.wait_for(release.wait(), 5)
                        return value

                    return read

                monkeypatch.setattr(item, "_read", gated_read(original_read))
            deadline = monotonic() + 25
            tasks = [asyncio.create_task(item.ensure_started(deadline=deadline)) for item in coordinators[:2]]
            first, second = await asyncio.gather(*tasks)
            for item in coordinators:
                native = item._starter._process
                if native is not None and native.identity is not None:
                    observers[item] = LinuxServiceObserverV1.reopen(native.identity)
            assert len(requests) == len(observers) == 1
            assert len(cold) == 2
            assert sum(item._starter._process is not None and item._starter._process._process is not None
                       for item in coordinators) == 1
            if busy_birth:
                assert len(registrations) >= 3
            assert first.instance == second.instance
            from loushang.apphost.managed.mux_management import ManagedMuxManagerV1

            # The just-started service may still be completing a bounded
            # registry transaction. Join that exact lock instead of turning
            # scheduler timing into a false concurrent-start failure.
            await asyncio.to_thread(
                registry.open, deadline=deadline, wait_for_lock=True,
            )
            manager_journal = ManagedServiceJournalV1(
                registry, namespace, service, Path(paths.lifecycle), defer_open=True,
            )
            await asyncio.to_thread(
                manager_journal.open, deadline=deadline, wait_for_lock=True,
            )
            manager = ManagedMuxManagerV1(registry, manager_journal, namespace, service, first.instance,
                                          application_id=APPLICATION_ID)
            reservation = registry.resolve("main")
            permit = await _same_control_operation(lambda: manager.issue_create(reservation, deadline=deadline), deadline=deadline)
            assert first.managed_mux_client is not None
            created = await first.managed_mux_client.create_managed_mux(permit)
            assert await _same_control_operation(
                lambda: manager.record_created(permit, created, deadline=deadline), deadline=deadline,
            ) == created
            before = await second.client.list_muxes()
            assert before.mux_spaces[0].mux_space_id == created.mux_space_id
            await asyncio.gather(*(item.close() for item in coordinators[:2]))
            native_observer = next(iter(observers.values()))
            assert not native_observer.exited()
            warm = await coordinators[2].ensure_started(deadline=monotonic() + 10)
            assert warm.instance == first.instance and len(requests) == 1
            assert coordinators[2]._starter._process is None
            assert await warm.client.list_muxes() == before
            assert await warm.managed_mux_client.create_managed_mux(permit) == created
            if lazy_store:
                assert not session_root.exists(), "empty Mux startup/reconnect created a Session store"
                assert not (Path(namespace.platform_home) / "state/session-stores").exists()
                scope = directory.read(ENDPOINT).scopes[0]
                query = SessionListV1("coding", scope.scope, scope.fingerprint)
                assert warm.discovery_client is not None
                empty = await warm.discovery_client.list_sessions(query)
                assert empty.complete and not empty.candidates
                assert not session_root.exists()
                assert not (Path(namespace.platform_home) / "state/session-stores").exists()
                controller = await open_hosted_mux_profile(warm.client, selector=MuxSelectorV1(name="main"))
                try:
                    view = await controller.open_member(SessionOpenSpecV1(
                        "coding", "first-manual-session", scope.scope, scope.fingerprint,
                        title="lazy first Session",
                    ))
                    assert len(view.windows) == 1 and session_root.is_dir()
                    session_id = view.windows[0].session_id
                finally:
                    await controller.close()
                controller = await open_hosted_mux_profile(warm.client, selector=MuxSelectorV1(name="main"))
                try:
                    assert len(controller.state.windows) == 1
                    assert controller.state.windows[0].session_id == session_id
                finally:
                    await controller.close()
                page = await warm.discovery_client.list_sessions(query)
                assert page.complete and len(page.candidates) == 1
                saved = session_root.with_name("saved-sessions")
                session_root.rename(saved)
                try:
                    with pytest.raises(AppServiceError) as unavailable:
                        await warm.discovery_client.list_sessions(query)
                    assert unavailable.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
                    assert not session_root.exists()
                finally:
                    saved.rename(session_root)
                assert len((await warm.discovery_client.list_sessions(query)).candidates) == 1
            stop = LocalAppClientConnectionV1(
                directory, ENDPOINT, mode=LocalConnectionModeV1.STOP,
                expected_product_id="coding", expected_instance=warm.instance.instance_id,
            )
            await stop.start()
            assert stop.stop_requested
            assert await asyncio.to_thread(native_observer.exited, timeout=10)
            original = next(item for item in coordinators if item._starter._process is not None)
            assert original._starter._process._process.wait(timeout=5) == 0
        finally:
            try:
                if stop is not None:
                    await stop.close()
            finally:
                try:
                    await asyncio.gather(*(item.close() for item in coordinators))
                    await asyncio.gather(*tasks, return_exceptions=True)
                finally:
                    try:
                        directory.close()
                    finally:
                        try:
                            if manager_journal is not None:
                                manager_journal.close()
                        finally:
                            registry.close()

    try:
        asyncio.run(scenario())
    finally:
        for item in coordinators:
            native = item._starter._process
            observer = observers.get(item)
            # On setup failure close may already have released the parent's
            # pidfd. Re-admit only this test's exact original native identity.
            if (observer is None and native is not None and native._process is not None
                    and native._process.poll() is None):
                observer = LinuxServiceObserverV1.reopen(native.identity)
            _stop_original(item._starter, observer)

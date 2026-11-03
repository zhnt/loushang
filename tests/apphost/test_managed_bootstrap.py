from __future__ import annotations

import asyncio
import os
import socket
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import get_ident
from time import monotonic

import pytest

from loushang.apphost.managed import bootstrap as module
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.bootstrap import ManagedChildBootstrapV1
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.paths import resolve_managed_paths
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1
from loushang.hosting.service import LinuxServiceObserverV1

from .test_managed_child import Application, until

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux child bootstrap")


@pytest.fixture
def deployment(tmp_path):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    placeholder = ManagedInstanceRefV1(namespace.namespace_key, service.service_id, "d" * 32)
    paths = resolve_managed_paths(namespace, service, placeholder, runtime_root=str(tmp_path / "runtime"))
    for path in (paths.registry, paths.lifecycle, paths.application, paths.connection):
        # mkdir(parents=True) does not apply mode to intermediate directories.
        for parent in reversed(Path(path).parents):
            if parent != tmp_path and parent.is_relative_to(tmp_path):
                parent.mkdir(mode=0o700, exist_ok=True)
    registry = ManagedRegistryV1(Path(paths.registry), namespace, create=True)
    registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
    journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle), create=True)
    state = journal.prepare("c" * 32, expected=None)
    paths = resolve_managed_paths(namespace, service, state.handoff.instance, runtime_root=str(tmp_path / "runtime"))
    try:
        yield namespace, service, journal, state, paths
    finally:
        journal.close()
        registry.close()


def make_bootstrap(deployment, tmp_path, **overrides):
    namespace, service, _, state, _ = deployment
    parent, endpoint = socket.socketpair()
    try:
        owner = ManagedChildBootstrapV1(
            overrides.get("namespace", namespace), service,
            overrides.get("instance", state.handoff.instance), overrides.get("attempt", state.handoff.attempt_id),
            endpoint, runtime_root=str(tmp_path / "runtime"),
            diagnostics=overrides.get("diagnostics", False),
        )
    except BaseException:
        parent.close()
        endpoint.close()
        raise
    return owner, parent


def test_managed_binding_borrows_original_dependencies_only_before_application_adoption(deployment, tmp_path, monkeypatch):
    owner, parent = make_bootstrap(deployment, tmp_path)
    try:
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.managed_mux_binding(application_id="coding.default")
        assert owner._mux_manager is None
        owner.open(deadline=monotonic() + 5)
        original_registry, original_journal = owner._registry, owner._journal

        def forbidden(*args, **kwargs):
            pytest.fail("pure management binding acquired another control owner")

        monkeypatch.setattr(module, "ManagedRegistryV1", forbidden)
        monkeypatch.setattr(module, "ManagedServiceJournalV1", forbidden)
        binding = owner.managed_mux_binding(application_id="coding.default")
        assert binding == owner.managed_mux_binding(application_id="coding.default")
        assert owner._mux_manager._registry is original_registry
        assert owner._mux_manager._journal is original_journal
        assert binding.closing is not None and binding.closing.recovery is not None
        assert owner._mux_manager._startup_native is owner._observer.identity
        assert owner._mux_manager._startup_attempt == deployment[3].handoff.attempt_id
        assert original_journal.read().handoff.phase.value == "provisional"
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.managed_mux_binding(application_id="coding.other")
        owner.close()
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.managed_mux_binding(application_id="coding.default")
        assert not owner.cleanup_pending
    finally:
        owner.close()
        parent.close()


def test_original_control_worker_waits_for_managed_commit_without_blocking_loop(deployment, tmp_path, monkeypatch):
    from loushang.appservice import (
        AppServiceRecoveryRequestV1,
        create_appservice_recovery_attempt,
    )
    from tests.appservice.test_continuity_runtime import _MemoryLease, _Resolver

    owner, parent = make_bootstrap(deployment, tmp_path)
    owner.open(deadline=monotonic() + 5)
    binding = owner.managed_mux_binding(application_id="coding.default")
    journal = owner._journal
    instance, attempt_id = deployment[3].handoff.instance, deployment[3].handoff.attempt_id
    journal.register_native(instance, attempt_id, owner._observer.identity)

    async def scenario():
        entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        loop, loop_thread = asyncio.get_running_loop(), get_ident()
        original_lock = journal._fence.lock

        @contextmanager
        def observed_lock(*args, **kwargs):
            if get_ident() != loop_thread:
                loop.call_soon_threadsafe(waiting.set)
            with original_lock(*args, **kwargs):
                yield

        monkeypatch.setattr(journal._fence, "lock", observed_lock)

        class Lease(_MemoryLease):
            async def commit(self, *, expected_revision, record):
                entered.set()
                await release.wait()
                await super().commit(expected_revision=expected_revision, record=record)

        lease = Lease()
        recovery = create_appservice_recovery_attempt(AppServiceRecoveryRequestV1(
            "coding", _Resolver([]), lease, managed_mux=binding,
        ))
        service = await recovery.open()
        journal.commit(instance, attempt_id, native_identity=owner._observer.identity)
        permit = owner._mux_manager.issue_create(owner._registry.resolve("dev"), deadline=monotonic() + 5)
        creation = asyncio.create_task(service.create_managed_mux(permit))
        control = None
        try:
            await entered.wait()
            control = asyncio.create_task(asyncio.to_thread(owner._control.observe, "stop", monotonic() + 5))
            await waiting.wait()
            assert not control.done() and not creation.done()
            release.set()  # Same loop remains able to settle the original commit.
            result = await creation
            stopped = await control
            assert result == lease.record.managed_creations[0]
            assert stopped.handoff.stop_requested
            assert len(lease.commits) == 1
        finally:
            release.set()
            await asyncio.gather(creation, *(() if control is None else (control,)), return_exceptions=True)
            await service.close()

    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        owner.close()
        parent.close()


def test_capture_factory_before_failed_bind_can_close_without_entering_loop(deployment, tmp_path):
    from loushang.apphost.managed._files import PrivateManagedDirectory

    owner, parent = make_bootstrap(deployment, tmp_path)
    scratch = PrivateManagedDirectory(Path(deployment[4].temporary), create=True, create_parents=True)
    scratch.close()
    try:
        owner.open(deadline=monotonic() + 5)
        factory = owner.output_capture_factory(deadline=monotonic() + 5)
        with pytest.raises(TypeError):
            owner.bind(object())
        assert owner._child is None and factory._loop is None
        owner.close()
        assert factory.settled and not owner.cleanup_pending
    finally:
        parent.close()
        owner.close()


def test_capture_factory_settles_before_shared_directory_and_registry(deployment, tmp_path, monkeypatch):
    from loushang.apphost.managed._files import PrivateManagedDirectory

    owner, parent = make_bootstrap(deployment, tmp_path)
    _, _, _, _, paths = deployment
    scratch = PrivateManagedDirectory(Path(paths.temporary), create=True, create_parents=True)
    scratch.close()
    try:
        owner.open(deadline=monotonic() + 5)
        factory = owner.output_capture_factory(deadline=monotonic() + 5)
        assert owner.output_capture_factory(deadline=monotonic() + 5) is factory
        registry, observer = owner._registry, owner._observer

        async def scenario():
            factory.new_capture()
            with pytest.raises(ManagedStorageError, match="busy"):
                await asyncio.to_thread(owner.close)
            assert owner._registry is registry and owner._capture_directory is not None
            await factory.close()
            assert factory.settled

        asyncio.run(scenario())
        directory = owner._capture_directory
        original_close = directory.close
        calls = 0

        def fail_once():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ManagedStorageError("busy")
            original_close()

        monkeypatch.setattr(directory, "close", fail_once)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.close()
        assert owner._capture_directory is directory
        assert owner._registry is registry and owner._observer is observer
        owner.close()
        assert not owner.cleanup_pending and calls == 2
    finally:
        parent.close()
        owner.close()


def test_bootstrap_real_layout_late_registration_and_bound_dependency_lifetime(deployment, tmp_path, monkeypatch):
    _, _, journal, state, paths = deployment
    owner, parent = make_bootstrap(deployment, tmp_path)
    owner.open(deadline=monotonic() + 5)
    assert owner.paths == paths
    assert journal.read().native_identity is None
    application = Application()
    child = owner.bind(application)
    with pytest.raises(ManagedStorageError, match="busy"):
        owner.close()  # Child has not even run yet, but owns its dependencies.
    assert not owner._closing

    async def scenario():
        observed = asyncio.Event()
        loop = asyncio.get_running_loop()
        original_observe = owner._control.observe
        observations = 0

        def observe(*args, **kwargs):
            nonlocal observations
            result = original_observe(*args, **kwargs)
            if result is not None and result.native_identity is None:
                observations += 1
                if observations == 2:  # Driver has processed the first snapshot.
                    loop.call_soon_threadsafe(observed.set)
            return result

        monkeypatch.setattr(owner._control, "observe", observe)
        runner = asyncio.create_task(child.run())
        try:
            await observed.wait()
            assert not child.accepting and child._prepare_task is None
            assert application.prepares == 0 and not application.prepared.is_set()
            journal.register_native(state.handoff.instance, state.handoff.attempt_id, owner._observer.identity)
            await until(lambda: child.accepting)
            assert application.prepares == 1
            parent.close()
            await asyncio.sleep(0.03)
            assert child.accepting
            await child.close()
            await runner
        finally:
            await child.close(retry_timeout=5)
            await asyncio.gather(runner, return_exceptions=True)
    try:
        asyncio.run(asyncio.wait_for(scenario(), 10))
    finally:
        parent.close()
        owner.close()
    assert not owner.cleanup_pending
    assert journal.read().evidence.application_cleanup_completed


def test_bootstrap_call_matrix_rejects_without_new_io_or_adoption(deployment, tmp_path, monkeypatch):
    owner, parent = make_bootstrap(deployment, tmp_path)
    application = Application()
    try:
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.bind(application)
        owner.open(deadline=monotonic() + 5)
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.open(deadline=monotonic() + 5)
        child = owner.bind(application)
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", lambda *a, **kw: pytest.fail("illegal operation performed IO"))
            with pytest.raises(ManagedStorageError, match="closed"):
                owner.open(deadline=monotonic() + 5)
            with pytest.raises(ManagedStorageError, match="closed"):
                owner.bind(application)
        asyncio.run(child.close())
        owner.close()
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.bind(Application())
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.open(deadline=monotonic() + 5)
    finally:
        parent.close()
        owner.close()


@pytest.mark.parametrize("mismatch", ["attempt", "instance", "native"])
def test_bootstrap_refuses_mismatched_binding(deployment, tmp_path, mismatch):
    _, _, journal, state, _ = deployment
    overrides = {}
    if mismatch == "native":
        observer = LinuxServiceObserverV1.capture(os.getpid())
        try:
            journal.register_native(state.handoff.instance, state.handoff.attempt_id,
                                    replace(observer.identity, start_ticks=observer.identity.start_ticks + 1))
        finally:
            observer.close()
    else:
        overrides[mismatch] = ("e" * 32 if mismatch == "attempt"
                               else replace(state.handoff.instance, instance_id="e" * 32))
    owner, parent = make_bootstrap(deployment, tmp_path, **overrides)
    before = journal.read()
    try:
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.open(deadline=monotonic() + 5)
        assert owner._control is None and owner._child is None
        assert journal.read() == before
    finally:
        parent.close()
        owner.close()


def test_bootstrap_failed_admission_retry_replaces_only_failed_container(deployment, tmp_path, monkeypatch):
    owner, parent = make_bootstrap(deployment, tmp_path)
    original = ManagedServiceJournalV1.open
    calls = []

    def fail_once(self, *, deadline=None):
        calls.append(self)
        original(self, deadline=deadline)
        if len(calls) == 1:
            raise ManagedStorageError("busy")

    monkeypatch.setattr(ManagedServiceJournalV1, "open", fail_once)
    deadline = monotonic() + 5
    try:
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.open(deadline=deadline)
        registry, failed = owner._registry, owner._journal
        assert failed is not None
        owner.open(deadline=deadline + 100)
        assert owner._registry is registry and owner._journal is not failed
        assert owner._deadline == deadline
        with pytest.raises(ManagedStorageError, match="closed"):
            failed.read()
    finally:
        parent.close()
        owner.close()


def test_bootstrap_cannot_extend_failed_admission_deadline(deployment, tmp_path, monkeypatch):
    from loushang.apphost.managed import _files

    owner, parent = make_bootstrap(deployment, tmp_path)
    now = [1.0]
    monkeypatch.setattr(_files, "monotonic", lambda: now[0])

    def fail(self, **kwargs):
        raise ManagedStorageError("busy")

    monkeypatch.setattr(ManagedRegistryV1, "open", fail)
    try:
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.open(deadline=2)
        registry = owner._registry
        now[0] = 3.0
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.open(deadline=100)
        assert owner._registry is registry and owner._deadline == 2
    finally:
        parent.close()
        owner.close()


@pytest.mark.parametrize("dependency", ["control", "journal", "registry"])
def test_bootstrap_partial_close_preserves_failed_owner_and_registry_order(deployment, tmp_path, monkeypatch, dependency):
    owner, parent = make_bootstrap(deployment, tmp_path)
    owner.open(deadline=monotonic() + 5)
    resource = getattr(owner, "_" + dependency)
    registry = owner._registry
    original = resource.close
    calls = []

    def fail_once():
        calls.append(1)
        if len(calls) == 1:
            raise ManagedStorageError("busy")
        original()

    monkeypatch.setattr(resource, "close", fail_once)
    try:
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.close()
        assert getattr(owner, "_" + dependency) is resource
        if dependency == "journal":
            assert owner._registry is registry
            assert registry.resolve("dev") is not None
        with pytest.raises(ManagedStorageError, match="closed"):
            owner.open(deadline=monotonic() + 5)
        owner.close()
        assert not owner.cleanup_pending and len(calls) == 2
    finally:
        parent.close()
        owner.close()


def test_bootstrap_native_close_uncertainty_does_not_skip_other_dependencies(deployment, tmp_path, monkeypatch):
    owner, parent = make_bootstrap(deployment, tmp_path)
    owner.open(deadline=monotonic() + 5)
    observer = owner._observer
    original = observer.close
    calls = []

    def unknown_close():
        calls.append(1)
        original()
        raise OSError("uncertain native close")

    monkeypatch.setattr(observer, "close", unknown_close)
    try:
        for _ in range(2):
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.close()
        assert owner.cleanup_pending and calls == [1]
        assert owner._journal is None and owner._registry is None and owner._control is None
    finally:
        parent.close()


def test_failed_native_capture_is_not_repeated_or_declared_clean(deployment, tmp_path, monkeypatch):
    owner, parent = make_bootstrap(deployment, tmp_path)
    calls = []

    def fail(pid):
        calls.append(pid)
        raise OSError("capture failed without a returned owner")

    monkeypatch.setattr(module.LinuxServiceObserverV1, "capture", fail)
    try:
        with pytest.raises(OSError):
            owner.open(deadline=monotonic() + 5)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.open(deadline=monotonic() + 5)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.close()
        assert owner.cleanup_pending and calls == [os.getpid()]
        assert owner._journal is None and owner._registry is None and owner._endpoint is None
    finally:
        parent.close()


def test_adopted_control_native_close_failure_remains_debt_and_preserves_reused_fd(deployment, tmp_path, monkeypatch):
    owner, parent = make_bootstrap(deployment, tmp_path)
    endpoint = owner._endpoint
    owner.open(deadline=monotonic() + 5)
    original = socket.socket._real_close
    calls, replacements = [], []

    def uncertain_close(self):
        original(self)
        if self is endpoint:
            calls.append(1)
            replacements.append(os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY))
            raise OSError("native socket closed but result is uncertain")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(socket.socket, "_real_close", uncertain_close)
            for _ in range(2):
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    owner.close()
        assert owner.cleanup_pending and owner._control is not None
        assert calls == [1] and endpoint.fileno() == -1
        assert owner._journal is None and owner._registry is None
        os.fstat(replacements[0])
    finally:
        parent.close()
        for fd in replacements:
            os.close(fd)


def test_constructor_revokes_inheritance_on_adopted_endpoint_without_database_io(deployment, tmp_path, monkeypatch):
    namespace, service, _, state, _ = deployment
    parent, endpoint = socket.socketpair()
    endpoint.set_inheritable(True)
    owner = None
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", lambda *a, **kw: pytest.fail("construction performed file IO"))
            owner = ManagedChildBootstrapV1(namespace, service, state.handoff.instance, state.handoff.attempt_id,
                                            endpoint, runtime_root=str(tmp_path / "runtime"))
        assert not endpoint.get_inheritable() and owner._endpoint is endpoint
        assert owner._registry is None and owner._observer is None
    finally:
        parent.close()
        if owner is not None:
            owner.close()
        else:
            endpoint.close()


@pytest.mark.parametrize("socket_kind", ["unconnected", "datagram", "tcp"])
def test_constructor_rejects_wrong_socket_shape_without_adopting_it(deployment, tmp_path, socket_kind):
    namespace, service, _, state, _ = deployment
    family = socket.AF_INET if socket_kind == "tcp" else socket.AF_UNIX
    kind = socket.SOCK_DGRAM if socket_kind == "datagram" else socket.SOCK_STREAM
    endpoint = socket.socket(family, kind)
    endpoint.set_inheritable(True)
    try:
        with pytest.raises(ManagedContractError):
            ManagedChildBootstrapV1(namespace, service, state.handoff.instance, state.handoff.attempt_id,
                                    endpoint, runtime_root=str(tmp_path / "runtime"))
        assert endpoint.fileno() >= 0 and endpoint.get_inheritable()
    finally:
        endpoint.close()


def test_bootstrap_rejects_native_io_on_application_event_loop(deployment, tmp_path):
    owner, parent = make_bootstrap(deployment, tmp_path)

    async def scenario():
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.open(deadline=monotonic() + 5)
        with pytest.raises(ManagedStorageError, match="busy"):
            owner.close()
    try:
        asyncio.run(scenario())
        assert owner._registry is None
    finally:
        parent.close()
        owner.close()


def test_constructor_and_bind_failure_leave_inputs_with_caller(deployment, tmp_path):
    namespace, service, _, state, _ = deployment
    parent, endpoint = socket.socketpair()
    try:
        wrong_namespace = replace(namespace, user_id=namespace.user_id + 1)
        with pytest.raises(ManagedContractError):
            ManagedChildBootstrapV1(wrong_namespace, service,
                                    replace(state.handoff.instance, namespace_key=wrong_namespace.namespace_key),
                                    state.handoff.attempt_id, endpoint,
                                    runtime_root=str(tmp_path / "runtime"))
        assert endpoint.fileno() >= 0
    finally:
        parent.close()
        endpoint.close()
    owner, parent = make_bootstrap(deployment, tmp_path)
    application = Application()
    try:
        owner.open(deadline=monotonic() + 5)
        with pytest.raises(ValueError):
            owner.bind(application, startup_timeout=0)
        assert owner._child is None and application.closes == 0 and not application.fenced
    finally:
        parent.close()
        owner.close()


@pytest.mark.parametrize("deadline", [None, True, 0, float("inf"), float("nan")])
def test_bootstrap_requires_finite_absolute_deadline_before_io(deployment, tmp_path, deadline):
    owner, parent = make_bootstrap(deployment, tmp_path)
    try:
        with pytest.raises(ManagedContractError):
            owner.open(deadline=deadline)
        assert owner._registry is None and owner._observer is None
    finally:
        parent.close()
        owner.close()

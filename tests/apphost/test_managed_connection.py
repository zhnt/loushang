from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from threading import Event
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory
from loushang.apphost.managed.connection import ManagedConnectionLeaseV1
from loushang.apphost.managed.contracts import ManagedContractError
from loushang.appserver.client import AppConnectionClosedError
from loushang.hosting.service import LinuxServiceObserverV1
from tests.apphost.test_managed_starter import owners as owners

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed connection")


def committed(owners):
    journal = owners[0]
    provisional = journal.prepare("c" * 32, expected=None)
    observer = LinuxServiceObserverV1.capture(os.getpid())
    try:
        identity = observer.identity
        journal.register_native(provisional.handoff.instance, "c" * 32, identity)
        return journal.commit(provisional.handoff.instance, "c" * 32, native_identity=identity)
    finally:
        observer.close()


def lease(owners, instance):
    journal, namespace, service, runtime = owners
    return ManagedConnectionLeaseV1(journal, namespace, service, instance, runtime_root=runtime, endpoint="workspace")


def fake_connection(monkeypatch):
    connections = []

    class Connection:
        def __init__(self, directory, endpoint, **kwargs):
            self.directory, self.endpoint, self.selection = directory, endpoint, kwargs
            self.client = object()
            self.discovery_client = self.execution_client = None
            self.scopes = ()
            self.started = False
            self.closed = False
            self.start_hook = None
            self.close_error = False
            connections.append(self)

        async def start(self):
            self.started = True
            if start_hook is not None:
                await start_hook(self)

        async def close(self):
            if self.close_error:
                raise RuntimeError("injected_cleanup")
            self.closed = True

    start_hook = None

    def on_start(callback):
        nonlocal start_hook
        start_hook = callback

    monkeypatch.setattr("loushang.apphost.managed.connection.LocalAppClientConnectionV1", Connection)
    return connections, on_start


def test_exact_instance_prepare_is_readonly_and_close_does_not_stop(owners, monkeypatch):
    state = committed(owners)
    connections, _ = fake_connection(monkeypatch)
    owner = lease(owners, state.handoff.instance)

    async def scenario():
        with pytest.raises(AppConnectionClosedError):
            _ = owner.client
        await owner.prepare(deadline=monotonic() + 5)
        assert owner.client is connections[0].client
        assert owner.instance == state.handoff.instance
        assert connections[0].selection["expected_instance"] == state.handoff.instance.instance_id
        assert connections[0].selection["expected_product_id"] == "coding"
        assert owner.scopes == () and owner.discovery_client is owner.execution_client is None
        with pytest.raises(ManagedStorageError, match="conflict"):
            await owner.prepare(deadline=monotonic() + 5)
        await owner.close()
        await owner.close()
        assert connections[0].closed and not owner.cleanup_pending
        with pytest.raises(AppConnectionClosedError):
            _ = owner.client

    asyncio.run(scenario())
    assert owners[0].read() == state
    assert not owner._root.exists()


@pytest.mark.parametrize("stop", [False, True])
def test_trace_publication_during_authentication_preserves_lifecycle_fence(owners, monkeypatch, stop):
    from loushang.apphost.managed.connection import _settled_native

    state = committed(owners)
    connections, on_start = fake_connection(monkeypatch)
    owner = lease(owners, state.handoff.instance)
    def publish():
        owners[0].record_trace_application(state.handoff.instance, state.handoff.attempt_id,
            native_identity=state.native_identity, trace_deadline_ms=int((monotonic() + 30) * 1000),
            deadline=monotonic() + 5)
        if stop:
            owners[0].request_stop(state.handoff.instance)
    async def during_authentication(connection):
        await _settled_native(publish)
    on_start(during_authentication)
    async def scenario():
        try:
            if stop:
                with pytest.raises(ManagedStorageError, match="unavailable"):
                    await owner.prepare(deadline=monotonic() + 5)
            else:
                await owner.prepare(deadline=monotonic() + 5)
                assert owner.client is connections[0].client
        finally:
            await owner.close()
    asyncio.run(scenario())
    assert connections[0].closed and not owner.cleanup_pending
    assert owners[0].read().handoff.stop_requested == stop


@pytest.mark.parametrize("change", ["revision_only", "skipped_revision", "removed_trace", "changed_trace"])
def test_connection_fence_does_not_ignore_other_revision_or_trace_changes(owners, change):
    from loushang.apphost.managed.connection import _same_connection_state
    from loushang.apphost.managed.lifecycle import ManagedTraceApplicationV1

    original = committed(owners)
    trace = ManagedTraceApplicationV1(original.handoff.instance.instance_id, original.handoff.attempt_id, 1000)
    current = replace(original, revision=original.revision + 1)
    if change == "skipped_revision":
        current = replace(current, revision=original.revision + 2, trace_application=trace)
    elif change in {"removed_trace", "changed_trace"}:
        original = replace(original, trace_application=trace)
        if change == "changed_trace":
            current = replace(current, trace_application=replace(trace, deadline_ms=2000))
    assert not _same_connection_state(original, current)


@pytest.mark.parametrize("kind", ["stale", "stop", "provisional", "absent"])
def test_unavailable_state_never_opens_connection(owners, monkeypatch, kind):
    state = committed(owners)
    instance = state.handoff.instance
    if kind == "stale":
        instance = replace(instance, instance_id="d" * 32)
    elif kind == "stop":
        owners[0].request_stop(instance)
    elif kind == "provisional":
        from loushang.apphost.managed.contracts import ManagedHandoffPhaseV1
        state = replace(state, handoff=replace(state.handoff, phase=ManagedHandoffPhaseV1.PROVISIONAL))
        monkeypatch.setattr(owners[0], "read", lambda **kwargs: state)
    else:
        monkeypatch.setattr(owners[0], "read", lambda **kwargs: None)
    connections, _ = fake_connection(monkeypatch)
    owner = lease(owners, instance)

    async def scenario():
        try:
            with pytest.raises(ManagedStorageError, match="unavailable"):
                await owner.prepare(deadline=monotonic() + 5)
            assert not connections
        finally:
            await owner.close()
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_stop_during_authentication_cannot_publish_client(owners, monkeypatch):
    state = committed(owners)
    connections, on_start = fake_connection(monkeypatch)
    owner = lease(owners, state.handoff.instance)

    async def stop(_):
        owners[0].request_stop(state.handoff.instance)

    on_start(stop)

    async def scenario():
        try:
            with pytest.raises(ManagedStorageError, match="unavailable"):
                await owner.prepare(deadline=monotonic() + 5)
            with pytest.raises(AppConnectionClosedError):
                _ = owner.client
        finally:
            await owner.close()
        assert connections[0].closed and not owner.cleanup_pending

    asyncio.run(scenario())
    assert owners[0].read().handoff.stop_requested


def test_cancelled_prepare_and_close_join_original_native_worker(owners, monkeypatch):
    state = committed(owners)
    owner = lease(owners, state.handoff.instance)
    connections, _ = fake_connection(monkeypatch)
    entered, release = Event(), Event()
    original = owner._admit_native

    def held(deadline):
        value = original(deadline)
        entered.set()
        assert release.wait(5)
        return value

    monkeypatch.setattr(owner, "_admit_native", held)

    async def scenario():
        preparation = asyncio.create_task(owner.prepare(deadline=monotonic() + 10))
        closing = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            preparation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await preparation
            closing = asyncio.create_task(owner.close())
            await asyncio.sleep(0)
            assert not closing.done() and owner.cleanup_pending
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert owner._observer is not None and not owner._observer.exited()
        finally:
            release.set()
            await owner.close()
            await asyncio.gather(preparation, *([closing] if closing is not None else []), return_exceptions=True)
        assert not connections and not owner.cleanup_pending

    asyncio.run(scenario())
    assert owners[0].read() == state


def test_cancelled_connection_joins_worker_waiting_on_original_flock(owners, monkeypatch):
    import fcntl

    state = committed(owners)
    owner = lease(owners, state.handoff.instance)
    connections, _ = fake_connection(monkeypatch)
    holder = PrivateManagedDirectory(owners[0]._fence._root)
    blocked = Event()
    native = fcntl.flock

    def probe(fd, flags):
        try:
            return native(fd, flags)
        except BlockingIOError:
            blocked.set()
            raise

    monkeypatch.setattr(fcntl, "flock", probe)

    async def scenario():
        preparation = closing = None
        try:
            with holder.lock("lifecycle.lock"):
                preparation = asyncio.create_task(owner.prepare(deadline=monotonic() + 10))
                assert await asyncio.to_thread(blocked.wait, 3)
                original = owner._prepare_task
                preparation.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await preparation
                closing = asyncio.create_task(owner.close())
                await asyncio.sleep(0)
                assert not closing.done() and owner.cleanup_pending
                assert owner._prepare_task is original and not original.done()
                assert owner._observer is None and not connections
                assert not owners[0]._fence._closing
            await owner.close()
        finally:
            await owner.close()
            await asyncio.gather(*(task for task in (preparation, closing) if task is not None),
                                 return_exceptions=True)
        assert not owner.cleanup_pending and not connections

    try:
        asyncio.run(scenario())
    finally:
        holder.close()
    assert owners[0].read() == state


def test_failed_client_close_retains_directory_and_retries_original(owners, monkeypatch):
    state = committed(owners)
    connections, _ = fake_connection(monkeypatch)
    owner = lease(owners, state.handoff.instance)

    async def scenario():
        await owner.prepare(deadline=monotonic() + 5)
        original_directory = owner._directory
        connections[0].close_error = True
        try:
            with pytest.raises(RuntimeError, match="injected_cleanup"):
                await owner.close()
            assert owner.cleanup_pending and owner._directory is original_directory
            assert owner._observer is None
        finally:
            connections[0].close_error = False
            await owner.close()
        assert not owner.cleanup_pending and len(connections) == 1

    asyncio.run(scenario())


def test_unknown_native_close_is_not_replayed_or_reported_settled(owners, monkeypatch):
    state = committed(owners)
    fake_connection(monkeypatch)
    owner = lease(owners, state.handoff.instance)

    async def scenario():
        await owner.prepare(deadline=monotonic() + 5)
        original = owner._observer.close
        calls = []

        def lost():
            original()  # No actual fd leak; only the receipt is lost.
            calls.append(1)
            raise RuntimeError("injected_close_receipt")

        monkeypatch.setattr(owner._observer, "close", lost)
        with pytest.raises(RuntimeError, match="injected_close_receipt"):
            await owner.close()
        with pytest.raises(ManagedStorageError, match="unavailable"):
            await owner.close()
        assert calls == [1] and owner.cleanup_pending
        assert owner._connection is owner._directory is None

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["namespace", "service", "user"])
def test_mismatched_binding_rejected_without_io(owners, kind):
    state = committed(owners)
    journal, namespace, service, runtime = owners
    instance = state.handoff.instance
    if kind == "namespace":
        instance = replace(instance, namespace_key="f" * 64)
    elif kind == "service":
        instance = replace(instance, service_id="f" * 64)
    else:
        namespace = replace(namespace, user_id=namespace.user_id + 1)
    with pytest.raises(ManagedContractError):
        ManagedConnectionLeaseV1(journal, namespace, service, instance, runtime_root=runtime, endpoint="workspace")


def test_close_before_prepare_never_opens_connection(owners, monkeypatch):
    state = committed(owners)
    connections, _ = fake_connection(monkeypatch)
    owner = lease(owners, state.handoff.instance)

    async def scenario():
        await owner.close()
        with pytest.raises(ManagedStorageError, match="conflict"):
            await owner.prepare(deadline=monotonic() + 5)
        assert not connections and not owner.cleanup_pending

    asyncio.run(scenario())


def test_native_acquisition_without_returned_owner_keeps_unknown_debt(owners, monkeypatch):
    state = committed(owners)
    owner = lease(owners, state.handoff.instance)
    connections, _ = fake_connection(monkeypatch)
    original = LinuxServiceObserverV1.reopen
    calls = []

    def lost(identity):
        native = original(identity)
        native.close()  # Actual test fd is closed; acquisition receipt is unknown.
        calls.append(1)
        raise RuntimeError("injected_native_receipt")

    monkeypatch.setattr(LinuxServiceObserverV1, "reopen", lost)

    async def scenario():
        with pytest.raises(RuntimeError, match="injected_native_receipt"):
            await owner.prepare(deadline=monotonic() + 5)
        for _ in range(2):
            with pytest.raises(ManagedStorageError, match="unavailable"):
                await owner.close()
        assert owner.cleanup_pending and owner._observer is None
        assert calls == [1] and not connections

    asyncio.run(scenario())


def test_internal_task_cancellation_cannot_outlive_native_receipt(owners, monkeypatch):
    state = committed(owners)
    owner = lease(owners, state.handoff.instance)
    connections, _ = fake_connection(monkeypatch)
    entered, release = Event(), Event()
    original = LinuxServiceObserverV1.reopen

    def held(identity):
        native = original(identity)
        entered.set()
        assert release.wait(5)
        return native

    monkeypatch.setattr(LinuxServiceObserverV1, "reopen", held)

    async def scenario():
        preparation = asyncio.create_task(owner.prepare(deadline=monotonic() + 10))
        closing = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            owner._prepare_task.cancel()
            await asyncio.sleep(0)
            closing = asyncio.create_task(owner.close())
            await asyncio.sleep(0)
            assert not closing.done() and owner.cleanup_pending
            assert owner._observer is None  # Native holds it, not yet returned.
        finally:
            release.set()
            await owner.close()
            await asyncio.gather(preparation, *([closing] if closing is not None else []), return_exceptions=True)
        assert not connections and not owner.cleanup_pending and owner._observer is None

    asyncio.run(scenario())


def test_late_post_auth_receipt_does_not_publish_ready(owners, monkeypatch):
    import loushang.apphost.managed.connection as module

    state = committed(owners)
    owner = lease(owners, state.handoff.instance)
    connections, _ = fake_connection(monkeypatch)
    original_check, original_recheck = module._check_deadline, owner._recheck
    returned = Event()

    def recheck(*args):
        original_recheck(*args)
        returned.set()

    def check(deadline):
        if returned.is_set():
            raise ManagedStorageError("busy")
        original_check(deadline)

    monkeypatch.setattr(owner, "_recheck", recheck)
    monkeypatch.setattr(module, "_check_deadline", check)

    async def scenario():
        try:
            with pytest.raises(ManagedStorageError, match="busy"):
                await owner.prepare(deadline=monotonic() + 5)
            assert connections[0].started
            with pytest.raises(AppConnectionClosedError):
                _ = owner.client
        finally:
            await owner.close()
        assert not owner.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["prepare", "close"])
def test_task_publication_fault_cannot_start_unowned_phase(owners, monkeypatch, phase):
    state = committed(owners)
    owner = lease(owners, state.handoff.instance)
    connections, _ = fake_connection(monkeypatch)

    async def scenario():
        if phase == "close":
            await owner.prepare(deadline=monotonic() + 5)
        original = asyncio.create_task
        unpublished = []

        def lost(work, **kwargs):
            unpublished.append(original(work, **kwargs))
            raise RuntimeError("injected_task_publication")

        with monkeypatch.context() as scoped:
            scoped.setattr(asyncio, "create_task", lost)
            with pytest.raises(RuntimeError, match="injected_task_publication"):
                if phase == "prepare":
                    await owner.prepare(deadline=monotonic() + 5)
                else:
                    await owner.close()
        await asyncio.gather(*unpublished, return_exceptions=True)
        if phase == "prepare":
            assert not connections and owner._observer is None
        else:
            assert not connections[0].closed and owner.cleanup_pending
        await owner.close()
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_executor_publication_fault_runs_no_native_effect(owners, monkeypatch):
    state = committed(owners)
    owner = lease(owners, state.handoff.instance)
    connections, _ = fake_connection(monkeypatch)

    async def scenario():
        loop = asyncio.get_running_loop()
        original = loop.run_in_executor
        unpublished = []

        def lost(executor, callback, *args):
            unpublished.append(original(executor, callback, *args))
            raise RuntimeError("injected_executor_publication")

        with monkeypatch.context() as scoped:
            scoped.setattr(loop, "run_in_executor", lost)
            with pytest.raises(RuntimeError, match="injected_executor_publication"):
                await owner.prepare(deadline=monotonic() + 5)
        await asyncio.gather(*unpublished)
        assert not connections and owner._observer is None and not owner._native_uncertain
        await owner.close()
        assert not owner.cleanup_pending

    asyncio.run(scenario())

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
from dataclasses import replace
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.child import ManagedChildApplicationV1, ManagedChildError
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.contracts import ManagedHandoffPhaseV1 as Phase
from loushang.apphost.managed.handoff import ManagedChildControlV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1
from loushang.hosting.service import LinuxServiceObserverV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed child")


@pytest.fixture
def binding(tmp_path):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True)
    registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
    journal = ManagedServiceJournalV1(registry, namespace, service, tmp_path / "fence", create=True)
    state = journal.prepare("c" * 32, expected=None)
    native = LinuxServiceObserverV1.capture(os.getpid())
    identity = native.identity
    native.close()
    journal.register_native(state.handoff.instance, "c" * 32, identity)
    parent, endpoint = socket.socketpair()
    control = ManagedChildControlV1(journal, state.handoff.instance, "c" * 32, identity, endpoint)
    try:
        yield journal, state.handoff.instance, identity, parent, control
    finally:
        parent.close()
        control.close()
        journal.close()
        registry.close()


class Application:
    def __init__(self):
        self.prepared = asyncio.Event()
        self.prepare_gate = asyncio.Event()
        self.prepare_gate.set()
        self.closed = asyncio.Event()
        self.fenced = False
        self.activations = 0
        self.prepares = 0
        self.closes = 0
        self.fail_close = False

    @property
    def cleanup_pending(self):
        return not self.closed.is_set()

    async def prepare(self, *, deadline=None):
        self.prepares += 1
        self.prepared.set()
        await self.prepare_gate.wait()
        if self.fenced:
            raise RuntimeError("closed during preparation")

    async def activate(self):
        if self.fenced:
            raise RuntimeError("closed during activation")
        self.activations += 1

    def fence(self):
        self.fenced = True
        self.prepare_gate.set()

    async def close(self, *, retry_timeout=None):
        self.closes += 1
        if self.fail_close:
            raise RuntimeError("injected application cleanup failure")
        self.closed.set()

    async def wait_closed(self):
        await self.closed.wait()


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


def test_committed_service_survives_parent_eof_and_cancelled_run_waiter(binding):
    journal, reference, _, parent, control = binding

    async def scenario():
        application = Application()
        owner = ManagedChildApplicationV1(application, control)
        waiter = asyncio.create_task(owner.run())
        try:
            await until(lambda: owner.accepting)
            assert journal.read().handoff.phase is Phase.COMMITTED
            parent.close()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            await asyncio.sleep(0.1)
            assert owner.accepting and application.activations == application.prepares == 1
            assert not application.fenced and application.closes == 0
            await owner.close()
            await owner.run()  # Join the same runner, not a second preparation.
            evidence = journal.read().evidence
            assert evidence.instance == reference and evidence.application_cleanup_completed
            assert not evidence.process_exited and not evidence.process_scope_settled
            assert not owner.cleanup_pending and application.closes == 1
        finally:
            await owner.close(retry_timeout=2)
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_parent_eof_during_preparation_aborts_without_activation(binding):
    journal, _, _, parent, control = binding

    async def scenario():
        application = Application()
        application.prepare_gate.clear()
        owner = ManagedChildApplicationV1(application, control)
        waiter = asyncio.create_task(owner.run())
        await application.prepared.wait()
        parent.close()
        await waiter
        assert application.activations == 0 and application.closes == 1
        assert journal.read().handoff.phase is Phase.ABORTING
        assert journal.read().evidence.application_cleanup_completed
        assert not owner.cleanup_pending
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_cleanup_failure_keeps_control_and_does_not_claim_application_success(binding):
    journal, _, _, _, control = binding

    async def scenario():
        application = Application()
        owner = ManagedChildApplicationV1(application, control)
        waiter = asyncio.create_task(owner.run())
        await until(lambda: owner.accepting)
        application.fail_close = True
        with pytest.raises(ManagedChildError, match="cleanup_incomplete"):
            await owner.close()
        await asyncio.shield(owner._stop_task)
        assert journal.read().handoff.stop_requested
        assert owner.cleanup_pending and not journal.read().evidence.application_cleanup_completed
        application.fail_close = False
        await owner.close(retry_timeout=2)
        await asyncio.gather(waiter, return_exceptions=True)
        assert not owner.cleanup_pending and journal.read().evidence.application_cleanup_completed
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_failed_cleanup_record_retries_fact_not_successful_application_close(binding, monkeypatch):
    journal, _, _, _, control = binding

    async def scenario():
        application = Application()
        owner = ManagedChildApplicationV1(application, control)
        waiter = asyncio.create_task(owner.run())
        await until(lambda: owner.accepting)
        original = journal.record_child_cleanup

        def unavailable(*args, **kwargs):
            raise ManagedStorageError("unavailable")

        monkeypatch.setattr(journal, "record_child_cleanup", unavailable)
        with pytest.raises(ManagedChildError, match="cleanup_incomplete"):
            await owner.close()
        assert application.closes == 1 and owner.cleanup_pending
        assert not journal.read().evidence.application_cleanup_completed
        monkeypatch.setattr(journal, "record_child_cleanup", original)
        await owner.close(retry_timeout=2)
        await asyncio.gather(waiter, return_exceptions=True)
        assert application.closes == 1 and not owner.cleanup_pending
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_hung_control_io_does_not_block_application_cleanup_or_lose_future(binding, monkeypatch):
    journal, _, _, _, control = binding

    async def scenario():
        application = Application()
        owner = ManagedChildApplicationV1(application, control, settlement_timeout=0.03)
        entered, release = threading.Event(), threading.Event()
        original = control.observe

        def blocked(action, deadline):
            if action == "poll" and not entered.is_set():
                entered.set()
                assert release.wait(5)
            return original(action, deadline)

        monkeypatch.setattr(control, "observe", blocked)
        waiter = asyncio.create_task(owner.run())
        try:
            await until(entered.is_set)
            pending = owner._pending_io
            with pytest.raises(ManagedChildError, match="cleanup_incomplete"):
                await owner.close()
            assert application.fenced and application.closed.is_set()
            assert owner._pending_io is pending and not pending.done()
            assert owner.cleanup_pending and not control._channel._closed
            release.set()
            await until(lambda: owner._close_task.done())
            await owner.close(retry_timeout=2)
            await asyncio.gather(waiter, return_exceptions=True)
            assert application.closes == 1 and not owner.cleanup_pending
        finally:
            release.set()
            await owner.close(retry_timeout=2)
    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("method", ["request_child_stop", "record_child_cleanup"])
@pytest.mark.parametrize("mismatch", ["attempt", "native", "instance"])
def test_child_stop_and_fact_binding_is_atomic(binding, method, mismatch):
    journal, reference, identity, _, _ = binding
    journal.request_stop(reference)
    before = journal.read()
    attempt = "c" * 32
    if mismatch == "attempt":
        attempt = "d" * 32
    elif mismatch == "native":
        identity = replace(identity, start_ticks=identity.start_ticks + 1)
    else:
        reference = replace(reference, instance_id="d" * 32)
    with pytest.raises(ManagedStorageError, match="conflict"):
        getattr(journal, method)(reference, attempt, identity, deadline=monotonic() + 1)
    assert journal.read() == before


def test_control_rejects_wrong_user_before_adopting_socket(binding):
    journal, reference, identity, _, _ = binding
    parent, endpoint = socket.socketpair()
    try:
        with pytest.raises(ManagedContractError):
            ManagedChildControlV1(
                journal, reference, "c" * 32, replace(identity, user_id=identity.user_id + 1), endpoint,
            )
        assert endpoint.fileno() >= 0
    finally:
        parent.close()
        endpoint.close()


@pytest.mark.parametrize("cause", ["deadline", "prepare_failure", "application_stop", "application_failure"])
def test_hung_io_does_not_block_autonomous_terminal_observation(binding, monkeypatch, cause):
    _, _, _, _, control = binding

    async def scenario():
        application = Application()
        owner = ManagedChildApplicationV1(application, control, startup_timeout=0.3, settlement_timeout=0.03)
        entered, release = threading.Event(), threading.Event()
        original = control.observe
        target = "read" if cause.startswith("application_") else "commit" if cause == "deadline" else "poll"
        if cause == "application_failure":
            async def failed_wait():
                await application.closed.wait()
                raise RuntimeError("private application failure")
            monkeypatch.setattr(application, "wait_closed", failed_wait)
        if cause == "prepare_failure":
            application.prepare_gate.clear()

            async def failure(*, deadline=None):
                application.prepared.set()
                await application.prepare_gate.wait()
                raise RuntimeError("private failure")

            monkeypatch.setattr(application, "prepare", failure)

        def blocked(action, deadline):
            should_block = action == target and (cause != "prepare_failure" or application.prepared.is_set())
            if should_block and not entered.is_set():
                entered.set()
                assert release.wait(5)
            return original(action, deadline)

        monkeypatch.setattr(control, "observe", blocked)
        waiter = asyncio.create_task(owner.run())
        try:
            await until(entered.is_set)
            pending = owner._pending_io
            if cause == "prepare_failure":
                application.prepare_gate.set()
            elif cause.startswith("application_"):
                application.closed.set()
            await until(lambda: application.fenced)
            await until(lambda: application.closed.is_set())
            assert owner._pending_io is pending and not pending.done()
            assert owner.cleanup_pending and not control._channel._closed
            release.set()
            await asyncio.gather(waiter, return_exceptions=True)
            await until(lambda: owner._close_task.done())
            await owner.close(retry_timeout=2)
            assert not owner.cleanup_pending and application.closes == 1
        finally:
            release.set()
            await owner.close(retry_timeout=2)
    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("failure", ["submit", "wait_task"])
def test_internal_scheduling_failure_fences_and_settles_owned_application(binding, monkeypatch, failure):
    _, _, _, _, control = binding

    async def scenario():
        from concurrent.futures import ThreadPoolExecutor

        import loushang.apphost.managed.child as module

        application = Application()
        owner = ManagedChildApplicationV1(application, control)
        injected = False
        if failure == "wait_task":
            original = module._spawn

            def fail_once(work):
                nonlocal injected
                if not injected and work.cr_code.co_name == "wait_closed":
                    injected = True
                    work.close()
                    raise RuntimeError("private factory failure")
                return original(work)

            monkeypatch.setattr(module, "_spawn", fail_once)
        else:
            original_submit = ThreadPoolExecutor.submit

            def fail_submit(self, *args, **kwargs):
                nonlocal injected
                if not injected:
                    injected = True
                    raise RuntimeError("private submit failure")
                return original_submit(self, *args, **kwargs)

            monkeypatch.setattr(ThreadPoolExecutor, "submit", fail_submit)
        with pytest.raises(ManagedChildError):
            await owner.run()
        assert injected and application.fenced and application.closes == 1
        assert not owner.cleanup_pending and owner._failure is not None
    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("phase", ["prepare", "activate"])
def test_cancel_run_during_stage_keeps_exact_task_and_service(binding, monkeypatch, phase):
    _, _, _, _, control = binding

    async def scenario():
        application = Application()
        entered, release = asyncio.Event(), asyncio.Event()
        original = getattr(application, phase)

        async def delayed(**kwargs):
            entered.set()
            await release.wait()
            await original(**kwargs)

        monkeypatch.setattr(application, phase, delayed)
        owner = ManagedChildApplicationV1(application, control)
        waiter = asyncio.create_task(owner.run())
        await entered.wait()
        owned = getattr(owner, f"_{phase}_task")
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not owned.done() and not application.fenced
        release.set()
        await until(lambda: owner.accepting)
        assert getattr(owner, f"_{phase}_task") is owned
        await owner.close()
        await owner.run()
        assert application.closes == application.activations == application.prepares == 1
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_stop_is_durable_while_application_cleanup_hangs_and_waiter_cancels(binding, monkeypatch):
    journal, _, _, _, control = binding

    async def scenario():
        application = Application()
        entered, release = asyncio.Event(), asyncio.Event()
        original = application.close

        async def delayed(**kwargs):
            entered.set()
            await release.wait()
            await original(**kwargs)

        monkeypatch.setattr(application, "close", delayed)
        owner = ManagedChildApplicationV1(application, control)
        runner = asyncio.create_task(owner.run())
        await until(lambda: owner.accepting)
        waiter = asyncio.create_task(owner.close())
        await entered.wait()
        owned, deadline = owner._close_task, owner._close_deadline
        await asyncio.shield(owner._stop_task)
        assert journal.read().handoff.stop_requested
        assert not journal.read().evidence.application_cleanup_completed
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        again = asyncio.create_task(owner.close(retry_timeout=2))
        await asyncio.sleep(0)
        assert owner._close_task is owned and owner._close_deadline == deadline
        release.set()
        await again
        await runner
        assert application.closes == 1 and not owner.cleanup_pending
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_durable_commit_confirmed_after_app_deadline_never_activates(binding, monkeypatch):
    journal, _, _, _, control = binding

    async def scenario():
        application = Application()
        owner = ManagedChildApplicationV1(application, control, startup_timeout=0.2, settlement_timeout=0.03)
        entered, release = threading.Event(), threading.Event()
        original = control._channel.commit

        def committed_then_held(**kwargs):
            result = original(**kwargs)
            entered.set()
            assert release.wait(5)
            return result

        monkeypatch.setattr(control._channel, "commit", committed_then_held)
        runner = asyncio.create_task(owner.run())
        try:
            await until(entered.is_set)
            assert journal.read().handoff.phase is Phase.COMMITTED
            await until(lambda: application.closed.is_set())
            assert application.fenced and application.activations == 0
            assert owner._pending_io is not None and not owner._pending_io.done()
            release.set()
            await asyncio.gather(runner, return_exceptions=True)
            await until(lambda: owner._close_task.done())
            await owner.close(retry_timeout=2)
            state = journal.read()
            assert state.handoff.phase is Phase.COMMITTED and state.handoff.stop_requested
            assert state.evidence.application_cleanup_completed and application.closes == 1
        finally:
            release.set()
            await owner.close(retry_timeout=2)
    asyncio.run(asyncio.wait_for(scenario(), 10))

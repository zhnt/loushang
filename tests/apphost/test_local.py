from __future__ import annotations

import asyncio
import inspect
from typing import cast

import pytest

from loushang.apphost.application import HostedApplicationError
from loushang.apphost.continuity import HostedApplicationContinuityRuntimeV1
from loushang.apphost.local import HostedLocalRuntimeV1
from loushang.appserver.local import LocalAppClientConnectionV1, LocalConnectionModeV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordError,
    LocalRecordErrorCodeV1,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol import (
    MuxAttachV1,
    MuxSelectorV1,
    SessionScopeV1,
    TurnTextV1,
)

from .test_continuity import _attempt, _Lease, _record, _Session

SCOPES = (LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),)


class _Application:
    application_id = "coding.default"
    product_id = "coding"

    def __init__(self, events):
        self.events = events
        self.gate = None

    def enable_client_scopes(self):
        self.events.append("enable")

    def open_client_scope(self):
        raise AssertionError("fake listener must not create clients")

    def fence_client_scopes(self):
        self.events.append("fence.scopes")

    async def close(self):
        self.events.append("application.close")
        if self.gate is not None:
            await self.gate.wait()


class _Directory:
    def __init__(self, events):
        self.events = events
        self.fail_once = False

    def close(self):
        self.events.append("directory.close")
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("private detail")


def _fake_runtime(monkeypatch, *, timeout=1):
    events = []

    class Listener:
        def __init__(self, *args, **kwargs):
            self.request_stop = kwargs["request_stop"]
            self.start_gate = self.close_gate = None
            self.entered = asyncio.Event()
            self.prepare_entered = asyncio.Event()
            self.prepare_gate = None

        async def prepare(self, *, deadline=None):
            self.deadline = deadline
            self.prepare_entered.set()
            if self.prepare_gate is not None:
                await self.prepare_gate.wait()

        async def activate(self):
            events.append("listener.start")
            self.entered.set()
            if self.start_gate is not None:
                await self.start_gate.wait()

        def fence(self):
            events.append("fence.listener")

        async def close(self):
            events.append("listener.close")
            if self.close_gate is not None:
                await self.close_gate.wait()

    monkeypatch.setattr("loushang.apphost.local.LocalAppServerV1", Listener)
    application, directory = _Application(events), _Directory(events)
    owner = HostedLocalRuntimeV1(
        cast(HostedApplicationContinuityRuntimeV1, application),
        cast(LocalConnectionDirectoryV1, directory),
        "workspace",
        scopes=SCOPES,
        settlement_timeout=timeout,
    )
    return owner, application, directory, events


def test_preparation_does_not_enable_scopes_or_renew_activation_budget(monkeypatch):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch)
        deadline = asyncio.get_running_loop().time() + 0.1
        await owner.prepare(deadline=deadline)
        assert not owner.accepting and events == []
        assert owner._startup_deadline == owner._server.deadline == deadline
        await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()) + 0.01)
        with pytest.raises(HostedApplicationError, match="startup_timeout"):
            await owner.activate()
        assert owner._activate_task is None and not owner.accepting
        assert "enable" not in events and "listener.start" not in events
        assert events[-1] == "application.close" and not owner.cleanup_pending
    asyncio.run(scenario())


def test_repeated_or_out_of_order_stages_leave_valid_owner_intact(monkeypatch):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch)
        with pytest.raises(HostedApplicationError):
            await owner.activate()
        await owner.prepare()
        for call in (owner.prepare, owner.start):
            with pytest.raises(HostedApplicationError):
                await call()
        assert events == [] and not owner._closing
        await owner.activate()
        with pytest.raises(HostedApplicationError):
            await owner.activate()
        assert events == ["enable", "listener.start"] and owner.accepting
        await owner.close()
        with pytest.raises(HostedApplicationError):
            await owner.activate()
    asyncio.run(scenario())


def test_close_fences_late_preparation_without_enabling_scopes(monkeypatch):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch, timeout=0.02)
        gate = owner._server.prepare_gate = asyncio.Event()
        preparing = asyncio.create_task(owner.prepare())
        await owner._server.prepare_entered.wait()
        owned = owner._start_task
        for call in (owner.prepare, owner.activate, owner.start):
            with pytest.raises(HostedApplicationError):
                await call()
        assert not owner._closing
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await owner.close()
        assert owner._start_task is owned and not owned.done()
        assert "application.close" not in events
        gate.set()
        with pytest.raises(HostedApplicationError):
            await preparing
        await owner.close(retry_timeout=1)
        assert "enable" not in events and "listener.start" not in events
        assert events.count("application.close") == 1 and not owner.cleanup_pending
    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf"), -float("inf"), 10**1000, -(10**1000), 0, -1])
def test_invalid_deadline_never_starts_or_fences_application(monkeypatch, deadline):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch)
        with pytest.raises(ValueError):
            await owner.prepare(deadline=deadline)
        assert owner._start_task is None and owner._startup_deadline is None
        assert events == [] and not owner._closing
        await owner.close()
    asyncio.run(scenario())


def test_one_step_start_reserves_both_phases(monkeypatch):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch)
        original = owner._prepare

        async def competing(**kwargs):
            await original(**kwargs)
            assert owner._start_task.done() and owner._prepared
            for call in (owner.prepare, owner.start, owner.activate):
                with pytest.raises(HostedApplicationError):
                    await call()
            assert owner._activate_task is None and not owner._closing

        monkeypatch.setattr(owner, "_prepare", competing)
        await owner.start()
        assert owner.accepting and events == ["enable", "listener.start"]
        await owner.close()
    asyncio.run(scenario())


def test_stop_publishes_owner_and_fences_before_reply_then_settles_dependencies(
    monkeypatch,
):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch)
        assert not owner.accepting
        await owner.start()
        assert owner.accepting
        reply = asyncio.get_running_loop().create_future()
        owner._server.request_stop(reply)
        assert not owner.accepting
        assert owner._close_task is not None
        assert events == ["enable", "listener.start", "fence.listener", "fence.scopes"]
        await asyncio.sleep(0)
        assert "listener.close" not in events
        reply.set_result(None)
        await owner.wait_closed()
        assert events[-3:] == ["listener.close", "directory.close", "application.close"]
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_stop_between_start_task_completion_and_delivery_rejects_ready(monkeypatch):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch)
        original = owner._activate_once
        reply = asyncio.get_running_loop().create_future()
        reply.set_result(None)

        async def start_then_stop():
            await original()
            # Dispatch stop before asyncio.wait delivers the finished task.
            asyncio.get_running_loop().call_soon(owner._server.request_stop, reply)

        monkeypatch.setattr(owner, "_activate_once", start_then_stop)
        with pytest.raises(HostedApplicationError, match="hosted_local_closed"):
            await owner.start()
        assert not owner.cleanup_pending
        assert events.count("application.close") == 1

    asyncio.run(scenario())


def test_cancelled_delivery_barrier_does_not_discard_admitted_stop(monkeypatch):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch)
        await owner.start()
        reply = asyncio.get_running_loop().create_future()
        owner._server.request_stop(reply)
        reply.cancel()
        await owner.wait_closed()
        assert events[-1] == "application.close"
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_timed_out_listener_keeps_application_and_exact_task_until_explicit_retry(
    monkeypatch,
):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch, timeout=0.02)
        gate = owner._server.close_gate = asyncio.Event()
        await owner.start()
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await owner.close()
        task = owner._phases["connection"]
        deadline = owner._deadline
        assert not task.done()
        assert "application.close" not in events
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await owner.close()
        assert owner._deadline == deadline
        assert owner._phases["connection"] is task
        gate.set()
        await owner.close(retry_timeout=1)
        assert events.count("listener.close") == 1
        assert events[-3:] == ["listener.close", "directory.close", "application.close"]

    asyncio.run(scenario())


def test_cancelled_close_waiter_cannot_cancel_application_cleanup(monkeypatch):
    async def scenario():
        owner, application, _, events = _fake_runtime(monkeypatch)
        application.gate = asyncio.Event()
        await owner.start()
        waiter = asyncio.create_task(owner.close())
        async with asyncio.timeout(1):
            while "application.close" not in events:
                await asyncio.sleep(0)
        task, deadline = owner._close_task, owner._deadline
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert task is not None and not task.done()
        application.gate.set()
        await owner.close(retry_timeout=1)  # In-flight joins cannot renew a budget.
        assert owner._close_task is task and owner._deadline == deadline
        assert events.count("application.close") == 1

    asyncio.run(scenario())


def test_directory_failure_retains_application_before_g13_lease_release(monkeypatch):
    async def scenario():
        owner, _, directory, events = _fake_runtime(monkeypatch)
        directory.fail_once = True
        await owner.start()
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await owner.close()
        assert "application.close" not in events
        assert owner.cleanup_pending
        await owner.close(retry_timeout=1)
        assert events.count("listener.close") == 1
        assert events.count("directory.close") == 2
        assert events[-1] == "application.close"

    asyncio.run(scenario())


def test_cancelled_startup_retains_late_listener_before_dependency_cleanup(monkeypatch):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch, timeout=0.02)
        gate = owner._server.start_gate = asyncio.Event()
        starting = asyncio.create_task(owner.start())
        await owner._server.entered.wait()
        starting.cancel()
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await starting
        assert "listener.close" not in events and "application.close" not in events
        gate.set()
        await owner.close(retry_timeout=1)
        assert events.count("listener.start") == 1
        assert events[-3:] == ["listener.close", "directory.close", "application.close"]

    asyncio.run(scenario())


def test_start_failure_is_not_mislabeled_as_incomplete_cleanup(monkeypatch):
    async def scenario():
        owner, application, _, events = _fake_runtime(monkeypatch)

        def reject():
            raise HostedApplicationError("hosted_application_client_mode_conflict")

        application.enable_client_scopes = reject
        with pytest.raises(HostedApplicationError, match="client_mode_conflict"):
            await owner.start()
        assert not owner.cleanup_pending
        assert "listener.start" not in events and "enable" not in events
        assert events[-1] == "application.close"

    asyncio.run(scenario())


def test_stop_task_creation_failure_retains_intent_and_closes_unstarted_work(
    monkeypatch,
):
    async def scenario():
        owner, _, _, events = _fake_runtime(monkeypatch)
        await owner.start()
        reply = asyncio.get_running_loop().create_future()
        observed = []

        def reject(work):
            observed.append(work)
            raise RuntimeError("task factory failed")

        with monkeypatch.context() as patch:
            patch.setattr(asyncio, "create_task", reject)
            with pytest.raises(RuntimeError, match="task factory"):
                owner._server.request_stop(reply)
        assert owner._close_task is None
        assert all(
            inspect.getcoroutinestate(work) == inspect.CORO_CLOSED for work in observed
        )
        assert events[-2:] == ["fence.listener", "fence.scopes"]
        reply.set_result(None)
        await owner.wait_closed()
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_whole_stop_uses_one_deadline_for_all_phases(monkeypatch):
    async def scenario():
        import loushang.apphost.local as local

        owner, _, _, _ = _fake_runtime(monkeypatch)
        await owner.start()
        deadlines = []
        original = local._wait

        async def capture(task, deadline, **kwargs):
            deadlines.append(deadline)
            return await original(task, deadline, **kwargs)

        monkeypatch.setattr(local, "_wait", capture)
        await owner.close()
        assert len(deadlines) == 6  # prepare/activate joins, reply, connection, directory, G13
        assert set(deadlines) == {owner._deadline}

    asyncio.run(scenario())


def test_G16_NATIVE_ready_g13_application_survives_client_eof_until_explicit_stop(
    tmp_path,
):
    async def scenario():
        events = []
        lease = _Lease(events, _record())
        attempt, resolver = _attempt(events, lease)
        application = await attempt.open()
        owner = HostedLocalRuntimeV1(
            application,
            LocalConnectionDirectoryV1(tmp_path / "runtime"),
            "workspace",
            scopes=SCOPES,
        )
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        first = LocalAppClientConnectionV1(directory, "workspace")
        second = LocalAppClientConnectionV1(directory, "workspace")
        stop = LocalAppClientConnectionV1(
            directory, "workspace", mode=LocalConnectionModeV1.STOP
        )
        try:
            await owner.start()
            assert resolver.requests[0].session_id == "session-1"
            await first.start()
            assert (await first.client.list_muxes()).mux_spaces[0].name == "dev"
            await first.close()
            assert application.accepting and not lease.closed and events == []
            await second.start()
            assert (await second.client.list_muxes()).mux_spaces[0].name == "dev"
            await stop.start()
            assert stop.stop_requested
            await owner.wait_closed()
            assert not owner.cleanup_pending and not application.accepting
            assert events == ["service", "apphost", "product", "lease"]
            assert lease.record is not None  # Stop retains desired state.
            with pytest.raises(LocalRecordError) as raised:
                directory.read("workspace")
            assert raised.value.code is LocalRecordErrorCodeV1.NOT_FOUND
        finally:
            await asyncio.gather(first.close(), second.close(), stop.close())
            await owner.close(retry_timeout=1)
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_G16_NATIVE_stop_settles_disconnected_accepted_work_before_g13_lease(
    tmp_path, monkeypatch
):
    async def scenario():
        events = []
        entered = asyncio.Event()
        released = asyncio.Event()

        async def turn(self, text):
            events.append("turn.start")
            entered.set()
            try:
                await released.wait()
            finally:
                events.append("turn.settled")

        monkeypatch.setattr(_Session, "start_turn", turn)
        lease = _Lease(events, _record())
        attempt, _ = _attempt(events, lease)
        application = await attempt.open()
        owner = HostedLocalRuntimeV1(
            application,
            LocalConnectionDirectoryV1(tmp_path / "runtime"),
            "workspace",
            scopes=SCOPES,
        )
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        client = LocalAppClientConnectionV1(directory, "workspace")
        stop = LocalAppClientConnectionV1(
            directory, "workspace", mode=LocalConnectionModeV1.STOP
        )
        delivery = None
        try:
            await owner.start()
            await client.start()
            attachment = await client.client.attach_mux(
                MuxAttachV1(MuxSelectorV1(name="dev"))
            )
            delivery = asyncio.create_task(
                client.client.start_turn(
                    TurnTextV1(
                        attachment.attachment_id,
                        attachment.controller_generation,
                        "member-1",
                        "retained",
                    )
                )
            )
            await entered.wait()
            await client.close()
            await asyncio.gather(delivery, return_exceptions=True)
            assert events == ["turn.start"] and not lease.closed
            await stop.start()
            assert stop.stop_requested
            await owner.wait_closed()
            assert events == [
                "turn.start",
                "turn.settled",
                "service",
                "apphost",
                "product",
                "lease",
            ]
        finally:
            released.set()
            if delivery is not None:
                await asyncio.gather(delivery, return_exceptions=True)
            await client.close()
            await stop.close()
            await owner.close(retry_timeout=1)
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 10))

from __future__ import annotations

import asyncio

import pytest

from loushang.apphost.application import HostedApplicationError
from loushang.coding.hosted_local import CodingLocalCommandV1

from .test_hosted_local import _local_launch


def _command(tmp_path, monkeypatch, *, timeout=1):
    events = []

    class Application:
        async def close(self):
            events.append("application.close")

    class Attempt:
        def __init__(self):
            self.gate = None
            self.entered = asyncio.Event()

        async def open(self):
            self.entered.set()
            if self.gate is not None:
                await self.gate.wait()
            events.append("recovered")
            return Application()

        async def close(self):
            events.append("attempt.close")

    class Local:
        def __init__(self, application, directory, *args, **kwargs):
            events.append("adopt")
            self.application = application
            self.start_gate = None
            self.close_gate = None
            self.entered = asyncio.Event()
            self.close_entered = asyncio.Event()
            self.fail_once = False
            self.budgets = []
            self.accepting = True
            self.settled = False

        async def start(self):
            self.entered.set()
            if self.start_gate is not None:
                await self.start_gate.wait()

        async def wait_closed(self):
            await self.close()

        async def close(self, *, retry_timeout=None):
            if self.settled:
                return
            self.accepting = False
            self.budgets.append(retry_timeout)
            self.close_entered.set()
            if self.fail_once:
                self.fail_once = False
                raise HostedApplicationError("hosted_local_cleanup_incomplete")
            if self.close_gate is not None:
                await self.close_gate.wait()
            if self.start_gate is not None:
                self.start_gate.set()
            await self.application.close()
            self.settled = True

    attempt = Attempt()
    monkeypatch.setattr(
        "loushang.coding.hosted_local.create_coding_hosted_attempt",
        lambda *a, **k: attempt,
    )
    monkeypatch.setattr("loushang.coding.hosted_local.HostedLocalRuntimeV1", Local)
    command = CodingLocalCommandV1(
        _local_launch(tmp_path.resolve()), settlement_timeout=timeout
    )
    return command, attempt, events


def test_G16_PRODUCT_CANCEL_late_recovery_is_retained_without_publishing_local_owner(
    tmp_path, monkeypatch
):
    async def scenario():
        command, attempt, events = _command(tmp_path, monkeypatch, timeout=0.02)
        attempt.gate = asyncio.Event()
        starting = asyncio.create_task(command.start())
        await attempt.entered.wait()
        starting.cancel()
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await starting
        owned = command._start_task
        assert owned is not None and not owned.done()
        assert events == [] and command.cleanup_pending
        attempt.gate.set()
        await command.close(retry_timeout=1)
        assert command._start_task is owned and owned.done()
        assert events == ["recovered", "application.close"]
        assert not command.cleanup_pending

    asyncio.run(scenario())


def test_G16_PRODUCT_CLOSE_never_reclaims_application_after_apphost_adoption(
    tmp_path, monkeypatch
):
    async def scenario():
        command, _, events = _command(tmp_path, monkeypatch)
        await command.start()
        local = command._local
        local.fail_once = True
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await command.close()
        assert events == ["recovered", "adopt"] and command.cleanup_pending
        assert command._application is None
        await command.close(retry_timeout=1)
        assert events == ["recovered", "adopt", "application.close"]
        assert local.budgets == [None, 1]

    asyncio.run(scenario())


def test_G16_PRODUCT_CLOSE_cancelled_waiter_joins_same_adopted_owner(
    tmp_path, monkeypatch
):
    async def scenario():
        command, _, events = _command(tmp_path, monkeypatch)
        await command.start()
        local = command._local
        local.close_gate = asyncio.Event()
        waiter = asyncio.create_task(command.close())
        await local.close_entered.wait()
        task, deadline = command._close_task, command._deadline
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert task is not None and not task.done()
        local.close_gate.set()
        await command.close(retry_timeout=1)
        assert command._close_task is task and command._deadline == deadline
        assert local.budgets == [None]
        assert events.count("application.close") == 1

    asyncio.run(scenario())


def test_G16_PRODUCT_CLOSE_settles_adopted_local_before_joining_outer_start(
    tmp_path, monkeypatch
):
    async def scenario():
        import loushang.coding.hosted_local as local_module

        command, _, events = _command(tmp_path, monkeypatch)
        factory = local_module.HostedLocalRuntimeV1
        gate = asyncio.Event()

        def create(*args, **kwargs):
            local = factory(*args, **kwargs)
            local.start_gate = gate
            return local

        monkeypatch.setattr(local_module, "HostedLocalRuntimeV1", create)
        starting = asyncio.create_task(command.start())
        async with asyncio.timeout(1):
            while command._local is None:
                await asyncio.sleep(0)
        await command._local.entered.wait()
        await asyncio.wait_for(command.close(), 1)
        with pytest.raises(HostedApplicationError, match="coding_local_closed"):
            await starting
        assert gate.is_set() and not command.cleanup_pending
        assert events == ["recovered", "adopt", "application.close"]

    asyncio.run(scenario())


def test_G16_PRODUCT_READY_stop_during_local_handoff_cannot_announce_ready(
    tmp_path, monkeypatch
):
    async def scenario():
        import loushang.coding.hosted_local as local_module

        command, _, events = _command(tmp_path, monkeypatch)

        async def stop(self):
            await self.close()

        monkeypatch.setattr(local_module.HostedLocalRuntimeV1, "start", stop)
        with pytest.raises(HostedApplicationError, match="coding_local_closed"):
            await command.run(ready=lambda: events.append("ready"))
        assert "ready" not in events
        assert events.count("application.close") == 1
        assert not command.cleanup_pending

    asyncio.run(scenario())

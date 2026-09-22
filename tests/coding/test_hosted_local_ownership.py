from __future__ import annotations

import asyncio
import inspect

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
            self.accepting = False
            self.settled = False
            self.activations = 0
            self.fenced = False

        async def prepare(self, *, deadline=None):
            self.deadline = deadline
            self.entered.set()
            if self.start_gate is not None:
                await self.start_gate.wait()

        async def activate(self):
            if self.fenced:
                raise HostedApplicationError("hosted_local_closed")
            self.activations += 1
            self.accepting = True

        def fence(self):
            self.fenced = True
            self.accepting = False

        async def wait_closed(self):
            await self.close()

        async def close(self, *, retry_timeout=None):
            if self.settled:
                return
            self.fence()
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


def test_managed_preparation_reuses_product_and_rejects_invalid_stage_calls(tmp_path, monkeypatch):
    async def scenario():
        command, _, events = _command(tmp_path, monkeypatch)
        with pytest.raises(HostedApplicationError):
            await command.activate()
        assert command._start_task is None
        deadline = asyncio.get_running_loop().time() + 1
        await command.prepare(deadline=deadline)
        local = command._local
        assert local.deadline == command._startup_deadline == deadline
        assert not local.accepting and local.activations == 0
        for call in (command.prepare, command.start):
            with pytest.raises(HostedApplicationError):
                await call()
        assert not command._closing and events == ["recovered", "adopt"]
        await command.activate()
        with pytest.raises(HostedApplicationError):
            await command.activate()
        assert local.accepting and local.activations == 1
        await command.close()
        assert events.count("application.close") == 1 and not command.cleanup_pending
    asyncio.run(scenario())


@pytest.mark.parametrize("expired", [False, True])
def test_managed_close_or_expiry_between_stages_never_activates(tmp_path, monkeypatch, expired):
    async def scenario():
        command, _, events = _command(tmp_path, monkeypatch)
        deadline = asyncio.get_running_loop().time() + 0.1
        await command.prepare(deadline=deadline)
        local = command._local
        if expired:
            await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()) + 0.01)
        else:
            await command.close()
        with pytest.raises(HostedApplicationError):
            await command.activate()
        assert command._startup_deadline == deadline and local.activations == 0
        assert not local.accepting and not command.cleanup_pending
        assert events.count("application.close") == 1
    asyncio.run(scenario())


def test_managed_prepare_deadline_starts_before_product_recovery(tmp_path, monkeypatch):
    async def scenario():
        command, attempt, events = _command(tmp_path, monkeypatch)
        attempt.gate = asyncio.Event()
        deadline = asyncio.get_running_loop().time() + 1
        preparing = asyncio.create_task(command.prepare(deadline=deadline))
        await attempt.entered.wait()
        assert command._startup_deadline == deadline
        for call in (command.prepare, command.activate, command.start):
            with pytest.raises(HostedApplicationError):
                await call()
        assert not command._closing
        attempt.gate.set()
        await preparing
        assert command._local.deadline == deadline
        assert events == ["recovered", "adopt"]
        await command.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf"), -float("inf"), 10**1000, -(10**1000), 0, -1])
def test_invalid_deadline_never_starts_product(tmp_path, monkeypatch, deadline):
    async def scenario():
        command, _, events = _command(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            await command.prepare(deadline=deadline)
        assert command._start_task is None and command._startup_deadline is None
        assert events == [] and not command._closing
        await command.close()
    asyncio.run(scenario())


def test_one_step_start_cannot_lose_activation_to_later_waiter(tmp_path, monkeypatch):
    async def scenario():
        command, _, events = _command(tmp_path, monkeypatch)
        original = command._prepare

        async def competing(**kwargs):
            await original(**kwargs)
            assert command._start_task.done() and command._prepared
            for call in (command.prepare, command.start, command.activate):
                with pytest.raises(HostedApplicationError):
                    await call()
            assert command._activate_task is None and not command._closing

        monkeypatch.setattr(command, "_prepare", competing)
        await command.start()
        assert command._local.activations == 1 and events == ["recovered", "adopt"]
        await command.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("active", [False, True])
def test_close_factory_failure_still_fences_prepared_or_active_deployment(tmp_path, monkeypatch, active):
    async def scenario():
        command, _, events = _command(tmp_path, monkeypatch)
        await command.prepare()
        if active:
            await command.activate()
        local = command._local
        captured = []

        def reject(work):
            captured.append(work)
            raise RuntimeError("injected task factory failure")

        with monkeypatch.context() as patch:
            patch.setattr(asyncio, "create_task", reject)
            with pytest.raises(RuntimeError, match="task factory"):
                await command.close()
        assert local.fenced and not local.accepting
        assert not local.settled and command.cleanup_pending
        assert all(inspect.getcoroutinestate(work) == inspect.CORO_CLOSED for work in captured)
        assert "application.close" not in events
        await command.close()
        assert not command.cleanup_pending and events.count("application.close") == 1
    asyncio.run(scenario())


def test_close_fences_already_queued_inner_activation(tmp_path, monkeypatch):
    async def scenario():
        command, _, events = _command(tmp_path, monkeypatch)
        await command.prepare()
        local = command._local
        entered, release = asyncio.Event(), asyncio.Event()
        original = local.activate

        async def delayed():
            entered.set()
            await release.wait()
            await original()

        monkeypatch.setattr(local, "activate", delayed)
        activating = asyncio.create_task(command.activate())
        await entered.wait()
        release.set()  # Activation is queued before the newly spawned close task.
        await command.close()
        with pytest.raises(HostedApplicationError):
            await activating
        assert local.activations == 0 and local.fenced and not local.accepting
        assert events.count("application.close") == 1 and not command.cleanup_pending
    asyncio.run(asyncio.wait_for(scenario(), 5))


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

        monkeypatch.setattr(local_module.HostedLocalRuntimeV1, "activate", stop)
        with pytest.raises(HostedApplicationError, match="coding_local_closed"):
            await command.run(ready=lambda: events.append("ready"))
        assert "ready" not in events
        assert events.count("application.close") == 1
        assert not command.cleanup_pending

    asyncio.run(scenario())

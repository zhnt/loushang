from __future__ import annotations

import asyncio

import pytest

from loushang.harness.events.host import HostLifecycleEvent
from loushang.harness.runtime.execution import (
    HostRuntime,
    HostStateError,
    HostTaskHandle,
)


class ReferenceDriver:
    def __init__(self) -> None:
        self.running = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.abort_calls = 0
        self.wait_calls = 0
        self.dispose_calls = 0

    async def run(self) -> str:
        self.running = True
        self.started.set()
        try:
            await self.release.wait()
            return "reference-result"
        finally:
            self.running = False

    def abort(self) -> None:
        self.abort_calls += 1
        self.release.set()

    async def wait_for_idle(self) -> None:
        self.wait_calls += 1

    async def dispose(self) -> None:
        self.dispose_calls += 1


def _runtime(driver: ReferenceDriver) -> HostRuntime[str]:
    return HostRuntime(
        abort_driver=driver.abort,
        wait_for_idle_driver=driver.wait_for_idle,
        dispose_driver=driver.dispose,
        is_running_driver=lambda: driver.running,
    )


async def _async_value(value: str) -> str:
    return value


def test_host_runtime_runs_reference_driver_and_publishes_lifecycle() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        events: list[HostLifecycleEvent] = []
        runtime.subscribe(events.append)

        task = asyncio.create_task(runtime.run(driver.run, run_id="research-run"))
        await driver.started.wait()
        assert runtime.snapshot().status == "running"
        assert runtime.snapshot().active_run_id == "research-run"
        driver.release.set()

        assert await task == "reference-result"
        assert runtime.snapshot().status == "idle"
        assert [event.kind for event in events] == ["run_started", "run_completed"]

    asyncio.run(scenario())


def test_host_runtime_abort_delegates_and_records_aborted_completion() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        events: list[HostLifecycleEvent] = []
        runtime.subscribe(events.append)
        task = asyncio.create_task(runtime.run(driver.run, run_id="design-run"))
        await driver.started.wait()

        assert runtime.abort() is True
        assert runtime.status == "aborting"
        assert await task == "reference-result"
        await runtime.wait_for_idle()

        assert driver.abort_calls == 1
        assert driver.wait_calls == 1
        assert [event.kind for event in events] == [
            "run_started",
            "abort_requested",
            "run_aborted",
        ]

    asyncio.run(scenario())


def test_host_runtime_recovers_to_idle_after_operation_failure() -> None:
    async def scenario() -> None:
        runtime: HostRuntime[None] = HostRuntime()
        events: list[HostLifecycleEvent] = []
        runtime.subscribe(events.append)

        async def fail() -> None:
            raise ValueError("reference failure")

        with pytest.raises(ValueError, match="reference failure"):
            await runtime.run(fail)

        assert runtime.status == "idle"
        assert events[-1].kind == "run_failed"
        assert events[-1].error == "reference failure"

    asyncio.run(scenario())


def test_host_runtime_recovers_to_idle_when_start_listener_fails() -> None:
    async def scenario() -> None:
        runtime: HostRuntime[None] = HostRuntime()

        def fail_on_start(event: HostLifecycleEvent) -> None:
            if event.kind == "run_started":
                raise RuntimeError("listener failure")

        runtime.subscribe(fail_on_start)

        async def operation() -> None:
            raise AssertionError("operation must not start")

        with pytest.raises(RuntimeError, match="listener failure"):
            await runtime.run(operation)

        assert runtime.status == "idle"
        assert runtime.snapshot().active_run_id is None

    asyncio.run(scenario())


def test_host_runtime_rejects_concurrent_and_external_driver_runs() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        task = asyncio.create_task(runtime.run(driver.run))
        await driver.started.wait()
        with pytest.raises(HostStateError, match="already running"):
            await runtime.run(driver.run)
        driver.release.set()
        await task

        driver.running = True
        with pytest.raises(HostStateError, match="already running"):
            await runtime.run(driver.run)

    asyncio.run(scenario())


def test_host_runtime_runs_deferred_operation_after_active_run() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        first = asyncio.create_task(runtime.run(driver.run))
        await driver.started.wait()

        second = asyncio.create_task(
            runtime.run_after_idle(lambda: _async_value("deferred-result"))
        )
        await asyncio.sleep(0)
        assert not second.done()

        driver.release.set()
        assert await first == "reference-result"
        assert await second == "deferred-result"
        assert runtime.status == "idle"

    asyncio.run(scenario())


def test_host_runtime_coalesces_deferred_operations_by_key() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        calls: list[str] = []

        async def operation() -> str:
            calls.append("continue")
            return "continued"

        first = runtime.defer_run(operation, key="agent-continue")
        second = runtime.defer_run(operation, key="agent-continue")
        assert first is second

        assert await first == "continued"
        assert calls == ["continue"]
        assert runtime.status == "idle"

    asyncio.run(scenario())


def test_canceling_deferred_run_does_not_cancel_active_run() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        events: list[HostLifecycleEvent] = []
        runtime.subscribe(events.append)
        active = asyncio.create_task(runtime.run(driver.run, run_id="active"))
        await driver.started.wait()

        deferred = runtime.defer_run(
            lambda: _async_value("must-not-run"),
            run_id="queued",
        )
        await asyncio.sleep(0)

        assert deferred.cancel() is True
        with pytest.raises(asyncio.CancelledError):
            await deferred
        assert not active.done()

        driver.release.set()
        assert await active == "reference-result"
        assert [
            (event.kind, event.run_id)
            for event in events
            if event.kind in {"run_started", "run_completed", "run_failed"}
        ] == [
            ("run_started", "active"),
            ("run_completed", "active"),
        ]

    asyncio.run(scenario())


def test_failed_active_run_does_not_poison_deferred_run() -> None:
    async def scenario() -> None:
        runtime: HostRuntime[str] = HostRuntime()
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        calls: list[str] = []

        async def first() -> str:
            calls.append("first")
            first_started.set()
            await release_first.wait()
            raise ValueError("first failed")

        async def second() -> str:
            calls.append("second")
            return "second-ok"

        first_task = runtime.defer_run(first, run_id="first")
        await first_started.wait()
        second_task = runtime.defer_run(second, run_id="second")
        await asyncio.sleep(0)
        release_first.set()

        with pytest.raises(ValueError, match="first failed"):
            await first_task
        assert await second_task == "second-ok"
        assert calls == ["first", "second"]
        assert runtime.status == "idle"

    asyncio.run(scenario())


def test_canceling_idle_waiter_does_not_cancel_active_run() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        active = asyncio.create_task(runtime.run(driver.run))
        await driver.started.wait()
        waiter = asyncio.create_task(runtime.wait_for_idle())
        await asyncio.sleep(0)

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not active.done()

        driver.release.set()
        assert await active == "reference-result"

    asyncio.run(scenario())


def test_canceling_external_idle_waiter_does_not_cancel_driver_task() -> None:
    async def scenario() -> None:
        running = True
        release = asyncio.Event()

        async def external_run() -> None:
            nonlocal running
            try:
                await release.wait()
            finally:
                running = False

        external_task = asyncio.create_task(external_run())
        runtime: HostRuntime[None] = HostRuntime(
            wait_for_idle_driver=lambda: external_task,
            is_running_driver=lambda: running,
        )
        waiter = asyncio.create_task(runtime.wait_for_idle())
        await asyncio.sleep(0)

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not external_task.done()

        release.set()
        await external_task
        await runtime.wait_for_idle()
        assert runtime.status == "idle"

    asyncio.run(scenario())


def test_start_listener_failure_releases_deferred_waiters() -> None:
    async def scenario() -> None:
        runtime: HostRuntime[str] = HostRuntime()
        listener_started = asyncio.Event()
        release_listener = asyncio.Event()
        fail_once = True
        calls: list[str] = []

        async def listener(event: HostLifecycleEvent) -> None:
            nonlocal fail_once
            if event.kind == "run_started" and fail_once:
                fail_once = False
                listener_started.set()
                await release_listener.wait()
                raise RuntimeError("listener failure")

        runtime.subscribe(listener)

        async def first() -> str:
            calls.append("first")
            return "must-not-run"

        async def second() -> str:
            calls.append("second")
            return "second-ok"

        first_task = runtime.defer_run(first, run_id="first")
        await listener_started.wait()
        second_task = runtime.defer_run(second, run_id="second")
        await asyncio.sleep(0)
        release_listener.set()

        with pytest.raises(RuntimeError, match="listener failure"):
            await first_task
        assert await asyncio.wait_for(second_task, timeout=1) == "second-ok"
        assert calls == ["second"]
        assert runtime.status == "idle"

    asyncio.run(scenario())


def test_deferred_broadcast_wakeups_preserve_single_active_run() -> None:
    async def scenario() -> None:
        runtime: HostRuntime[int | None] = HostRuntime()
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        active_operations = 0
        max_active_operations = 0
        calls: list[int] = []

        async def blocker() -> None:
            blocker_started.set()
            await release_blocker.wait()

        async def operation(index: int) -> int:
            nonlocal active_operations, max_active_operations
            active_operations += 1
            max_active_operations = max(max_active_operations, active_operations)
            calls.append(index)
            try:
                await asyncio.sleep(0)
                if index % 7 == 0:
                    raise ValueError(f"failure-{index}")
                return index
            finally:
                active_operations -= 1

        blocker_task = asyncio.create_task(runtime.run(blocker))
        await blocker_started.wait()
        deferred = [
            runtime.defer_run(lambda index=index: operation(index))
            for index in range(30)
        ]
        await asyncio.sleep(0)
        release_blocker.set()

        await blocker_task
        results = await asyncio.gather(*deferred, return_exceptions=True)

        assert sorted(calls) == list(range(30))
        assert max_active_operations == 1
        for index, result in enumerate(results):
            if index % 7 == 0:
                assert isinstance(result, ValueError)
            else:
                assert result == index
        assert runtime.status == "idle"

    asyncio.run(scenario())


def test_host_task_handle_wait_is_observational() -> None:
    async def scenario() -> None:
        runtime: HostRuntime[str] = HostRuntime()
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation() -> str:
            started.set()
            await release.wait()
            return "background-result"

        handle = runtime.defer_run_handle(operation)
        assert isinstance(handle, HostTaskHandle)
        await started.wait()
        waiter = asyncio.create_task(handle.wait())
        await asyncio.sleep(0)

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert handle.done() is False

        release.set()
        assert await handle.wait() == "background-result"
        assert handle.done() is True
        assert handle.cancelled() is False
        assert handle.cancel() is False

    asyncio.run(scenario())


def test_host_task_handle_cancel_aborts_only_its_active_run() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        events: list[HostLifecycleEvent] = []
        runtime.subscribe(events.append)
        handle = runtime.defer_run_handle(driver.run, run_id="child-round")
        await driver.started.wait()

        assert handle.run_id == "child-round"
        assert handle.cancel() is True
        assert await handle.wait() == "reference-result"
        await runtime.wait_for_idle()

        assert driver.abort_calls == 1
        assert handle.cancel() is False
        assert [event.kind for event in events] == [
            "run_started",
            "abort_requested",
            "run_aborted",
        ]

    asyncio.run(scenario())


def test_host_task_handle_coalesces_identity_and_run_id_by_key() -> None:
    async def scenario() -> None:
        runtime: HostRuntime[str] = HostRuntime()
        calls: list[str] = []

        async def operation() -> str:
            calls.append("continued")
            return "continued"

        first = runtime.defer_run_handle(
            operation,
            key="agent-continue",
            run_id="original-run",
        )
        second = runtime.defer_run_handle(
            operation,
            key="agent-continue",
            run_id="ignored-run",
        )

        assert first is second
        assert second.run_id == "original-run"
        assert await first.wait() == "continued"
        assert calls == ["continued"]

    asyncio.run(scenario())


def test_host_runtime_abort_and_wait_recovers_an_external_driver_run() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        driver.running = True
        runtime = _runtime(driver)

        assert runtime.status == "running"
        assert runtime.abort() is True
        assert runtime.status == "aborting"
        driver.running = False
        await runtime.wait_for_idle()

        assert runtime.status == "idle"
        assert driver.abort_calls == 1

    asyncio.run(scenario())


def test_host_runtime_disposes_idempotently_and_rejects_new_runs() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        events: list[HostLifecycleEvent] = []
        runtime.subscribe(events.append)
        task = asyncio.create_task(runtime.run(driver.run, run_id="ppt-run"))
        await driver.started.wait()

        await runtime.dispose()
        await task
        await runtime.dispose()

        assert runtime.status == "disposed"
        assert driver.abort_calls == 1
        assert driver.dispose_calls == 1
        assert events[-1].kind == "host_disposed"
        with pytest.raises(HostStateError, match="disposed"):
            await runtime.run(driver.run)

    asyncio.run(scenario())


def test_host_runtime_dispose_cancels_queued_deferred_runs() -> None:
    async def scenario() -> None:
        driver = ReferenceDriver()
        runtime = _runtime(driver)
        queued_calls: list[str] = []
        active = runtime.defer_run_handle(driver.run, run_id="active")
        await driver.started.wait()

        async def queued_operation() -> str:
            queued_calls.append("queued")
            return "queued-result"

        queued = [
            runtime.defer_run_handle(
                queued_operation,
                run_id=f"queued-{index}",
            )
            for index in range(3)
        ]
        await asyncio.sleep(0)

        await runtime.dispose()

        assert await active.wait() == "reference-result"
        for handle in queued:
            with pytest.raises(asyncio.CancelledError):
                await handle.wait()
            assert handle.cancelled() is True
        assert queued_calls == []
        assert runtime.is_disposed is True

    asyncio.run(scenario())


def test_host_runtime_calls_dispose_driver_when_wait_for_idle_fails() -> None:
    async def scenario() -> None:
        dispose_calls = 0

        async def fail_wait() -> None:
            raise RuntimeError("wait failure")

        async def dispose_driver() -> None:
            nonlocal dispose_calls
            dispose_calls += 1

        runtime: HostRuntime[None] = HostRuntime(
            wait_for_idle_driver=fail_wait,
            dispose_driver=dispose_driver,
        )

        with pytest.raises(RuntimeError, match="wait failure"):
            await runtime.dispose()

        assert runtime.status == "disposed"
        assert dispose_calls == 1

    asyncio.run(scenario())

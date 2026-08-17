from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from loushang.harness.events.session import RetryAttempt, RetryOutcome
from loushang.harness.runtime.retry import (
    RetryCoordinator,
    RetryPolicy,
)


@dataclass
class CancelHandle:
    cancelled: bool = False


def test_retry_coordinator_owns_backoff_and_success_waiter() -> None:
    attempts: list[RetryAttempt] = []
    outcomes: list[RetryOutcome] = []
    continued: list[str] = []
    delays: list[int] = []
    coordinator = _coordinator(attempts, outcomes, delays)

    async def scenario() -> None:
        assert await coordinator.retry("busy", policy=RetryPolicy(True, 3, 25)) is True
        coordinator.continue_retry(lambda: _append(continued, "continue"))
        await asyncio.sleep(0)
        assert await coordinator.retry("busy", policy=RetryPolicy(True, 3, 25)) is True
        coordinator.continue_retry(lambda: _append(continued, "continue"))
        await asyncio.sleep(0)
        await coordinator.finish(RetryOutcome(success=True, attempt=2))
        await coordinator.wait()

    asyncio.run(scenario())

    assert delays == [25, 50]
    assert [attempt.attempt for attempt in attempts] == [1, 2]
    assert outcomes == [RetryOutcome(success=True, attempt=2)]
    assert continued == ["continue", "continue"]
    assert coordinator.is_retrying is False


def test_retry_coordinator_cancels_pending_delay_and_resolves_waiter() -> None:
    attempts: list[RetryAttempt] = []
    outcomes: list[RetryOutcome] = []
    started = asyncio.Event()

    async def blocking_delay(delay_ms: int, handle: CancelHandle) -> None:
        del delay_ms
        started.set()
        while not handle.cancelled:
            await asyncio.sleep(0)
        raise asyncio.CancelledError

    coordinator = RetryCoordinator(
        create_cancel_handle=CancelHandle,
        cancel=lambda handle: setattr(handle, "cancelled", True),
        delay=blocking_delay,
        on_started=lambda attempt: _append(attempts, attempt),
        on_finished=lambda outcome: _append(outcomes, outcome),
    )

    async def scenario() -> None:
        task = asyncio.create_task(
            coordinator.retry("busy", policy=RetryPolicy(True, 2, 1))
        )
        await started.wait()
        coordinator.abort()
        assert await task is False
        await coordinator.wait()

    asyncio.run(scenario())

    assert outcomes == [RetryOutcome(success=False, attempt=1, cancelled=True)]
    assert coordinator.is_retrying is False


def test_retry_coordinator_rejects_reentry_and_reports_exhaustion() -> None:
    gate = asyncio.Event()
    outcomes: list[RetryOutcome] = []

    async def delay(delay_ms: int, handle: CancelHandle) -> None:
        del delay_ms, handle
        await gate.wait()

    coordinator = RetryCoordinator(
        create_cancel_handle=CancelHandle,
        cancel=lambda handle: setattr(handle, "cancelled", True),
        delay=delay,
        on_started=lambda attempt: _noop(),
        on_finished=lambda outcome: _append(outcomes, outcome),
    )

    async def scenario() -> None:
        active = asyncio.create_task(
            coordinator.retry("busy", policy=RetryPolicy(True, 1, 1))
        )
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="already in progress"):
            await coordinator.retry("busy", policy=RetryPolicy(True, 1, 1))
        gate.set()
        assert await active is True
        assert (
            await coordinator.retry("still busy", policy=RetryPolicy(True, 1, 1))
            is False
        )

    asyncio.run(scenario())

    assert outcomes == [RetryOutcome(success=False, attempt=1, error="still busy")]


def test_retry_coordinator_cleans_up_when_a_driver_fails() -> None:
    async def fail_started(_attempt: RetryAttempt) -> None:
        raise RuntimeError("event sink failed")

    coordinator = RetryCoordinator(
        create_cancel_handle=CancelHandle,
        cancel=lambda handle: setattr(handle, "cancelled", True),
        delay=lambda delay_ms, handle: _noop(),
        on_started=fail_started,
        on_finished=lambda outcome: _noop(),
    )

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="event sink failed"):
            await coordinator.retry("busy", policy=RetryPolicy(True, 2, 1))
        await coordinator.wait()

    asyncio.run(scenario())

    assert coordinator.is_retrying is False
    assert coordinator.attempt == 0


def test_retry_coordinator_observes_deferred_continuation_failure() -> None:
    outcomes: list[RetryOutcome] = []

    async def fail_continue() -> None:
        raise RuntimeError("host is already running")

    coordinator = RetryCoordinator(
        create_cancel_handle=CancelHandle,
        cancel=lambda handle: setattr(handle, "cancelled", True),
        delay=lambda delay_ms, handle: _noop(),
        on_started=lambda attempt: _noop(),
        on_finished=lambda outcome: _append(outcomes, outcome),
    )

    async def scenario() -> None:
        assert await coordinator.retry("busy", policy=RetryPolicy(True, 1, 1))
        coordinator.continue_retry(fail_continue)
        await coordinator.wait()

    asyncio.run(scenario())

    assert outcomes == [
        RetryOutcome(
            success=False,
            attempt=1,
            error="host is already running",
        )
    ]
    assert coordinator.is_retrying is False


def _coordinator(
    attempts: list[RetryAttempt],
    outcomes: list[RetryOutcome],
    delays: list[int],
) -> RetryCoordinator[CancelHandle]:
    async def delay(delay_ms: int, handle: CancelHandle) -> None:
        del handle
        delays.append(delay_ms)

    return RetryCoordinator(
        create_cancel_handle=CancelHandle,
        cancel=lambda handle: setattr(handle, "cancelled", True),
        delay=delay,
        on_started=lambda attempt: _append(attempts, attempt),
        on_finished=lambda outcome: _append(outcomes, outcome),
    )


async def _append(values: list, value: object) -> None:
    values.append(value)


async def _noop() -> None:
    return None

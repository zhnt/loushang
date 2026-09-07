from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appservice._operations import _OwnedAppOperations


def test_G16_ACCEPTED_WORK_cancelled_waiter_retains_work_and_busy_key() -> None:
    async def scenario() -> None:
        owner = _OwnedAppOperations()
        entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls: list[str] = []

        async def operation() -> None:
            calls.append("started")
            entered.set()
            await release.wait()
            calls.append("completed")
            completed.set()

        waiter = asyncio.create_task(owner.execute(operation, key="session-1"))
        await entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert owner.pending_counts == (1, 0)
        with pytest.raises(AppServiceError) as busy:
            await owner.execute(operation, key="session-1")
        assert busy.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        assert calls == ["started"]
        release.set()
        await completed.wait()
        assert calls == ["started", "completed"]
        assert owner.pending_counts == (0, 0)
        await owner.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_BOUNDS_ordinary_and_control_capacity_are_independent() -> None:
    async def scenario() -> None:
        owner = _OwnedAppOperations(max_ordinary=1, max_control=1)
        entered, control_entered = asyncio.Event(), asyncio.Event()
        release = asyncio.Event()

        async def ordinary() -> None:
            entered.set()
            await release.wait()

        async def control() -> None:
            control_entered.set()
            await release.wait()

        first = asyncio.create_task(owner.execute(ordinary))
        await entered.wait()
        second = asyncio.create_task(owner.execute(control, control=True))
        await control_entered.wait()
        assert owner.pending_counts == (1, 1)
        for callback, reserved in ((ordinary, False), (control, True)):
            with pytest.raises(AppServiceError) as full:
                await owner.execute(callback, control=reserved)
            assert full.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
        await owner.close()
        await asyncio.gather(first, second, return_exceptions=True)
        assert owner.pending_counts == (0, 0)

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_STOP_timeout_retains_cleanup_without_repeated_cancellation() -> None:
    async def scenario() -> None:
        owner = _OwnedAppOperations(close_timeout=0.01)
        entered, cancellation, cleanup_release = (
            asyncio.Event(), asyncio.Event(), asyncio.Event()
        )
        cancellations: list[str] = []

        async def operation() -> None:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellations.append("cancelled")
                cancellation.set()
                await cleanup_release.wait()

        waiter = asyncio.create_task(owner.execute(operation))
        await entered.wait()
        for _ in range(2):
            with pytest.raises(AppServiceError) as debt:
                await owner.close()
            assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
        assert cancellation.is_set() and cancellations == ["cancelled"]
        assert owner.pending_counts == (1, 0)
        with pytest.raises(AppServiceError) as fenced:
            await owner.execute(operation)
        assert fenced.value.code is AppErrorCodeV1.SERVICE_CLOSED
        cleanup_release.set()
        await waiter
        await owner.close()
        assert owner.pending_counts == (0, 0)

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_STOP_cancelling_close_waiter_keeps_single_cleanup_owner() -> None:
    async def scenario() -> None:
        owner = _OwnedAppOperations(close_timeout=1)
        entered, cancellation, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def operation() -> None:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation.set()
                await release.wait()

        waiter = asyncio.create_task(owner.execute(operation))
        await entered.wait()
        closing = asyncio.create_task(owner.close())
        await cancellation.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert owner.pending_counts == (1, 0)
        release.set()
        await owner.close()
        await waiter
        assert owner.pending_counts == (0, 0)

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_ACCEPTED_WORK_failure_after_delivery_loss_is_observed() -> None:
    async def scenario() -> None:
        owner = _OwnedAppOperations()
        entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        errors: list[dict[str, object]] = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, context: errors.append(context)
        )

        async def operation() -> None:
            entered.set()
            await release.wait()
            completed.set()
            raise ValueError("private-operation-error")

        waiter = asyncio.create_task(owner.execute(operation))
        await entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        await completed.wait()
        await owner.close()
        assert owner.pending_counts == (0, 0)
        assert errors == []

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_BOUNDS_task_cancelled_before_first_step_releases_reservation() -> None:
    async def scenario() -> None:
        owner = _OwnedAppOperations(max_ordinary=1)
        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()
        effects: list[str] = []

        async def operation() -> None:
            effects.append("effect")

        def cancelled_factory(loop, coroutine, **kwargs):
            task = asyncio.Task(coroutine, loop=loop, **kwargs)
            task.cancel()
            return task

        loop.set_task_factory(cancelled_factory)
        try:
            with pytest.raises(asyncio.CancelledError):
                await owner.execute(operation, key="session-1")
        finally:
            loop.set_task_factory(previous)
        assert owner.pending_counts == (0, 0) and effects == []
        await owner.execute(operation, key="session-1")
        assert effects == ["effect"]
        await owner.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_BOUNDS_task_factory_failure_rolls_back_before_effect() -> None:
    async def scenario() -> None:
        owner = _OwnedAppOperations(max_ordinary=1)
        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()
        effects: list[str] = []

        async def operation() -> None:
            effects.append("effect")

        def failed_factory(loop, coroutine, **kwargs):
            raise RuntimeError("task-factory-failed")

        loop.set_task_factory(failed_factory)
        try:
            with pytest.raises(RuntimeError, match="task-factory-failed"):
                await owner.execute(operation, key="session-1")
        finally:
            loop.set_task_factory(previous)
        assert owner.pending_counts == (0, 0) and effects == []
        await owner.execute(operation, key="session-1")
        assert effects == ["effect"]
        await owner.close()

    asyncio.run(asyncio.wait_for(scenario(), 2))


def test_G16_STOP_task_factory_failure_keeps_work_owned_for_retry() -> None:
    async def scenario() -> None:
        owner = _OwnedAppOperations()
        entered = asyncio.Event()

        async def operation() -> None:
            entered.set()
            await asyncio.Event().wait()

        waiter = asyncio.create_task(owner.execute(operation))
        await entered.wait()
        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()

        def failed_factory(loop, coroutine, **kwargs):
            raise RuntimeError("task-factory-failed")

        loop.set_task_factory(failed_factory)
        try:
            with pytest.raises(RuntimeError, match="task-factory-failed"):
                await owner.close()
        finally:
            loop.set_task_factory(previous)
        assert owner.pending_counts == (1, 0) and not waiter.done()
        await owner.close()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert owner.pending_counts == (0, 0)

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_G16_BOUNDS_rejects_invalid_capacity(capacity: int) -> None:
    with pytest.raises(ValueError):
        _OwnedAppOperations(max_ordinary=capacity)


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan")])
def test_G16_BOUNDS_rejects_invalid_close_deadline(timeout: float) -> None:
    with pytest.raises(ValueError):
        _OwnedAppOperations(close_timeout=timeout)

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps

import pytest

from loushang.appserver.protocol import (
    AckV1,
    AppErrorCodeV1,
    AppFailureV1,
    AppServiceError,
)
from loushang.appservice.execution_contract import (
    ExecutionOutcomeV1,
    ExecutionRequestV1,
    ExecutionStatusV1,
    InterruptModeV1,
)
from loushang.appservice.execution_guard import ExecutionControlV1, ExecutionGuardV1


def scenario(fn: Callable[[], Awaitable[None]]) -> Callable[[], None]:
    @wraps(fn)
    def run() -> None:
        asyncio.run(asyncio.wait_for(fn(), 3))

    return run


class Work:
    def __init__(self, *, agent: bool = False) -> None:
        self.agent = agent
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cleaning = asyncio.Event()
        self.quiesce = asyncio.Event()
        self.quiesce.set()
        self.interrupted = asyncio.Event()
        self.result = ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
        self.raise_error = False
        self.cleanup_error = False
        self.starts = 0
        self.turn_interrupts = 0

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
        self.starts += 1

        def abort() -> bool:
            self.turn_interrupts += 1
            self.interrupted.set()
            self.release.set()
            return True

        unsubscribe = control.bind_turn_interrupt(abort) if self.agent else lambda: None
        self.entered.set()
        try:
            await self.release.wait()
            if self.raise_error:
                raise RuntimeError("private Product details")
            return self.result
        except asyncio.CancelledError:
            self.interrupted.set()
            raise
        finally:
            unsubscribe()

    async def settle(self) -> None:
        self.cleaning.set()
        await self.quiesce.wait()
        if self.cleanup_error:
            raise RuntimeError("private cleanup details")


@scenario
async def test_explicit_entry_is_delivered_before_silent_work_and_terminal_after_cleanup():
    guard, work = ExecutionGuardV1(source_cursor=lambda: 7), Work()
    seen = []

    def observe(value):
        seen.append((value, work.starts, work.cleaning.is_set()))

    unsubscribe = guard.subscribe_observation(observe)
    guard.start(ExecutionRequestV1("silent", "command"), work)
    assert seen == []
    await work.entered.wait()
    assert len(seen) == 1
    assert seen[0][0].execution_id == "silent"
    assert seen[0][0].status is ExecutionStatusV1.RUNNING
    assert seen[0][1:] == (0, False)
    work.release.set()
    await guard.wait("silent")
    assert seen[-1][0].final_cursor == 7
    assert seen[-1][1:] == (1, True)
    unsubscribe()
    guard.start(ExecutionRequestV1("cancel-before-entry", "command"), Work())
    guard.interrupt("cancel-before-entry", InterruptModeV1.WHOLE_EXECUTION)
    await guard.wait("cancel-before-entry")
    assert len(seen) == 2


@scenario
async def test_whole_interrupt_covers_preflight_and_retains_cleanup_ownership() -> None:
    guard = ExecutionGuardV1()
    work = Work()
    work.quiesce.clear()
    guard.start(ExecutionRequestV1("A", "command"), work)
    await work.entered.wait()
    assert guard.observation.status is ExecutionStatusV1.RUNNING
    assert guard.interrupt("A", InterruptModeV1.LEGACY_TURN_ONLY) is False
    assert not work.interrupted.is_set()
    assert guard.interrupt("A", InterruptModeV1.WHOLE_EXECUTION) is True
    await work.cleaning.wait()
    assert work.interrupted.is_set()
    assert guard.observation.status is ExecutionStatusV1.RUNNING
    with pytest.raises(AppServiceError) as busy:
        guard.start(ExecutionRequestV1("B", "next"), Work())
    assert busy.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
    assert guard.interrupt("A", InterruptModeV1.WHOLE_EXECUTION) is True
    waiter = asyncio.create_task(guard.wait("A"))
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not work.quiesce.is_set()
    work.quiesce.set()
    result = await guard.wait("A")
    assert result.status is ExecutionStatusV1.INTERRUPTED
    assert guard.observation.status is ExecutionStatusV1.INTERRUPTED


@scenario
async def test_pre_first_step_interrupt_never_enters_product() -> None:
    guard = ExecutionGuardV1()
    work = Work()
    guard.start(ExecutionRequestV1("A", "hello"), work)
    assert guard.interrupt("A", InterruptModeV1.WHOLE_EXECUTION)
    assert (await guard.wait("A")).status is ExecutionStatusV1.INTERRUPTED
    assert work.starts == 0
    assert not work.cleaning.is_set()


@scenario
async def test_no_model_success_and_late_interrupt_cannot_affect_next_execution() -> (
    None
):
    guard = ExecutionGuardV1()
    first = Work()
    first.release.set()
    guard.start(ExecutionRequestV1("A", "handled by command"), first)
    assert (await guard.wait("A")).status is ExecutionStatusV1.SUCCEEDED
    second = Work()
    guard.start(ExecutionRequestV1("B", "next"), second)
    await second.entered.wait()
    assert not guard.interrupt("A", InterruptModeV1.WHOLE_EXECUTION)
    assert not second.interrupted.is_set()
    second.release.set()
    assert (await guard.wait("B")).status is ExecutionStatusV1.SUCCEEDED


@scenario
async def test_explicit_failed_outcome_preserves_legacy_ack() -> None:
    guard = ExecutionGuardV1()
    work = Work()
    work.result = ExecutionOutcomeV1(
        ExecutionStatusV1.FAILED, error_code="model_failed"
    )
    work.release.set()
    guard.start(ExecutionRequestV1("A", "hello"), work)
    result = await guard.wait("A")
    assert result.status is ExecutionStatusV1.FAILED
    assert result.legacy_result == AckV1()


@scenario
async def test_natural_completion_wins_interrupt_during_cleanup() -> None:
    guard = ExecutionGuardV1()
    work = Work()
    work.release.set()
    work.quiesce.clear()
    guard.start(ExecutionRequestV1("A", "hello"), work)
    await work.cleaning.wait()
    assert guard.interrupt("A", InterruptModeV1.WHOLE_EXECUTION)
    work.quiesce.set()
    assert (await guard.wait("A")).status is ExecutionStatusV1.SUCCEEDED


@scenario
async def test_legacy_agent_abort_uses_product_callback_without_full_call_cancel() -> (
    None
):
    guard = ExecutionGuardV1()
    work = Work(agent=True)
    work.result = ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
    guard.start(ExecutionRequestV1("A", "hello"), work)
    await work.entered.wait()
    assert guard.interrupt("A", InterruptModeV1.LEGACY_TURN_ONLY)
    assert work.turn_interrupts == 1
    assert not guard.interrupt_requested
    assert (await guard.wait("A")).status is ExecutionStatusV1.INTERRUPTED


@scenario
async def test_cleanup_failure_keeps_slot_until_explicit_retry_proves_quiescence() -> (
    None
):
    guard = ExecutionGuardV1()
    work = Work()
    work.raise_error = True
    work.cleanup_error = True
    work.release.set()
    guard.start(ExecutionRequestV1("A", "hello"), work)
    with pytest.raises(AppServiceError) as debt:
        await guard.wait("A")
    assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
    assert guard.observation.status is ExecutionStatusV1.RUNNING
    with pytest.raises(AppServiceError):
        guard.start(ExecutionRequestV1("B", "next"), Work())
    work.cleanup_error = False
    await guard.retry_settlement("A")
    result = await guard.wait("A")
    assert result.status is ExecutionStatusV1.FAILED
    assert result.error_code == "execution_failed"
    assert result.legacy_result == AppFailureV1(AppErrorCodeV1.SESSION_UNAVAILABLE)
    assert work.starts == 1


@scenario
async def test_waiter_keeps_its_result_when_next_execution_starts_before_delivery() -> (
    None
):
    guard = ExecutionGuardV1()
    first, second = Work(), Work()
    guard.start(ExecutionRequestV1("A", "first"), first)
    await first.entered.wait()
    assert guard._task is not None
    guard._task.add_done_callback(
        lambda _: guard.start(ExecutionRequestV1("B", "next"), second)
    )
    joined = asyncio.Event()

    async def wait() -> ExecutionOutcomeV1:
        joined.set()
        return await guard.wait("A")

    waiter = asyncio.create_task(wait())
    await joined.wait()
    first.release.set()
    result = await waiter
    assert result.status is ExecutionStatusV1.SUCCEEDED
    second.release.set()
    await guard.wait("B")


@scenario
async def test_cancelled_delivery_waiter_does_not_cancel_running_work() -> None:
    guard = ExecutionGuardV1()
    work = Work()
    guard.start(ExecutionRequestV1("A", "input"), work)
    await work.entered.wait()
    joined = asyncio.Event()

    async def wait() -> ExecutionOutcomeV1:
        joined.set()
        return await guard.wait("A")

    waiter = asyncio.create_task(wait())
    await joined.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not work.interrupted.is_set()
    assert guard.state.status is ExecutionStatusV1.RUNNING
    work.release.set()
    assert (await guard.wait("A")).status is ExecutionStatusV1.SUCCEEDED


@scenario
async def test_uncancellable_child_effect_is_joined_before_terminal_publication() -> (
    None
):
    entered, release, finished, joining = (asyncio.Event() for _ in range(4))

    class ChildWork:
        child: asyncio.Task[None] | None = None

        async def effect(self) -> None:
            entered.set()
            await release.wait()
            finished.set()

        async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
            self.child = asyncio.create_task(self.effect())
            await asyncio.shield(self.child)
            return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)

        async def settle(self) -> None:
            joining.set()
            assert self.child is not None
            await asyncio.shield(self.child)

    guard = ExecutionGuardV1()
    guard.start(ExecutionRequestV1("A", "external effect"), ChildWork())
    await entered.wait()
    guard.interrupt("A", InterruptModeV1.WHOLE_EXECUTION)
    await joining.wait()
    assert not finished.is_set()
    assert guard.state.status is ExecutionStatusV1.RUNNING
    release.set()
    assert (await guard.wait("A")).status is ExecutionStatusV1.INTERRUPTED
    assert finished.is_set()


def test_task_construction_failure_does_not_consume_the_guard(monkeypatch) -> None:
    async def run() -> None:
        guard = ExecutionGuardV1()
        work = Work()
        original = asyncio.create_task

        def fail(coroutine):
            raise RuntimeError("construction failed")

        with monkeypatch.context() as patch:
            patch.setattr(asyncio, "create_task", fail)
            with pytest.raises(RuntimeError, match="construction failed"):
                guard.start(ExecutionRequestV1("A", "input"), work)
        assert guard.state is None
        assert work.starts == 0
        assert asyncio.create_task is original
        work.release.set()
        guard.start(ExecutionRequestV1("A", "input"), work)
        await guard.wait("A")

    asyncio.run(run())


def test_immediate_failed_settlement_retry_retains_debt(monkeypatch) -> None:
    async def run() -> None:
        guard, work = ExecutionGuardV1(), Work()
        work.release.set()
        work.cleanup_error = True
        guard.start(ExecutionRequestV1("A", "input"), work)
        with pytest.raises(AppServiceError):
            await guard.wait("A")

        def immediate(coroutine):
            # This retry has no suspension: exercise eager completion even on 3.11.
            future = asyncio.get_running_loop().create_future()
            try:
                coroutine.send(None)
            except StopIteration as result:
                future.set_result(result.value)
            except Exception as error:
                future.set_exception(error)
            else:
                coroutine.close()
                raise AssertionError("fixture retry unexpectedly suspended")
            return future

        with monkeypatch.context() as patch:
            patch.setattr(asyncio, "create_task", immediate)
            with pytest.raises(AppServiceError) as debt:
                await guard.retry_settlement("A")
            assert debt.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
            work.cleanup_error = False
            await guard.retry_settlement("A")
        assert (await guard.wait("A")).status is ExecutionStatusV1.SUCCEEDED
        assert work.starts == 1

    asyncio.run(run())

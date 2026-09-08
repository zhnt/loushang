"""Opt-in Product helper for retained invocation and whole-call settlement.

Products still own work and resource cleanup. The helper never treats Task
completion as quiescence: the Product's retryable settle callback must finish.
It owns one binding's active and latest invocation, not a submission ledger.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from loushang.appserver.protocol import AppErrorCodeV1, AppFailureV1, AppServiceError

from .execution_contract import (
    ExecutionObservationV1,
    ExecutionOutcomeV1,
    ExecutionRequestV1,
    ExecutionStateV1,
    ExecutionStatusV1,
    InterruptModeV1,
    _counter,
    _identifier,
)


def _observe(task: asyncio.Task[ExecutionOutcomeV1]) -> None:
    if not task.cancelled():
        task.exception()


class ExecutionControlV1:
    """One invocation's legacy turn hook; Product clears it when that turn ends."""

    def __init__(self) -> None:
        self._turn_interrupt: Callable[[], bool] | None = None

    def bind_turn_interrupt(self, callback: Callable[[], bool]) -> Callable[[], None]:
        if not callable(callback) or self._turn_interrupt is not None:
            raise ValueError("execution already has a turn interrupt binding")
        self._turn_interrupt = callback

        def unbind() -> None:
            if self._turn_interrupt is callback:
                self._turn_interrupt = None

        return unbind


class ExecutionWorkV1(Protocol):
    """Product-owned work and retryable proof of its resource quiescence.

    run may catch cancellation and return its actual outcome. settle joins all
    retained effects, including uncancellable work; failure leaves cleanup debt.
    It must be safe to retry settle, but run is never retried by this helper.
    """

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1: ...

    async def settle(self) -> None: ...


class ExecutionGuardV1:
    def __init__(self, *, source_cursor: Callable[[], int] = lambda: 0) -> None:
        self._source_cursor = source_cursor
        self._state: ExecutionStateV1 | None = None
        self._observation = ExecutionObservationV1()
        self._task: asyncio.Task[ExecutionOutcomeV1] | None = None
        self._work: ExecutionWorkV1 | None = None
        self._control = ExecutionControlV1()
        self._entered = False
        self._candidate: ExecutionOutcomeV1 | None = None
        self._debt = False

    @property
    def observation(self) -> ExecutionObservationV1:
        return self._observation

    @property
    def state(self) -> ExecutionStateV1 | None:
        return self._state

    @property
    def interrupt_requested(self) -> bool:
        return self._state is not None and self._state.interrupt_requested

    def start(self, request: ExecutionRequestV1, work: ExecutionWorkV1) -> None:
        if type(request) is not ExecutionRequestV1:
            raise TypeError("invalid execution request")
        if self._state is not None and (
            not self._state.status.terminal
            or self._state.execution_id == request.execution_id
        ):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        # Hold publication even with an eager Task factory.
        published = asyncio.get_running_loop().create_future()

        async def invoke() -> ExecutionOutcomeV1:
            await published
            return await self._drive()

        invocation = invoke()
        try:
            task = asyncio.create_task(invocation)
        except BaseException:
            invocation.close()
            raise
        self._state = ExecutionStateV1(
            request.execution_id, ExecutionStatusV1.ACCEPTED, 1
        )
        self._work = work
        self._control = ExecutionControlV1()
        self._candidate = None
        self._entered = False
        self._debt = False
        self._task = task
        task.add_done_callback(_observe)
        published.set_result(None)

    def interrupt(self, execution_id: str, mode: InterruptModeV1) -> bool:
        _identifier(execution_id)
        if type(mode) is not InterruptModeV1:
            raise TypeError("invalid interrupt mode")
        state = self._state
        if state is None or state.execution_id != execution_id or state.status.terminal:
            return False
        if mode is InterruptModeV1.LEGACY_TURN_ONLY:
            callback = self._control._turn_interrupt
            if callback is None:
                return False
            result = callback()
            if type(result) is not bool:
                raise TypeError("invalid Product interrupt result")
            return result
        if not state.interrupt_requested:
            self._state = replace(
                state, revision=state.revision + 1, interrupt_requested=True
            )
            # Never inject another cancellation into resource settlement. Before
            # entry, the coroutine itself observes the request without running work.
            if self._entered and self._candidate is None:
                assert self._task is not None
                self._task.cancel()
        return True

    async def wait(self, execution_id: str) -> ExecutionOutcomeV1:
        state = self._require_target(execution_id)
        if state.outcome is not None:
            return state.outcome
        task = self._task
        assert task is not None
        # Bind delivery to this invocation, even when B starts before A's waiter
        # is rescheduled. The binding's current/latest state may already be B.
        return await asyncio.shield(task)

    async def retry_settlement(self, execution_id: str) -> None:
        self._require_target(execution_id)
        if self._debt:
            # Install the retained retry before yielding so concurrent retries join it.
            operation = self._settle()
            # An eager factory may settle (or restore debt) inside create_task.
            self._debt = False
            try:
                task = asyncio.create_task(operation)
            except BaseException:
                operation.close()
                self._debt = True
                raise
            self._task = task
            task.add_done_callback(_observe)
        await self.wait(execution_id)

    def _require_target(self, execution_id: str) -> ExecutionStateV1:
        _identifier(execution_id)
        if self._state is None or self._state.execution_id != execution_id:
            raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
        return self._state

    async def _drive(self) -> ExecutionOutcomeV1:
        assert self._state is not None and self._work is not None
        if self._state.interrupt_requested:
            self._candidate = ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
            self._commit()
            return self._candidate
        self._entered = True
        self._state = replace(
            self._state,
            status=ExecutionStatusV1.RUNNING,
            revision=self._state.revision + 1,
        )
        self._observation = ExecutionObservationV1(
            self._state.execution_id, ExecutionStatusV1.RUNNING
        )
        try:
            outcome = await self._work.run(self._control)
            if type(outcome) is not ExecutionOutcomeV1:
                raise TypeError("Product did not return an explicit outcome")
            self._candidate = outcome
        except asyncio.CancelledError:
            self._candidate = ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
        except Exception as error:
            self._candidate = ExecutionOutcomeV1(
                ExecutionStatusV1.FAILED,
                error_code="execution_failed",
                legacy_result=AppFailureV1(
                    error.code
                    if isinstance(error, AppServiceError)
                    else AppErrorCodeV1.SESSION_UNAVAILABLE
                ),
            )
        finally:
            self._control._turn_interrupt = None
        return await self._settle()

    async def _settle(self) -> ExecutionOutcomeV1:
        assert self._work is not None
        try:
            await self._work.settle()
            self._commit()
            assert self._candidate is not None
            return self._candidate
        except (Exception, asyncio.CancelledError):
            self._debt = True
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE) from None

    def _commit(self) -> None:
        assert self._state is not None and self._candidate is not None
        if self._entered:
            cursor = self._source_cursor()
            _counter(cursor)
            self._observation = ExecutionObservationV1(
                self._state.execution_id, self._candidate.status, cursor
            )
        self._state = replace(
            self._state,
            status=self._candidate.status,
            revision=self._state.revision + 1,
            outcome=self._candidate,
        )
        self._debt = False

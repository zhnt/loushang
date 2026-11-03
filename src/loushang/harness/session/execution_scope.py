"""Retain one Session-bound execution and its ordered resource cleanup.

The integration supplies domain callbacks. This scope neither drives Work nor
interprets domain state; the existing caller remains the advancing task.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar

from loushang.harness.session.execution_admission import (
    SessionExecutionAdmission,
    SessionExecutionUnavailable,
)

T = TypeVar("T")
CloseStage = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class ExecutionScopePorts:
    begin_close: Callable[[], None]
    quiesce: CloseStage
    settle: CloseStage
    release: CloseStage
    finalize: CloseStage


class SessionExecutionScope:
    def __init__(self, admission: SessionExecutionAdmission, ports: ExecutionScopePorts,
                 *, close_parent: CloseStage | None = None) -> None:
        self.admission, self._ports, self._close_parent = admission, ports, close_parent
        self.closing = self.closed = False
        self._close_begun = False
        self._advance_task: asyncio.Task | None = None
        self._invoke_done: asyncio.Future[None] | None = None
        self._invoke_error: BaseException | None = None
        self._interruption_requested = False
        self._prepare_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._finalize_task: asyncio.Task | None = None
        self._stage = 0
        self._parent_closed = False
        self._parent_resources_released = False
        self._closing_parent = False
        self._retired: Callable[[], None] | None = None

    def bind_retirement(self, callback: Callable[[], None]) -> None:
        if self._retired is not None or self.closing:
            raise SessionExecutionUnavailable("execution scope retirement already bound")
        self._retired = callback

    async def invoke(self, operation: Callable[[], Awaitable[T]]) -> T:
        self.admission.require_current()
        if self.closing or self._advance_task is not None:
            raise SessionExecutionUnavailable("Session execution scope is closing or busy")
        self._advance_task = asyncio.current_task()
        self._invoke_done = asyncio.get_running_loop().create_future()
        self._invoke_error = None
        self._interruption_requested = False
        try:
            return await operation()
        except BaseException as error:
            if self._interruption_requested and not isinstance(error, asyncio.CancelledError):
                self._invoke_error = error
            raise
        finally:
            self._advance_task = None
            self._invoke_done.set_result(None)

    def begin_close(self) -> None:
        if self._advance_task is asyncio.current_task():
            raise SessionExecutionUnavailable("request execution scope close from its external owner")
        self.closing = True
        if not self._close_begun:
            self._ports.begin_close()
            self._close_begun = True

    async def prepare_release(self) -> None:
        """Called before releasing the borrowed Session's dependencies."""
        self.begin_close()
        if self._prepare_task is None or self._failed(self._prepare_task):
            self._prepare_task = self._owned_task(self._prepare_release(), "session-execution:release")
        await asyncio.shield(self._prepare_task)

    async def _prepare_release(self) -> None:
        # Join the invocation boundary, not the caller's whole task: its outer
        # finally may itself close this scope and await our retained cleanup.
        if self._stage == 0:
            task, done = self._advance_task, self._invoke_done
            if task is not None:
                self._interruption_requested = True
                task.cancel()
                assert done is not None
                await asyncio.shield(done)
            if self._invoke_error is not None:
                error, self._invoke_error = self._invoke_error, None
                # Report the interrupted invocation's failure once. A retry
                # must reach the original owners again; they retain unresolved
                # execution and cleanup state and remain the settlement authority.
                raise error
        stages = (self._ports.quiesce, self._ports.settle, self._ports.release)
        while self._stage < len(stages):
            await stages[self._stage]()
            self._stage += 1

    async def finalize(self) -> None:
        """Retire domain writers after the owning parent has closed, if any."""
        if self._close_parent is not None and not self._parent_resources_released:
            raise SessionExecutionUnavailable("owning Session must release before finalizing execution")
        await self.prepare_release()
        if self.closed:
            return
        if self._finalize_task is None or self._failed(self._finalize_task):
            self._finalize_task = self._owned_task(self._finalize(), "session-execution:finalize")
        await asyncio.shield(self._finalize_task)

    async def _finalize(self) -> None:
        await self._ports.finalize()
        self.closed = True
        if self._retired is not None:
            self._retired()

    async def parent_released(self) -> None:
        self._parent_resources_released = True
        if not self._closing_parent:
            await self.finalize()
            self._parent_closed = True

    async def close(self) -> None:
        await asyncio.shield(self.close_handle())

    def close_handle(self) -> asyncio.Task:
        self.begin_close()
        if self._close_task is None or self._failed(self._close_task):
            self._close_task = self._owned_task(self._close(), "session-execution:close")
        return self._close_task

    async def _close(self) -> None:
        await self.prepare_release()
        if self._close_parent is not None and not self._parent_closed:
            self._closing_parent = True
            try:
                await self._close_parent()
            finally:
                self._closing_parent = False
            self._parent_closed = True
            self._parent_resources_released = True
        await self.finalize()

    @staticmethod
    def _failed(task: asyncio.Task) -> bool:
        return task.done() and (task.cancelled() or task.exception() is not None)

    @staticmethod
    def _owned_task(operation: Coroutine[Any, Any, None], name: str) -> asyncio.Task:
        task = asyncio.create_task(operation, name=name)
        task.add_done_callback(SessionExecutionScope._observe)
        return task

    @staticmethod
    def _observe(task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()


class ExecutionObservations:
    """Join observer invocations without joining their callers' outer cleanup.

    Observations execute in the original caller Task. Closing interrupts them,
    waits for their own finally blocks, and retains any cleanup failure rather
    than releasing dependencies with an unknown reader state.
    """

    def __init__(self) -> None:
        self._pending: dict[asyncio.Task, asyncio.Future[BaseException | None]] = {}
        self._closing: tuple[asyncio.Future[BaseException | None], ...] | None = None
        self._error: BaseException | None = None

    async def invoke(self, operation: Callable[[], Awaitable[T]]) -> T:
        task = asyncio.current_task()
        if self._closing is not None or task is None or task in self._pending:
            raise SessionExecutionUnavailable("execution observation is closing or reentrant")
        done: asyncio.Future[BaseException | None] = asyncio.get_running_loop().create_future()
        self._pending[task] = done
        error: BaseException | None = None
        try:
            return await operation()
        except BaseException as failure:
            error = failure
            raise
        finally:
            self._pending.pop(task)
            done.set_result(error)

    async def quiesce(self) -> None:
        if asyncio.current_task() in self._pending:
            raise SessionExecutionUnavailable("close observations from their external owner")
        if self._closing is None:
            self._closing = tuple(self._pending.values())
            for task in tuple(self._pending):
                task.cancel()
        results = await asyncio.gather(*(asyncio.shield(done) for done in self._closing))
        if self._error is None:
            self._error = next((error for error in results if error is not None
                                and not isinstance(error, asyncio.CancelledError)), None)
        if self._error is not None:
            raise self._error

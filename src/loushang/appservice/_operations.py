"""Private retained execution owner for the optional G16 semantic scope.

The caller must validate semantic authority before submitting an operation.
This owner only reserves capacity and retains its lifetime independently of a
delivery waiter. It does not grant authority or replay a lost request.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar, cast

from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

_Result = TypeVar("_Result")


@dataclass(eq=False, slots=True)
class _Operation:
    control: bool
    key: str | None
    task: asyncio.Task[object] | None = None
    cancellation_sent: bool = False


class _OwnedAppOperations:
    """Application-owned work; only explicit application/member stop cancels it."""

    def __init__(
        self,
        *,
        max_ordinary: int = 32,
        max_control: int = 8,
        close_timeout: float = 10.0,
    ) -> None:
        for capacity in (max_ordinary, max_control):
            if type(capacity) is not int or not 1 <= capacity <= 1024:
                raise ValueError("invalid application operation capacity")
        if (
            type(close_timeout) not in (int, float)
            or not math.isfinite(close_timeout)
            or not 0 < close_timeout <= 60
        ):
            raise ValueError("invalid application operation close timeout")
        self._limits = {False: max_ordinary, True: max_control}
        self._counts = {False: 0, True: 0}
        self._entries: set[_Operation] = set()
        self._keys: set[str] = set()
        self._timeout = float(close_timeout)
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None

    @property
    def pending_counts(self) -> tuple[int, int]:
        return self._counts[False], self._counts[True]

    async def execute(
        self,
        operation: Callable[[], Awaitable[_Result]],
        *,
        control: bool = False,
        key: str | None = None,
    ) -> _Result:
        return await asyncio.shield(self.admit(operation, control=control, key=key))

    def admit(
        self,
        operation: Callable[[], Awaitable[_Result]],
        *,
        control: bool = False,
        key: str | None = None,
    ) -> asyncio.Task[_Result]:
        """Reserve and publish without yielding between authority and ownership."""
        if type(control) is not bool or (
            key is not None
            and (type(key) is not str or not key or len(key) > 128)
        ):
            raise ValueError("invalid application operation identity")
        if self._closing:
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)
        if self._counts[control] >= self._limits[control] or (
            key is not None and key in self._keys
        ):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

        entry = _Operation(control, key)
        self._entries.add(entry)
        self._counts[control] += 1
        if key is not None:
            self._keys.add(key)
        published = asyncio.get_running_loop().create_future()

        async def invoke() -> _Result:
            try:
                # Even an eager task factory cannot run a Product effect before
                # the exact task is installed in the retained ownership record.
                await published
                return await operation()
            finally:
                self._release(entry)

        invocation = invoke()
        try:
            task = asyncio.create_task(invocation)
        except BaseException:
            invocation.close()
            self._release(entry)
            raise
        entry.task = cast(asyncio.Task[object], task)
        task.add_done_callback(lambda result: self._finished(entry, result))
        published.set_result(None)
        return task

    async def close(self) -> None:
        self._closing = True
        task = self._close_task
        if task is None or (
            task.done() and (task.cancelled() or task.exception() is not None)
        ):
            closing = self._close_once()
            try:
                task = asyncio.create_task(closing)
            except BaseException:
                closing.close()
                raise
            task.add_done_callback(_observe)
            self._close_task = task
        await asyncio.shield(task)

    def cancel_ordinary(self) -> None:
        """Application-stop phase; leave settlement admission available."""
        for entry in tuple(self._entries):
            task = entry.task
            if (
                not entry.control and task is not None and not task.done()
                and not entry.cancellation_sent
            ):
                entry.cancellation_sent = True
                task.cancel()

    def cancel_sessions(self, session_ids: frozenset[str]) -> None:
        for entry in tuple(self._entries):
            task = entry.task
            if (
                entry.key in session_ids and task is not None and not task.done()
                and not entry.cancellation_sent
            ):
                entry.cancellation_sent = True
                task.cancel()

    async def join_sessions(self, session_ids: frozenset[str]) -> None:
        tasks = {
            entry.task for entry in self._entries
            if entry.key in session_ids and entry.task is not None
        }
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=self._timeout)
            if pending:
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)

    async def _close_once(self) -> None:
        tasks: set[asyncio.Task[object]] = set()
        for entry in tuple(self._entries):
            task = entry.task
            if task is None:
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
            tasks.add(task)
            if not task.done() and not entry.cancellation_sent:
                entry.cancellation_sent = True
                task.cancel()
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=self._timeout)
            if pending:
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)

    def _release(self, entry: _Operation) -> None:
        if entry not in self._entries:
            return
        self._entries.remove(entry)
        self._counts[entry.control] -= 1
        if entry.key is not None:
            self._keys.discard(entry.key)

    def _finished(self, entry: _Operation, task: asyncio.Task[object]) -> None:
        # A task cancelled before its first step never enters invoke's finally.
        self._release(entry)
        _observe(task)


def _observe(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()

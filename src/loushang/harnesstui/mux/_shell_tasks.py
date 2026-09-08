"""Bounded client waiter ownership, never ownership of remote accepted work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import TypeVar

from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

T = TypeVar("T")


def owned_task(action: Callable[[], Coroutine[object, object, T]]) -> asyncio.Task[T]:
    published = asyncio.get_running_loop().create_future()

    async def invoke() -> T:
        await published
        return await action()

    work = invoke()
    try:
        task = asyncio.create_task(work)
    except BaseException:
        work.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    published.set_result(None)
    return task


async def join(
    task: asyncio.Task[object], deadline: float, *, ignore_error: bool = False
) -> None:
    if not task.done():
        await asyncio.wait(
            {task}, timeout=max(0, deadline - asyncio.get_running_loop().time())
        )
    if not task.done():
        raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
    if not ignore_error:
        task.result()


class ShellActions:
    """64 local action slots, including eight reserved for controls."""

    def __init__(self, failed: Callable[[BaseException], None]) -> None:
        self._tasks: dict[asyncio.Task[object], bool] = {}
        self._failed = failed
        self._closing = False

    @property
    def pending(self) -> int:
        return len(self._tasks)

    def submit(
        self,
        action: Callable[[], Coroutine[object, object, object]],
        *,
        control: bool = False,
    ) -> None:
        ordinary = sum(not kind for kind in self._tasks.values())
        if self._closing or len(self._tasks) >= 64 or (not control and ordinary >= 56):
            raise ValueError("action_queue_full")
        task = owned_task(action)
        self._tasks[task] = control
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[object]) -> None:
        self._tasks.pop(task, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            self._failed(error)

    async def close(self, deadline: float) -> None:
        self._closing = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            await join(task, deadline, ignore_error=True)

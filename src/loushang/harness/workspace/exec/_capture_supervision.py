"""Observe borrowed execution tasks without cancelling or owning them."""

from __future__ import annotations

import asyncio
from typing import Literal, TypeVar

CaptureWakeReason = Literal["exit", "abort", "timeout"]
_Exit = TypeVar("_Exit")


async def wait_for_captured_process(
    *,
    exit_task: asyncio.Task[_Exit],
    stdin_task: asyncio.Task[None],
    readers: tuple[asyncio.Task[None], asyncio.Task[None]],
    abort_task: asyncio.Task[None] | None,
    timeout: float | None,
) -> CaptureWakeReason:
    """Surface IO failure even while stdin or process exit is still pending.

    The caller retains all tasks and must terminate/join its original process
    on failure or cancellation. A normal reader EOF is not process completion.
    No task is shielded into a new owner or cancelled by this observer.
    """
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    io_tasks = {stdin_task, *readers}
    while True:
        # Failure wins over a simultaneous successful exit: output may be lost.
        for task in tuple(io_tasks):
            if task.done():
                task.result()
                io_tasks.remove(task)
        if exit_task.done():
            exit_task.result()
            return "exit"
        if abort_task is not None and abort_task.done():
            abort_task.result()
            return "abort"
        remaining = None if deadline is None else deadline - loop.time()
        if remaining is not None and remaining <= 0:
            return "timeout"
        waiters = {exit_task, *io_tasks}
        if abort_task is not None:
            waiters.add(abort_task)
        await asyncio.wait(
            waiters, timeout=remaining, return_when=asyncio.FIRST_COMPLETED,
        )

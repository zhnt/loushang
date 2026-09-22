"""Private native IO settlement shared by durable stores and their owners."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar, cast

ResultT = TypeVar("ResultT")


async def settled_io(operation: Callable[..., ResultT], *args: Any, **kwargs: Any) -> ResultT:
    """Join one native operation before returning, including on cancellation.

    The independent receipt outlives cancellation of the private offload task.
    A submitted operation without a receipt remains pending, never resubmitted.
    The owning application must keep its event loop alive through settlement.
    """
    loop = asyncio.get_running_loop()
    published: asyncio.Future[None] = loop.create_future()
    receipt: asyncio.Future[tuple[bool, object]] = loop.create_future()
    dispatched = False

    def native() -> None:
        try:
            outcome: tuple[bool, object] = (True, operation(*args, **kwargs))
        except BaseException as error:
            outcome = (False, error)
        loop.call_soon_threadsafe(receipt.set_result, outcome)

    async def run() -> None:
        nonlocal dispatched
        await published
        dispatched = True
        await asyncio.to_thread(native)

    work = run()
    try:
        task = loop.create_task(work)
    except BaseException:
        published.cancel()
        work.close()
        raise
    published.set_result(None)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancellation = error
        except BaseException:
            break  # Preserve the task error after native settlement, if dispatched.
    if not dispatched:
        task.result()  # Failed/cancelled before native submission: no native effect.
        raise RuntimeError("file IO task ended before dispatch")
    task_error = asyncio.CancelledError() if task.cancelled() else task.exception()
    while not receipt.done():
        try:
            await asyncio.shield(receipt)
        except asyncio.CancelledError as error:
            cancellation = error
    succeeded, result = receipt.result()
    if not succeeded:
        raise cast(BaseException, result)
    if task_error is not None:
        raise task_error
    if cancellation is not None:
        raise cancellation
    return cast(ResultT, result)

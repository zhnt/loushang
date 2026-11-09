"""Borrowed-task joins with three preserved, explicitly distinct contracts.

Lifecycle owners retain the task and any cleanup/retry debt. No submission,
timeout, registration, cancellation request or ownership transfer happens here.
"""

from __future__ import annotations

import asyncio
from typing import TypeVar, cast

T = TypeVar("T")


async def _join_cancellation_first(task: asyncio.Task[T]) -> T:
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = exc
        except BaseException as exc:
            if cancellation is not None:
                raise cancellation from exc
            raise
    if cancellation is not None:
        raise cancellation
    return cast(T, result)


async def _join_failure_first(task: asyncio.Task[T]) -> T:
    """Join an owned task before propagating cancellation of its caller.

    Exposed to Products as ``harness.runtime.await_owned_task``. The caller
    supplies an existing task and retains its resource and retry ownership.
    Successful settlement returns the task result, or raises the last caught
    caller cancellation. Task failures and task cancellation propagate through
    the original task result; this helper never retries or resubmits work.
    """
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = exc
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


async def _join_preserving_cancellation(task: asyncio.Task[T]) -> T:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if caller is None or caller.cancelling() == 0:
                break
            cancellation = error
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


__all__: list[str] = []

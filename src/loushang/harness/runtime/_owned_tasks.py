"""Cancellation-safe joins for tasks whose effects outlive their caller."""

from __future__ import annotations

import asyncio
from typing import TypeVar

T = TypeVar("T")


async def _await_cancellation_atomic(task: asyncio.Task[T]) -> T:
    """Join an owned task before propagating cancellation of its caller."""

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


__all__: list[str] = []

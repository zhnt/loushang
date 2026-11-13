"""Waiter lifetime over an existing authorized process handle."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from .types import ProcessHandle


async def wait_for_process_exit(
    handle: ProcessHandle,
    *,
    timeout_seconds: float,
    task_name: str,
    error_type: type[Exception],
    error_message: str,
) -> None:
    """Settle one borrowed handle waiter after graceful exit or termination."""
    waiter = asyncio.create_task(
        handle.wait(),
        name=task_name,
    )
    try:
        try:
            await asyncio.wait_for(
                asyncio.shield(waiter),
                timeout_seconds,
            )
        except TimeoutError:
            await handle.terminate()
            await waiter
    except BaseException as exc:
        if not waiter.done():
            waiter.cancel()
            with suppress(asyncio.CancelledError):
                await waiter
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise error_type(
            f"{error_message}: {exc}"
        ) from exc


"""Retain the real debt-test controller until its own child cleanup completes."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress


async def _wait(waiter):
    await asyncio.wait_for(asyncio.shield(waiter), timeout=15)


async def release_controller(process, release):
    # A historical child.pid is a diagnostic, never permission to send SIGKILL.
    # Only the actual Product controller may terminate/reap its Hosted child.
    previous = signal.signal(signal.SIGINT, lambda *_: None)
    waiter = asyncio.create_task(process.wait())
    try:
        while True:
            try:
                release.touch()
                await _wait(waiter)
                return
            except (OSError, TimeoutError, asyncio.CancelledError):
                # Cancellation of the test must not cancel the retained wait
                # task or discard the controller because an observation timed out.
                with suppress(OSError, ValueError):
                    print("debt test reclamation pending; controller retained", flush=True)
                with suppress(asyncio.CancelledError):
                    await asyncio.sleep(0.01)
    finally:
        signal.signal(signal.SIGINT, previous)

"""Private loop-lifetime settlement policy; application stages stay child-owned.

The process composition must keep the event loop alive while run is pending.
Shielding a public waiter cannot prevent its caller from closing the whole loop.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ._files import ManagedStorageError
from .child import ManagedChildApplicationV1, _spawn

if TYPE_CHECKING:
    from .bootstrap import ManagedChildBootstrapV1


class _ChildLifetime:
    def __init__(self, child: ManagedChildApplicationV1, dependencies: ManagedChildBootstrapV1) -> None:
        self._child, self._dependencies = child, dependencies
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[int] | None = None
        self._close_task: asyncio.Task[bool] | None = None
        self._close_unknown = False
        self._status = 0

    @property
    def cleanup_pending(self) -> bool:
        return self._close_unknown or self._close_task is not None

    @property
    def close_unknown(self) -> bool:
        return self._close_unknown

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise ManagedStorageError("conflict")
        self._loop = loop
        delay = 1
        while self._task is None:
            try:
                # Publication gate guarantees task-factory failure starts no
                # application work. Keep this owner and retry only scheduling.
                self._task = _spawn(self._drive())
            except Exception:
                self._status = 1
                await _pause(delay)
                delay = min(30, delay * 2)
        return await asyncio.shield(self._task)

    async def _drive(self) -> int:
        try:
            await self._child.run()
        except BaseException:
            self._status = 1
        delay = 1
        while self._child.cleanup_pending:
            await _pause(delay)
            try:
                # This is a retry grant, not authority to replace any in-flight
                # phase or extend its original budget. The child decides that.
                await self._child.close(retry_timeout=30)
            except BaseException:
                self._status = 1
            delay = min(30, delay * 2)

        delay = 1
        while self._dependencies._application_cleanup_pending() or self._close_unknown:
            if self._close_task is None and not self._close_unknown:
                try:
                    self._close_task = _spawn(asyncio.to_thread(self._close_dependencies))
                except Exception:
                    self._status = 1  # Publication failed before offload began.
            task = self._close_task
            if task is not None and not self._close_unknown:
                try:
                    succeeded = await asyncio.shield(task)
                except BaseException:
                    # Offload cancellation/failure is not a native completion
                    # receipt. Retain that exact task; never enqueue a replacement.
                    self._close_unknown = True
                    self._status = 1
                else:
                    self._close_task = None
                    if not succeeded:
                        self._status = 1
            if not self._dependencies._application_cleanup_pending() and not self._close_unknown:
                break
            await _pause(delay)
            delay = min(30, delay * 2)
        return self._status

    def _close_dependencies(self) -> bool:
        # An ordinary resource-close failure is returned only after the native
        # callable has finished. Its owner retains exact resources/unknown debt.
        try:
            self._dependencies.close()
        except BaseException:
            return False
        return True


async def _pause(delay: float) -> None:
    await asyncio.sleep(delay)

"""Process-lifetime inherited stdio adapter, with no default-executor reads.

The foreground composition lends its standard descriptors until process exit.
Closing fences IO and wakes async waiters; an OS read/write already in progress
may remain parked in one of the two daemon workers until the peer or process
exits. This adapter is single-use per process, not a reusable pipe pool.
"""

from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
from contextlib import suppress
from dataclasses import dataclass

from .framing import AppConnectionClosedError

_claim_lock = threading.Lock()
_claimed = False


@dataclass(frozen=True, slots=True)
class _Job:
    argument: int | bytes
    future: asyncio.Future[bytes]


class _Direction:
    def __init__(self, descriptor: int, *, reading: bool) -> None:
        self._descriptor = descriptor
        self._reading = reading
        self._loop = asyncio.get_running_loop()
        self._jobs: queue.Queue[_Job | None] = queue.Queue(maxsize=1)
        self._pending: asyncio.Future[bytes] | None = None
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    async def submit(self, argument: int | bytes) -> bytes:
        if self._closed or self._pending is not None:
            raise AppConnectionClosedError()
        future: asyncio.Future[bytes] = self._loop.create_future()
        future.add_done_callback(_observe_future)
        self._pending = future
        self._jobs.put_nowait(_Job(argument, future))
        try:
            return await future
        except asyncio.CancelledError:
            # A cancelled OS operation cannot safely be followed by another one.
            self.close()
            raise
        finally:
            self._pending = None

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                if self._reading:
                    assert type(job.argument) is int
                    result = os.read(self._descriptor, job.argument)
                else:
                    assert type(job.argument) is bytes
                    view = memoryview(job.argument)
                    while view:
                        written = os.write(self._descriptor, view)
                        if written <= 0:
                            raise OSError()
                        view = view[written:]
                    result = b""
                failed = False
            except (OSError, ValueError):
                result, failed = b"", True
            with suppress(RuntimeError):
                self._loop.call_soon_threadsafe(
                    self._complete, job.future, result, failed
                )

    @staticmethod
    def _complete(future: asyncio.Future[bytes], result: bytes, failed: bool) -> None:
        if future.done():
            return
        if failed:
            future.set_exception(AppConnectionClosedError())
        else:
            future.set_result(result)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._pending is not None and not self._pending.done():
            self._pending.set_exception(AppConnectionClosedError())
        # Drop a not-yet-started job, then leave an exit marker for this worker.
        with suppress(queue.Empty):
            self._jobs.get_nowait()
        self._jobs.put_nowait(None)


class InheritedStdioTransportV1:
    """Explicit exclusive process-lifetime claim of already inherited stdio."""

    def __init__(self, *, input_fd: int, output_fd: int) -> None:
        global _claimed
        if type(input_fd) is not int or type(output_fd) is not int:
            raise ValueError("invalid inherited stdio descriptors")
        if input_fd < 0 or output_fd < 0 or input_fd == output_fd:
            raise ValueError("invalid inherited stdio descriptors")
        if os.isatty(input_fd) or os.isatty(output_fd):
            raise ValueError("foreground stdio requires redirected byte streams")
        asyncio.get_running_loop()
        with _claim_lock:
            if _claimed:
                raise RuntimeError("inherited stdio already claimed in this process")
            _claimed = True
        if sys.platform == "win32":
            import msvcrt

            msvcrt.setmode(input_fd, os.O_BINARY)
            msvcrt.setmode(output_fd, os.O_BINARY)
        self._read = _Direction(input_fd, reading=True)
        try:
            self._write = _Direction(output_fd, reading=False)
        except BaseException:
            self._read.close()
            raise

    async def read(self, size: int) -> bytes:
        return await self._read.submit(size)

    async def write(self, data: bytes) -> None:
        await self._write.submit(data)

    async def close(self) -> None:
        self._read.close()
        self._write.close()


__all__ = ["InheritedStdioTransportV1"]


def _observe_future(future: asyncio.Future[bytes]) -> None:
    if not future.cancelled():
        future.exception()

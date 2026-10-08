"""Private Linux process shell; no Product stages or native termination policy."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from time import sleep
from typing import TYPE_CHECKING, Any

from .child import ManagedChildApplicationV1, _spawn

if TYPE_CHECKING:
    from .bootstrap import ManagedChildBootstrapV1


class _ChildProcess:
    def __init__(self, bootstrap: ManagedChildBootstrapV1, child: ManagedChildApplicationV1) -> None:
        self._bootstrap, self._child = bootstrap, child
        self._runner: asyncio.Runner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._serve_task: asyncio.Task[int] | None = None
        self._waiter: asyncio.Task[int] | None = None
        self._signal_waiter: asyncio.Task[bool] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._wakeup = asyncio.Event()
        self._protection_unknown = False
        self._stop_requested = self._failed = self._ending = False
        self._unknown = self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    @property
    def unknown(self) -> bool:
        return self._unknown

    def accepts_loop(self, loop: asyncio.AbstractEventLoop) -> bool:
        return self._loop is loop and not self._ending

    def _new_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()
        self._loop = loop  # Retain before Runner performs its remaining setup.
        return loop

    def run(self) -> int:
        # Dedicated process policy, not borrowed handlers. It stays installed
        # through final diagnostics and OS exit, including with other threads.
        self._protect_maintenance()
        if self._protection_unknown:
            self._failed = self._stop_requested = True
        try:
            self._runner = asyncio.Runner(loop_factory=self._new_loop)
            loop = self._runner.get_loop()
        except BaseException:
            # No second Runner or native loop creation after uncertain setup.
            self._unknown = self._ending = True
            self._protect_maintenance()
            _park()
            raise AssertionError("unreachable")

        while True:
            if self._serve_task is None:
                work = self._serve()
                try:
                    self._serve_task = loop.create_task(work)
                except BaseException:
                    work.close()
                    self._failed = self._stop_requested = True
                    sleep(1)
                    continue
            try:
                # Unlike Runner.run, this never installs the default two-INT
                # cancellation/escalation handler over a partial installation.
                status = loop.run_until_complete(self._serve_task)
                break
            except asyncio.CancelledError:
                self._serve_task = None  # Join the same retained application driver.
            except BaseException:
                self._failed = self._stop_requested = True
                if self._serve_task.done():
                    self._serve_task = None
                sleep(1)

        self._ending = True  # Signal callbacks must not wake a closing/closed loop.
        try:
            self._runner.close()
        except BaseException:
            self._unknown = True  # Partial close is not retryable native authority.
        self._unknown = self._unknown or self._protection_unknown
        if self._unknown:
            self._protect_maintenance()
        if self._unknown:
            _park()
        self._settled = True
        return int(bool(status or self._failed))

    def _signal(self, signum: int, frame: object) -> None:
        self._stop_requested = True
        loop = self._loop
        if not self._ending and loop is not None and not loop.is_closed():
            # The sticky flag survives the closing-loop window.
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(self._wakeup.set)

    def _request_stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = _spawn(self._child.close(retry_timeout=30))

    async def _serve(self) -> int:
        if self._stop_requested:
            self._request_stop()
        if (self._waiter is None or self._waiter.cancelled()
                or self._waiter.done() and self._waiter.exception() is not None):
            self._waiter = _spawn(self._bootstrap.run())
        if self._signal_waiter is None or self._signal_waiter.cancelled():
            self._signal_waiter = _spawn(self._wakeup.wait())
        while not self._waiter.done():
            if self._signal_waiter.done() and not self._stop_requested:
                self._failed = self._stop_requested = True
            if self._stop_requested:
                self._request_stop()
            pending: set[asyncio.Task[Any]] = {self._waiter}
            if not self._stop_requested:
                pending.add(self._signal_waiter)
            if self._stop_task is not None and not self._stop_task.done():
                pending.add(self._stop_task)
            await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        status = await asyncio.shield(self._waiter)
        if self._stop_task is not None:
            try:
                await asyncio.shield(self._stop_task)
            except asyncio.CancelledError:
                if not self._stop_task.cancelled():
                    raise  # Rejoin this exact still-running (or successful) stop waiter.
                self._failed = True
            except BaseException:
                self._failed = True
        # Only this pure event waiter is cancelled, never an application/close job.
        self._signal_waiter.cancel()
        await asyncio.gather(self._signal_waiter, return_exceptions=True)
        return status

    def _protect_maintenance(self) -> None:
        for kind in _SIGNALS:
            try:
                signal.signal(
                    kind,
                    signal.SIG_IGN if kind == _SIGHUP else self._signal,
                )
            except BaseException:
                # No unconditional residency guarantee if the OS refuses the
                # protective disposition itself. Still never return a clean code.
                self._protection_unknown = True


_SIGHUP = getattr(signal, "SIGHUP", None)
_SIGNALS = tuple(
    kind
    for kind in (signal.SIGINT, signal.SIGTERM, _SIGHUP)
    if kind is not None
)


def _park() -> None:
    """No implicit exit or native retry after an uncertain process-shell close."""
    while True:
        with suppress(BaseException):
            sleep(30)

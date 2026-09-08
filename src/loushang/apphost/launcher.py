"""Optional foreground client/process owner; no Product or UI composition."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import TypeVar

from loushang.appserver.client import AppClientV1, SessionDiscoveryClientV1
from loushang.appserver.framing import (
    AppConnectionClosedError,
    AppFramedStreamV1,
    require_timeout,
)
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.remote_client import RemoteAppClientV1
from loushang.hosting.contracts import (
    LaunchPreparationPort,
    ProcessExit,
    ProcessHostingPort,
    ProcessLaunchRequest,
    ProcessLease,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class HostedLaunchDiagnosticsV1:
    """Pathless facts; raw stderr, argv and environment never cross this view."""

    exit_code: int | None
    forced_exit: bool
    stderr_bytes: int
    stderr_truncated: bool


def _failed(task: asyncio.Task[object]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _owned(operation: Callable[[], Coroutine[object, object, T]]) -> asyncio.Task[T]:
    published = asyncio.get_running_loop().create_future()

    async def invoke() -> T:
        await published
        return await operation()

    coroutine = invoke()
    try:
        task = asyncio.create_task(coroutine)
    except BaseException:
        coroutine.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    published.set_result(None)
    return task


async def _join(
    task: asyncio.Task[T], deadline: float, *, ignore_error: bool = False
) -> T | None:
    if not task.done():
        await asyncio.wait(
            {task}, timeout=max(0, deadline - asyncio.get_running_loop().time())
        )
    if not task.done():
        raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
    if ignore_error and _failed(task):
        return None
    if task.cancelled():
        raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
    try:
        return task.result()
    except Exception:
        # Cleanup implementations may include paths or launch material in their
        # exceptions. Keep the public settlement failure stable and pathless.
        raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE) from None


class _ProcessByteTransport:
    """One framed writer over bounded Hosting IO; close requests only EOF."""

    def __init__(self, lease: ProcessLease) -> None:
        self._lease = lease
        self._writer = asyncio.Lock()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None

    async def read(self, size: int) -> bytes:
        return await self._lease.read_stdout(min(size, 64 * 1024))

    async def write(self, data: bytes) -> None:
        async with self._writer:
            if self._closing:
                raise AppConnectionClosedError()
            for offset in range(0, len(data), 1024 * 1024):
                await self._lease.write_stdin(data[offset : offset + 1024 * 1024])

    async def close(self) -> None:
        self._closing = True
        if self._close_task is None or _failed(self._close_task):
            self._close_task = _owned(self._eof)
        await asyncio.shield(self._close_task)

    async def _eof(self) -> None:
        async with self._writer:
            await self._lease.close_stdin()


class HostedForegroundClientV1:
    """Adopt a dedicated host before spawn, never a shared host or UI object.

    Product supplies complete launch material and compatible Hosting IO bounds
    (read >=64 KiB, write >=1 MiB, captured bounded stderr). Preparation service
    is borrowed; Hosting owns each preparation lease. No ambient discovery runs.
    """

    def __init__(
        self,
        request: ProcessLaunchRequest,
        *,
        host: ProcessHostingPort,
        preparation: LaunchPreparationPort,
        profile: AppConnectionProfileV1 = AppConnectionProfileV1.STDIO_DISCOVERY,
        startup_timeout: float = 30.0,
        close_timeout: float = 20.0,
        graceful_timeout: float = 10.0,
    ) -> None:
        for timeout in (startup_timeout, close_timeout, graceful_timeout):
            require_timeout(timeout)
        if (
            startup_timeout > 30
            or close_timeout > 20
            or graceful_timeout > min(10, close_timeout)
        ):
            raise ValueError("invalid foreground budgets")
        if (
            type(request) is not ProcessLaunchRequest
            or request.streams.stdin is not ProcessStdinMode.PIPE
            or request.streams.stdout is not ProcessStdoutMode.PIPE
            or request.streams.stderr is not ProcessStderrMode.CAPTURE_TAIL
            or type(profile) is not AppConnectionProfileV1
            or profile
            not in {
                AppConnectionProfileV1.STDIO,
                AppConnectionProfileV1.STDIO_DISCOVERY,
            }
        ):
            raise ValueError("invalid foreground launch contract")
        self._request, self._host, self._preparation = request, host, preparation
        self._profile = profile
        self._startup_timeout, self._close_timeout, self._graceful_timeout = (
            startup_timeout,
            close_timeout,
            graceful_timeout,
        )
        self._lease: ProcessLease | None = None
        self._transport: _ProcessByteTransport | None = None
        self._client: RemoteAppClientV1 | None = None
        self._startup: asyncio.Task[None] | None = None
        self._exit: asyncio.Task[ProcessExit] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._force_task: asyncio.Task[None] | None = None
        self._phases: dict[str, asyncio.Task[None]] = {}
        self._phase_attempts: dict[str, int] = {}
        self._attempt = 0
        self._detach: Callable[[], Awaitable[None]] | None = None
        self._deadline: float | None = None
        self._cutoff: float | None = None
        self._closing = self._ready = self._settled = self._forced = False

    @property
    def client(self) -> AppClientV1:
        if not self._ready or self._closing or self._client is None:
            raise AppConnectionClosedError()
        return self._client

    @property
    def discovery_client(self) -> SessionDiscoveryClientV1 | None:
        return (
            self._client.discovery_client
            if self._ready and not self._closing and self._client
            else None
        )

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    @property
    def forced_exit(self) -> bool:
        return self._forced

    @property
    def process_exit(self) -> ProcessExit | None:
        return (
            self._exit.result()
            if self._exit is not None and self._exit.done() and not _failed(self._exit)
            else None
        )

    @property
    def diagnostics(self) -> HostedLaunchDiagnosticsV1:
        tail = self._lease.stderr_tail() if self._lease is not None else None
        size = len(tail.content) if tail is not None else 0
        exit_fact = self.process_exit
        return HostedLaunchDiagnosticsV1(
            exit_fact.return_code if exit_fact else None,
            self._forced,
            min(size, 64 * 1024),
            bool(tail and tail.truncated) or size > 64 * 1024,
        )

    async def start(self) -> None:
        if self._startup is not None or self._closing:
            raise AppConnectionClosedError()
        self._startup = _owned(self._open)
        try:
            done, _ = await asyncio.wait({self._startup}, timeout=self._startup_timeout)
            if not done:
                raise TimeoutError("hosted_startup_timeout")
            await asyncio.shield(self._startup)
        except BaseException:
            await self.close()
            raise

    async def _open(self) -> None:
        # Always retain a late resource before evaluating the close fence.
        self._lease = await self._host.start(self._request, self._preparation)
        self._transport = _ProcessByteTransport(self._lease)
        self._exit = _owned(self._lease.wait)
        if self._closing:
            raise AppConnectionClosedError()
        self._client = RemoteAppClientV1(
            AppFramedStreamV1(self._transport),
            profile=self._profile,
        )
        await self._client.start()
        if self._closing:
            raise AppConnectionClosedError()
        self._ready = True

    def _phase(
        self,
        name: str,
        action: Callable[[], Coroutine[object, object, None]],
        *,
        retry: bool = False,
        mandatory: bool = False,
    ) -> asyncio.Task[None]:
        task = self._phases.get(name)
        if task is None or (
            retry and _failed(task) and self._phase_attempts[name] != self._attempt
        ):
            if not mandatory and (
                self._deadline is None
                or asyncio.get_running_loop().time() >= self._deadline
            ):
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
            task = _owned(action)
            self._phases[name] = task
            self._phase_attempts[name] = self._attempt
        return task

    async def close(
        self,
        *,
        detach: Callable[[], Awaitable[None]] | None = None,
        retry_timeout: float | None = None,
    ) -> None:
        if detach is not None and not callable(detach):
            raise TypeError("invalid detach binding")
        if retry_timeout is not None:
            require_timeout(retry_timeout)
            if retry_timeout > 20:
                raise ValueError("invalid foreground retry budget")
        if self._closing and detach is not None and detach != self._detach:
            raise ValueError("foreground detach binding is frozen")
        if self._settled:
            return
        now = asyncio.get_running_loop().time()
        if not self._closing:
            self._closing, self._ready, self._detach = True, False, detach
            self._deadline = now + self._close_timeout
            self._cutoff = now + self._graceful_timeout
            if self._startup is not None and not self._startup.done():
                self._startup.cancel()
            if self._lease is None:
                self._phase("host", self._host.close)
            # Publish the independent cutoff before invoking optional UI cleanup.
            self._force_task = _owned(self._force)
        elif retry_timeout is not None:
            if self._close_task is not None and not self._close_task.done():
                raise ValueError("foreground close still running")
            self._deadline = now + retry_timeout
            self._attempt += 1
            if (
                self._force_task is not None
                and _failed(self._force_task)
                and self._lease is not None
            ):
                self._force_task = _owned(lambda: self._reclaim(retry=True))
        if self._close_task is None or _failed(self._close_task):
            assert self._deadline is not None
            deadline = self._deadline
            self._close_task = _owned(
                lambda: self._settle(deadline, retry_timeout is not None)
            )
        await asyncio.shield(self._close_task)

    async def _force(self) -> None:
        assert self._cutoff is not None
        if self._lease is None and self._startup is not None:
            try:
                await asyncio.shield(self._startup)
            except BaseException:
                current = asyncio.current_task()
                if not self._startup.done() or (
                    current is not None and current.cancelling()
                ):
                    raise
        if self._lease is None:
            return
        assert self._exit is not None
        if not self._exit.done():
            await asyncio.wait(
                {self._exit},
                timeout=max(0, self._cutoff - asyncio.get_running_loop().time()),
            )
        if not self._exit.done() or _failed(self._exit):
            if self._exit.done():
                await asyncio.sleep(
                    max(0, self._cutoff - asyncio.get_running_loop().time())
                )
            await self._reclaim()

    async def _reclaim(self, *, retry: bool = False) -> None:
        assert self._lease is not None
        try:
            await asyncio.shield(
                self._phase("terminate", self._terminate, retry=retry, mandatory=True)
            )
        except Exception:
            # Hosting.close owns fallback handle/tree reclamation even when
            # terminate or the exit observation failed. Do not gate it on IO.
            self._forced = True
        await asyncio.shield(
            self._phase(
                "lease",
                self._lease.close,
                retry=retry,
                mandatory=True,
            )
        )

    async def _terminate(self) -> None:
        assert self._lease is not None
        self._forced = True
        await self._lease.terminate()

    async def _drain(self) -> None:
        assert self._lease is not None
        while await self._lease.read_stdout(64 * 1024):
            pass

    async def _settle(self, deadline: float, retry: bool) -> None:
        assert self._cutoff is not None and self._force_task is not None
        detach_task = None
        if self._detach is not None:

            async def detach_once() -> None:
                assert self._detach is not None
                await self._detach()

            detach_task = self._phase("detach", detach_once)
            if not detach_task.done():
                await asyncio.wait(
                    {detach_task},
                    timeout=max(
                        0,
                        min(deadline, self._cutoff) - asyncio.get_running_loop().time(),
                    ),
                )
            # Cutoff stops waiting, not observing. Cancelling an adopted UI
            # cleanup wrapper would erase proof of its eventual settlement.
        if self._transport is not None:
            self._phase("eof", self._transport.close, retry=retry)
        if self._lease is None:
            await _join(self._phase("host", self._host.close, retry=retry), deadline)
        if self._startup is not None:
            await _join(self._startup, deadline, ignore_error=True)
        # Hello IO is in startup, not RemoteAppClient's response reader. Both
        # must settle before stdout can transfer to the drain owner.
        if self._client is not None:
            await _join(
                self._phase("client", self._client.close, retry=retry), deadline
            )
        if self._transport is not None:
            await _join(
                self._phase("eof", self._transport.close, retry=retry), deadline
            )
        drain = (
            self._phase("drain", self._drain, retry=retry)
            if self._lease is not None
            else None
        )
        await _join(self._force_task, deadline, ignore_error=True)
        if self._lease is not None:
            await _join(self._phase("lease", self._lease.close, retry=retry), deadline)
            assert self._exit is not None
            if not self._exit.done():
                self._exit.cancel()  # Observation only; successful lease.close reclaimed the tree.
            await _join(self._exit, deadline, ignore_error=True)
        if drain is not None:
            # Closing the process handle can end a disposable raw drain with an
            # IO error. Actual waiter completion, not successful reads, releases it.
            await _join(drain, deadline, ignore_error=True)
        await _join(self._phase("host", self._host.close, retry=retry), deadline)
        if detach_task is not None:
            await _join(detach_task, deadline)
        self._settled = True


__all__ = ["HostedForegroundClientV1", "HostedLaunchDiagnosticsV1"]

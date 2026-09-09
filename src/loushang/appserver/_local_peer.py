"""One bounded local peer: authentication, borrowed semantics and retained close."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from typing import Protocol

from .client import AppClientV1, SessionDiscoveryClientV1
from .connection import AppServerConnectionV1
from .execution.client import ExecutionClientV1
from .framing import AppByteTransportV1, AppConnectionClosedError
from .local_auth import LocalAuthenticationV1, authenticate_local_server
from .protocol import AppErrorCodeV1, AppServiceError
from .protocol.connection_profile import AppConnectionProfileV1

LOCAL_APP_MODE = b"app"
LOCAL_STOP_MODE = b"stop"
LOCAL_STOP_ACK = b'{"result":"stop_requested"}'


class OwnedLocalClientScopeV1(AppClientV1, Protocol):
    """Factory result owned by one authenticated peer; not the application."""

    async def close(self) -> None: ...


class OwnedLocalDiscoveryScopeV1(OwnedLocalClientScopeV1, Protocol):
    """Optional factory result; the legacy scope surface stays unchanged."""

    @property
    def discovery_client(self) -> SessionDiscoveryClientV1 | None: ...


class OwnedLocalExecutionScopeV1(OwnedLocalDiscoveryScopeV1, Protocol):
    @property
    def execution_client(self) -> ExecutionClientV1 | None: ...


def _observe(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _failed(task: asyncio.Task[None]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _spawn(work: Coroutine[object, object, None]) -> asyncio.Task[None]:
    try:
        return asyncio.create_task(work)
    except BaseException:
        work.close()
        raise


class _LocalPeer:
    def __init__(
        self, transport: AppByteTransportV1, credentials: LocalAuthenticationV1, *,
        fence: Callable[[], None], abort: Callable[[], None],
        scope_factory: Callable[[], OwnedLocalClientScopeV1],
        admit: Callable[[_LocalPeer, bytes], bool], retire: Callable[[_LocalPeer], None],
        request_stop: Callable[[Awaitable[None]], None], auth_timeout: float,
        close_timeout: float,
        profile: AppConnectionProfileV1 = AppConnectionProfileV1.LOCAL,
        discovery_scope_factory: Callable[[], OwnedLocalDiscoveryScopeV1] | None = None,
        execution_scope_factory: Callable[[], OwnedLocalExecutionScopeV1] | None = None,
    ) -> None:
        self.mode: bytes | None = None
        self.task: asyncio.Task[None] | None = None
        self._transport, self._credentials = transport, credentials
        self._fence, self._abort, self._scope_factory = fence, abort, scope_factory
        self._admit, self._retire, self._request_stop = admit, retire, request_stop
        self._auth_timeout, self._timeout = auth_timeout, close_timeout
        self._profile, self._discovery_factory = profile, discovery_scope_factory
        self._execution_factory = execution_scope_factory
        self._published = asyncio.get_running_loop().create_future()
        self._scope: OwnedLocalClientScopeV1 | None = None
        self._connection: AppServerConnectionV1 | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._closed = False

    def start(self) -> None:
        work = self._serve()
        try:
            self.task = asyncio.create_task(work)
        except BaseException:
            work.close()
            self._abort()
            raise
        self.task.add_done_callback(self._completed)
        self._published.set_result(None)

    def _completed(self, task: asyncio.Task[None]) -> None:
        _observe(task)
        if task is self.task and self._close_task is None:
            self._closed = True
            self._abort()
            self._close_task = _spawn(self._close_once())
            self._close_task.add_done_callback(self._completed)
        if self.settled:
            self._retire(self)

    def abort_io(self) -> None:
        self._closed = True
        self._abort()

    @property
    def settled(self) -> bool:
        return (
            self.task is not None and self.task.done()
            and self._close_task is not None and self._close_task.done()
            and not _failed(self._close_task)
        )

    async def _serve(self) -> None:
        await self._published
        try:
            frames = await authenticate_local_server(
                self._transport, self._credentials, timeout=self._auth_timeout
            )
            async with asyncio.timeout(self._auth_timeout):
                mode = await frames.receive()
            if (self._closed or mode not in {LOCAL_APP_MODE, LOCAL_STOP_MODE}
                    or not self._admit(self, mode)):
                raise AppConnectionClosedError()
            if mode == LOCAL_APP_MODE:
                discovery = None
                execution = None
                if self._execution_factory is not None:
                    execution_scope = self._execution_factory()
                    self._scope = execution_scope
                    execution = execution_scope.execution_client
                    if execution is None:
                        raise AppConnectionClosedError()
                    if self._discovery_factory is not None:
                        discovery = execution_scope.discovery_client
                        if discovery is None:
                            raise AppConnectionClosedError()
                elif self._discovery_factory is None:
                    self._scope = self._scope_factory()
                else:
                    scope = self._discovery_factory()
                    self._scope = scope  # Ownership precedes the fallible borrow.
                    discovery = scope.discovery_client
                    if discovery is None:
                        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
                self._connection = AppServerConnectionV1(
                    self._scope, frames, profile=self._profile,
                    phase_timeout=self._timeout, discovery=discovery,
                    execution=execution,
                )
                await self._connection.serve()
            else:
                reply_finished: asyncio.Future[None] = asyncio.get_running_loop().create_future()
                try:
                    # Admission synchronously publishes the application's stop
                    # owner. It waits on this read-only barrier before teardown.
                    self._request_stop(asyncio.shield(reply_finished))
                    async with asyncio.timeout(self._timeout):
                        await frames.send(LOCAL_STOP_ACK)
                finally:
                    reply_finished.set_result(None)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Connection errors are local and never disclose credentials. Any
            # cleanup failure below keeps this peer in the listener's capacity.
            pass
        finally:
            with suppress(AppServiceError):
                await self.close()

    async def close(self) -> None:
        self._closed = True
        self._fence()
        task = self._close_task
        if task is None or _failed(task):
            task = self._close_task = _spawn(self._close_once())
            task.add_done_callback(self._completed)
        done, _ = await asyncio.wait({task}, timeout=self._timeout)
        if not done:
            self._abort()
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        failed = False
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                failed = True
        else:
            try:
                await self._transport.close()
            except Exception:
                failed = True
        if self._scope is not None:
            try:
                await self._scope.close()
            except Exception:
                failed = True
        if failed:
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)

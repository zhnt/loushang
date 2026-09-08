"""Explicit authenticated loopback deployment; no Product or application owner.

The caller publishes these owners before start and retains them through close.
Directories are borrowed; each server owns only its endpoint reservation. The
scope factory and stop admission callback belong to the ready application.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress
from enum import Enum

from ._local_peer import (
    LOCAL_APP_MODE,
    LOCAL_STOP_ACK,
    LOCAL_STOP_MODE,
    OwnedLocalClientScopeV1,
    OwnedLocalDiscoveryScopeV1,
    _failed,
    _LocalPeer,
    _observe,
    _spawn,
)
from .client import AppClientV1, SessionDiscoveryClientV1
from .framing import AppConnectionClosedError, AsyncioStreamTransportV1, require_timeout
from .local_auth import authenticate_local_client
from .local_record import (
    LocalConnectionDirectoryV1,
    LocalConnectionRecordV1,
    LocalEndpointReservationV1,
    LocalRecordScopeV1,
)
from .protocol import AppErrorCodeV1, AppServiceError
from .remote_client import RemoteAppClientV1

MAX_LOCAL_CONNECTIONS = 8
MAX_LOCAL_APP_CONNECTIONS = 7  # One authenticated slot is reserved for stop.
MAX_LOCAL_AUTHENTICATING = 8
_LOOPBACK = "127.0.0.1"
_READ_LIMIT = 64 * 1024


class LocalConnectionModeV1(str, Enum):
    APP = "app"
    STOP = "stop"


class _LocalTransport(AsyncioStreamTransportV1):
    async def close(self) -> None:
        # A native plain-TCP reset is not itself residual ownership. Still
        # require the admitted handle to be closed after connection_lost.
        self._writer.close()
        with suppress(ConnectionError, OSError):
            await self._writer.wait_closed()
        native = self._writer.get_extra_info("socket")
        if native is None or native.fileno() != -1:
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)


def _transport(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> _LocalTransport:
    writer.transport.set_write_buffer_limits(high=_READ_LIMIT, low=_READ_LIMIT // 4)
    return _LocalTransport(reader, writer)


async def _join_close(task: asyncio.Task[None], timeout: float) -> None:
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
    await asyncio.shield(task)


class LocalAppServerV1:
    """Bounded local admission; closing peers does not close their application."""

    def __init__(
        self, directory: LocalConnectionDirectoryV1, endpoint: str, *,
        application_id: str, product_id: str, scopes: tuple[LocalRecordScopeV1, ...],
        scope_factory: Callable[[], OwnedLocalClientScopeV1],
        request_stop: Callable[[Awaitable[None]], None],
        auth_timeout: float = 5.0, close_timeout: float = 10.0,
        discovery_scope_factory: Callable[[], OwnedLocalDiscoveryScopeV1] | None = None,
    ) -> None:
        require_timeout(auth_timeout)
        require_timeout(close_timeout)
        if auth_timeout > 5 or close_timeout > 30:
            raise ValueError("local deployment timeout exceeds profile bound")
        if discovery_scope_factory is not None and not callable(discovery_scope_factory):
            raise TypeError("invalid discovery scope factory")
        # Validate all record facts before obtaining a lock or opening IO.
        LocalConnectionRecordV1(endpoint=endpoint, application_id=application_id,
                                product_id=product_id, scopes=scopes, port=1,
                                instance="0" * 32, key=bytes(32))
        self._directory, self._endpoint = directory, endpoint
        self._application_id, self._product_id, self._scopes = application_id, product_id, scopes
        self._scope_factory, self._request_stop = scope_factory, request_stop
        self._discovery_factory = discovery_scope_factory
        self._auth_timeout, self._timeout = auth_timeout, close_timeout
        self._reservation: LocalEndpointReservationV1 | None = None
        self._record: LocalConnectionRecordV1 | None = None
        self._socket: socket.socket | None = None
        self._server: asyncio.Server | None = None
        self._peers: set[_LocalPeer] = set()
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._ready = False
        self._closed = False
        self._stop_requested = False

    @property
    def record(self) -> LocalConnectionRecordV1:
        if not self._ready or self._closed or self._record is None:
            raise AppConnectionClosedError()
        return self._record

    @property
    def connection_counts(self) -> tuple[int, int]:
        admitted = sum(peer.mode is not None for peer in self._peers)
        return len(self._peers) - admitted, admitted

    async def start(self) -> None:
        if self._closed or self._start_task is not None:
            raise AppConnectionClosedError()
        task = self._start_task = _spawn(self._start_once())
        task.add_done_callback(_observe)
        try:
            await _join_close(task, self._timeout)
            if self._closed or self._stop_requested or not self._ready:
                raise AppConnectionClosedError()
        except BaseException:
            await self.close()
            raise

    async def _start_once(self) -> None:
        self._reservation = self._directory.acquire(self._endpoint)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.set_inheritable(False)
        self._socket.setblocking(False)
        if os.name == "nt":
            self._socket.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE"), 1)
        self._socket.bind((_LOOPBACK, 0))
        port = self._socket.getsockname()[1]
        self._server = await asyncio.start_server(
            self._accepted, sock=self._socket, backlog=16, limit=_READ_LIMIT,
            start_serving=False,
        )
        self._socket = None  # asyncio.Server has adopted that exact socket.
        if self._closed:
            self._server.close()
            raise AppConnectionClosedError()
        self._record = self._reservation.publish(
            application_id=self._application_id, product_id=self._product_id,
            port=port, scopes=self._scopes,
            session_discovery=self._discovery_factory is not None,
        )
        self._ready = True
        await self._server.start_serving()
        if self._closed:
            self._server.close()
            raise AppConnectionClosedError()

    def _accepted(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if (not self._ready or self._closed or self._stop_requested
                or self.connection_counts[0] >= MAX_LOCAL_AUTHENTICATING):
            writer.transport.abort()
            return
        assert self._record is not None
        try:
            peer = _LocalPeer(
                _transport(reader, writer), self._record.authentication,
                fence=writer.close, abort=writer.transport.abort, scope_factory=self._scope_factory,
                admit=self._admit, retire=self._peers.discard, request_stop=self._admit_stop,
                auth_timeout=self._auth_timeout, close_timeout=self._timeout,
                profile=self._record.semantic_profile,
                discovery_scope_factory=self._discovery_factory,
            )
        except Exception:
            writer.transport.abort()
            return
        self._peers.add(peer)  # Capacity precedes even an eager task factory.
        try:
            peer.start()
        except BaseException:
            self._peers.discard(peer)
            writer.transport.abort()

    def _admit(self, peer: _LocalPeer, mode: bytes) -> bool:
        if self._closed or self._stop_requested or self.connection_counts[1] >= MAX_LOCAL_CONNECTIONS:
            return False
        if (mode == LOCAL_APP_MODE
                and sum(item.mode == LOCAL_APP_MODE for item in self._peers) >= MAX_LOCAL_APP_CONNECTIONS):
            return False
        peer.mode = mode
        return True

    def _admit_stop(self, reply_finished: Awaitable[None]) -> None:
        self._stop_requested = True
        self._request_stop(reply_finished)

    def fence(self) -> None:
        self._closed = True
        self._ready = False
        if self._server is not None:
            self._server.close()

    async def close(self) -> None:
        self.fence()
        task = self._close_task
        if task is None or _failed(task):
            task = self._close_task = _spawn(self._close_once())
            task.add_done_callback(_observe)
        try:
            await _join_close(task, self._timeout)
        except AppServiceError:
            for peer in tuple(self._peers):
                peer.abort_io()
            raise

    async def _close_once(self) -> None:
        if self._start_task is not None:
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._server is not None:
            self._server.close()
        peers = tuple(self._peers)
        await asyncio.gather(*(peer.close() for peer in peers), return_exceptions=True)
        await asyncio.gather(*(peer.task for peer in peers if peer.task is not None), return_exceptions=True)
        for peer in peers:
            if peer.settled:
                self._peers.discard(peer)
        if self._peers:
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
        if self._server is not None:
            await self._server.wait_closed()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._reservation is not None:
            self._reservation.close()
            self._reservation = None


class LocalAppClientConnectionV1:
    """One explicit record selection; never discovers, spawns or retries work."""

    def __init__(
        self, directory: LocalConnectionDirectoryV1, endpoint: str, *,
        mode: LocalConnectionModeV1 = LocalConnectionModeV1.APP, timeout: float = 10.0,
        expected_product_id: str | None = None,
    ) -> None:
        require_timeout(timeout)
        if timeout > 30 or type(mode) is not LocalConnectionModeV1:
            raise ValueError("invalid local client selection")
        if expected_product_id is not None and (
            type(expected_product_id) is not str or not 1 <= len(expected_product_id) <= 128
        ):
            raise ValueError("invalid expected local Product")
        self._directory, self._endpoint = directory, endpoint
        self._expected_product_id = expected_product_id
        self._mode, self._timeout = mode, timeout
        self._socket: socket.socket | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._transport: _LocalTransport | None = None
        self._client: RemoteAppClientV1 | None = None
        self._scopes: tuple[LocalRecordScopeV1, ...] = ()
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._closed = False
        self._ready = False
        self._stop_requested = False

    @property
    def client(self) -> AppClientV1:
        if not self._ready or self._closed or self._client is None:
            raise AppConnectionClosedError()
        return self._client

    @property
    def discovery_client(self) -> SessionDiscoveryClientV1 | None:
        if not self._ready or self._closed or self._client is None:
            return None
        return self._client.discovery_client

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @property
    def scopes(self) -> tuple[LocalRecordScopeV1, ...]:
        """Pathless scope facts from the exact mutually authenticated record."""
        if not self._ready or self._closed or self._mode is not LocalConnectionModeV1.APP:
            raise AppConnectionClosedError()
        return self._scopes

    async def start(self) -> None:
        if self._closed or self._start_task is not None:
            raise AppConnectionClosedError()
        task = self._start_task = _spawn(self._start_once())
        task.add_done_callback(_observe)
        try:
            await _join_close(task, self._timeout)
            if self._closed or not self._ready:
                raise AppConnectionClosedError()
        except BaseException:
            await self.close()
            raise

    async def _start_once(self) -> None:
        record = self._directory.read(self._endpoint)
        if self._expected_product_id is not None and record.product_id != self._expected_product_id:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        async with asyncio.timeout(self._timeout):
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.set_inheritable(False)
            self._socket.setblocking(False)
            await asyncio.get_running_loop().sock_connect(self._socket, (_LOOPBACK, record.port))
            if self._closed:
                raise AppConnectionClosedError()
            reader, self._writer = await asyncio.open_connection(sock=self._socket, limit=_READ_LIMIT)
            self._socket = None
            self._transport = _transport(reader, self._writer)
            if self._closed:
                self._writer.transport.abort()
                raise AppConnectionClosedError()
            frames = await authenticate_local_client(self._transport, record.authentication)
            await frames.send(LOCAL_APP_MODE if self._mode is LocalConnectionModeV1.APP else LOCAL_STOP_MODE)
            if self._mode is LocalConnectionModeV1.APP:
                self._client = RemoteAppClientV1(
                    frames, profile=record.semantic_profile, phase_timeout=self._timeout
                )
                await self._client.start()
                self._scopes = record.scopes
            else:
                if await frames.receive() != LOCAL_STOP_ACK:
                    raise AppConnectionClosedError()
                self._stop_requested = True
            self._ready = True

    async def close(self) -> None:
        self._closed = True
        if self._writer is not None:
            self._writer.close()
        task = self._close_task
        if task is None or _failed(task):
            task = self._close_task = _spawn(self._close_once())
            task.add_done_callback(_observe)
        try:
            await _join_close(task, self._timeout)
        except AppServiceError:
            if self._writer is not None:
                self._writer.transport.abort()
            raise

    async def _close_once(self) -> None:
        if self._start_task is not None:
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._client is not None:
            await self._client.close()
        elif self._transport is not None:
            await self._transport.close()
        elif self._writer is not None:
            self._writer.close()
            with suppress(ConnectionError, OSError):
                await self._writer.wait_closed()
        if self._socket is not None:
            self._socket.close()
            self._socket = None


__all__ = [
    "LocalAppServerV1", "LocalAppClientConnectionV1", "LocalConnectionModeV1",
    "OwnedLocalClientScopeV1", "MAX_LOCAL_CONNECTIONS", "MAX_LOCAL_APP_CONNECTIONS",
    "OwnedLocalDiscoveryScopeV1",
    "MAX_LOCAL_AUTHENTICATING",
]

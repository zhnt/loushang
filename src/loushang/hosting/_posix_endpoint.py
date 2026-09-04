"""Private POSIX socketpair endpoint backend."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Callable
from typing import cast

from ._endpoint_backend import (
    _EndpointTransport,
    _PlatformEndpointPair,
    _SingleUseProcessInheritance,
)
from .errors import HostingError, HostingFailureCategory


class _PosixEndpointTransport(_EndpointTransport):
    def __init__(self, endpoint: socket.socket) -> None:
        self._endpoint = endpoint
        self._close_lock = asyncio.Lock()
        self._closed = False
        self._operations: set[asyncio.Task[object]] = set()

    async def read(self, max_bytes: int) -> bytes:
        if self._closed:
            return b""
        task = asyncio.create_task(
            asyncio.get_running_loop().sock_recv(self._endpoint, max_bytes),
            name="hosting-posix-endpoint-read",
        )
        self._track(cast(asyncio.Task[object], task))
        try:
            return await task
        except asyncio.CancelledError:
            if self._closed:
                return b""
            raise
        except (BrokenPipeError, ConnectionResetError):
            return b""

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise BrokenPipeError("POSIX host endpoint is closed")
        task = asyncio.create_task(
            asyncio.get_running_loop().sock_sendall(self._endpoint, data),
            name="hosting-posix-endpoint-write",
        )
        self._track(cast(asyncio.Task[object], task))
        try:
            await task
        except asyncio.CancelledError as exc:
            if self._closed:
                raise BrokenPipeError("POSIX host endpoint is closed") from exc
            raise

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            operations = tuple(self._operations)
            for operation in operations:
                operation.cancel()
            if operations:
                await asyncio.gather(*operations, return_exceptions=True)
            self._endpoint.close()

    def _track(self, task: asyncio.Task[object]) -> None:
        self._operations.add(task)

        def settle(completed: asyncio.Task[object]) -> None:
            self._operations.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(settle)


class _PosixEndpointBackend:
    backend_id = "posix-socketpair-v1"

    def __init__(self) -> None:
        if os.name != "posix" or not callable(getattr(socket, "socketpair", None)):
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "POSIX socketpair endpoints are unavailable",
            )

    async def create_pair(
        self,
        *,
        on_create: Callable[[_PlatformEndpointPair], None],
    ) -> _PlatformEndpointPair:
        try:
            host_endpoint, child_endpoint = socket.socketpair(
                socket.AF_UNIX, socket.SOCK_STREAM
            )
        except OSError as exc:
            raise HostingError(
                HostingFailureCategory.ENDPOINT_UNAVAILABLE,
                "POSIX endpoint pair creation failed",
            ) from exc
        try:
            host_endpoint.setblocking(False)
            child_endpoint.setblocking(True)
            host_endpoint.set_inheritable(False)
            child_endpoint.set_inheritable(False)

            def close_child() -> None:
                child_endpoint.close()

            descriptor = child_endpoint.fileno()
            pair = _PlatformEndpointPair(
                transport=_PosixEndpointTransport(host_endpoint),
                inheritance=_SingleUseProcessInheritance(
                    backend_id="posix-process-group-v1",
                    values=(descriptor, descriptor),
                    close_values=close_child,
                ),
            )
        except BaseException as exc:
            host_endpoint.close()
            child_endpoint.close()
            if isinstance(exc, HostingError):
                raise
            raise HostingError(
                HostingFailureCategory.ENDPOINT_UNAVAILABLE,
                "POSIX endpoint pair configuration failed",
            ) from exc
        try:
            on_create(pair)
        except BaseException as primary:
            try:
                await pair.close()
            except BaseException as cleanup:
                primary.add_note(f"endpoint attachment cleanup also failed: {cleanup}")
                raise primary from cleanup
            raise
        return pair

    async def close_backend(self) -> None:
        return


__all__: list[str] = []

"""Bounded framing over explicitly owned, asynchronous byte ports."""

from __future__ import annotations

import asyncio
import math
from typing import Protocol

from .client import AppConnectionClosedError as AppConnectionClosedError
from .protocol import AppServiceError, InvalidAppMessageError
from .protocol.codec import MAX_MESSAGE_BYTES


class AppByteTransportV1(Protocol):
    """read returns at most size bytes; empty bytes means terminal EOF."""

    async def read(self, size: int) -> bytes: ...

    async def write(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class AppMessageStreamV1(Protocol):
    """One bounded, complete-message stream already admitted by its owner."""

    async def receive(self) -> bytes: ...

    async def send(self, payload: bytes) -> None: ...

    async def close(self) -> None: ...


class AppConnectionEOFError(AppConnectionClosedError):
    """Clean EOF between frames, distinct from an IO failure or truncation."""


def require_timeout(value: float) -> None:
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 < value <= 60
    ):
        raise ValueError("invalid connection timeout")


class _SizedFramedStream:
    """Shared private framing mechanics; public profiles fix their own bounds."""

    def __init__(
        self, transport: AppByteTransportV1, *, max_payload: int,
        io_timeout: float = 10.0,
    ) -> None:
        require_timeout(io_timeout)
        if type(max_payload) is not int or not 1 <= max_payload <= MAX_MESSAGE_BYTES + 40:
            raise ValueError("invalid frame payload limit")
        self._max_payload = max_payload
        self._transport = transport
        self._io_timeout = io_timeout
        self._writer = asyncio.Lock()
        self._closed = False

    async def receive(self) -> bytes:
        if self._closed:
            raise AppConnectionClosedError()
        try:
            # Idle connections may wait; once a frame starts it has a deadline.
            first = await self._read_exactly(1, allow_eof=True)
            async with asyncio.timeout(self._io_timeout):
                header = first + await self._read_exactly(3)
                length = int.from_bytes(header, "big")
                if not 1 <= length <= self._max_payload:
                    raise InvalidAppMessageError()
                return await self._read_exactly(length)
        except (AppServiceError, asyncio.CancelledError):
            raise
        except Exception:
            raise AppConnectionClosedError() from None

    async def _read_exactly(self, size: int, *, allow_eof: bool = False) -> bytes:
        output = bytearray()
        while len(output) < size:
            data = await self._transport.read(size - len(output))
            if type(data) is not bytes or len(data) > size - len(output):
                raise InvalidAppMessageError()
            if not data:
                if allow_eof and not output:
                    raise AppConnectionEOFError()
                raise InvalidAppMessageError()
            output.extend(data)
        return bytes(output)

    async def send(self, payload: bytes) -> None:
        if type(payload) is not bytes or not 1 <= len(payload) <= self._max_payload:
            raise InvalidAppMessageError()
        try:
            async with asyncio.timeout(self._io_timeout):
                async with self._writer:
                    if self._closed:
                        raise AppConnectionClosedError()
                    await self._transport.write(
                        len(payload).to_bytes(4, "big") + payload
                    )
        except (AppServiceError, asyncio.CancelledError):
            raise
        except Exception:
            raise AppConnectionClosedError() from None

    async def close(self) -> None:
        self._closed = True
        try:
            async with asyncio.timeout(self._io_timeout):
                await self._transport.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise AppConnectionClosedError() from None


class AppFramedStreamV1(_SizedFramedStream):
    """G14 framing: one reader/writer and the unchanged 1 MiB payload bound."""

    def __init__(
        self, transport: AppByteTransportV1, *, io_timeout: float = 10.0
    ) -> None:
        super().__init__(transport, max_payload=MAX_MESSAGE_BYTES, io_timeout=io_timeout)


class AsyncioStreamTransportV1:
    """An already connected pipe/stream pair; never launches or discovers peers."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def read(self, size: int) -> bytes:
        return await self._reader.read(size)

    async def write(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()


__all__ = [
    "AppByteTransportV1",
    "AppMessageStreamV1",
    "AppConnectionClosedError",
    "AppFramedStreamV1",
    "AsyncioStreamTransportV1",
]

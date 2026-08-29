"""Loop-epoch gate for Product-shared Resource Catalog input transactions."""

from __future__ import annotations

import asyncio
from threading import Lock
from types import TracebackType
from typing import Protocol


class ResourceCatalogRefreshGateLoopError(RuntimeError):
    """The same gate was entered concurrently from different event loops."""


class ResourceCatalogRefreshGatePort(Protocol):
    """Minimal async context-manager port consumed by Session refresh runtime."""

    async def __aenter__(self) -> object: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class ResourceCatalogRefreshGate:
    """Serialize shared refresh inputs and rotate only between idle loop epochs."""

    def __init__(self) -> None:
        self._state_lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._users = 0

    async def __aenter__(self) -> ResourceCatalogRefreshGate:
        loop = asyncio.get_running_loop()
        with self._state_lock:
            if self._loop is not loop:
                if self._users:
                    raise ResourceCatalogRefreshGateLoopError(
                        "Resource Catalog refresh gate cannot span active "
                        "event loops"
                    )
                self._loop = loop
                self._lock = asyncio.Lock()
            lock = self._lock
            if lock is None:
                raise RuntimeError("Resource Catalog refresh gate is unavailable")
            self._users += 1
        try:
            await lock.acquire()
        except BaseException:
            with self._state_lock:
                self._users -= 1
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        with self._state_lock:
            lock = self._lock
            if lock is None or self._users < 1:
                raise RuntimeError("Resource Catalog refresh gate is not entered")
            lock.release()
            self._users -= 1


__all__ = [
    "ResourceCatalogRefreshGate",
    "ResourceCatalogRefreshGateLoopError",
    "ResourceCatalogRefreshGatePort",
]

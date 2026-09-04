"""Private platform seam and single-use ownership for inherited endpoints."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ._process_backend import _ProcessInheritance
from .errors import HostingError, HostingFailureCategory


class _EndpointTransport(Protocol):
    async def read(self, max_bytes: int) -> bytes: ...

    async def write(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class _EndpointCleanupDebt(HostingError):
    """Typed internal marker that preserves otherwise orphaned endpoint debt."""

    def __init__(self, message: str, cause: BaseException) -> None:
        super().__init__(HostingFailureCategory.CLEANUP_FAILED, message)
        self.__cause__ = cause


class _SingleUseProcessInheritance(_ProcessInheritance):
    """One backend-bound child-side claim with an idempotent close path."""

    def __init__(
        self,
        *,
        backend_id: str,
        values: tuple[int, ...],
        close_values: Callable[[], None],
    ) -> None:
        if not backend_id or not values or any(
            type(value) is not int or value < 0 for value in values
        ):
            raise ValueError("endpoint inheritance material is invalid")
        self._backend_id = backend_id
        self._values = values
        self._close_values = close_values
        self._state = "owned"
        self._lock = threading.Lock()

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def claim(self, *, backend_id: str) -> tuple[int, ...]:
        with self._lock:
            if backend_id != self._backend_id:
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "endpoint inheritance targets a different platform backend",
                )
            if self._state != "owned":
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "endpoint inheritance has already been claimed",
                )
            self._state = "claimed"
            return self._values

    def mark_transferred(self) -> None:
        with self._lock:
            if self._state != "claimed":
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "endpoint inheritance is not claimed for transfer",
                )
            try:
                self._close_values()
            except BaseException as exc:
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "parent child-endpoint copies could not be closed",
                ) from exc
            self._state = "transferred"

    async def close(self) -> None:
        with self._lock:
            if self._state in {"closed", "transferred"}:
                return
            self._close_values()
            self._state = "closed"


@dataclass(frozen=True, slots=True)
class _PlatformEndpointPair:
    transport: _EndpointTransport
    inheritance: _ProcessInheritance

    async def close(self) -> None:
        results = await asyncio.gather(
            self.inheritance.close(),
            self.transport.close(),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup("endpoint pair cleanup failed", failures)


class _EndpointBackend(Protocol):
    @property
    def backend_id(self) -> str: ...

    async def create_pair(
        self,
        *,
        on_create: Callable[[_PlatformEndpointPair], None],
    ) -> _PlatformEndpointPair: ...

    async def close_backend(self) -> None: ...


__all__: list[str] = []

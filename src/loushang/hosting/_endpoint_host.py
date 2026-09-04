"""Private bounded owner for inherited peer endpoint pairs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar, cast

from ._endpoint_backend import (
    _EndpointBackend,
    _EndpointCleanupDebt,
    _EndpointTransport,
    _PlatformEndpointPair,
)
from ._process_backend import _ProcessInheritance
from .contracts import (
    HostByteEndpoint,
    HostingComponent,
    HostingLifecycleTransition,
    HostingObservation,
    HostingObservationSink,
)
from .errors import HostingError, HostingFailureCategory

_T = TypeVar("_T")


class _BoundedHostEndpoint(HostByteEndpoint):
    def __init__(
        self,
        transport: _EndpointTransport,
        *,
        max_read_bytes: int,
        max_write_bytes: int,
    ) -> None:
        self._transport = transport
        self._max_read_bytes = max_read_bytes
        self._max_write_bytes = max_write_bytes
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._closed = False

    async def read(self, max_bytes: int) -> bytes:
        if (
            type(max_bytes) is not int
            or max_bytes < 1
            or max_bytes > self._max_read_bytes
        ):
            raise HostingError(
                HostingFailureCategory.READ_BOUND_EXCEEDED,
                "host endpoint read exceeds its fixed bound",
            )
        async with self._read_lock:
            if self._closed:
                return b""
            try:
                chunk = await self._transport.read(max_bytes)
            except (BrokenPipeError, ConnectionResetError):
                return b""
        if not isinstance(chunk, bytes) or len(chunk) > max_bytes:
            raise HostingError(
                HostingFailureCategory.READ_BOUND_EXCEEDED,
                "endpoint backend violated the requested read bound",
            )
        return chunk

    async def write(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("host endpoint writes must be bytes")
        if len(data) > self._max_write_bytes:
            raise HostingError(
                HostingFailureCategory.WRITE_BOUND_EXCEEDED,
                "host endpoint write exceeds its fixed bound",
            )
        async with self._write_lock:
            if self._closed:
                raise HostingError(
                    HostingFailureCategory.PEER_CLOSED,
                    "host endpoint is closed",
                )
            try:
                await self._transport.write(data)
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise HostingError(
                    HostingFailureCategory.PEER_CLOSED,
                    "child endpoint is closed",
                ) from exc

    async def close(self) -> None:
        async with self._close_lock:
            task = self._close_task
            if task is None:
                task = asyncio.create_task(
                    self._close_owned(), name="hosting-host-endpoint-close"
                )
                self._close_task = task
        try:
            await _await_owned(task)
        except BaseException:
            async with self._close_lock:
                if self._close_task is task and _owner_task_failed(task):
                    self._close_task = None
            raise

    async def _close_owned(self) -> None:
        self._closed = True
        await self._transport.close()


class _InheritedEndpointLease:
    def __init__(
        self,
        pair: _PlatformEndpointPair,
        *,
        max_read_bytes: int,
        max_write_bytes: int,
        owner_id: str,
        session_id: str | None,
        on_close: Callable[
            ["_InheritedEndpointLease", BaseException | None], Awaitable[None]
        ],
        on_closing: Callable[["_InheritedEndpointLease"], None],
    ) -> None:
        self.endpoint = _BoundedHostEndpoint(
            pair.transport,
            max_read_bytes=max_read_bytes,
            max_write_bytes=max_write_bytes,
        )
        self.inheritance: _ProcessInheritance = pair.inheritance
        self.owner_id = owner_id
        self.session_id = session_id
        self._pair = pair
        self._on_close = on_close
        self._on_closing = on_closing
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        async with self._close_lock:
            task = self._close_task
            if task is None:
                self._on_closing(self)
                task = asyncio.create_task(
                    self._close_owned(), name="hosting-inherited-endpoint-close"
                )
                self._close_task = task
        try:
            await _await_owned(task)
        except BaseException:
            async with self._close_lock:
                if self._close_task is task and _owner_task_failed(task):
                    self._close_task = None
            raise

    async def _close_owned(self) -> None:
        failure: BaseException | None = None
        try:
            results = await asyncio.gather(
                self._pair.inheritance.close(),
                self.endpoint.close(),
                return_exceptions=True,
            )
            failures = [
                result for result in results if isinstance(result, BaseException)
            ]
            if failures:
                raise BaseExceptionGroup("endpoint lease cleanup failed", failures)
        except BaseException as exc:
            failure = exc
        finally:
            await self._on_close(self, failure)
        if failure is not None:
            raise failure


@dataclass(slots=True)
class _EndpointReservation:
    reservation_id: int
    owner_id: str
    session_id: str | None
    owner: asyncio.Task[object]
    settled: asyncio.Event
    pair: _PlatformEndpointPair | None = None
    cleanup_pairs: tuple[_PlatformEndpointPair, ...] = ()
    cleanup_error: BaseException | None = None

    def attach(self, pair: _PlatformEndpointPair) -> None:
        if self.pair is not None and self.pair is not pair:
            raise RuntimeError("endpoint reservation already owns a pair")
        self.pair = pair


class _InheritedEndpointHost:
    def __init__(
        self,
        backend: _EndpointBackend,
        *,
        max_endpoints: int = 4,
        max_read_bytes: int = 64 * 1024,
        max_write_bytes: int = 1024 * 1024,
        observation_sink: HostingObservationSink | None = None,
    ) -> None:
        for name, value in (
            ("max_endpoints", max_endpoints),
            ("max_read_bytes", max_read_bytes),
            ("max_write_bytes", max_write_bytes),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._backend = backend
        backend_id = backend.backend_id
        if (
            not isinstance(backend_id, str)
            or not backend_id
            or len(backend_id) > 128
            or "\0" in backend_id
        ):
            raise ValueError("backend_id must be 1-128 characters")
        self._backend_id = backend_id
        self._max_endpoints = max_endpoints
        self._max_read_bytes = max_read_bytes
        self._max_write_bytes = max_write_bytes
        self._observation_sink = observation_sink
        self._lock = asyncio.Lock()
        self._state = "open"
        self._reservations: dict[int, _EndpointReservation] = {}
        self._next_reservation = 1
        self._leases: set[_InheritedEndpointLease] = set()
        self._close_task: asyncio.Task[None] | None = None

    async def create(self, *, session_id: str | None = None) -> _InheritedEndpointLease:
        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("endpoint creation requires an asyncio task")
        async with self._lock:
            if self._state != "open":
                raise HostingError(
                    HostingFailureCategory.HOST_CLOSED,
                    "inherited endpoint host is closing",
                )
            if len(self._reservations) + len(self._leases) >= self._max_endpoints:
                raise HostingError(
                    HostingFailureCategory.CAPACITY_EXHAUSTED,
                    "inherited endpoint capacity is exhausted",
                )
            reservation_id = self._next_reservation
            self._next_reservation += 1
            owner_id = f"endpoint-{reservation_id}"
            reservation = _EndpointReservation(
                reservation_id,
                owner_id,
                session_id,
                owner,
                asyncio.Event(),
            )
            self._reservations[reservation_id] = reservation
        self._emit(
            reservation.owner_id,
            reservation.session_id,
            HostingLifecycleTransition.CAPACITY_RESERVED,
        )
        published = False
        pair: _PlatformEndpointPair | None = None
        try:
            self._emit(
                reservation.owner_id,
                reservation.session_id,
                HostingLifecycleTransition.SPAWNING,
            )
            pair = await self._backend.create_pair(on_create=reservation.attach)
            if reservation.pair is None:
                reservation.attach(pair)
                raise RuntimeError("endpoint backend returned before owner attachment")
            reservation.attach(pair)
            lease = _InheritedEndpointLease(
                pair,
                max_read_bytes=self._max_read_bytes,
                max_write_bytes=self._max_write_bytes,
                owner_id=owner_id,
                session_id=session_id,
                on_close=self._release,
                on_closing=self._begin_close,
            )
            async with self._lock:
                if (
                    self._state != "open"
                    or self._reservations.get(reservation_id) is not reservation
                ):
                    raise HostingError(
                        HostingFailureCategory.HOST_CLOSED,
                        "inherited endpoint host closed during creation",
                    )
                self._reservations.pop(reservation_id)
                self._leases.add(lease)
                published = True
            self._emit(
                reservation.owner_id,
                reservation.session_id,
                HostingLifecycleTransition.PUBLISHED,
            )
            return lease
        except BaseException as primary:
            inherited_debt = _find_cleanup_debt(primary)
            if inherited_debt is not None:
                reservation.cleanup_error = inherited_debt
            self._emit(
                reservation.owner_id,
                reservation.session_id,
                HostingLifecycleTransition.FAILED,
                _endpoint_failure_category(primary),
            )
            pairs_by_id = {
                id(candidate): candidate
                for candidate in (reservation.pair, pair)
                if candidate is not None
            }
            if pairs_by_id:
                reservation.cleanup_pairs = tuple(pairs_by_id.values())
                self._emit(
                    reservation.owner_id,
                    reservation.session_id,
                    HostingLifecycleTransition.CLEANING,
                )
                cleanup = asyncio.create_task(
                    _close_pairs(tuple(pairs_by_id.values())),
                    name="hosting-inherited-endpoint-rollback",
                )
                try:
                    await _await_owned(cleanup)
                except BaseException as cleanup_error:
                    debt = _EndpointCleanupDebt(
                        "endpoint acquisition rollback did not settle",
                        cleanup_error,
                    )
                    reservation.cleanup_error = debt
                    async with self._lock:
                        if self._state == "open":
                            self._state = "faulted"
                    if isinstance(primary, asyncio.CancelledError):
                        raise primary from debt
                    primary.add_note(f"endpoint rollback also failed: {cleanup_error}")
                    raise primary from debt
                reservation.cleanup_pairs = ()
                if reservation.cleanup_error is None:
                    self._emit(
                        reservation.owner_id,
                        reservation.session_id,
                        HostingLifecycleTransition.CLOSED,
                    )
            raise
        finally:
            if not published:
                async with self._lock:
                    if reservation.cleanup_error is None:
                        self._reservations.pop(reservation_id, None)
                    elif self._state == "open":
                        self._state = "faulted"
                reservation.settled.set()

    async def close(self) -> None:
        caller = asyncio.current_task()
        async with self._lock:
            task = self._close_task
            if task is None:
                if any(
                    reservation.owner is caller
                    and not reservation.settled.is_set()
                    for reservation in self._reservations.values()
                ):
                    raise RuntimeError("endpoint host cannot close during its own create")
                self._state = "closing"
                task = asyncio.create_task(
                    self._close_owned(), name="hosting-inherited-endpoint-host-close"
                )
                self._close_task = task
        try:
            await _await_owned(task)
        except BaseException:
            async with self._lock:
                if self._close_task is task and _owner_task_failed(task):
                    self._close_task = None
            raise

    async def _close_owned(self) -> None:
        async with self._lock:
            reservations = tuple(self._reservations.values())
            leases = tuple(self._leases)
        for reservation in reservations:
            if (
                not reservation.settled.is_set()
                and reservation.owner is not asyncio.current_task()
            ):
                reservation.owner.cancel()
        if reservations:
            await asyncio.gather(
                *(reservation.settled.wait() for reservation in reservations)
            )
        retry_results = await asyncio.gather(
            *(
                self._retry_reservation(reservation)
                for reservation in reservations
                if reservation.cleanup_error is not None
                and reservation.cleanup_pairs
            ),
            return_exceptions=True,
        )
        results = await asyncio.gather(
            *(lease.close() for lease in leases), return_exceptions=True
        )
        failures = [
            reservation.cleanup_error
            for reservation in reservations
            if reservation.cleanup_error is not None
            and not reservation.cleanup_pairs
        ]
        failures.extend(
            result for result in retry_results if isinstance(result, BaseException)
        )
        failures.extend(
            result for result in results if isinstance(result, BaseException)
        )
        try:
            await self._backend.close_backend()
        except BaseException as exc:
            failures.append(exc)
        async with self._lock:
            self._state = "closed"
        if failures:
            raise BaseExceptionGroup("endpoint host cleanup failed", failures)

    async def _retry_reservation(
        self,
        reservation: _EndpointReservation,
    ) -> None:
        try:
            await _close_pairs(reservation.cleanup_pairs)
        except BaseException as cleanup_error:
            debt = _EndpointCleanupDebt(
                "endpoint acquisition rollback retry did not settle",
                cleanup_error,
            )
            reservation.cleanup_error = debt
            raise debt
        reservation.cleanup_pairs = ()
        reservation.cleanup_error = None
        async with self._lock:
            self._reservations.pop(reservation.reservation_id, None)
        self._emit(
            reservation.owner_id,
            reservation.session_id,
            HostingLifecycleTransition.CLOSED,
        )

    async def _release(
        self,
        lease: _InheritedEndpointLease,
        failure: BaseException | None,
    ) -> None:
        async with self._lock:
            if failure is None:
                self._leases.discard(lease)
            elif self._state == "open":
                self._state = "faulted"
        if failure is None:
            self._emit(
                lease.owner_id,
                lease.session_id,
                HostingLifecycleTransition.CLOSED,
            )
        else:
            self._emit(
                lease.owner_id,
                lease.session_id,
                HostingLifecycleTransition.FAILED,
                HostingFailureCategory.CLEANUP_FAILED,
            )

    def _begin_close(self, lease: _InheritedEndpointLease) -> None:
        self._emit(
            lease.owner_id,
            lease.session_id,
            HostingLifecycleTransition.CLEANING,
        )

    def _emit(
        self,
        owner_id: str,
        session_id: str | None,
        transition: HostingLifecycleTransition,
        failure: HostingFailureCategory | None = None,
    ) -> None:
        sink = self._observation_sink
        if sink is None:
            return
        observation = HostingObservation(
            component=HostingComponent.ENDPOINT,
            transition=transition,
            owner_id=owner_id,
            session_id=session_id,
            backend_id=self._backend_id,
            failure=failure,
        )
        try:
            sink.observe(observation)
        except BaseException:
            return


async def _close_pairs(pairs: tuple[_PlatformEndpointPair, ...]) -> None:
    results = await asyncio.gather(
        *(pair.close() for pair in pairs), return_exceptions=True
    )
    failures = [result for result in results if isinstance(result, BaseException)]
    if failures:
        raise BaseExceptionGroup("endpoint rollback cleanup failed", failures)


def _endpoint_failure_category(error: BaseException) -> HostingFailureCategory:
    if isinstance(error, HostingError):
        return error.category
    return HostingFailureCategory.ENDPOINT_UNAVAILABLE


def _find_cleanup_debt(error: BaseException) -> BaseException | None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop()
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        if (
            isinstance(candidate, HostingError)
            and candidate.category is HostingFailureCategory.CLEANUP_FAILED
        ):
            return candidate
        if isinstance(candidate, BaseExceptionGroup):
            pending.extend(candidate.exceptions)
        if candidate.__cause__ is not None:
            pending.append(candidate.__cause__)
        if candidate.__context__ is not None:
            pending.append(candidate.__context__)
    return None


async def _await_owned(task: asyncio.Task[_T]) -> _T:
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = exc
        except BaseException as exc:
            if cancellation is not None:
                raise cancellation from exc
            raise
    if cancellation is not None:
        raise cancellation
    return cast(_T, result)


def _owner_task_failed(task: asyncio.Task[object]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


__all__: list[str] = []

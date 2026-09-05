"""Private H4 atomic process-plus-endpoint lifetime owner."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TypeVar, cast

from ._endpoint_host import _InheritedEndpointHost, _InheritedEndpointLease
from ._launch_preparation import (
    _CapturedLaunchMaterial,
    _LaunchCaptureBackend,
    _ManagedLaunchPreparationPort,
    _ManagedLaunchPreparationResult,
    _ReservationLaunchCapture,
)
from ._process_backend import _ProcessInheritance
from ._process_host import _ProcessHost
from .contracts import (
    ChildSessionHostingPort,
    ChildSessionLease,
    ChildSessionRequest,
    HostByteEndpoint,
    HostingComponent,
    HostingLifecycleTransition,
    HostingObservation,
    HostingObservationSink,
    LaunchPreparationLease,
    LaunchPreparationPort,
    ProcessLaunchRequest,
    ProcessLease,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from .errors import HostingError, HostingFailureCategory

_T = TypeVar("_T")
_MAX_MANAGED_LAUNCH_SLOTS = 64


class _DeferredProcessInheritance(_ProcessInheritance):
    """Binds endpoint material after process capacity and preparation exist."""

    def __init__(self, *, backend_id: str) -> None:
        self._backend_id = backend_id
        self._bound: _ProcessInheritance | None = None
        self._lock = threading.Lock()

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def bind(self, inheritance: _ProcessInheritance) -> None:
        with self._lock:
            if self._bound is not None:
                raise RuntimeError("child-session inheritance is already bound")
            if inheritance.backend_id != self._backend_id:
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "endpoint and process backends are incompatible",
                )
            self._bound = inheritance

    def claim(self, *, backend_id: str) -> tuple[int, ...]:
        with self._lock:
            bound = self._require_bound()
            return bound.claim(backend_id=backend_id)

    def mark_transferred(self) -> None:
        with self._lock:
            self._require_bound().mark_transferred()

    async def close(self) -> None:
        with self._lock:
            bound = self._bound
        if bound is not None:
            await bound.close()

    def _require_bound(self) -> _ProcessInheritance:
        if self._bound is None:
            raise HostingError(
                HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                "child-session endpoint inheritance is not bound",
            )
        return self._bound


@dataclass(frozen=True, slots=True)
class _NestedCleanupDebt:
    """Exact lower-owner debt retained for one Child Session transaction."""

    session_id: str
    error: BaseException
    process: bool
    endpoint: bool

    def settled(
        self,
        process_host: _ProcessHost,
        endpoint_host: _InheritedEndpointHost,
    ) -> bool:
        return (
            not self.process or not process_host._has_cleanup_debt(self.session_id)
        ) and (
            not self.endpoint or not endpoint_host._has_cleanup_debt(self.session_id)
        )


@dataclass(slots=True)
class _SessionReservation:
    reservation_id: int
    session_id: str
    owner: asyncio.Task[object]
    settled: asyncio.Event
    endpoint: _InheritedEndpointLease | None = None
    launch_captures: list[_CapturedLaunchMaterial] = field(default_factory=list)
    pending_preparation: LaunchPreparationLease | None = None
    process: ProcessLease | None = None
    retained_cleanup_debt: "_NestedCleanupDebt | None" = None
    cleanup_error: BaseException | None = None

    def attach_endpoint(self, endpoint: _InheritedEndpointLease) -> None:
        if self.endpoint is not None and self.endpoint is not endpoint:
            raise RuntimeError("child-session reservation already owns an endpoint")
        self.endpoint = endpoint

    def attach_launch_capture(self, material: _CapturedLaunchMaterial) -> None:
        if any(owned is material for owned in self.launch_captures):
            return
        if len(self.launch_captures) >= 2:
            raise RuntimeError("child-session launch capture debt bound is exhausted")
        self.launch_captures.append(material)

    def release_launch_capture(self, material: _CapturedLaunchMaterial) -> None:
        if not any(owned is material for owned in self.launch_captures):
            raise RuntimeError("child-session launch capture owner is inconsistent")
        self.launch_captures = [
            owned for owned in self.launch_captures if owned is not material
        ]

    def attach_pending_preparation(
        self, preparation: LaunchPreparationLease
    ) -> None:
        if (
            self.pending_preparation is not None
            and self.pending_preparation is not preparation
        ):
            raise RuntimeError("child-session reservation already owns preparation")
        self.pending_preparation = preparation

    def replace_pending_preparation(
        self,
        expected: LaunchPreparationLease,
        replacement: LaunchPreparationLease,
    ) -> None:
        if self.pending_preparation is not expected:
            raise RuntimeError("child-session preparation owner is inconsistent")
        self.pending_preparation = replacement

    def release_pending_preparation(
        self, preparation: LaunchPreparationLease
    ) -> None:
        if self.pending_preparation is not preparation:
            raise RuntimeError("child-session preparation owner is inconsistent")
        self.pending_preparation = None

    def attach_process(self, process: ProcessLease) -> None:
        if self.process is not None and self.process is not process:
            raise RuntimeError("child-session reservation already owns a process")
        self.process = process


class _SessionPreparationPort(LaunchPreparationPort):
    def __init__(
        self,
        caller: LaunchPreparationPort,
        endpoint_host: _InheritedEndpointHost,
        deferred: _DeferredProcessInheritance,
        reservation: _SessionReservation,
        capture_backend: _LaunchCaptureBackend | None,
        max_capture_slots: int,
    ) -> None:
        self._caller = caller
        self._endpoint_host = endpoint_host
        self._deferred = deferred
        self._reservation = reservation
        self._capture_backend = capture_backend
        self._max_capture_slots = max_capture_slots

    async def prepare(
        self, request: ProcessLaunchRequest
    ) -> LaunchPreparationLease:
        capture: _ReservationLaunchCapture | None = None
        managed_result: _ManagedLaunchPreparationResult | None = None
        if self._capture_backend is not None and isinstance(
            self._caller, _ManagedLaunchPreparationPort
        ):
            capture = _ReservationLaunchCapture(
                self._capture_backend,
                attempt_id=self._reservation.session_id,
                max_inherited_slots=self._max_capture_slots,
                on_capture=self._reservation.attach_launch_capture,
                on_orphan=self._reservation.attach_launch_capture,
            )
            managed_result = await self._caller.prepare_managed(request, capture)
            if not isinstance(managed_result, _ManagedLaunchPreparationResult):
                raise TypeError("managed preparation port returned an invalid result")
            prepared = managed_result.lease
        else:
            prepared = await self._caller.prepare(request)
        if not isinstance(prepared, LaunchPreparationLease):
            raise TypeError("preparation port returned an invalid lease")
        self._reservation.attach_pending_preparation(prepared)
        try:
            prepared_request = prepared.request
            if not isinstance(prepared_request, ProcessLaunchRequest):
                raise TypeError("preparation lease returned an invalid request")
            _validate_session_process_request(prepared_request)
            managed = (
                capture.bind_result(managed_result)
                if capture is not None and managed_result is not None
                else None
            )
            if managed is not None:
                assert capture is not None
                material = capture.material
                if material is None:
                    raise RuntimeError("managed launch capture was not attached")
                self._reservation.replace_pending_preparation(prepared, managed)
                self._reservation.release_launch_capture(material)
            endpoint = await self._endpoint_host.create(
                session_id=self._reservation.session_id
            )
            self._reservation.attach_endpoint(endpoint)
            if capture is None:
                self._deferred.bind(endpoint.inheritance)
                self._reservation.release_pending_preparation(prepared)
                return prepared
            assert managed is not None
            self._deferred.bind(endpoint.inheritance)
            self._reservation.release_pending_preparation(managed)
            return managed
        except BaseException:
            # The aggregate reservation owns the pending preparation until the
            # Process Host can attach it synchronously after this method returns.
            raise
        raise AssertionError("unreachable child-session preparation path")


class _HostedChildSession(ChildSessionLease):
    def __init__(
        self,
        *,
        session_id: str,
        process: ProcessLease,
        endpoint: _InheritedEndpointLease,
        on_closing: Callable[["_HostedChildSession"], None],
        on_finalized: Callable[
            ["_HostedChildSession", BaseException | None], Awaitable[None]
        ],
    ) -> None:
        self._session_id = session_id
        self._process = process
        self._endpoint_lease = endpoint
        self._on_closing = on_closing
        self._on_finalized = on_finalized
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._watch_task: asyncio.Task[None] | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def process(self) -> ProcessLease:
        return self._process

    @property
    def endpoint(self) -> HostByteEndpoint:
        return self._endpoint_lease.endpoint

    def begin(self) -> None:
        if self._watch_task is not None:
            raise RuntimeError("child-session watcher already started")
        task = asyncio.create_task(
            self._watch_process(),
            name=f"hosting-{self._session_id}-watcher",
        )
        self._watch_task = task

        def settle(completed: asyncio.Task[None]) -> None:
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(settle)

    async def close(self) -> None:
        async with self._close_lock:
            task = self._close_task
            if task is None:
                self._on_closing(self)
                task = asyncio.create_task(
                    self._close_owned(),
                    name=f"hosting-{self._session_id}-close",
                )
                self._close_task = task
        try:
            await _await_owned(task)
        except BaseException:
            async with self._close_lock:
                if self._close_task is task and _owner_task_failed(task):
                    self._close_task = None
            raise

    async def _watch_process(self) -> None:
        with suppress(BaseException):
            await self._process.wait()
        with suppress(BaseException):
            await self.close()

    async def _close_owned(self) -> None:
        failures: list[BaseException] = []
        try:
            await self._process.close()
        except BaseException as exc:
            failures.append(exc)
        try:
            await self._endpoint_lease.close()
        except BaseException as exc:
            failures.append(exc)
        failure: BaseException | None = None
        if failures:
            failure = BaseExceptionGroup("child-session cleanup failed", failures)
        await self._on_finalized(self, failure)
        if failure is not None:
            raise failure


class _ChildSessionHost(ChildSessionHostingPort):
    def __init__(
        self,
        process_host: _ProcessHost,
        endpoint_host: _InheritedEndpointHost,
        *,
        max_sessions: int,
        observation_sink: HostingObservationSink | None = None,
        launch_capture_backend: _LaunchCaptureBackend | None = None,
        max_capture_slots: int = 8,
    ) -> None:
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be a positive integer")
        if (
            type(max_capture_slots) is not int
            or max_capture_slots < 1
            or max_capture_slots > _MAX_MANAGED_LAUNCH_SLOTS
        ):
            raise ValueError("max_capture_slots is invalid")
        if (
            launch_capture_backend is not None
            and launch_capture_backend.backend_id != process_host._backend_id
        ):
            raise ValueError("launch capture backend must match the process backend")
        self._process_host = process_host
        self._endpoint_host = endpoint_host
        self._max_sessions = max_sessions
        self._observation_sink = observation_sink
        self._launch_capture_backend = launch_capture_backend
        self._max_capture_slots = max_capture_slots
        self._backend_id = (
            f"{process_host._backend_id}+{endpoint_host._backend_id}"
        )
        self._lock = asyncio.Lock()
        self._state = "open"
        self._next_id = 1
        self._instance_id = uuid.uuid4().hex
        self._reservations: dict[int, _SessionReservation] = {}
        self._leases: set[_HostedChildSession] = set()
        self._close_task: asyncio.Task[None] | None = None

    async def start(
        self,
        request: ChildSessionRequest,
        preparation: LaunchPreparationPort,
    ) -> ChildSessionLease:
        if not isinstance(request, ChildSessionRequest):
            raise TypeError("child-session host requires ChildSessionRequest")
        _validate_session_process_request(request.process)
        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("child-session start requires an asyncio task")
        async with self._lock:
            if self._state != "open":
                raise HostingError(
                    HostingFailureCategory.HOST_CLOSED,
                    "child-session host is closing",
                )
            if len(self._reservations) + len(self._leases) >= self._max_sessions:
                raise HostingError(
                    HostingFailureCategory.CAPACITY_EXHAUSTED,
                    "child-session capacity is exhausted",
                )
            reservation_id = self._next_id
            self._next_id += 1
            session_id = f"child-session-{self._instance_id}-{reservation_id}"
            reservation = _SessionReservation(
                reservation_id,
                session_id,
                owner,
                asyncio.Event(),
            )
            self._reservations[reservation_id] = reservation

        self._emit(reservation, HostingLifecycleTransition.CAPACITY_RESERVED)
        self._emit(reservation, HostingLifecycleTransition.PREPARING)
        published = False
        try:
            deferred = _DeferredProcessInheritance(
                backend_id=self._process_host._backend_id
            )
            preparation_port = _SessionPreparationPort(
                preparation,
                self._endpoint_host,
                deferred,
                reservation,
                self._launch_capture_backend,
                self._max_capture_slots,
            )
            process = await self._process_host._start_with_inheritance(
                request.process,
                preparation_port,
                inheritance=deferred,
                session_id=session_id,
            )
            reservation.attach_process(process)
            endpoint = reservation.endpoint
            if endpoint is None:
                raise RuntimeError("child-session process started without an endpoint")
            lease = _HostedChildSession(
                session_id=session_id,
                process=process,
                endpoint=endpoint,
                on_closing=self._begin_close,
                on_finalized=self._release,
            )
            async with self._lock:
                if (
                    self._state != "open"
                    or self._reservations.get(reservation_id) is not reservation
                ):
                    raise HostingError(
                        HostingFailureCategory.HOST_CLOSED,
                        "child-session host closed during start",
                    )
                self._reservations.pop(reservation_id)
                self._leases.add(lease)
                lease.begin()
                published = True
            self._emit(reservation, HostingLifecycleTransition.PUBLISHED)
            return lease
        except BaseException as caught:
            primary = _session_failure(caught)
            process_debt = self._process_host._has_cleanup_debt(session_id)
            endpoint_debt = self._endpoint_host._has_cleanup_debt(session_id)
            if process_debt or endpoint_debt:
                reservation.retained_cleanup_debt = _NestedCleanupDebt(
                    session_id=session_id,
                    error=caught,
                    process=process_debt,
                    endpoint=endpoint_debt,
                )
                reservation.cleanup_error = caught
            self._emit(
                reservation,
                HostingLifecycleTransition.FAILED,
                _failure_category(primary),
            )
            rollback = asyncio.create_task(
                self._rollback(reservation),
                name=f"hosting-{session_id}-rollback",
            )
            try:
                await _await_owned(rollback)
            except BaseException as cleanup_error:
                if isinstance(primary, asyncio.CancelledError):
                    raise primary from cleanup_error
                primary.add_note(f"child-session rollback also failed: {cleanup_error}")
                raise primary from cleanup_error
            if primary is caught:
                raise
            raise primary from caught
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
                    raise RuntimeError(
                        "child-session host cannot close during its own start"
                    )
                self._state = "closing"
                task = asyncio.create_task(
                    self._close_owned(), name="hosting-child-session-host-close"
                )
                self._close_task = task
        await _await_owned(task)

    async def _rollback(self, reservation: _SessionReservation) -> None:
        self._emit(reservation, HostingLifecycleTransition.CLEANING)
        reservation.cleanup_error = None
        failures: list[BaseException] = []
        if reservation.process is not None:
            try:
                await reservation.process.close()
            except BaseException as exc:
                failures.append(exc)
        if reservation.endpoint is not None:
            try:
                await reservation.endpoint.close()
            except BaseException as exc:
                failures.append(exc)
        if reservation.pending_preparation is not None:
            pending = reservation.pending_preparation
            try:
                await pending.close()
                reservation.release_pending_preparation(pending)
            except BaseException as exc:
                failures.append(exc)
        for material in tuple(reservation.launch_captures):
            try:
                await material.close()
                reservation.release_launch_capture(material)
            except BaseException as exc:
                failures.append(exc)
        if failures:
            local_failure = BaseExceptionGroup(
                "child-session rollback failed", failures
            )
            reservation.cleanup_error = (
                local_failure
                if reservation.retained_cleanup_debt is None
                else BaseExceptionGroup(
                    "child-session cleanup debt",
                    [reservation.retained_cleanup_debt.error, local_failure],
                )
            )
        elif reservation.retained_cleanup_debt is not None:
            reservation.cleanup_error = reservation.retained_cleanup_debt.error
        if reservation.cleanup_error is not None:
            async with self._lock:
                if self._state == "open":
                    self._state = "faulted"
            self._emit(
                reservation,
                HostingLifecycleTransition.FAILED,
                HostingFailureCategory.CLEANUP_FAILED,
            )
            raise reservation.cleanup_error
        async with self._lock:
            self._reservations.pop(reservation.reservation_id, None)
        self._emit(reservation, HostingLifecycleTransition.CLOSED)

    async def _close_owned(self) -> None:
        async with self._lock:
            reservations = tuple(self._reservations.values())
        for reservation in reservations:
            if not reservation.settled.is_set():
                reservation.owner.cancel()
        if reservations:
            await asyncio.gather(
                *(reservation.settled.wait() for reservation in reservations)
            )
        debt_reservations = tuple(
            reservation
            for reservation in reservations
            if reservation.cleanup_error is not None
        )
        retained_debts = tuple(
            reservation.cleanup_error
            for reservation in debt_reservations
            if reservation.cleanup_error is not None
        )
        local_debt_results = await asyncio.gather(
            *(
                self._rollback(reservation)
                for reservation in debt_reservations
                if reservation.retained_cleanup_debt is None
            ),
            return_exceptions=True,
        )
        async with self._lock:
            leases = tuple(self._leases)
        results = await asyncio.gather(
            *(lease.close() for lease in leases), return_exceptions=True
        )
        failures: list[BaseException] = list(retained_debts)
        failures.extend(
            result
            for result in local_debt_results
            if isinstance(result, BaseException)
        )
        failures.extend(
            result for result in results if isinstance(result, BaseException)
        )
        backend_results = await asyncio.gather(
            self._process_host.close(),
            self._endpoint_host.close(),
            return_exceptions=True,
        )
        failures.extend(
            result for result in backend_results if isinstance(result, BaseException)
        )
        upstream_debts = tuple(
            reservation
            for reservation in debt_reservations
            if reservation.retained_cleanup_debt is not None
        )
        settled_upstream = tuple(
            reservation
            for reservation in upstream_debts
            if reservation.retained_cleanup_debt is not None
            and reservation.retained_cleanup_debt.settled(
                self._process_host,
                self._endpoint_host,
            )
        )
        if settled_upstream:
            for reservation in settled_upstream:
                reservation.retained_cleanup_debt = None
            upstream_results = await asyncio.gather(
                *(self._rollback(reservation) for reservation in settled_upstream),
                return_exceptions=True,
            )
            failures.extend(
                result
                for result in upstream_results
                if isinstance(result, BaseException)
            )
        async with self._lock:
            self._state = "closed"
        if failures:
            raise BaseExceptionGroup("child-session host cleanup failed", failures)

    def _begin_close(self, lease: _HostedChildSession) -> None:
        self._emit_lease(lease, HostingLifecycleTransition.CLEANING)

    async def _release(
        self,
        lease: _HostedChildSession,
        failure: BaseException | None,
    ) -> None:
        async with self._lock:
            if failure is None:
                self._leases.discard(lease)
            elif self._state == "open":
                self._state = "faulted"
        if failure is None:
            self._emit_lease(lease, HostingLifecycleTransition.CLOSED)
        else:
            self._emit_lease(
                lease,
                HostingLifecycleTransition.FAILED,
                HostingFailureCategory.CLEANUP_FAILED,
            )

    def _emit(
        self,
        reservation: _SessionReservation,
        transition: HostingLifecycleTransition,
        failure: HostingFailureCategory | None = None,
    ) -> None:
        self._emit_values(reservation.session_id, transition, failure)

    def _emit_lease(
        self,
        lease: _HostedChildSession,
        transition: HostingLifecycleTransition,
        failure: HostingFailureCategory | None = None,
    ) -> None:
        self._emit_values(lease.session_id, transition, failure)

    def _emit_values(
        self,
        session_id: str,
        transition: HostingLifecycleTransition,
        failure: HostingFailureCategory | None,
    ) -> None:
        sink = self._observation_sink
        if sink is None:
            return
        observation = HostingObservation(
            component=HostingComponent.SESSION,
            transition=transition,
            owner_id=session_id,
            session_id=session_id,
            backend_id=self._backend_id,
            failure=failure,
        )
        try:
            sink.observe(observation)
        except BaseException:
            return


def _session_failure(caught: BaseException) -> BaseException:
    if isinstance(caught, (asyncio.CancelledError, HostingError)):
        return caught
    if not isinstance(caught, Exception):
        return caught
    return HostingError(
        HostingFailureCategory.SPAWN_FAILED,
        "hosting child-session start failed",
    )


def _failure_category(error: BaseException) -> HostingFailureCategory:
    if isinstance(error, HostingError):
        return error.category
    return HostingFailureCategory.SPAWN_FAILED


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


def _validate_session_process_request(request: ProcessLaunchRequest) -> None:
    if (
        request.streams.stdin is not ProcessStdinMode.CLOSED
        or request.streams.stdout is not ProcessStdoutMode.DISCARD
    ):
        raise HostingError(
            HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
            "child sessions reserve process stdin and stdout for the endpoint",
        )


__all__: list[str] = []

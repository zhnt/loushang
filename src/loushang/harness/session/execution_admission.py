"""Reservations at one Session's original input and execution boundary.

This module owns no queue, driver, Work facts, or domain decisions. A trusted
integration commits a reservation in its synchronous accept resolver, explicitly
binds the accepted execution task, then releases after its original owner settles.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from typing import Literal


class SessionExecutionUnavailable(RuntimeError):
    pass


ReservationState = Literal["reserved", "invalidated", "committed", "settling", "released"]


@dataclass(eq=False)
class ExecutionReservation:
    operation_id: str | None
    _owner: SessionExecutionAdmission = field(repr=False)
    _generation: int = field(repr=False)
    _lifecycle_generation: int = field(repr=False)
    state: ReservationState = "reserved"
    exclusive_input: bool = True
    _task: asyncio.Task | None = field(default=None, repr=False)
    _participants: set[asyncio.Task] = field(default_factory=set, repr=False)

    def commit(self) -> None:
        self._owner.commit(self)

    def bind_operation(self, operation_id: str) -> None:
        self._owner.validate_reservation(self, require_operation=False)
        if self.operation_id is not None or not isinstance(operation_id, str) or not operation_id:
            raise SessionExecutionUnavailable("execution operation identity is already frozen or invalid")
        self.operation_id = operation_id

    def allow_queued_input(self) -> None:
        self._owner._check(self)
        if self.state != "reserved":
            raise SessionExecutionUnavailable("input isolation is frozen at commit")
        self.exclusive_input = False

    @property
    def children_active(self) -> bool:
        return bool(self._participants)

    @contextmanager
    def executing(self) -> Iterator[None]:
        self._owner._check(self, committed=True)
        if self._task is not None:
            raise SessionExecutionUnavailable("execution task already bound")
        self._task = asyncio.current_task()
        if self._task is None:
            raise SessionExecutionUnavailable("execution requires an owned task")
        try:
            yield
        finally:
            self._task = None

    def begin_settling(self) -> None:
        self._owner._check(self)
        if self.state == "committed":
            self.state = "settling"

    def release(self) -> None:
        self._owner.release(self)


@dataclass(eq=False)
class InputAdmission:
    _owner: SessionExecutionAdmission
    _clear_generation: int
    execution: ExecutionReservation | None
    _closed: bool = False

    def check(self) -> None:
        if self._closed or self._owner.closed or not self._owner._is_current():
            raise SessionExecutionUnavailable("Session input is no longer current")
        if self.execution is not None:
            self._owner.check_execution(self.execution)
        elif self._clear_generation != self._owner._clear_generation:
            raise SessionExecutionUnavailable("input cleared during preparation")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.execution is None:
            self._owner._preparing -= 1


class SessionExecutionAdmission:
    def __init__(self, *, busy: Callable[[], bool], pending: Callable[[], bool],
                 delivery_released: Callable[[], None]) -> None:
        self._busy, self._pending = busy, pending
        self._delivery_released = delivery_released
        self._generation = self._clear_generation = self._preparing = 0
        self._reservation: ExecutionReservation | None = None
        self.backend: object | None = None
        self._backend_busy: Callable[[], bool] = lambda: False
        self._settle_backend: Callable[[], Awaitable[None]] | None = None
        self._is_current: Callable[[], bool] = lambda: True
        self._transition_pending: Callable[[], bool] = lambda: False
        self._lifecycle_generation: Callable[[], int] = lambda: 0
        self._delivery_available = asyncio.Event()
        self._delivery_available.set()
        self.closed = False

    def bind_backend(self, backend: object, *, busy: Callable[[], bool],
                     settle: Callable[[], Awaitable[None]] | None = None) -> None:
        if self.closed or (self.backend is not None and self.backend is not backend):
            raise SessionExecutionUnavailable("Session already owns another execution backend")
        self.backend, self._backend_busy = backend, busy
        self._settle_backend = settle

    async def settle_backend(self) -> None:
        """Join the registered owner before releasing Session dependencies."""
        if self._settle_backend is not None:
            await self._settle_backend()
        if self._backend_busy():
            raise SessionExecutionUnavailable("Session execution backend has not settled")

    def retire_backend(self) -> None:
        if not self.closed or self._backend_busy():
            raise SessionExecutionUnavailable("Session backend is not ready for retirement")
        self.backend = None
        self._settle_backend = None
        self._backend_busy = lambda: False

    def bind_lifecycle(self, *, is_current: Callable[[], bool],
                       transition_pending: Callable[[], bool],
                       generation: Callable[[], int] = lambda: 0) -> None:
        self.input_arrived()
        self._is_current, self._transition_pending = is_current, transition_pending
        self._lifecycle_generation = generation

    def ordinary_work_arrived(self) -> None:
        self.input_arrived()
        self.require_unbound_run()

    def require_current(self) -> None:
        if self.closed or not self._is_current() or self._transition_pending():
            raise SessionExecutionUnavailable("Session execution identity is no longer current")

    def observe_execution(self, reservation: ExecutionReservation) -> tuple[int, int]:
        self._check(reservation)
        self.require_current()
        if reservation.state == "reserved":
            self.validate_reservation(reservation, require_operation=False)
        elif reservation.state != "committed":
            raise SessionExecutionUnavailable("execution reservation invalidated")
        if self._preparing or self._busy() or self._backend_busy() or self._pending():
            raise SessionExecutionUnavailable("Session input or execution pending")
        return self._generation, self._lifecycle_generation()

    @property
    def delivery_held(self) -> bool:
        return self.execution_reserved and self._reservation is not None and self._reservation.exclusive_input

    @property
    def execution_reserved(self) -> bool:
        return self._reservation is not None and self._reservation.state in {
            "committed", "settling"
        }

    def reserve(self, operation_id: str) -> ExecutionReservation:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("execution operation identity required")
        return self._reserve(operation_id)

    def reserve_candidate(self) -> ExecutionReservation:
        return self._reserve(None)

    def _reserve(self, operation_id: str | None) -> ExecutionReservation:
        if (self.closed or not self._is_current() or self._transition_pending()
                or self._reservation is not None or self._preparing
                or self._busy() or self._backend_busy() or self._pending()):
            raise SessionExecutionUnavailable("Session execution unavailable")
        reservation = ExecutionReservation(operation_id, self, self._generation, self._lifecycle_generation())
        self._reservation = reservation
        return reservation

    def input_arrived(self) -> None:
        self._generation += 1
        if self._reservation is not None and self._reservation.state == "reserved":
            self._reservation.state = "invalidated"

    def begin_input(self, execution: ExecutionReservation | None = None) -> InputAdmission:
        if self.closed or not self._is_current():
            raise SessionExecutionUnavailable("Session admission closed")
        if execution is None:
            self.input_arrived()
            self._preparing += 1
        else:
            self.check_execution(execution)
        return InputAdmission(self, self._clear_generation, execution)

    def clear_inputs(self) -> None:
        self.input_arrived()
        self._clear_generation += 1

    def commit(self, reservation: ExecutionReservation) -> None:
        self.validate_reservation(reservation)
        reservation.state = "committed"
        self._delivery_available.clear()

    def validate_reservation(self, reservation: ExecutionReservation, *, require_operation: bool = True) -> None:
        self._check(reservation)
        if (reservation.state != "reserved" or self.closed or not self._is_current()
                or self._transition_pending() or self._preparing
                or reservation._generation != self._generation
                or reservation._lifecycle_generation != self._lifecycle_generation()
                or require_operation and reservation.operation_id is None
                or self._busy() or self._backend_busy() or self._pending()):
            raise SessionExecutionUnavailable("execution reservation invalidated")

    def check_execution(self, reservation: ExecutionReservation) -> None:
        self._check(reservation, committed=True)
        task = asyncio.current_task()
        if self.closed or not self._is_current() or (reservation._task is not task and task not in reservation._participants):
            raise SessionExecutionUnavailable("execution task or Session is no longer current")

    def current_execution(self) -> ExecutionReservation | None:
        reservation = self._reservation
        task = asyncio.current_task()
        if (reservation is not None and reservation.state == "committed" and (
                task is reservation._task or task in reservation._participants)):
            self.check_execution(reservation)
            return reservation
        return None

    def execution_scope(
        self, reservation: ExecutionReservation,
    ) -> Callable[[], AbstractContextManager[None]]:
        """Explicitly delegate only at the original owner's task-creation seam.

        The factory must be called by an already admitted parent before creating
        its child. Merely copying context or spawning a task grants nothing.
        """
        self.check_execution(reservation)

        def factory() -> AbstractContextManager[None]:
            self.check_execution(reservation)
            execution_owner = reservation._task

            @contextmanager
            def entered() -> Iterator[None]:
                self._check(reservation, committed=True)
                if (self.closed or execution_owner is None or execution_owner.done()
                        or reservation._task is not execution_owner):
                    raise SessionExecutionUnavailable("execution parent is no longer current")
                child = asyncio.current_task()
                if child is None or child is reservation._task or child in reservation._participants:
                    raise SessionExecutionUnavailable("execution child already bound")
                reservation._participants.add(child)
                try:
                    yield
                finally:
                    reservation._participants.remove(child)

            return entered()

        return factory

    def require_unbound_run(self) -> None:
        if self.closed or self.execution_reserved:
            raise SessionExecutionUnavailable("Session reserved by another execution")

    def require_execution_actor(self) -> ExecutionReservation | None:
        if self.closed or not self._is_current():
            raise SessionExecutionUnavailable("Session is no longer current")
        if not self.execution_reserved:
            return None
        execution = self.current_execution()
        if execution is None:
            raise SessionExecutionUnavailable("Session reserved by another execution")
        return execution

    def release(self, reservation: ExecutionReservation) -> None:
        if reservation._owner is not self:
            raise SessionExecutionUnavailable("foreign execution reservation")
        if reservation.state == "released":
            return
        self._check(reservation)
        if reservation._task is not None or reservation._participants or reservation.state == "committed":
            raise SessionExecutionUnavailable("original execution must settle before release")
        # Retain the reservation on a delivery failure; the same owner retries.
        if reservation.state == "settling" and not self.closed:
            reservation.state = "reserved"
            try:
                self._delivery_released()
            except BaseException:
                reservation.state = "settling"
                raise
        reservation.state = "released"
        self._reservation = None
        self._delivery_available.set()

    def close_admission(self) -> None:
        self.closed = True
        self.input_arrived()
        self._delivery_available.set()

    async def wait_for_unbound_run(self) -> None:
        while self.execution_reserved and not self.closed:
            await self._delivery_available.wait()
        self.require_unbound_run()

    def require_released(self) -> None:
        if self._reservation is not None:
            raise SessionExecutionUnavailable("execution owner must release before Session disposal")

    def _check(self, reservation: ExecutionReservation, *, committed: bool = False) -> None:
        if reservation._owner is not self or self._reservation is not reservation:
            raise SessionExecutionUnavailable("foreign or expired execution reservation")
        if committed and reservation.state != "committed":
            raise SessionExecutionUnavailable("execution has not been committed")

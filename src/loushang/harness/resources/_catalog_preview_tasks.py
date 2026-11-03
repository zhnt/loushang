"""Bounded native computation owned by the Resource Catalog preview scope."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from typing import cast

from ._catalog_preview_scheduler import CatalogPreviewExecutor, CatalogPreviewPriority

_EXECUTOR = CatalogPreviewExecutor()
_SLOTS = threading.BoundedSemaphore(8)
_BACKGROUND_SLOTS = threading.BoundedSemaphore(6)
_SUBMISSION_FENCED = threading.Event()


class CatalogPreviewTaskError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class _Admission:
    background: bool
    released: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def acquire(cls, priority: CatalogPreviewPriority) -> _Admission:
        if not _SLOTS.acquire(blocking=False):
            raise CatalogPreviewTaskError("catalog_preview_capacity_exceeded")
        background = priority == "background"
        if background and not _BACKGROUND_SLOTS.acquire(blocking=False):
            _SLOTS.release()
            raise CatalogPreviewTaskError("catalog_preview_background_capacity_exceeded")
        return cls(background)

    def promote(self) -> None:
        with self.lock:
            if self.background:
                self.background = False
                _BACKGROUND_SLOTS.release()

    def release(self) -> None:
        with self.lock:
            if self.released:
                return
            self.released = True
            if self.background:
                self.background = False
                _BACKGROUND_SLOTS.release()
            _SLOTS.release()


@dataclass(eq=False)
class _Job:
    key: object
    receipt: asyncio.Future[tuple[bool, object]]
    cancelled: threading.Event
    admission: _Admission
    references: int = 0
    native_operation: Callable[[], None] | None = None
    scope_references: dict[CatalogPreviewTaskScope, int] = field(default_factory=dict)


# Only running pure Resource computations live here. No completed value or
# authority is cached; an event loop cannot borrow another loop's Future.
_IN_FLIGHT: list[_Job] = []
_IN_FLIGHT_LOCK = threading.Lock()


class CatalogPreviewTaskScope:
    """Keep native completion separate from cancellation of a Session waiter.

    Jobs retain only a pure computation and its temporary read pins. No result
    constitutes Resource selection, Writer admission, or execution authority.
    The process shares two native slots and at most eight admitted jobs, with
    at most six background jobs so foreground preparation can still enter.
    Matching scopes on the same event loop borrow a reference to running work.
    Closing one scope fences its references and joins native pin settlement;
    another open scope's reference keeps the shared computation alive.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._jobs: list[_Job] = []
        self._closed = False

    def _on_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise CatalogPreviewTaskError("catalog_preview_loop_changed")
        return loop

    async def run(
        self, key: object,
        prepare: Callable[[], tuple[Callable[[Callable[[], None]], str], Callable[[], None]]], *,
        max_work_units: int, time_budget_seconds: float,
        priority: CatalogPreviewPriority = "background",
    ) -> str:
        loop = self._on_loop()
        if self._closed:
            raise CatalogPreviewTaskError("catalog_preview_closed")
        if _SUBMISSION_FENCED.is_set():
            raise CatalogPreviewTaskError("catalog_preview_scheduler_unavailable")
        if priority not in ("foreground", "background"):
            raise ValueError("invalid Catalog preview priority")
        with _IN_FLIGHT_LOCK:
            job = next((item for item in _IN_FLIGHT
                        if item.receipt.get_loop() is loop and item.key == key
                        and not item.cancelled.is_set()), None)
        if job is None:
            admission = _Admission.acquire(priority)
            try:
                operation, dispose = prepare()
            except BaseException:
                admission.release()
                raise
            job = _Job(key, loop.create_future(), threading.Event(), admission)
            self._jobs.append(job)
            with _IN_FLIGHT_LOCK:
                _IN_FLIGHT.append(job)
            selected = job
            deadline = time.monotonic() + time_budget_seconds
            units = 0
            published = threading.Event()
            admitted = False

            def probe() -> None:
                nonlocal units
                if selected.cancelled.is_set():
                    raise CancelledError("Catalog preview reference released")
                units += 1
                if units > max_work_units:
                    raise CatalogPreviewTaskError("catalog_preview_work_budget_exceeded")
                if time.monotonic() > deadline:
                    raise CatalogPreviewTaskError("catalog_preview_time_budget_exceeded")

            def publish(outcome: tuple[bool, object]) -> None:
                with _IN_FLIGHT_LOCK:
                    _IN_FLIGHT.remove(selected)
                selected.receipt.set_result(outcome)
                for scope, references in tuple(selected.scope_references.items()):
                    if references == 0:
                        scope._jobs.remove(selected)
                        del selected.scope_references[scope]

            def native() -> None:
                published.wait()
                if not admitted:
                    return  # Unknown submission never admits source reads.
                try:
                    try:
                        outcome: tuple[bool, object] = (True, operation(probe))
                    finally:
                        dispose()
                except BaseException as error:
                    outcome = (False, error)
                finally:
                    selected.admission.release()
                loop.call_soon_threadsafe(publish, outcome)

            try:
                job.native_operation = native
                _EXECUTOR.submit(native, priority=priority)
                admitted = True
            except BaseException as error:
                # submit may throw after queue admission. The publication gate
                # proves the queued callback cannot read or close these pins.
                _SUBMISSION_FENCED.set()
                selected.cancelled.set()
                try:
                    dispose()
                except BaseException as cleanup_error:
                    error.add_note(f"preview pin cleanup failed: {type(cleanup_error).__name__}")
                self._jobs.remove(selected)
                with _IN_FLIGHT_LOCK:
                    _IN_FLIGHT.remove(selected)
                selected.admission.release()
                raise
            finally:
                published.set()
        if job.references >= 64:
            raise CatalogPreviewTaskError("catalog_preview_reference_capacity_exceeded")
        if job not in self._jobs:
            self._jobs.append(job)
        job.scope_references[self] = job.scope_references.get(self, 0) + 1
        job.references += 1
        try:
            if priority == "foreground" and job.native_operation is not None:
                _EXECUTOR.promote(job.native_operation)
                job.admission.promote()
            succeeded, value = await asyncio.shield(job.receipt)
            if self._closed:
                raise CatalogPreviewTaskError("catalog_preview_closed")
            if not succeeded:
                raise cast(BaseException, value)
            return cast(str, value)
        finally:
            job.references -= 1
            job.scope_references[self] -= 1
            if job.references == 0:
                job.cancelled.set()
                if job.native_operation is not None:
                    _EXECUTOR.promote(job.native_operation)
            if job.scope_references[self] == 0 and job.receipt.done():
                self._jobs.remove(job)
                del job.scope_references[self]

    def fence(self) -> bool:
        """Stop new references; return whether actual native work is settled."""

        self._closed = True
        for job in self._jobs:
            if not any(not scope._closed and references > 0
                       for scope, references in job.scope_references.items()):
                job.cancelled.set()
                if job.native_operation is not None:
                    _EXECUTOR.promote(job.native_operation)
        return all(job.receipt.done() for job in self._jobs)

    async def close(self) -> None:
        self._on_loop()
        self.fence()
        cancellation: asyncio.CancelledError | None = None
        for job in tuple(self._jobs):
            while not job.receipt.done():
                try:
                    await asyncio.shield(job.receipt)
                except asyncio.CancelledError as error:
                    cancellation = error
        if cancellation is not None:
            raise cancellation

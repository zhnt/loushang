"""One explicit service-start/reuse operation over already admitted storage.

No Product selection, directory initialization, Mux mutation or unclean restart.
The caller retains this owner before ensure_started and keeps its journal and
event loop alive through close. A cancelled waiter does not stop the service.
"""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Literal

from loushang.appserver.client import AppConnectionClosedError
from loushang.appserver.local_record import (
    LocalRecordError,
    LocalRecordErrorCodeV1,
    require_endpoint,
)

from ._files import ManagedStorageError, _check_deadline
from .child import _spawn
from .connection import ManagedConnectionLeaseV1, _settled_native
from .contracts import (
    ManagedHandoffPhaseV1,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from .lifecycle import ManagedServiceJournalV1, ManagedServiceStateV1
from .starter import ManagedLaunchRequestFactoryV1, ManagedServiceStarterV1


class ManagedServiceCoordinatorV1:
    """Own one generated operation ID and at most one native start attempt.

    Competing callers may converge on one instance. Once selected, replacement
    is refused; neither absent endpoints nor failed authentication starts another
    child. Only read/connection attempts and the original birth registration are
    retried. This is not durable historical operation deduplication or recovery.
    """

    def __init__(
        self, journal: ManagedServiceJournalV1, namespace: ManagedNamespaceV1,
        service: ManagedServiceKeyV1, *, runtime_root: str, endpoint: str,
        request_factory: ManagedLaunchRequestFactoryV1,
        temporary_override: str | None = None,
        trace_deadline_ms: int | None = None,
    ) -> None:
        require_endpoint(endpoint)
        self._starter = ManagedServiceStarterV1(
            journal, namespace, service, runtime_root=runtime_root, request_factory=request_factory,
            temporary_override=temporary_override,
            trace_deadline_ms=trace_deadline_ms,
        )
        self._journal, self._namespace, self._service = journal, namespace, service
        self._runtime_root, self._endpoint = runtime_root, endpoint
        self._trace_deadline_ms = trace_deadline_ms
        self._instance: ManagedInstanceRefV1 | None = None
        self._connection: ManagedConnectionLeaseV1 | None = None
        self._task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._deadline: float | None = None
        self._closing = self._ready = self._settled = False

    @property
    def operation_id(self) -> str:
        return self._starter._attempt

    @property
    def instance(self) -> ManagedInstanceRefV1 | None:
        return self._instance

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ManagedStorageError("conflict")

    def _check(self, deadline: float) -> None:
        _check_deadline(deadline)
        if self._closing:
            raise ManagedStorageError("closed")

    async def ensure_started(self, *, deadline: float) -> ManagedConnectionLeaseV1:
        """Start/reuse, then return a borrowed exact-instance connection lease.

        Rejoining this operation uses its original deadline, never a new budget.
        Closing the returned lease does not transfer ownership from this object.
        """
        self._bind_loop()
        self._check(deadline)
        if self._task is None:
            self._deadline = deadline
            self._task = _spawn(self._ensure_once(deadline))
        elif deadline != self._deadline:
            raise ManagedStorageError("conflict")
        await asyncio.shield(self._task)
        self._check(deadline)
        if not self._ready or self._connection is None:
            raise ManagedStorageError("unavailable")
        # A borrower may have explicitly closed its lease between joins.
        # Rejoining observes that closure; it never silently reconnects.
        _ = self._connection.client
        return self._connection

    async def _read(self, deadline: float) -> ManagedServiceStateV1 | None:
        while True:
            self._check(deadline)
            try:
                return await _settled_native(lambda: self._journal.read(deadline=deadline))
            except ManagedStorageError as error:
                if error.code != "busy":
                    raise
                await self._pause(deadline)

    async def observe_requested_trace(
        self, *, deadline: float,
    ) -> Literal["applied", "expired", "not_applied_reused_instance", "not_confirmed"]:
        """Read the exact startup fact; never install, restart or extend trace.

        Uses the original startup budget. Missing/late evidence is unknown,
        not proof of non-application. Applied describes a historical fact.
        """
        self._bind_loop()
        if self._trace_deadline_ms is None or not self._ready or self._instance is None or self._closing:
            raise ManagedStorageError("conflict")
        if self._deadline is None or deadline > self._deadline:
            raise ManagedStorageError("conflict")
        while True:
            try:
                state = await self._read(deadline)
            except ManagedStorageError as error:
                if error.code == "busy" and monotonic() >= deadline:
                    return "not_confirmed"
                raise
            if state is None or state.handoff.instance != self._instance:
                raise ManagedStorageError("conflict")
            if state.handoff.attempt_id != self.operation_id:
                return "not_applied_reused_instance"
            receipt = state.trace_application
            if receipt is not None:
                if receipt.deadline_ms != self._trace_deadline_ms:
                    raise ManagedStorageError("conflict")
                return "expired" if monotonic() * 1000 >= receipt.deadline_ms else "applied"
            if state.handoff.stop_requested or monotonic() * 1000 >= self._trace_deadline_ms:
                return "not_confirmed"
            if monotonic() >= deadline:
                return "not_confirmed"
            await asyncio.sleep(min(0.05, max(0, deadline - monotonic())))

    async def _pause(self, deadline: float) -> None:
        self._check(deadline)
        await asyncio.sleep(0.05)
        self._check(deadline)

    async def _ensure_once(self, deadline: float) -> None:
        state = await self._read(deadline)
        if state is None or state.cleanly_stopped:
            self._check(deadline)
            try:
                state = await _settled_native(lambda: self._starter.start(expected=state, deadline=deadline))
            except ManagedStorageError as error:
                if error.code not in {"busy", "conflict", "unavailable"}:
                    raise
                # Observe after unknown/CAS contention; never replay start.
                state = await self._read(deadline)
                if state is None or state.cleanly_stopped:
                    raise error
        assert state is not None
        self._instance = state.handoff.instance
        while True:
            self._check(deadline)
            if (state.handoff.instance != self._instance or state.handoff.stop_requested
                    or state.handoff.phase is ManagedHandoffPhaseV1.ABORTING or state.cleanly_stopped):
                raise ManagedStorageError("conflict")
            process = self._starter._process
            if (state.handoff.attempt_id == self.operation_id and state.native_identity is None
                    and process is not None and process.identity is not None):
                try:
                    state = await _settled_native(lambda: self._starter.register_birth(deadline=deadline))
                except ManagedStorageError as error:
                    if error.code != "busy":
                        raise
            if state.handoff.phase is ManagedHandoffPhaseV1.COMMITTED:
                self._connection = ManagedConnectionLeaseV1(
                    self._journal, self._namespace, self._service, self._instance,
                    runtime_root=self._runtime_root, endpoint=self._endpoint,
                )
                try:
                    await self._connection.prepare(deadline=deadline)
                except (LocalRecordError, ConnectionRefusedError, AppConnectionClosedError, ManagedStorageError) as error:
                    if isinstance(error, LocalRecordError) and error.code is not LocalRecordErrorCodeV1.NOT_FOUND:
                        raise
                    if isinstance(error, ManagedStorageError) and error.code != "busy":
                        raise
                    # Read-only readiness retry, only after original cleanup.
                    await self._connection.close()
                    self._connection = None
                else:
                    self._check(deadline)
                    self._ready = True
                    return
            await self._pause(deadline)
            current = await self._read(deadline)
            if current is None:
                raise ManagedStorageError("unavailable")
            state = current

    def fence(self) -> None:
        """Prevent further startup/reuse work without closing borrowed delivery."""
        self._bind_loop()
        self._closing = True
        self._ready = False
        self._starter.fence()

    async def close(self) -> None:
        self.fence()
        task = self._close_task
        if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
            task = self._close_task = _spawn(self._close_once())
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        errors: list[BaseException] = []
        if self._connection is not None:
            try:
                await self._connection.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._connection = None
        try:
            await _settled_native(self._starter.close)
        except BaseException as error:
            errors.append(error)
        if errors:
            raise errors[0]
        self._settled = True


__all__ = ["ManagedServiceCoordinatorV1"]

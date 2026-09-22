"""Owned all-or-nothing AppService recovery for G13."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field, replace
from typing import TypeVar

from loushang.appserver.managed_mux_close import ManagedMuxClosePhaseV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionIdentityV1,
    SessionOpenSpecV1,
)

from .continuity import (
    APPLICATION_CONTINUITY_VERSION,
    MANAGED_CLOSE_CONTINUITY_VERSION,
    MANAGED_CONTINUITY_VERSION,
    ApplicationContinuityLeaseV1,
    ApplicationContinuityRecordV1,
    require_application_id,
    require_owner_epoch,
)
from .discovery_ports import HostedSessionDiscoveryBindingV1, require_discovery_context
from .execution_service import HostedExecutionServiceBindingV1
from .managed_mux import ManagedMuxServiceBindingV1
from .managed_mux_close import ManagedMuxCloseRecoveryAdmissionV1, ManagedMuxCloseUseV1
from .ports import HostedSessionPortV1, HostedSessionResolverV1
from .runtime import (
    _CONTINUITY_TOKEN,
    AppServiceV1,
    _SessionOwner,
    _start_continuity_io,
)


@dataclass(frozen=True, slots=True)
class AppServiceRecoveryRequestV1:
    """Complete Product-neutral input for one owned recovery attempt."""

    product_id: str
    resolver: HostedSessionResolverV1 = field(repr=False)
    continuity_lease: ApplicationContinuityLeaseV1 = field(repr=False)
    id_factory: Callable[[], str] | None = field(default=None, repr=False)
    close_timeout_seconds: float = 10.0
    discovery: HostedSessionDiscoveryBindingV1 | None = field(default=None, repr=False)
    execution: HostedExecutionServiceBindingV1 | None = field(default=None, repr=False)
    managed_mux: ManagedMuxServiceBindingV1 | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        require_discovery_context(self.discovery, self.product_id)
        if self.managed_mux is not None and (
            type(self.managed_mux) is not ManagedMuxServiceBindingV1
            or self.managed_mux.application_id != self.continuity_lease.application_id
        ):
            raise ValueError("invalid managed Mux recovery activation")
        if self.execution is not None and (
            type(self.execution) is not HostedExecutionServiceBindingV1
            or self.execution.application_id != self.continuity_lease.application_id
        ):
            raise ValueError("invalid execution recovery activation")
        if type(self.product_id) is not str or not self.product_id:
            raise ValueError("invalid recovery Product identity")
        if not inspect.iscoroutinefunction(
            inspect.getattr_static(type(self.resolver), "open_session", None)
        ):
            raise TypeError("invalid recovery Session resolver")
        for name in ("load", "commit", "delete", "close"):
            if not inspect.iscoroutinefunction(
                inspect.getattr_static(type(self.continuity_lease), name, None)
            ):
                raise TypeError("invalid continuity recovery lease")
        application_id = self.continuity_lease.application_id
        owner_epoch = self.continuity_lease.owner_epoch
        try:
            require_application_id(application_id)
            require_owner_epoch(owner_epoch)
        except (TypeError, ValueError):
            raise ValueError("invalid continuity recovery lease identity") from None
        if self.id_factory is not None and not callable(self.id_factory):
            raise TypeError("invalid recovery ID factory")
        if (
            isinstance(self.close_timeout_seconds, bool)
            or not isinstance(self.close_timeout_seconds, (int, float))
            or not 0 < self.close_timeout_seconds <= 60
        ):
            raise ValueError("invalid recovery close timeout")


@dataclass(slots=True)
class _CloseRecoveryState:
    """Data retained by the original attempt, never an independent runtime."""

    original: ApplicationContinuityRecordV1 | None
    sessions: dict[str, _SessionOwner] = field(default_factory=dict)
    admission: ManagedMuxCloseRecoveryAdmissionV1 | None = None
    confirmed: ApplicationContinuityRecordV1 | None = None
    uncertain: bool = False


class AppServiceRecoveryAttemptV1:
    """Published owner for every Session adopted before recovery publication."""

    __slots__ = (
        "_cleanup_debt",
        "_closed",
        "_close_task",
        "_close_recovery",
        "_control_lock",
        "_open_task",
        "_request",
        "_service",
        "_transferred",
    )

    def __init__(self, request: AppServiceRecoveryRequestV1) -> None:
        if type(request) is not AppServiceRecoveryRequestV1:
            raise TypeError("invalid AppService recovery request")
        self._request = request
        self._control_lock = asyncio.Lock()
        self._open_task: asyncio.Task[AppServiceV1] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._close_recovery: _CloseRecoveryState | None = None
        self._service: AppServiceV1 | None = None
        self._cleanup_debt: list[_SessionOwner | _RawSessionOwner] = []
        self._transferred = False
        self._closed = False

    @property
    def cleanup_pending(self) -> bool:
        recovery = self._close_recovery
        return bool(self._cleanup_debt) or (
            self._service is not None and not self._transferred
        ) or (self._open_task is not None and not self._open_task.done()) or (
            recovery is not None and (recovery.uncertain or recovery.admission is not None)
        )

    async def open(self) -> AppServiceV1:
        async with self._control_lock:
            if self._closed:
                raise _error(AppErrorCodeV1.SERVICE_CLOSED)
            if self._service is not None:
                self._transferred = True
                return self._service
            task = self._open_task
            if task is None or (
                task.done() and (task.cancelled() or task.exception() is not None)
            ):
                task = _start_continuity_io(self._open_once)
                task.add_done_callback(_observe_background_result)
                self._open_task = task
        service = await _join_owned(task)
        async with self._control_lock:
            rejected = self._closed
            if not rejected:
                self._transferred = True
        if rejected:
            await self.close()
            raise _error(AppErrorCodeV1.SERVICE_CLOSED)
        return service

    async def close(self) -> None:
        async with self._control_lock:
            self._closed = True
            task = self._close_task
            if task is None or (
                task.done() and (task.cancelled() or task.exception() is not None)
            ):
                task = _start_continuity_io(self._close_once)
                task.add_done_callback(_observe_background_result)
                self._close_task = task
        await _join_owned(task)

    async def _close_once(self) -> None:
        task = self._open_task
        if task is not None:
            with suppress(BaseException):
                await _join_owned(task)
        if self._service is not None and not self._transferred:
            try:
                await self._service.close()
            except BaseException:
                raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE) from None
            self._service = None
        await self._settle_cleanup_debt()
        if self._close_recovery is not None and self._close_recovery.uncertain:
            raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE)

    async def _open_once(self) -> AppServiceV1:
        await self._settle_cleanup_debt()
        if self._close_recovery is not None and self._close_recovery.uncertain:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        try:
            record = await self._request.continuity_lease.load()
        except BaseException:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
        if record is not None and type(record) is not ApplicationContinuityRecordV1:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        if record is not None and (
            record.application_id != self._request.continuity_lease.application_id
        ):
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        if record is not None and record.product_id != self._request.product_id:
            raise _error(AppErrorCodeV1.PRODUCT_MISMATCH)
        state = self._close_recovery
        if state is not None and record != (state.confirmed or state.original):
            raise _error(AppErrorCodeV1.REVISION_CONFLICT)
        managed = self._request.managed_mux
        versions: tuple[str, ...] = (MANAGED_CONTINUITY_VERSION,)
        if managed is not None and managed.closing is not None and managed.closing.recovery is not None:
            versions = (*versions, MANAGED_CLOSE_CONTINUITY_VERSION)
        if record is not None and (
            (managed is None and record.contract_version != APPLICATION_CONTINUITY_VERSION)
            or (managed is not None and (
                record.contract_version not in versions
                or record.managed_service_id != managed.service_id
            ))
        ):
            # Reject profile/owner mismatch before opening any retained Session.
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)

        sessions: dict[str, _SessionOwner] = {}
        try:
            if managed is not None and managed.closing is not None and managed.closing.recovery is not None:
                record = await self._recover_managed_closes(record)
            if record is not None:
                for mux in record.mux_spaces:
                    for member in mux.members:
                        owner = await self._recover_session(
                            member.session, member.title
                        )
                        if owner.identity != member.session:
                            self._retain_cleanup((owner,))
                            raise _error(AppErrorCodeV1.PRODUCT_MISMATCH)
                        sessions[owner.identity.session_id] = owner
            service = AppServiceV1(
                product_id=self._request.product_id,
                resolver=self._request.resolver,
                id_factory=self._request.id_factory,
                close_timeout_seconds=self._request.close_timeout_seconds,
                discovery=self._request.discovery,
                execution=self._request.execution,
                managed_mux=self._request.managed_mux,
            )
            service._adopt_continuity_state(
                lease=self._request.continuity_lease,
                record=record,
                sessions=sessions,
                _token=_CONTINUITY_TOKEN,
            )
            sessions.clear()
            # Own the successful result before cancellation reaches any waiter.
            self._service = service
            return service
        except BaseException as error:
            self._retain_cleanup(tuple(reversed(tuple(sessions.values()))))
            try:
                await self._settle_cleanup_debt()
            except AppServiceError:
                raise
            if isinstance(error, AppServiceError):
                raise
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE) from None

    async def _recover_managed_closes(
        self, record: ApplicationContinuityRecordV1 | None,
    ) -> ApplicationContinuityRecordV1 | None:
        state = self._close_recovery
        if state is None:
            state = _CloseRecoveryState(record)
            self._close_recovery = state
        if record != (state.confirmed or state.original):
            raise _error(AppErrorCodeV1.REVISION_CONFLICT)
        async with self._recovery_permission(state.original, ManagedMuxCloseUseV1.ADMIT):
            pass
        if record is None:
            return None
        if state.confirmed is not None:
            return state.confirmed
        pending = {item.mux_space_id for item in record.managed_closures
                   if item.phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING}
        if not pending:
            state.confirmed = record
            return record
        for mux in record.mux_spaces:
            if mux.mux_space_id not in pending:
                continue
            for member in mux.members:
                if member.session.session_id in state.sessions:
                    continue
                owner = await self._recover_session(member.session, member.title)
                self._retain_cleanup((owner,))
                if owner.identity != member.session:
                    raise _error(AppErrorCodeV1.PRODUCT_MISMATCH)
                state.sessions[owner.identity.session_id] = owner
        await self._settle_cleanup_debt()
        settled = replace(
            record, record_revision=record.record_revision + 1,
            mux_spaces=tuple(mux for mux in record.mux_spaces if mux.mux_space_id not in pending),
            managed_closures=tuple(replace(item, phase=ManagedMuxClosePhaseV1.CLOSED)
                                   for item in record.managed_closures),
        )
        async with self._recovery_permission(record, ManagedMuxCloseUseV1.SETTLE):
            try:
                await self._request.continuity_lease.commit(
                    expected_revision=record.record_revision, record=settled,
                )
            except BaseException:
                state.uncertain = True
                raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
            # Save confirmed outcome before release can fail, never repeat CAS.
            state.confirmed = settled
        return settled

    @asynccontextmanager
    async def _recovery_permission(
        self, record: ApplicationContinuityRecordV1 | None, use: ManagedMuxCloseUseV1,
    ) -> AsyncIterator[None]:
        managed, state = self._request.managed_mux, self._close_recovery
        if (managed is None or managed.closing is None or managed.closing.recovery is None
                or state is None or state.admission is not None):
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        try:
            owner = managed.closing.recovery.prepare(record, use)
            state.admission = owner
            await owner.acquire()
            owner.check_record(record)
            yield
        except AppServiceError:
            raise
        except BaseException:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
        finally:
            await self._release_recovery_admission()

    async def _release_recovery_admission(self) -> None:
        state = self._close_recovery
        if state is None or state.admission is None:
            return
        try:
            await state.admission.close()
        except BaseException:
            raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE) from None
        state.admission = None

    async def _recover_session(
        self,
        identity: SessionIdentityV1,
        title: str,
    ) -> _SessionOwner:
        request = SessionOpenSpecV1(
            product_id=identity.product_id,
            continuity_id=identity.continuity_id,
            scope=identity.scope,
            scope_fingerprint=identity.scope_fingerprint,
            title=title,
            session_id=identity.session_id,
        )
        try:
            port = await self._request.resolver.open_session(request)
        except BaseException:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE) from None
        try:
            return _SessionOwner(port)
        except BaseException:
            self._retain_cleanup((_RawSessionOwner(port),))
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE) from None

    def _retain_cleanup(
        self,
        owners: tuple[_SessionOwner | _RawSessionOwner, ...],
    ) -> None:
        for owner in owners:
            if not any(retained is owner for retained in self._cleanup_debt):
                self._cleanup_debt.append(owner)

    async def _settle_cleanup_debt(self) -> None:
        await self._release_recovery_admission()
        if not self._cleanup_debt:
            return
        owners = tuple(self._cleanup_debt)
        results = await asyncio.gather(
            *(
                asyncio.wait_for(
                    owner.close(),
                    timeout=self._request.close_timeout_seconds,
                )
                for owner in owners
            ),
            return_exceptions=True,
        )
        completed = {
            id(owner)
            for owner, result in zip(owners, results, strict=True)
            if not isinstance(result, BaseException)
        }
        self._cleanup_debt = [
            owner for owner in self._cleanup_debt if id(owner) not in completed
        ]
        if self._cleanup_debt:
            raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE)


class _RawSessionOwner:
    """Retryable last-resort owner when Session adaptation cannot complete."""

    __slots__ = ("_close_lock", "_close_task", "_port", "_settled")

    def __init__(self, port: HostedSessionPortV1) -> None:
        self._port = port
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._settled = False

    async def close(self) -> None:
        async with self._close_lock:
            if self._settled:
                return
            task = self._close_task
            if task is None:
                close = getattr(self._port, "close", None)
                if not inspect.iscoroutinefunction(close):
                    raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE)
                task = asyncio.create_task(close())
                task.add_done_callback(_observe_background_result)
                self._close_task = task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except BaseException:
            async with self._close_lock:
                if self._close_task is task:
                    self._close_task = None
            raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE) from None
        async with self._close_lock:
            if self._close_task is task:
                self._close_task = None
                self._settled = True


def create_appservice_recovery_attempt(
    request: AppServiceRecoveryRequestV1,
) -> AppServiceRecoveryAttemptV1:
    """Publish the G13 attempt owner before any recovery effect."""

    return AppServiceRecoveryAttemptV1(request)


_OwnedResult = TypeVar("_OwnedResult")


async def _join_owned(task: asyncio.Task[_OwnedResult]) -> _OwnedResult:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if caller is None or caller.cancelling() == 0:
                break
            cancellation = error
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


def _observe_background_result(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


def _error(code: AppErrorCodeV1) -> AppServiceError:
    return AppServiceError(code)


__all__ = [
    "AppServiceRecoveryAttemptV1",
    "AppServiceRecoveryRequestV1",
    "create_appservice_recovery_attempt",
]

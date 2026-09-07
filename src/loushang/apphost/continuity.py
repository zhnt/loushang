"""Optional AppHost lifecycle owner for G13 durable application continuity."""

from __future__ import annotations

import asyncio
import inspect
import re
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from loushang.appserver.client import AppClientV1
from loushang.appservice import (
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityLeaseV1,
    ApplicationContinuityStoreV1,
    AppServiceRecoveryAttemptV1,
    AppServiceRecoveryRequestV1,
    AppServiceV1,
    create_appservice_recovery_attempt,
)

from .application import (
    HostedApplicationError,
    HostedApplicationRequestV1,
    HostedApplicationRuntimeV1,
    HostedApplicationShutdownReportV1,
    _adopt_recovered_appservice,
    _create_unpublished_hosted_application_runtime,
)

if TYPE_CHECKING:
    from loushang.appservice.client_scope import AppClientScopeV1

HOSTED_APPLICATION_CONTINUITY_CONTRACT_VERSION = (
    "loushang.apphost.application-continuity/v1"
)

_STABLE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")
_RUNTIME_TOKEN = object()


class HostedApplicationContinuityPhase(str, Enum):
    """Lease-last G13 settlement phases outside the G12 application owner."""

    APPLICATION = "application"
    RECORD = "record"
    LEASE = "lease"


class _SettlementIntent(str, Enum):
    RETAIN = "retain"
    RETIRE = "retire"


@dataclass(frozen=True, slots=True)
class HostedApplicationContinuityActivationV1:
    """Exact trusted-composition activation for durable coordination."""

    contract_version: str = HOSTED_APPLICATION_CONTINUITY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != HOSTED_APPLICATION_CONTINUITY_CONTRACT_VERSION:
            raise ValueError("unsupported hosted application continuity activation")


@dataclass(frozen=True, slots=True)
class HostedApplicationContinuityRequestV1:
    """Complete Product-neutral input whose owners transfer to one attempt."""

    activation: HostedApplicationContinuityActivationV1
    application: HostedApplicationRequestV1
    application_id: str
    owner_epoch: str
    store: ApplicationContinuityStoreV1 | None = field(default=None, repr=False)
    continuity_lease: ApplicationContinuityLeaseV1 | None = field(
        default=None,
        repr=False,
    )
    phase_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if type(self.activation) is not HostedApplicationContinuityActivationV1:
            raise TypeError("hosted continuity requires explicit activation")
        if type(self.application) is not HostedApplicationRequestV1:
            raise TypeError("invalid hosted continuity application request")
        if _STABLE_ID.fullmatch(self.application_id) is None:
            raise ValueError("invalid hosted continuity application identity")
        if _OPAQUE_TOKEN.fullmatch(self.owner_epoch) is None:
            raise ValueError("invalid hosted continuity owner epoch")
        if (self.store is None) == (self.continuity_lease is None):
            raise TypeError("hosted continuity requires exactly one acquisition owner")
        if self.store is not None:
            for name in ("acquire", "list_applications"):
                if not inspect.iscoroutinefunction(
                    inspect.getattr_static(type(self.store), name, None)
                ):
                    raise TypeError("invalid hosted continuity store")
        if self.continuity_lease is not None:
            for name in ("load", "commit", "delete", "close"):
                if not inspect.iscoroutinefunction(
                    inspect.getattr_static(type(self.continuity_lease), name, None)
                ):
                    raise TypeError("invalid hosted continuity lease")
            if (
                self.continuity_lease.application_id != self.application_id
                or self.continuity_lease.owner_epoch != self.owner_epoch
            ):
                raise ValueError("hosted continuity lease identity mismatch")
        if (
            isinstance(self.phase_timeout_seconds, bool)
            or not isinstance(self.phase_timeout_seconds, (int, float))
            or not 0 < self.phase_timeout_seconds <= 60
        ):
            raise ValueError("invalid hosted continuity timeout")


@dataclass(frozen=True, slots=True)
class HostedApplicationContinuityShutdownReportV1:
    """Bounded G13 settlement facts with the complete nested G12 report."""

    completed: bool
    retired: bool
    timed_out_phases: tuple[HostedApplicationContinuityPhase, ...]
    failed_phases: tuple[HostedApplicationContinuityPhase, ...]
    application_shutdown: HostedApplicationShutdownReportV1 | None
    record_retired: bool
    lease_released: bool
    contract_version: str = HOSTED_APPLICATION_CONTINUITY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for value in (
            self.completed,
            self.retired,
            self.record_retired,
            self.lease_released,
        ):
            if type(value) is not bool:
                raise TypeError("invalid hosted continuity shutdown report")
        if self.contract_version != HOSTED_APPLICATION_CONTINUITY_CONTRACT_VERSION:
            raise ValueError("unsupported hosted continuity shutdown report")
        for phases in (self.timed_out_phases, self.failed_phases):
            if (
                not isinstance(phases, tuple)
                or any(
                    type(item) is not HostedApplicationContinuityPhase
                    for item in phases
                )
                or len(phases) != len(set(phases))
            ):
                raise ValueError("invalid hosted continuity shutdown phases")
        if set(self.timed_out_phases).intersection(self.failed_phases):
            raise ValueError("duplicate hosted continuity shutdown phase")
        if (
            self.application_shutdown is not None
            and type(self.application_shutdown) is not HostedApplicationShutdownReportV1
        ):
            raise TypeError("invalid hosted continuity application report")
        if self.record_retired and not self.retired:
            raise ValueError("retained continuity report deleted its record")
        expected = (
            not self.timed_out_phases
            and not self.failed_phases
            and self.application_shutdown is not None
            and self.application_shutdown.completed
            and self.lease_released
            and (not self.retired or self.record_retired)
        )
        if self.completed != expected:
            raise ValueError("inconsistent hosted continuity shutdown report")


class HostedApplicationContinuityRuntimeV1:
    """Own one recovered G12 application and release its lease last."""

    __slots__ = (
        "_application",
        "_control_lock",
        "_intent",
        "_lease",
        "_lease_released",
        "_phase_tasks",
        "_phase_timeout_seconds",
        "_record_retired",
        "_settlement_task",
    )

    def __init__(
        self,
        application: HostedApplicationRuntimeV1,
        lease: ApplicationContinuityLeaseV1,
        *,
        phase_timeout_seconds: float,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _RUNTIME_TOKEN:
            raise TypeError("hosted continuity runtime requires its attempt")
        self._application = application
        self._lease = lease
        self._phase_timeout_seconds = phase_timeout_seconds
        self._control_lock = asyncio.Lock()
        self._intent: _SettlementIntent | None = None
        self._settlement_task: (
            asyncio.Task[HostedApplicationContinuityShutdownReportV1] | None
        ) = None
        self._phase_tasks: dict[
            HostedApplicationContinuityPhase, asyncio.Task[object]
        ] = {}
        self._record_retired = False
        self._lease_released = False

    @property
    def application_id(self) -> str:
        return self._lease.application_id

    @property
    def product_id(self) -> str:
        return self._application.product_id

    @property
    def generation_id(self) -> str:
        return self._application.generation_id

    @property
    def client(self) -> AppClientV1:
        return self._application.client

    def enable_client_scopes(self) -> None:
        """Opt in only after this recovered runtime is published by its attempt."""
        if not self.accepting:
            raise HostedApplicationError("hosted_application_not_ready")
        self._application.enable_client_scopes()

    def open_client_scope(self) -> AppClientScopeV1:
        if not self.accepting:
            raise HostedApplicationError("hosted_application_not_ready")
        return self._application.open_client_scope()

    def fence_client_scopes(self) -> None:
        self._application.fence_client_scopes()

    @property
    def accepting(self) -> bool:
        return self._intent is None and self._application.accepting

    @property
    def continuity_revision(self) -> int | None:
        return self._application.continuity_revision

    async def shutdown(self) -> HostedApplicationContinuityShutdownReportV1:
        """Retain desired state, settle live owners, then release the lease."""

        return await self._settle(_SettlementIntent.RETAIN)

    async def retire(self) -> HostedApplicationContinuityShutdownReportV1:
        """Settle live owners, CAS-delete desired state, then release the lease."""

        return await self._settle(_SettlementIntent.RETIRE)

    async def close(self) -> None:
        report = await self.shutdown()
        if not report.completed:
            raise HostedApplicationError("hosted_continuity_cleanup_incomplete")

    async def _settle(
        self,
        intent: _SettlementIntent,
    ) -> HostedApplicationContinuityShutdownReportV1:
        async with self._control_lock:
            if self._intent is not None and self._intent is not intent:
                raise HostedApplicationError("hosted_continuity_intent_conflict")
            self._intent = intent
            task = self._settlement_task
            if task is None or _report_task_needs_retry(task):
                task = asyncio.create_task(self._settle_once(intent))
                task.add_done_callback(_observe_background_result)
                self._settlement_task = task
        return await _join_report(task)

    async def _settle_once(
        self,
        intent: _SettlementIntent,
    ) -> HostedApplicationContinuityShutdownReportV1:
        timed_out: list[HostedApplicationContinuityPhase] = []
        failed: list[HostedApplicationContinuityPhase] = []
        try:
            application = await self._application.shutdown()
        except asyncio.CancelledError:
            raise
        except BaseException:
            application = None
            failed.append(HostedApplicationContinuityPhase.APPLICATION)
        if application is not None and not application.completed:
            target = timed_out if application.timed_out_phases else failed
            target.append(HostedApplicationContinuityPhase.APPLICATION)
        if application is None or not application.completed:
            return _report(intent, timed_out, failed, application, False, False)

        if intent is _SettlementIntent.RETIRE and not self._record_retired:
            revision = self._application.continuity_revision
            if revision is None:
                self._record_retired = True
            else:
                result = await self._run_phase(
                    HostedApplicationContinuityPhase.RECORD,
                    lambda: self._lease.delete(expected_revision=revision),
                )
                if result == "timed_out":
                    timed_out.append(HostedApplicationContinuityPhase.RECORD)
                elif result == "failed":
                    failed.append(HostedApplicationContinuityPhase.RECORD)
                else:
                    self._record_retired = True
            if not self._record_retired:
                return _report(intent, timed_out, failed, application, False, False)

        if not self._lease_released:
            result = await self._run_phase(
                HostedApplicationContinuityPhase.LEASE,
                self._lease.close,
            )
            if result == "timed_out":
                timed_out.append(HostedApplicationContinuityPhase.LEASE)
            elif result == "failed":
                failed.append(HostedApplicationContinuityPhase.LEASE)
            else:
                self._lease_released = True
        return _report(
            intent,
            timed_out,
            failed,
            application,
            self._record_retired,
            self._lease_released,
        )

    async def _run_phase(
        self,
        phase: HostedApplicationContinuityPhase,
        callback: object,
    ) -> str:
        task = self._phase_tasks.get(phase)
        if task is None or _void_task_needs_retry(task):
            task = asyncio.create_task(callback())  # type: ignore[operator]
            task.add_done_callback(_observe_background_result)
            self._phase_tasks[phase] = task
        try:
            async with asyncio.timeout(self._phase_timeout_seconds):
                await asyncio.shield(task)
        except TimeoutError:
            return "timed_out"
        except asyncio.CancelledError:
            raise
        except BaseException:
            return "failed"
        return "completed"


class HostedApplicationContinuityAttemptV1:
    """Published owner for G12 dependencies, recovery debt, and the G13 lease."""

    __slots__ = (
        "_application",
        "_close_lock",
        "_close_task",
        "_closed",
        "_lease",
        "_open_lock",
        "_open_task",
        "_recovered_service",
        "_recovery",
        "_request",
        "_runtime",
        "_service_adopted",
        "_settled",
        "_transferred",
    )

    def __init__(self, request: HostedApplicationContinuityRequestV1) -> None:
        if type(request) is not HostedApplicationContinuityRequestV1:
            raise TypeError("invalid hosted application continuity request")
        self._request = request
        self._application = _create_unpublished_hosted_application_runtime(
            request.application
        )
        self._lease = request.continuity_lease
        self._recovery: AppServiceRecoveryAttemptV1 | None = None
        self._recovered_service: AppServiceV1 | None = None
        self._runtime: HostedApplicationContinuityRuntimeV1 | None = None
        self._open_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._open_task: asyncio.Task[HostedApplicationContinuityRuntimeV1] | None = (
            None
        )
        self._close_task: asyncio.Task[None] | None = None
        self._service_adopted = False
        self._transferred = False
        self._closed = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._transferred and not self._settled

    async def open(self) -> HostedApplicationContinuityRuntimeV1:
        async with self._open_lock:
            if self._closed:
                raise HostedApplicationError("hosted_continuity_attempt_closed")
            if self._runtime is not None:
                self._transferred = True
                return self._runtime
            task = self._open_task
            if task is None or _runtime_task_needs_retry(task):
                task = asyncio.create_task(self._open_once())
                task.add_done_callback(_observe_background_result)
                self._open_task = task
        runtime = await _join_runtime(task)
        async with self._open_lock:
            rejected = self._closed
            if not rejected:
                self._runtime = runtime
                self._transferred = True
        if rejected:
            await self.close()
            raise HostedApplicationError("hosted_continuity_attempt_closed")
        return runtime

    async def close(self) -> None:
        async with self._close_lock:
            if self._settled or self._transferred:
                return
            self._closed = True
            task = self._close_task
            if task is None or _void_task_needs_retry(task):
                task = asyncio.create_task(self._close_once())
                task.add_done_callback(_observe_background_result)
                self._close_task = task
        await _join_void(task)

    async def _open_once(self) -> HostedApplicationContinuityRuntimeV1:
        if self._lease is None:
            store = self._request.store
            if store is None:
                raise HostedApplicationError("hosted_continuity_unavailable")
            try:
                self._lease = await store.acquire(
                    application_id=self._request.application_id,
                    owner_epoch=self._request.owner_epoch,
                )
            except ApplicationContinuityError as error:
                code = (
                    "hosted_continuity_locked"
                    if error.code is ApplicationContinuityErrorCodeV1.LOCKED
                    else "hosted_continuity_unavailable"
                )
                raise HostedApplicationError(code) from None
            except BaseException:
                raise HostedApplicationError("hosted_continuity_unavailable") from None
        if self._recovery is None:
            self._recovery = create_appservice_recovery_attempt(
                AppServiceRecoveryRequestV1(
                    product_id=self._request.application.product_id,
                    resolver=self._request.application.resolver,
                    continuity_lease=self._lease,
                    id_factory=self._request.application.service_id_factory,
                    close_timeout_seconds=(
                        self._request.application.service_close_timeout_seconds
                    ),
                )
            )
        service = await self._recovery.open()
        self._recovered_service = service
        _adopt_recovered_appservice(self._application, service)
        self._service_adopted = True
        runtime = HostedApplicationContinuityRuntimeV1(
            self._application,
            self._lease,
            phase_timeout_seconds=self._request.phase_timeout_seconds,
            _construction_token=_RUNTIME_TOKEN,
        )
        self._runtime = runtime
        return runtime

    async def _close_once(self) -> None:
        open_task = self._open_task
        if open_task is not None and not open_task.done():
            with suppress(BaseException):
                await _join_runtime(open_task)
        if self._transferred:
            return
        runtime = self._runtime
        if runtime is not None:
            report = await runtime.shutdown()
            if not report.completed:
                raise HostedApplicationError("hosted_continuity_cleanup_incomplete")
            self._settled = True
            return
        recovery = self._recovery
        if recovery is not None:
            try:
                await recovery.close()
            except BaseException:
                raise HostedApplicationError(
                    "hosted_continuity_cleanup_incomplete"
                ) from None
        if self._recovered_service is not None and not self._service_adopted:
            try:
                await self._recovered_service.close()
            except BaseException:
                raise HostedApplicationError(
                    "hosted_continuity_cleanup_incomplete"
                ) from None
            self._recovered_service = None
        application = await self._application.shutdown()
        if not application.completed:
            raise HostedApplicationError("hosted_continuity_cleanup_incomplete")
        if self._lease is not None:
            try:
                await self._lease.close()
            except BaseException:
                raise HostedApplicationError(
                    "hosted_continuity_cleanup_incomplete"
                ) from None
        self._settled = True


def create_hosted_application_continuity_attempt(
    request: HostedApplicationContinuityRequestV1,
) -> HostedApplicationContinuityAttemptV1:
    """Publish the sole G13 attempt owner before acquiring its lease."""

    return HostedApplicationContinuityAttemptV1(request)


def _report(
    intent: _SettlementIntent,
    timed_out: list[HostedApplicationContinuityPhase],
    failed: list[HostedApplicationContinuityPhase],
    application: HostedApplicationShutdownReportV1 | None,
    record_retired: bool,
    lease_released: bool,
) -> HostedApplicationContinuityShutdownReportV1:
    retired = intent is _SettlementIntent.RETIRE
    return HostedApplicationContinuityShutdownReportV1(
        completed=(
            not timed_out
            and not failed
            and application is not None
            and application.completed
            and lease_released
            and (not retired or record_retired)
        ),
        retired=retired,
        timed_out_phases=tuple(timed_out),
        failed_phases=tuple(failed),
        application_shutdown=application,
        record_retired=record_retired if retired else False,
        lease_released=lease_released,
    )


async def _join_report(
    task: asyncio.Task[HostedApplicationContinuityShutdownReportV1],
) -> HostedApplicationContinuityShutdownReportV1:
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


async def _join_runtime(
    task: asyncio.Task[HostedApplicationContinuityRuntimeV1],
) -> HostedApplicationContinuityRuntimeV1:
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


async def _join_void(task: asyncio.Task[None]) -> None:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if caller is None or caller.cancelling() == 0:
                break
            cancellation = error
    task.result()
    if cancellation is not None:
        raise cancellation


def _report_task_needs_retry(
    task: asyncio.Task[HostedApplicationContinuityShutdownReportV1],
) -> bool:
    return task.done() and (
        task.cancelled() or task.exception() is not None or not task.result().completed
    )


def _runtime_task_needs_retry(
    task: asyncio.Task[HostedApplicationContinuityRuntimeV1],
) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _void_task_needs_retry(task: asyncio.Task[object]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _observe_background_result(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = [
    "HOSTED_APPLICATION_CONTINUITY_CONTRACT_VERSION",
    "HostedApplicationContinuityActivationV1",
    "HostedApplicationContinuityAttemptV1",
    "HostedApplicationContinuityPhase",
    "HostedApplicationContinuityRequestV1",
    "HostedApplicationContinuityRuntimeV1",
    "HostedApplicationContinuityShutdownReportV1",
    "create_hosted_application_continuity_attempt",
]

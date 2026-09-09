"""Coding-owned current-generation composition for G13 hosted continuity."""

from __future__ import annotations

import asyncio
import inspect
import re
from contextlib import suppress
from dataclasses import dataclass, field

from loushang.apphost import AppHostCatalogInputV1, AppHostCatalogV1, AppHostRuntimeV1
from loushang.apphost.application import HostedApplicationError
from loushang.apphost.continuity import (
    HostedApplicationContinuityActivationV1,
    HostedApplicationContinuityAttemptV1,
    HostedApplicationContinuityRequestV1,
    HostedApplicationContinuityRuntimeV1,
    create_hosted_application_continuity_attempt,
)
from loushang.appservice import (
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityLeaseV1,
    ApplicationContinuityStoreV1,
)

from .hosted_application import (
    CodingAppHostHostedSessionResolverV1,
    CodingForegroundHostedApplicationRequestV1,
    CodingForegroundProductFactoryV1,
    _coding_hosted_application_request,
    _coding_hosted_registrations,
    _settle_failed_construction,
)

_STABLE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")


@dataclass(frozen=True, slots=True)
class CodingHostedContinuityRequestV1:
    """Exact G13 opt-in layered over the unchanged G12 Coding request."""

    activation: HostedApplicationContinuityActivationV1
    foreground: CodingForegroundHostedApplicationRequestV1
    application_id: str
    owner_epoch: str
    store: ApplicationContinuityStoreV1 = field(repr=False)
    phase_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if type(self.activation) is not HostedApplicationContinuityActivationV1:
            raise TypeError("Coding hosted continuity requires explicit activation")
        if type(self.foreground) is not CodingForegroundHostedApplicationRequestV1:
            raise TypeError("invalid Coding foreground application request")
        if _STABLE_ID.fullmatch(self.application_id) is None:
            raise ValueError("invalid Coding hosted continuity application identity")
        if _OPAQUE_TOKEN.fullmatch(self.owner_epoch) is None:
            raise ValueError("invalid Coding hosted continuity owner epoch")
        for name in ("acquire", "list_applications"):
            if not inspect.iscoroutinefunction(
                inspect.getattr_static(type(self.store), name, None)
            ):
                raise TypeError("invalid Coding hosted continuity store")
        if (
            isinstance(self.phase_timeout_seconds, bool)
            or not isinstance(self.phase_timeout_seconds, (int, float))
            or not 0 < self.phase_timeout_seconds <= 60
        ):
            raise ValueError("invalid Coding hosted continuity timeout")


class CodingHostedContinuityAttemptV1:
    """Published owner before Coding catalog admission or continuity acquisition."""

    __slots__ = (
        "_catalog",
        "_close_lock",
        "_close_task",
        "_closed",
        "_continuity",
        "_continuity_runtime",
        "_lease",
        "_open_lock",
        "_open_task",
        "_product_factory",
        "_request",
        "_runtime",
        "_settled",
        "_transferred",
    )

    def __init__(self, request: CodingHostedContinuityRequestV1) -> None:
        if type(request) is not CodingHostedContinuityRequestV1:
            raise TypeError("invalid Coding hosted continuity request")
        self._request = request
        self._product_factory = CodingForegroundProductFactoryV1(
            request.foreground.session_factory
        )
        self._catalog: AppHostCatalogV1 | None = None
        self._runtime: AppHostRuntimeV1 | None = None
        self._lease: ApplicationContinuityLeaseV1 | None = None
        self._continuity: HostedApplicationContinuityAttemptV1 | None = None
        self._continuity_runtime: HostedApplicationContinuityRuntimeV1 | None = None
        self._open_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._open_task: asyncio.Task[HostedApplicationContinuityRuntimeV1] | None = (
            None
        )
        self._close_task: asyncio.Task[None] | None = None
        self._transferred = False
        self._closed = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._transferred and not self._settled

    async def open(self) -> HostedApplicationContinuityRuntimeV1:
        async with self._open_lock:
            if self._closed:
                raise HostedApplicationError("coding_hosted_continuity_attempt_closed")
            task = self._open_task
            if task is None or _runtime_task_needs_retry(task):
                task = asyncio.create_task(self._open_once())
                task.add_done_callback(_observe_background_result)
                self._open_task = task
        runtime = await _join_runtime(task)
        async with self._open_lock:
            rejected = self._closed
            if not rejected:
                self._transferred = True
        if rejected:
            await self.close()
            raise HostedApplicationError("coding_hosted_continuity_attempt_closed")
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
        request = self._request.foreground
        if self._lease is None:
            try:
                self._lease = await self._request.store.acquire(
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
        if self._runtime is None:
            product, profile = _coding_hosted_registrations(
                request,
                self._product_factory,
            )
            self._catalog = await AppHostCatalogV1.admit(
                AppHostCatalogInputV1(
                    generation_id=request.generation_id,
                    products=(product,),
                    profiles=(profile,),
                )
            )
            self._runtime = AppHostRuntimeV1(self._catalog, request.sessions)
        if self._continuity is None:
            resolver = CodingAppHostHostedSessionResolverV1(
                runtime=self._runtime,
                sessions=request.sessions,
                profile_id=request.profile_id,
                operation_id_factory=request.operation_id_factory,
                admitted_scopes=request.admitted_scopes,
                execution=request.execution is not None,
            )
            application = _coding_hosted_application_request(
                request,
                product_factory=self._product_factory,
                runtime=self._runtime,
                resolver=resolver,
            )
            self._continuity = create_hosted_application_continuity_attempt(
                HostedApplicationContinuityRequestV1(
                    activation=self._request.activation,
                    application=application,
                    application_id=self._request.application_id,
                    owner_epoch=self._request.owner_epoch,
                    continuity_lease=self._lease,
                    phase_timeout_seconds=self._request.phase_timeout_seconds,
                )
            )
        continuity_runtime = await self._continuity.open()
        self._continuity_runtime = continuity_runtime
        return continuity_runtime

    async def _close_once(self) -> None:
        open_task = self._open_task
        if open_task is not None and not open_task.done():
            with suppress(BaseException):
                await _join_runtime(open_task)
        if self._transferred:
            return
        if self._continuity_runtime is not None:
            report = await self._continuity_runtime.shutdown()
            if not report.completed:
                raise HostedApplicationError(
                    "coding_hosted_continuity_cleanup_incomplete"
                )
        elif self._continuity is not None:
            await self._continuity.close()
        else:
            try:
                await _settle_failed_construction(
                    self._runtime,
                    self._catalog,
                    self._product_factory,
                )
            except BaseException:
                raise HostedApplicationError(
                    "coding_hosted_continuity_cleanup_incomplete"
                ) from None
            if self._lease is not None:
                try:
                    await self._lease.close()
                except BaseException:
                    raise HostedApplicationError(
                        "coding_hosted_continuity_cleanup_incomplete"
                    ) from None
        self._settled = True


def create_coding_hosted_continuity_attempt(
    request: CodingHostedContinuityRequestV1,
) -> CodingHostedContinuityAttemptV1:
    """Publish the Coding G13 owner before the first admission effect."""

    return CodingHostedContinuityAttemptV1(request)


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
    "CodingHostedContinuityAttemptV1",
    "CodingHostedContinuityRequestV1",
    "create_coding_hosted_continuity_attempt",
]

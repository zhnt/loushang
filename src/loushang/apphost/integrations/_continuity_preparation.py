"""Fixed preparation for the existing Product continuity attempt object.

The concrete Product attempt keeps its original slots, dependencies and state.
This optional implementation adds no owner instance or second lifecycle engine.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import ClassVar, Generic, Protocol, TypeVar

from loushang.appservice import (
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityLeaseV1,
    ApplicationContinuityStoreV1,
)
from loushang.foundation._owned_tasks import _join_failure_first

from .._ownership import _settle_failed_product_construction
from ..application import (
    HostedApplicationError,
    HostedApplicationProductOwnerV1,
    HostedApplicationRequestV1,
)
from ..catalog import AppHostCatalogV1
from ..continuity import (
    _CONTINUITY_ATTEMPT_SLOTS,
    HostedApplicationContinuityActivationV1,
    HostedApplicationContinuityAttemptV1,
    HostedApplicationContinuityRequestV1,
    HostedApplicationContinuityRuntimeV1,
    _ContinuityAttemptLifecycle,
    _join_runtime,
    create_hosted_application_continuity_attempt,
)
from ..contracts import AppHostCatalogInputV1, SessionIdentityCatalogPortV1
from ..runtime import AppHostRuntimeV1

ForegroundT = TypeVar("ForegroundT")


class _ProductContinuityRequest(Protocol):
    @property
    def activation(self) -> HostedApplicationContinuityActivationV1: ...
    @property
    def application_id(self) -> str: ...
    @property
    def owner_epoch(self) -> str: ...
    @property
    def store(self) -> ApplicationContinuityStoreV1: ...
    @property
    def phase_timeout_seconds(self) -> float: ...


class _ProductContinuityAttempt(_ContinuityAttemptLifecycle, Generic[ForegroundT]):
    __slots__ = _CONTINUITY_ATTEMPT_SLOTS
    _request: _ProductContinuityRequest
    _product_factory: HostedApplicationProductOwnerV1
    _prefix_cleanup_error: ClassVar[str]
    _construction_cleanup_error: ClassVar[str]

    async def _load_foreground_request(self) -> ForegroundT:
        raise NotImplementedError

    def _foreground_sessions(
        self, request: ForegroundT
    ) -> SessionIdentityCatalogPortV1:
        raise NotImplementedError

    def _catalog_input(self, request: ForegroundT) -> AppHostCatalogInputV1:
        raise NotImplementedError

    def _application_request(self, request: ForegroundT) -> HostedApplicationRequestV1:
        raise NotImplementedError

    def _initialize_product_continuity_state(self) -> None:
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

    async def _open_once(self) -> HostedApplicationContinuityRuntimeV1:
        request = await self._load_foreground_request()
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
            self._catalog = await AppHostCatalogV1.admit(self._catalog_input(request))
            self._runtime = AppHostRuntimeV1(
                self._catalog, self._foreground_sessions(request)
            )
        if self._continuity is None:
            application = self._application_request(request)
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
        if open_task is not None and (not open_task.done()):
            with suppress(BaseException):
                await _join_runtime(open_task)
        if self._transferred:
            return
        if self._continuity_runtime is not None:
            report = await self._continuity_runtime.shutdown()
            if not report.completed:
                raise HostedApplicationError(self._prefix_cleanup_error)
        elif self._continuity is not None:
            await self._continuity.close()
        else:
            try:
                await _settle_failed_product_construction(
                    self._runtime,
                    self._catalog,
                    self._product_factory,
                    error_code=self._construction_cleanup_error,
                    join_owned=_join_failure_first,
                )
            except BaseException:
                raise HostedApplicationError(self._prefix_cleanup_error) from None
            if self._lease is not None:
                try:
                    await self._lease.close()
                except BaseException:
                    raise HostedApplicationError(self._prefix_cleanup_error) from None
        self._settled = True

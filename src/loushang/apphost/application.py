"""Optional foreground AppHost/AppService composition for G12."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from loushang.appserver.client import AppClientV1
from loushang.appservice import (
    AppServiceV1,
    HostedSessionResolverV1,
    InProcessAppClientV1,
)

from .contracts import AppHostShutdownBudgetV1, AppHostShutdownReportV1

HOSTED_APPLICATION_CONTRACT_VERSION = "loushang.apphost.application/v1"

_STABLE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")
_CONSTRUCTION_TOKEN = object()


class HostedApplicationShutdownPhase(str, Enum):
    """Dependency-ordered G12 application shutdown phases."""

    SERVICE = "service"
    APPHOST = "apphost"
    PRODUCT = "product"


class HostedApplicationError(RuntimeError):
    """Stable optional-composition failure without nested exception text."""

    def __init__(self, code: str) -> None:
        if _STABLE_ID.fullmatch(code) is None:
            raise ValueError("invalid hosted application error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class HostedApplicationActivationV1:
    """Unforgeable-by-omission typed activation selected by trusted composition."""

    contract_version: str = HOSTED_APPLICATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != HOSTED_APPLICATION_CONTRACT_VERSION:
            raise ValueError("unsupported hosted application activation")


class HostedApplicationAppHostPortV1(Protocol):
    """The exact AppHost shutdown capability owned by the composition."""

    async def shutdown(
        self,
        budget: AppHostShutdownBudgetV1,
    ) -> AppHostShutdownReportV1: ...


class HostedApplicationProductOwnerV1(Protocol):
    """Product construction-debt owner settled after AppHost."""

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class HostedApplicationRequestV1:
    """Complete explicit input for one foreground hosted application."""

    activation: HostedApplicationActivationV1
    product_id: str
    generation_id: str
    apphost: HostedApplicationAppHostPortV1
    resolver: HostedSessionResolverV1
    product_owner: HostedApplicationProductOwnerV1
    shutdown_budget: AppHostShutdownBudgetV1
    phase_timeout_seconds: float = 10.0
    service_close_timeout_seconds: float = 10.0
    service_id_factory: Callable[[], str] | None = None

    def __post_init__(self) -> None:
        if type(self.activation) is not HostedApplicationActivationV1:
            raise TypeError("hosted application requires explicit activation")
        if _STABLE_ID.fullmatch(self.product_id) is None:
            raise ValueError("invalid hosted application Product identity")
        if _OPAQUE_TOKEN.fullmatch(self.generation_id) is None:
            raise ValueError("invalid hosted application generation identity")
        _require_async_method(self.apphost, "shutdown")
        _require_async_method(self.resolver, "open_session")
        _require_async_method(self.product_owner, "close")
        if type(self.shutdown_budget) is not AppHostShutdownBudgetV1:
            raise TypeError("invalid hosted application shutdown budget")
        for value in (
            self.phase_timeout_seconds,
            self.service_close_timeout_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 < value <= 60
            ):
                raise ValueError("invalid hosted application timeout")
        if self.service_id_factory is not None and not callable(
            self.service_id_factory
        ):
            raise TypeError("invalid hosted application ID factory")


@dataclass(frozen=True, slots=True)
class HostedApplicationShutdownReportV1:
    """Bounded owner-specific G12 settlement facts."""

    completed: bool
    timed_out_phases: tuple[HostedApplicationShutdownPhase, ...]
    failed_phases: tuple[HostedApplicationShutdownPhase, ...]
    apphost_shutdown: AppHostShutdownReportV1 | None
    product_cleanup_complete: bool
    contract_version: str = HOSTED_APPLICATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if type(self.completed) is not bool or type(
            self.product_cleanup_complete
        ) is not bool:
            raise TypeError("invalid hosted application shutdown report")
        if self.contract_version != HOSTED_APPLICATION_CONTRACT_VERSION:
            raise ValueError("unsupported hosted application shutdown report")
        for values in (self.timed_out_phases, self.failed_phases):
            if (
                not isinstance(values, tuple)
                or any(type(item) is not HostedApplicationShutdownPhase for item in values)
                or len(values) != len(set(values))
            ):
                raise ValueError("invalid hosted application shutdown phases")
        if set(self.timed_out_phases).intersection(self.failed_phases):
            raise ValueError("duplicate hosted application shutdown phase")
        if self.apphost_shutdown is not None and type(self.apphost_shutdown) is not (
            AppHostShutdownReportV1
        ):
            raise TypeError("invalid nested AppHost shutdown report")
        expected = (
            not self.timed_out_phases
            and not self.failed_phases
            and self.apphost_shutdown is not None
            and self.apphost_shutdown.completed
            and self.product_cleanup_complete
        )
        if self.completed != expected:
            raise ValueError("inconsistent hosted application shutdown report")


class HostedApplicationRuntimeV1:
    """Sole owner of one foreground AppService/AppHost lifecycle."""

    __slots__ = (
        "_accepting",
        "_apphost",
        "_client",
        "_control_lock",
        "_phase_tasks",
        "_phase_timeout_seconds",
        "_product_owner",
        "_service",
        "_shutdown_budget",
        "_shutdown_task",
        "generation_id",
        "product_id",
    )

    def __init__(
        self,
        request: HostedApplicationRequestV1,
        service: AppServiceV1,
        *,
        _construction_token: object,
    ) -> None:
        if _construction_token is not _CONSTRUCTION_TOKEN:
            raise TypeError("hosted application requires its factory")
        self.product_id = request.product_id
        self.generation_id = request.generation_id
        self._apphost = request.apphost
        self._product_owner = request.product_owner
        self._shutdown_budget = request.shutdown_budget
        self._phase_timeout_seconds = float(request.phase_timeout_seconds)
        self._service = service
        self._client = InProcessAppClientV1(service)
        self._accepting = True
        self._control_lock = asyncio.Lock()
        self._shutdown_task: asyncio.Task[HostedApplicationShutdownReportV1] | None = (
            None
        )
        self._phase_tasks: dict[HostedApplicationShutdownPhase, asyncio.Task[object]] = (
            {}
        )

    @property
    def client(self) -> AppClientV1:
        """Return the non-owning transport-neutral client view."""

        return self._client

    @property
    def accepting(self) -> bool:
        return self._accepting

    async def shutdown(self) -> HostedApplicationShutdownReportV1:
        """Fence and settle every owner; an incomplete report is retryable."""

        async with self._control_lock:
            task = self._shutdown_task
            if task is None or (
                task.done()
                and (
                    task.cancelled()
                    or task.exception() is not None
                    or not task.result().completed
                )
            ):
                task = asyncio.create_task(self._shutdown_once())
                task.add_done_callback(_observe_background_result)
                self._shutdown_task = task
        return await _join_owned(task)

    async def close(self) -> None:
        report = await self.shutdown()
        if not report.completed:
            raise HostedApplicationError("hosted_application_cleanup_incomplete")

    async def _shutdown_once(self) -> HostedApplicationShutdownReportV1:
        self._accepting = False
        timed_out: list[HostedApplicationShutdownPhase] = []
        failed: list[HostedApplicationShutdownPhase] = []

        service_result = await self._run_phase(
            HostedApplicationShutdownPhase.SERVICE,
            self._service.close,
        )
        if service_result == "timed_out":
            timed_out.append(HostedApplicationShutdownPhase.SERVICE)
        elif service_result == "failed":
            failed.append(HostedApplicationShutdownPhase.SERVICE)
        if service_result != "completed":
            return _shutdown_report(timed_out, failed, None, False)

        apphost_report: AppHostShutdownReportV1 | None = None
        apphost_result, raw_report = await self._run_apphost_phase()
        if apphost_result == "timed_out":
            timed_out.append(HostedApplicationShutdownPhase.APPHOST)
        elif apphost_result == "failed":
            failed.append(HostedApplicationShutdownPhase.APPHOST)
        else:
            apphost_report = raw_report
            if apphost_report is None or not apphost_report.completed:
                failed.append(HostedApplicationShutdownPhase.APPHOST)
        if timed_out or failed:
            return _shutdown_report(timed_out, failed, apphost_report, False)

        product_result = await self._run_phase(
            HostedApplicationShutdownPhase.PRODUCT,
            self._product_owner.close,
        )
        if product_result == "timed_out":
            timed_out.append(HostedApplicationShutdownPhase.PRODUCT)
        elif product_result == "failed":
            failed.append(HostedApplicationShutdownPhase.PRODUCT)
        return _shutdown_report(
            timed_out,
            failed,
            apphost_report,
            product_result == "completed",
        )

    async def _run_phase(
        self,
        phase: HostedApplicationShutdownPhase,
        callback: object,
    ) -> str:
        task = self._phase_tasks.get(phase)
        if task is None or _phase_task_failed(task):
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

    async def _run_apphost_phase(
        self,
    ) -> tuple[str, AppHostShutdownReportV1 | None]:
        phase = HostedApplicationShutdownPhase.APPHOST
        task = self._phase_tasks.get(phase)
        if task is None or _apphost_phase_needs_retry(task):
            task = asyncio.create_task(self._apphost.shutdown(self._shutdown_budget))
            task.add_done_callback(_observe_background_result)
            self._phase_tasks[phase] = task
        try:
            async with asyncio.timeout(self._phase_timeout_seconds):
                raw = await asyncio.shield(task)
        except TimeoutError:
            return "timed_out", None
        except asyncio.CancelledError:
            raise
        except BaseException:
            return "failed", None
        if type(raw) is not AppHostShutdownReportV1:
            return "failed", None
        return "completed", raw


def create_hosted_application_runtime(
    request: HostedApplicationRequestV1,
) -> HostedApplicationRuntimeV1:
    """Construct the explicit G12 lifecycle owner without installed activation."""

    if type(request) is not HostedApplicationRequestV1:
        raise TypeError("invalid hosted application request")
    service = AppServiceV1(
        product_id=request.product_id,
        resolver=request.resolver,
        id_factory=request.service_id_factory,
        close_timeout_seconds=request.service_close_timeout_seconds,
    )
    return HostedApplicationRuntimeV1(
        request,
        service,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _shutdown_report(
    timed_out: list[HostedApplicationShutdownPhase],
    failed: list[HostedApplicationShutdownPhase],
    apphost: AppHostShutdownReportV1 | None,
    product_complete: bool,
) -> HostedApplicationShutdownReportV1:
    timed_out_tuple = tuple(timed_out)
    failed_tuple = tuple(failed)
    return HostedApplicationShutdownReportV1(
        completed=(
            not timed_out_tuple
            and not failed_tuple
            and apphost is not None
            and apphost.completed
            and product_complete
        ),
        timed_out_phases=timed_out_tuple,
        failed_phases=failed_tuple,
        apphost_shutdown=apphost,
        product_cleanup_complete=product_complete,
    )


async def _join_owned(
    task: asyncio.Task[HostedApplicationShutdownReportV1],
) -> HostedApplicationShutdownReportV1:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = error
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


def _method_descriptor(value: object, name: str) -> object:
    descriptor = inspect.getattr_static(type(value), name, None)
    if isinstance(descriptor, (classmethod, staticmethod)):
        return descriptor.__func__
    return descriptor


def _phase_task_failed(task: asyncio.Task[object]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _apphost_phase_needs_retry(task: asyncio.Task[object]) -> bool:
    if not task.done():
        return False
    if task.cancelled() or task.exception() is not None:
        return True
    result = task.result()
    return type(result) is not AppHostShutdownReportV1 or not result.completed


def _require_async_method(value: object, name: str) -> None:
    if not inspect.iscoroutinefunction(_method_descriptor(value, name)):
        raise TypeError(f"hosted application {name} port is invalid")


def _observe_background_result(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = [
    "HOSTED_APPLICATION_CONTRACT_VERSION",
    "HostedApplicationActivationV1",
    "HostedApplicationAppHostPortV1",
    "HostedApplicationError",
    "HostedApplicationProductOwnerV1",
    "HostedApplicationRequestV1",
    "HostedApplicationRuntimeV1",
    "HostedApplicationShutdownPhase",
    "HostedApplicationShutdownReportV1",
    "create_hosted_application_runtime",
]

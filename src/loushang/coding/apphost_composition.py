"""Explicit default-dark production composition for the Coding AppHost path."""

from __future__ import annotations

import asyncio
import inspect
import re
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from loushang.apphost import (
    AdmissionGenerationSourceV1,
    AppHostCatalogInputV1,
    AppHostCatalogV1,
    AppHostRuntimeV1,
    AppHostSessionLeaseV1,
    AppHostShutdownBudgetV1,
    AppHostShutdownReportV1,
    ProductCandidateValidatorV1,
    ProfileRegistrationV1,
    SessionBindingKeyV1,
    SessionCandidateRefV1,
    SessionCreateRequestV1,
    SessionIdentityCatalogPortV1,
)

from .apphost_product import (
    CodingAppHostProductFactoryV1,
    CodingAppHostWorkerAttemptFactoryV1,
    coding_apphost_product_registration,
)
from .product_plan import CODING_PRODUCT_ID

CODING_APPHOST_COMPOSITION_VERSION = 1
CODING_APPHOST_ROLLBACK_REPORT_VERSION = 1
CODING_APPHOST_MAX_ACTIVE_ATTEMPT_FINGERPRINTS = 4096

_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
_STABLE_CODE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_CONSTRUCTION_TOKEN = object()

CodingAppHostSettlementMode = Literal["close", "rollback"]
CodingAppHostSettlementPhase = Literal[
    "rollback_latch",
    "apphost_shutdown",
    "product_cleanup",
]


class CodingAppHostCompositionError(RuntimeError):
    """Stable Product-owned failure for explicit composition control."""

    def __init__(self, *, code: str) -> None:
        if not isinstance(code, str) or _STABLE_CODE.fullmatch(code) is None:
            raise ValueError("Coding AppHost composition error code is invalid")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CodingAppHostCompositionActivationV1:
    """Explicit selection token; constructing the composition is the opt-in."""

    owner: Literal["hosting"] = "hosting"
    activation_version: int = CODING_APPHOST_COMPOSITION_VERSION

    def __post_init__(self) -> None:
        if self.owner != "hosting":
            raise ValueError("Coding AppHost composition requires Hosting")
        if (
            type(self.activation_version) is not int
            or self.activation_version != CODING_APPHOST_COMPOSITION_VERSION
        ):
            raise ValueError("Coding AppHost composition activation is unsupported")


@dataclass(frozen=True, slots=True)
class CodingAppHostRollbackLatchV1:
    """Bounded Product-owned result of the durable future-attempt latch."""

    selection_generation: int
    active_attempt_fingerprints: tuple[str, ...]
    latch_version: int = CODING_APPHOST_ROLLBACK_REPORT_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.selection_generation) is not int
            or self.selection_generation < 1
        ):
            raise ValueError("Coding AppHost rollback generation is invalid")
        fingerprints = self.active_attempt_fingerprints
        if (
            not isinstance(fingerprints, tuple)
            or len(fingerprints) > CODING_APPHOST_MAX_ACTIVE_ATTEMPT_FINGERPRINTS
            or any(
                not isinstance(item, str) or _FINGERPRINT.fullmatch(item) is None
                for item in fingerprints
            )
            or len(fingerprints) != len(set(fingerprints))
            or fingerprints != tuple(sorted(fingerprints))
        ):
            raise ValueError("Coding AppHost rollback attempts are invalid")
        if (
            type(self.latch_version) is not int
            or self.latch_version != CODING_APPHOST_ROLLBACK_REPORT_VERSION
        ):
            raise ValueError("Coding AppHost rollback latch is unsupported")


class CodingAppHostRollbackControlV1(Protocol):
    """Product-owned durable control; never exposed through an AppHost profile."""

    async def latch_future_attempts(self) -> CodingAppHostRollbackLatchV1: ...


@dataclass(frozen=True, slots=True)
class CodingAppHostCompositionRequestV1:
    """Complete trusted-composition input with no discovery or defaulting."""

    activation: CodingAppHostCompositionActivationV1
    generation_id: str
    product_version: str
    compatibility_id: str
    product_admission_source: AdmissionGenerationSourceV1 = field(repr=False)
    candidate_validator: ProductCandidateValidatorV1 = field(repr=False)
    attempt_factory: CodingAppHostWorkerAttemptFactoryV1 = field(repr=False)
    profiles: tuple[ProfileRegistrationV1, ...]
    sessions: SessionIdentityCatalogPortV1 = field(repr=False)
    rollback_control: CodingAppHostRollbackControlV1 = field(repr=False)
    shutdown_budget: AppHostShutdownBudgetV1

    def __post_init__(self) -> None:
        if type(self.activation) is not CodingAppHostCompositionActivationV1:
            raise TypeError("Coding AppHost composition requires explicit activation")
        for name, value in (
            ("generation_id", self.generation_id),
            ("product_version", self.product_version),
            ("compatibility_id", self.compatibility_id),
        ):
            _require_opaque(value, name=name)
        if (
            not isinstance(self.profiles, tuple)
            or not self.profiles
            or any(type(item) is not ProfileRegistrationV1 for item in self.profiles)
        ):
            raise TypeError("Coding AppHost profiles must be a non-empty exact tuple")
        _require_async_method(self.product_admission_source, "acquire_pin")
        _require_async_method(self.candidate_validator, "open_product_candidate")
        _require_sync_method(self.attempt_factory, "create_attempt")
        for method in (
            "list_identities",
            "open_candidate",
            "find_created_candidate",
            "create_candidate",
        ):
            _require_async_method(self.sessions, method)
        _require_async_method(self.rollback_control, "latch_future_attempts")
        if type(self.shutdown_budget) is not AppHostShutdownBudgetV1:
            raise TypeError("Coding AppHost shutdown budget is invalid")


@dataclass(frozen=True, slots=True)
class CodingAppHostSettlementReportV1:
    """Bounded owner-specific close/rollback facts without raw failures."""

    mode: CodingAppHostSettlementMode
    completed: bool
    admission_fenced: bool
    rollback_latch: CodingAppHostRollbackLatchV1 | None
    apphost_shutdown: AppHostShutdownReportV1 | None
    product_cleanup_complete: bool
    failed_phases: tuple[CodingAppHostSettlementPhase, ...]
    report_version: int = CODING_APPHOST_ROLLBACK_REPORT_VERSION

    def __post_init__(self) -> None:
        if self.mode not in {"close", "rollback"}:
            raise ValueError("Coding AppHost settlement mode is invalid")
        if type(self.completed) is not bool or type(self.admission_fenced) is not bool:
            raise TypeError("Coding AppHost settlement booleans are invalid")
        if type(self.product_cleanup_complete) is not bool:
            raise TypeError("Coding AppHost cleanup result is invalid")
        if self.rollback_latch is not None and type(self.rollback_latch) is not (
            CodingAppHostRollbackLatchV1
        ):
            raise TypeError("Coding AppHost rollback result is invalid")
        if self.apphost_shutdown is not None and type(self.apphost_shutdown) is not (
            AppHostShutdownReportV1
        ):
            raise TypeError("Coding AppHost shutdown result is invalid")
        allowed = {"rollback_latch", "apphost_shutdown", "product_cleanup"}
        canonical_order = ("rollback_latch", "apphost_shutdown", "product_cleanup")
        if (
            not isinstance(self.failed_phases, tuple)
            or any(item not in allowed for item in self.failed_phases)
            or len(self.failed_phases) != len(set(self.failed_phases))
            or self.failed_phases
            != tuple(item for item in canonical_order if item in self.failed_phases)
        ):
            raise ValueError("Coding AppHost failed phases are invalid")
        if self.mode == "close" and self.rollback_latch is not None:
            raise ValueError("Normal close cannot claim a rollback latch")
        expected_complete = (
            self.admission_fenced
            and (self.mode == "close" or self.rollback_latch is not None)
            and self.apphost_shutdown is not None
            and self.apphost_shutdown.completed
            and self.product_cleanup_complete
            and not self.failed_phases
        )
        if self.completed != expected_complete:
            raise ValueError("Coding AppHost settlement completion is inconsistent")
        if (
            type(self.report_version) is not int
            or self.report_version != CODING_APPHOST_ROLLBACK_REPORT_VERSION
        ):
            raise ValueError("Coding AppHost settlement report is unsupported")


class CodingAppHostCompositionV1:
    """Sole process-scoped owner of the explicit Coding AppHost composition."""

    __slots__ = (
        "_accepting",
        "_activation",
        "_admission_lock",
        "_control_lock",
        "_control_mode",
        "_control_task",
        "_generation_id",
        "_product_factory",
        "_rollback_control",
        "_rollback_latch",
        "_runtime",
        "_shutdown_budget",
    )

    def __init__(
        self,
        *,
        activation: CodingAppHostCompositionActivationV1,
        generation_id: str,
        runtime: AppHostRuntimeV1,
        product_factory: CodingAppHostProductFactoryV1,
        rollback_control: CodingAppHostRollbackControlV1,
        shutdown_budget: AppHostShutdownBudgetV1,
        _construction_token: object,
    ) -> None:
        if _construction_token is not _CONSTRUCTION_TOKEN:
            raise TypeError("Coding AppHost composition requires its factory")
        self._activation = activation
        self._generation_id = generation_id
        self._runtime = runtime
        self._product_factory = product_factory
        self._rollback_control = rollback_control
        self._shutdown_budget = shutdown_budget
        self._accepting = True
        self._admission_lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        self._control_mode: CodingAppHostSettlementMode | None = None
        self._control_task: asyncio.Task[CodingAppHostSettlementReportV1] | None = None
        self._rollback_latch: CodingAppHostRollbackLatchV1 | None = None

    @property
    def activation(self) -> CodingAppHostCompositionActivationV1:
        return self._activation

    @property
    def generation_id(self) -> str:
        return self._generation_id

    @property
    def accepting(self) -> bool:
        return self._accepting

    async def attach_resume(
        self,
        *,
        reference: SessionCandidateRefV1,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        await self._admit()
        return await self._runtime.attach_resume(
            product_id=CODING_PRODUCT_ID,
            reference=reference,
            profile_id=profile_id,
        )

    async def attach_create(
        self,
        request: SessionCreateRequestV1,
        *,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        await self._admit()
        if request.product_id != CODING_PRODUCT_ID:
            raise CodingAppHostCompositionError(
                code="coding_apphost_composition_product_mismatch"
            )
        return await self._runtime.attach_create(request, profile_id=profile_id)

    async def close_session(self, key: SessionBindingKeyV1) -> None:
        await self._admit()
        await self._runtime.close_session(key)

    async def rollback(self) -> CodingAppHostSettlementReportV1:
        task = await self._settlement_task("rollback")
        return await asyncio.shield(task)

    async def close(self) -> None:
        task = await self._settlement_task("close")
        report = await asyncio.shield(task)
        if not report.completed:
            raise CodingAppHostCompositionError(
                code="coding_apphost_composition_cleanup_incomplete"
            )

    async def _admit(self) -> None:
        async with self._admission_lock:
            if not self._accepting:
                raise CodingAppHostCompositionError(
                    code="coding_apphost_composition_fenced"
                )

    async def _fence(self) -> None:
        async with self._admission_lock:
            self._accepting = False

    async def _settlement_task(
        self,
        requested_mode: CodingAppHostSettlementMode,
    ) -> asyncio.Task[CodingAppHostSettlementReportV1]:
        async with self._control_lock:
            task = self._control_task
            mode = self._control_mode
            if mode == "close" and requested_mode == "rollback":
                assert task is not None
                task = asyncio.create_task(
                    self._upgrade_close_to_rollback(task)
                )
                task.add_done_callback(_observe_background_result)
                self._control_task = task
                self._control_mode = "rollback"
                return task
            effective_mode: CodingAppHostSettlementMode = (
                "rollback" if mode == "rollback" else requested_mode
            )
            retry = task is None or (
                task.done()
                and (
                    task.cancelled()
                    or task.exception() is not None
                    or not task.result().completed
                )
            )
            if retry:
                task = asyncio.create_task(self._settle_once(effective_mode))
                task.add_done_callback(_observe_background_result)
                self._control_task = task
                self._control_mode = effective_mode
            assert task is not None
            return task

    async def _settle_once(
        self,
        mode: CodingAppHostSettlementMode,
        *,
        attempt_rollback_latch: bool = True,
    ) -> CodingAppHostSettlementReportV1:
        await self._fence()
        failed: list[CodingAppHostSettlementPhase] = []

        if (
            mode == "rollback"
            and self._rollback_latch is None
            and (not attempt_rollback_latch or not await self._latch_rollback())
        ):
            failed.append("rollback_latch")

        shutdown: AppHostShutdownReportV1 | None = None
        try:
            shutdown = await self._runtime.shutdown(self._shutdown_budget)
            if not shutdown.completed:
                failed.append("apphost_shutdown")
        except Exception:
            failed.append("apphost_shutdown")

        product_cleanup_complete = False
        if shutdown is not None and shutdown.completed:
            try:
                await self._product_factory.close()
                product_cleanup_complete = True
            except Exception:
                failed.append("product_cleanup")

        failed_phases = tuple(dict.fromkeys(failed))
        completed = (
            (mode == "close" or self._rollback_latch is not None)
            and shutdown is not None
            and shutdown.completed
            and product_cleanup_complete
            and not failed_phases
        )
        return CodingAppHostSettlementReportV1(
            mode=mode,
            completed=completed,
            admission_fenced=True,
            rollback_latch=(self._rollback_latch if mode == "rollback" else None),
            apphost_shutdown=shutdown,
            product_cleanup_complete=product_cleanup_complete,
            failed_phases=cast(
                tuple[CodingAppHostSettlementPhase, ...],
                failed_phases,
            ),
        )

    async def _upgrade_close_to_rollback(
        self,
        close_task: asyncio.Task[CodingAppHostSettlementReportV1],
    ) -> CodingAppHostSettlementReportV1:
        """Make an emergency rollback dominate an earlier normal close."""

        await self._fence()
        await self._latch_rollback()
        with suppress(asyncio.CancelledError, Exception):
            await asyncio.shield(close_task)
        # The retryable runtime/factory owners, rather than the prior task
        # result, determine whether the upgraded settlement is complete.
        return await self._settle_once(
            "rollback",
            attempt_rollback_latch=False,
        )

    async def _latch_rollback(self) -> bool:
        if self._rollback_latch is not None:
            return True
        try:
            raw_latch = await self._rollback_control.latch_future_attempts()
            if type(raw_latch) is not CodingAppHostRollbackLatchV1:
                raise TypeError("rollback control returned an invalid latch")
        except Exception:
            return False
        self._rollback_latch = raw_latch
        return True


async def create_coding_apphost_composition(
    request: CodingAppHostCompositionRequestV1,
) -> CodingAppHostCompositionV1:
    """Construct the sole explicit Coding Product/AppHost composition."""

    if type(request) is not CodingAppHostCompositionRequestV1:
        raise TypeError("Coding AppHost composition request is invalid")
    product_factory = CodingAppHostProductFactoryV1(request.attempt_factory)
    catalog: AppHostCatalogV1 | None = None
    try:
        product = coding_apphost_product_registration(
            generation_id=request.generation_id,
            product_version=request.product_version,
            compatibility_id=request.compatibility_id,
            supported_profile_ids=tuple(
                profile.descriptor.profile_id for profile in request.profiles
            ),
            admission_source=request.product_admission_source,
            candidate_validator=request.candidate_validator,
            product_factory=product_factory,
        )
        catalog_input = AppHostCatalogInputV1(
            generation_id=request.generation_id,
            products=(product,),
            profiles=request.profiles,
        )
        catalog = await AppHostCatalogV1.admit(catalog_input)
        runtime = AppHostRuntimeV1(catalog, request.sessions)
        return CodingAppHostCompositionV1(
            activation=request.activation,
            generation_id=request.generation_id,
            runtime=runtime,
            product_factory=product_factory,
            rollback_control=request.rollback_control,
            shutdown_budget=request.shutdown_budget,
            _construction_token=_CONSTRUCTION_TOKEN,
        )
    except asyncio.CancelledError:
        await _join_failed_construction_cleanup(catalog, product_factory)
        raise
    except Exception as error:
        try:
            await _join_failed_construction_cleanup(catalog, product_factory)
        except CodingAppHostCompositionError:
            raise
        raise CodingAppHostCompositionError(
            code="coding_apphost_composition_unavailable"
        ) from error


async def _settle_failed_construction(
    catalog: AppHostCatalogV1 | None,
    product_factory: CodingAppHostProductFactoryV1,
) -> None:
    failures: list[BaseException] = []
    if catalog is not None:
        try:
            await catalog.close()
        except BaseException as error:
            failures.append(error)
    try:
        await product_factory.close()
    except BaseException as error:
        failures.append(error)
    if failures:
        raise CodingAppHostCompositionError(
            code="coding_apphost_composition_cleanup_incomplete"
        ) from None


async def _join_failed_construction_cleanup(
    catalog: AppHostCatalogV1 | None,
    product_factory: CodingAppHostProductFactoryV1,
) -> None:
    operation = asyncio.create_task(
        _settle_failed_construction(catalog, product_factory)
    )
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not operation.done():
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError as error:
            if caller is None or caller.cancelling() == 0:
                return operation.result()
            cancellation = error
    operation.result()
    if cancellation is not None:
        raise cancellation


def _require_opaque(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 128
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"Coding AppHost {name} is invalid")


def _method_descriptor(value: object, name: str) -> object:
    descriptor = inspect.getattr_static(type(value), name, None)
    if isinstance(descriptor, (classmethod, staticmethod)):
        return descriptor.__func__
    return descriptor


def _require_async_method(value: object, name: str) -> None:
    if not inspect.iscoroutinefunction(_method_descriptor(value, name)):
        raise TypeError(f"Coding AppHost {name} port is invalid")


def _require_sync_method(value: object, name: str) -> None:
    descriptor = _method_descriptor(value, name)
    if not callable(descriptor) or inspect.iscoroutinefunction(descriptor):
        raise TypeError(f"Coding AppHost {name} port is invalid")


def _observe_background_result(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = [
    "CODING_APPHOST_COMPOSITION_VERSION",
    "CODING_APPHOST_MAX_ACTIVE_ATTEMPT_FINGERPRINTS",
    "CODING_APPHOST_ROLLBACK_REPORT_VERSION",
    "CodingAppHostCompositionActivationV1",
    "CodingAppHostCompositionError",
    "CodingAppHostCompositionRequestV1",
    "CodingAppHostCompositionV1",
    "CodingAppHostRollbackControlV1",
    "CodingAppHostRollbackLatchV1",
    "CodingAppHostSettlementReportV1",
    "create_coding_apphost_composition",
]

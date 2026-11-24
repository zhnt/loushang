"""Explicit default-dark production composition for the Coding AppHost path."""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from loushang.apphost import (
    AdmissionGenerationSourceV1,
    AppHostCatalogInputV1,
    AppHostRuntimeV1,
    AppHostShutdownBudgetV1,
    AppHostShutdownReportV1,
    ProductCandidateValidatorV1,
    ProfileRegistrationV1,
    SessionIdentityCatalogPortV1,
)
from loushang.apphost._ownership import (
    _construct_product_apphost,
    _ExplicitProductAppHostLifecycle,
    _method_descriptor,
)
from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.hosted.product import (
    CodingAppHostProductFactoryV1,
    CodingAppHostWorkerAttemptFactoryV1,
    coding_apphost_product_registration,
)
from loushang.harness.runtime import await_owned_task as _await_owned_task

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
        if type(self.selection_generation) is not int or self.selection_generation < 1:
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


class CodingAppHostCompositionV1(
    _ExplicitProductAppHostLifecycle[
        CodingAppHostRollbackLatchV1, CodingAppHostSettlementReportV1
    ]
):
    """Sole process-scoped owner of the explicit Coding AppHost composition."""

    _product_id = CODING_PRODUCT_ID
    _rollback_latch_type = CodingAppHostRollbackLatchV1
    _settlement_report_type = CodingAppHostSettlementReportV1

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
        self._initialize_lifecycle(
            runtime, product_factory, rollback_control, shutdown_budget
        )

    def _composition_error(self, code: str) -> CodingAppHostCompositionError:
        return CodingAppHostCompositionError(code=f"coding_apphost_composition_{code}")

    @property
    def activation(self) -> CodingAppHostCompositionActivationV1:
        return self._activation

    @property
    def generation_id(self) -> str:
        return self._generation_id

    async def rollback(self) -> CodingAppHostSettlementReportV1:
        return await self._rollback()


async def create_coding_apphost_composition(
    request: CodingAppHostCompositionRequestV1,
) -> CodingAppHostCompositionV1:
    """Construct the sole explicit Coding Product/AppHost composition."""

    if type(request) is not CodingAppHostCompositionRequestV1:
        raise TypeError("Coding AppHost composition request is invalid")
    product_factory = CodingAppHostProductFactoryV1(request.attempt_factory)

    def catalog_input() -> AppHostCatalogInputV1:
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
        return AppHostCatalogInputV1(
            generation_id=request.generation_id,
            products=(product,),
            profiles=request.profiles,
        )

    def bind(runtime: AppHostRuntimeV1) -> CodingAppHostCompositionV1:
        return CodingAppHostCompositionV1(
            activation=request.activation,
            generation_id=request.generation_id,
            runtime=runtime,
            product_factory=product_factory,
            rollback_control=request.rollback_control,
            shutdown_budget=request.shutdown_budget,
            _construction_token=_CONSTRUCTION_TOKEN,
        )

    return await _construct_product_apphost(
        catalog_input,
        request.sessions,
        product_factory,
        bind,
        cleanup_failure=CodingAppHostCompositionError(
            code="coding_apphost_composition_cleanup_incomplete"
        ),
        construction_failure=CodingAppHostCompositionError(
            code="coding_apphost_composition_unavailable"
        ),
        close_runtime_on_failure=False,
        join_owned=_await_owned_task,
        caught=(asyncio.CancelledError, Exception),
    )


def _require_opaque(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 128
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"Coding AppHost {name} is invalid")


def _require_async_method(value: object, name: str) -> None:
    if not inspect.iscoroutinefunction(_method_descriptor(value, name)):
        raise TypeError(f"Coding AppHost {name} port is invalid")


def _require_sync_method(value: object, name: str) -> None:
    descriptor = _method_descriptor(value, name)
    if not callable(descriptor) or inspect.iscoroutinefunction(descriptor):
        raise TypeError(f"Coding AppHost {name} port is invalid")


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

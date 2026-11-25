"""Default-dark Coding Product integration for the AppHost G8 join."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from secrets import token_hex
from typing import Literal, Protocol, cast

from loushang.apphost import (
    AdmissionGenerationSourceV1,
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    OpenedProductCandidateV1,
    ProductCandidateValidatorV1,
    ProductDescriptorV1,
    ProductProfileBindingV1,
    ProductRegistrationV1,
    ScopedProductRuntimeV1,
    SessionBindingKeyV1,
)
from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.hosted._worker_canary import CodingProductWorkerCanaryStatusV1
from loushang.harness.runtime._owned_tasks import _UnpublishedProductOwners
from loushang.harness.worker import ProductWorkerActivationReceiptV1
from loushang.harness.worker._product_attempt_lifecycle import (
    _BoundProductWorkerAttempt,
)

CODING_APPHOST_PRODUCT_JOIN_VERSION = 1

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT_ID = re.compile(r"[0-9a-f]{32}\Z")
_STATUS_CODE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")


class CodingAppHostProductError(RuntimeError):
    """Stable Product-owned failure hidden by the AppHost error boundary."""

    def __init__(self, *, code: str) -> None:
        if not isinstance(code, str) or _STATUS_CODE.fullmatch(code) is None:
            raise ValueError("Coding AppHost Product error code is invalid")
        self.code = code
        super().__init__(code)


class CodingAppHostWorkerAttemptV1(Protocol):
    """Fresh Product-owned Worker attempt consumed by one AppHost binding."""

    @property
    def status(self) -> CodingProductWorkerCanaryStatusV1: ...

    def receipt_for_entrypoint(
        self,
        entrypoint: str,
    ) -> ProductWorkerActivationReceiptV1 | None: ...

    async def recover(self) -> tuple[str, ...]: ...

    async def start(
        self,
        *,
        correlation_id: str,
    ) -> CodingProductWorkerCanaryStatusV1: ...

    async def close(self) -> None: ...


class CodingAppHostWorkerAttemptFactoryV1(Protocol):
    """Synchronous effect-free minting seam for one unpublished attempt."""

    def create_attempt(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> CodingAppHostWorkerAttemptV1: ...


@dataclass(frozen=True, slots=True)
class CodingAppHostProductBindingV1:
    """Frozen non-owning Worker facts visible to Product profile adapters."""

    binding_key: SessionBindingKeyV1
    receipt_fingerprint: str
    attempt_id: str
    owner_generation: int
    required: bool
    requested_owner: Literal["hosting"]
    effective_owner: Literal["hosting"]
    readiness: Literal["ready", "degraded"]
    status_code: str
    join_version: int = CODING_APPHOST_PRODUCT_JOIN_VERSION

    def __post_init__(self) -> None:
        if type(self.binding_key) is not SessionBindingKeyV1:
            raise TypeError("Coding AppHost binding key is invalid")
        if _SHA256.fullmatch(self.receipt_fingerprint) is None:
            raise ValueError("Coding AppHost receipt fingerprint is invalid")
        if _ATTEMPT_ID.fullmatch(self.attempt_id) is None:
            raise ValueError("Coding AppHost attempt identity is invalid")
        if type(self.owner_generation) is not int or self.owner_generation < 1:
            raise ValueError("Coding AppHost owner generation is invalid")
        if type(self.required) is not bool:
            raise TypeError("Coding AppHost requiredness is invalid")
        if self.requested_owner != "hosting" or self.effective_owner != "hosting":
            raise ValueError("Coding AppHost Worker owner is invalid")
        if self.readiness not in {"ready", "degraded"}:
            raise ValueError("Coding AppHost readiness is invalid")
        if self.required and self.readiness != "ready":
            raise ValueError("Required Coding AppHost Worker is not ready")
        if _STATUS_CODE.fullmatch(self.status_code) is None:
            raise ValueError("Coding AppHost status code is invalid")
        if self.join_version != CODING_APPHOST_PRODUCT_JOIN_VERSION:
            raise ValueError("Coding AppHost Product join version is unsupported")


class _WorkerAttemptOwner(_BoundProductWorkerAttempt[CodingProductWorkerCanaryStatusV1]):
    __slots__ = ()
    _status_type = CodingProductWorkerCanaryStatusV1
    _failure = staticmethod(lambda reason: CodingAppHostProductError(code=f"coding_apphost_{reason}"))


class _CodingProductProfileBinding:
    __slots__ = ("_binding",)

    def __init__(self, binding: CodingAppHostProductBindingV1) -> None:
        self._binding = binding

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding.binding_key

    @property
    def opaque_binding(self) -> object:
        return self._binding


class _CodingScopedProductRuntime:
    __slots__ = ("_attempt", "_binding", "_profile")

    def __init__(
        self,
        attempt: _WorkerAttemptOwner,
        binding: CodingAppHostProductBindingV1,
    ) -> None:
        self._attempt = attempt
        self._binding = binding
        self._profile = _CodingProductProfileBinding(binding)

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding.binding_key

    @property
    def profile_binding(self) -> ProductProfileBindingV1:
        return self._profile

    async def close(self) -> None:
        await self._attempt.close()


class CodingAppHostProductFactoryV1:
    """Concrete Coding Product factory implementing the default-dark G8 join."""

    __slots__ = (
        "_correlation_id_factory",
        "_create_attempt",
        "_unpublished",
    )

    def __init__(
        self,
        attempt_factory: CodingAppHostWorkerAttemptFactoryV1,
        *,
        correlation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        create_attempt = getattr(attempt_factory, "create_attempt", None)
        if not callable(create_attempt) or inspect.iscoroutinefunction(create_attempt):
            raise TypeError("Coding AppHost attempt factory must be synchronous")
        if correlation_id_factory is not None and not callable(
            correlation_id_factory
        ):
            raise TypeError("Coding AppHost correlation id factory is invalid")
        self._create_attempt = create_attempt
        self._correlation_id_factory = correlation_id_factory or (
            lambda: token_hex(16)
        )
        self._unpublished = _UnpublishedProductOwners[_WorkerAttemptOwner]()

    @property
    def pending_cleanup_count(self) -> int:
        return self._unpublished.pending_count

    async def create_runtime(
        self,
        candidate: OpenedProductCandidateV1,
    ) -> ScopedProductRuntimeV1:
        await self.settle_pending_cleanup()
        key, opaque = _candidate_facts(candidate)
        if key.product_id != CODING_PRODUCT_ID:
            raise CodingAppHostProductError(code="coding_apphost_product_mismatch")
        raw = self._create_attempt(
            binding_key=key,
            opaque_session_binding=opaque,
        )
        try:
            owner = _WorkerAttemptOwner(raw)
        except BaseException:
            raise CodingAppHostProductError(
                code="coding_apphost_attempt_unowned"
            ) from None
        self._unpublished.adopt(owner)
        try:
            owner.bind()
            receipt = owner.receipt()
            _require_receipt_binding(receipt, key)
            await owner.recover()
            status = await owner.start(correlation_id=self._correlation_id())
            binding = _bind_status(key, receipt, status)
            if owner.status != status:
                raise CodingAppHostProductError(code="coding_apphost_status_changed")
        except BaseException as error:
            await self._unpublished.abort(
                owner,
                failure=CodingAppHostProductError(code="coding_apphost_cleanup_incomplete"),
                join_close=True,
            )
            if isinstance(error, (asyncio.CancelledError, CodingAppHostProductError)):
                raise
            raise CodingAppHostProductError(
                code="coding_apphost_runtime_unavailable"
            ) from None
        self._unpublished.publish(owner)
        return _CodingScopedProductRuntime(owner, binding)

    async def settle_pending_cleanup(self) -> None:
        if not await self._unpublished.retry_cleanup():
            raise CodingAppHostProductError(code="coding_apphost_cleanup_incomplete")

    async def close(self) -> None:
        await self.settle_pending_cleanup()

    def _correlation_id(self) -> str:
        value = self._correlation_id_factory()
        if (
            not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) > 128
            or any(character.isspace() for character in value)
        ):
            raise CodingAppHostProductError(
                code="coding_apphost_correlation_invalid"
            )
        return value


def coding_apphost_product_registration(
    *,
    generation_id: str,
    product_version: str,
    compatibility_id: str,
    supported_profile_ids: tuple[str, ...],
    admission_source: AdmissionGenerationSourceV1,
    candidate_validator: ProductCandidateValidatorV1,
    product_factory: CodingAppHostProductFactoryV1,
) -> ProductRegistrationV1:
    """Register one explicitly outer-owned Coding Product factory."""

    if type(product_factory) is not CodingAppHostProductFactoryV1:
        raise TypeError("Coding AppHost Product factory is invalid")
    return ProductRegistrationV1(
        descriptor=ProductDescriptorV1(
            product_id=CODING_PRODUCT_ID,
            product_version=product_version,
            compatibility_id=compatibility_id,
            supported_profile_ids=supported_profile_ids,
        ),
        factory=product_factory,
        candidate_validator=candidate_validator,
        admission_identity=AdmissionIdentityV1(
            generation_id=generation_id,
            subject_kind=AppHostAdmissionSubjectKind.PRODUCT,
            subject_id=CODING_PRODUCT_ID,
        ),
        admission_source=admission_source,
    )


def _candidate_facts(
    candidate: OpenedProductCandidateV1,
) -> tuple[SessionBindingKeyV1, object]:
    try:
        key = candidate.binding_key
        opaque = candidate.opaque_binding
    except BaseException:
        raise CodingAppHostProductError(code="coding_apphost_candidate_invalid") from None
    if type(key) is not SessionBindingKeyV1:
        raise CodingAppHostProductError(code="coding_apphost_candidate_invalid")
    return key, opaque


def _require_receipt_binding(
    receipt: ProductWorkerActivationReceiptV1,
    key: SessionBindingKeyV1,
) -> None:
    policy = receipt.policy
    if (
        policy.product_id != key.product_id
        or policy.session_id != key.session_id
        or not policy.enabled
        or policy.requested_owner != "hosting"
        or not policy.no_fallback
    ):
        raise CodingAppHostProductError(code="coding_apphost_receipt_mismatch")


def _bind_status(
    key: SessionBindingKeyV1,
    receipt: ProductWorkerActivationReceiptV1,
    status: CodingProductWorkerCanaryStatusV1,
) -> CodingAppHostProductBindingV1:
    policy = receipt.policy
    if (
        status.receipt_fingerprint != receipt.fingerprint
        or status.attempt_id is None
        or status.owner_generation != policy.owner_selection_generation
        or status.required != policy.effective_required
        or status.requested_owner != "hosting"
        or status.effective_owner != "hosting"
        or status.readiness not in {"ready", "degraded"}
        or (policy.effective_required and status.readiness != "ready")
    ):
        raise CodingAppHostProductError(code="coding_apphost_status_mismatch")
    return CodingAppHostProductBindingV1(
        binding_key=key,
        receipt_fingerprint=receipt.fingerprint,
        attempt_id=status.attempt_id,
        owner_generation=cast(int, status.owner_generation),
        required=status.required,
        requested_owner="hosting",
        effective_owner="hosting",
        readiness=cast(Literal["ready", "degraded"], status.readiness),
        status_code=status.code,
    )


__all__ = [
    "CODING_APPHOST_PRODUCT_JOIN_VERSION",
    "CodingAppHostProductBindingV1",
    "CodingAppHostProductError",
    "CodingAppHostProductFactoryV1",
    "CodingAppHostWorkerAttemptFactoryV1",
    "CodingAppHostWorkerAttemptV1",
    "coding_apphost_product_registration",
]

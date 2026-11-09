"""Bind Coding Resume intent context to the original Worker C5 owner."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock

from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
)

from .resume_activation_attempt import CodingResumeRecoveryRequired
from .resume_activation_attempt_v2 import (
    CodingActivationAttemptV2,
    CodingResumeEffectOwnerV1,
)


class CodingWorkerResumeParentError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _parent_failure(code: str) -> CodingWorkerResumeParentError:
    return CodingWorkerResumeParentError("coding_worker_resume_" + code)


def prepare_coding_worker_resume_effect_owner(
    *, product_id: str, product_scope_id: str
) -> CodingResumeEffectOwnerV1:
    """Freeze the original C5 lookup obligation without opening its journal."""

    return CodingResumeEffectOwnerV1(
        owner_id="harness.worker-activation",
        scope_digest=ProductWorkerActivationCoordinator.resume_parent_scope_digest(
            product_id=product_id,
            product_scope_id=product_scope_id,
        ),
        contract_digest=(
            ProductWorkerActivationCoordinator.resume_parent_contract_digest_value()
        ),
        phases=("reservation", "start"),
    )


class CodingWorkerResumeSettlementBinding:
    """Read exact live/no-start/cleanup facts from the original C5 owner."""

    def __init__(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        context: ResumeEffectParentContextV1,
    ) -> None:
        if (
            type(receipt) is not ProductWorkerActivationReceiptV1
            or type(context) is not ResumeEffectParentContextV1
            or context.product_id != receipt.policy.product_id
            or context.session_id != receipt.policy.session_id
            or context.owner_id != "harness.worker-activation"
            or context.scope_digest
            != ProductWorkerActivationCoordinator.resume_parent_scope_digest(
                product_id=receipt.policy.product_id,
                product_scope_id=receipt.policy.product_scope_id,
            )
            or context.contract_digest
            != ProductWorkerActivationCoordinator.resume_parent_contract_digest_value()
        ):
            raise TypeError("Coding Worker Resume settlement inputs are invalid")
        self._receipt = receipt
        self._context = context
        self._coordinator: ProductWorkerActivationCoordinator | None = None
        self._lock = RLock()

    def matches(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        context: ResumeEffectParentContextV1,
    ) -> bool:
        """Return whether one pending Host supplied the exact frozen inputs."""

        return receipt == self._receipt and context == self._context

    def bind(self, coordinator: ProductWorkerActivationCoordinator) -> None:
        """Retain the actual attempt owner after native evidence is bound."""

        if not isinstance(coordinator, ProductWorkerActivationCoordinator):
            raise TypeError("Coding Worker Resume settlement owner is invalid")
        snapshot = _snapshot(coordinator, self._context)
        if snapshot is None:
            raise CodingWorkerResumeParentError("coding_worker_resume_parent_missing")
        with self._lock:
            if self._coordinator is not None and self._coordinator is not coordinator:
                raise CodingWorkerResumeParentError(
                    "coding_worker_resume_settlement_owner_changed"
                )
            self._coordinator = coordinator

    def require_current(self, attempt: CodingActivationAttemptV2) -> None:
        """Require sealed exact membership and current live or cleanup proof."""

        if type(attempt) is not CodingActivationAttemptV2:
            raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
        owners = {
            owner.owner_id: owner
            for owner in attempt.effect_owners
            if owner.owner_id == "harness.worker-activation"
        }
        owner = owners.get("harness.worker-activation")
        if owner is None or attempt.parent_context(owner) != self._context:
            raise CodingResumeRecoveryRequired("input.effect_owner_set_unsupported")
        with self._lock:
            coordinator = self._coordinator
        if coordinator is None:
            raise CodingResumeRecoveryRequired("input.effect_settlement_unknown")
        ProductWorkerActivationCoordinator.require_resume_parent_settlement(
            coordinator,
            self._context,
            receipt=self._receipt,
            failure=lambda _code: CodingResumeRecoveryRequired(
                "input.effect_settlement_unknown"
            ),
        )


def _snapshot(
    coordinator: ProductWorkerActivationCoordinator,
    context: ResumeEffectParentContextV1,
) -> Mapping[str, object] | None:
    return ProductWorkerActivationCoordinator._resume_parent_if_known(
        coordinator, context
    )


def enroll_coding_worker_resume_parent(
    *,
    coordinator: ProductWorkerActivationCoordinator,
    receipt: ProductWorkerActivationReceiptV1,
    context: ResumeEffectParentContextV1 | None,
) -> Mapping[str, object] | None:
    """Enroll or recover the exact durable parent before payload preparation."""

    return ProductWorkerActivationCoordinator.observe_or_enroll_resume_parent(
        coordinator,
        context=context,
        failure=_parent_failure,
        receipt=receipt,
    )


def seal_coding_worker_resume_parent(
    *,
    coordinator: ProductWorkerActivationCoordinator,
    context: ResumeEffectParentContextV1 | None,
) -> Mapping[str, object] | None:
    """Seal the exact native membership after Worker C5 publication."""

    return ProductWorkerActivationCoordinator.seal_current_resume_parent(
        coordinator,
        context=context,
        failure=_parent_failure,
    )


__all__ = [
    "CodingWorkerResumeParentError",
    "CodingWorkerResumeSettlementBinding",
    "enroll_coding_worker_resume_parent",
    "prepare_coding_worker_resume_effect_owner",
    "seal_coding_worker_resume_parent",
]

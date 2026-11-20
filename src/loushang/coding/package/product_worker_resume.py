"""Bind Coding Resume intent context to the original Worker C5 owner."""

from __future__ import annotations

from collections.abc import Mapping

from loushang.coding.resume.activation_attempt import CodingResumeRecoveryRequired
from loushang.coding.resume.activation_attempt_v2 import (
    CodingActivationAttemptV2,
    CodingResumeEffectOwnerV1,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    _WorkerResumeSettlementMethods,
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


class CodingWorkerResumeSettlementBinding(_WorkerResumeSettlementMethods):
    """Bind Coding intent policy to the original Worker C5 settlement owner."""

    def __init__(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        context: ResumeEffectParentContextV1,
    ) -> None:
        self._initialize_settlement(
            receipt=receipt,
            context=context,
            invalid_inputs="Coding Worker Resume settlement inputs are invalid",
        )

    def bind(self, coordinator: ProductWorkerActivationCoordinator) -> None:
        """Retain the actual attempt owner after native evidence is bound."""
        self._bind_settlement(
            coordinator,
            invalid_owner="Coding Worker Resume settlement owner is invalid",
            failure=lambda code: CodingWorkerResumeParentError(
                "coding_worker_resume_" + code
            ),
        )

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
        self._require_current_settlement(
            failure=lambda _code: CodingResumeRecoveryRequired(
                "input.effect_settlement_unknown"
            ),
        )


def _resume_parent_matches_settlement(
    receipt: ProductWorkerActivationReceiptV1,
    context: ResumeEffectParentContextV1 | None,
    settlement: CodingWorkerResumeSettlementBinding | None,
) -> bool:
    if (
        (context is not None and type(context) is not ResumeEffectParentContextV1)
        or ((context is None) != (settlement is None))
        or (
            settlement is not None
            and (
                not isinstance(settlement, CodingWorkerResumeSettlementBinding)
                or context is None
                or not settlement.matches(receipt=receipt, context=context)
            )
        )
    ):
        return False
    return True


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

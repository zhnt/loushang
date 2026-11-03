"""Bind Coding Resume intent context to the original Worker C5 owner."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock

from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    _ActivationRejected,
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
            raise CodingWorkerResumeParentError(
                "coding_worker_resume_parent_missing"
            )
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
        try:
            snapshot = coordinator.resume_parent_snapshot(self._context)
            admission = coordinator.evaluate(self._receipt.policy, self._receipt)
        except (ValueError, _ActivationRejected) as error:
            raise CodingResumeRecoveryRequired(
                "input.effect_settlement_unknown"
            ) from error
        native_attempts = snapshot.get("nativeAttempts")
        if (
            snapshot.get("sealed") is not True
            or not isinstance(snapshot.get("membershipDigest"), str)
            or not isinstance(native_attempts, Mapping)
            or not native_attempts
        ):
            raise CodingResumeRecoveryRequired("input.effect_settlement_unknown")
        current_live = admission.get("reason") == "admitted"
        for raw in native_attempts.values():
            if not isinstance(raw, Mapping):
                raise CodingResumeRecoveryRequired("input.effect_settlement_unknown")
            phase = raw.get("phase")
            exact = (
                raw.get("receiptFingerprint") == self._receipt.fingerprint
                and raw.get("policyFingerprint") == self._receipt.policy.fingerprint
                and raw.get("ownerGeneration")
                == self._receipt.policy.owner_selection_generation
                and raw.get("cleanupContractVersion") == 2
            )
            if not exact:
                raise CodingResumeRecoveryRequired("input.effect_settlement_unknown")
            if phase == "published":
                if (
                    not current_live
                    or raw.get("readiness") != "ready"
                    or raw.get("cleanupSettlement") is not None
                    or raw.get("cleanupDebt") is not None
                    or raw.get("protocolTerminal") is not False
                    or raw.get("domainRetired") is not False
                ):
                    raise CodingResumeRecoveryRequired(
                        "input.effect_settlement_unknown"
                    )
                continue
            settlement = raw.get("cleanupSettlement")
            if (
                phase != "settled"
                or not isinstance(settlement, Mapping)
                or settlement.get("settlementVersion") != 2
                or settlement.get("protocolTerminal") is not True
                or settlement.get("domainRetired") is not True
                or settlement.get("treeSettled") is not True
                or settlement.get("nativeContainmentSettled") is not True
                or raw.get("cleanupDebt") is not None
            ):
                raise CodingResumeRecoveryRequired("input.effect_settlement_unknown")


def _snapshot(
    coordinator: ProductWorkerActivationCoordinator,
    context: ResumeEffectParentContextV1,
) -> Mapping[str, object] | None:
    try:
        return coordinator.resume_parent_snapshot(context)
    except _ActivationRejected as error:
        if error.reason.value == "resume_parent_unknown":
            return None
        raise


def enroll_coding_worker_resume_parent(
    *,
    coordinator: ProductWorkerActivationCoordinator,
    receipt: ProductWorkerActivationReceiptV1,
    context: ResumeEffectParentContextV1 | None,
) -> Mapping[str, object] | None:
    """Enroll or recover the exact durable parent before payload preparation."""

    if context is None:
        return None
    if (
        type(context) is not ResumeEffectParentContextV1
        or context.product_id != receipt.policy.product_id
        or context.owner_id != "harness.worker-activation"
        or context.scope_digest
        != coordinator.resume_parent_scope_digest(
            product_id=receipt.policy.product_id,
            product_scope_id=receipt.policy.product_scope_id,
        )
        or context.contract_digest != coordinator.resume_parent_contract_digest
    ):
        raise CodingWorkerResumeParentError(
            "coding_worker_resume_parent_context_mismatch"
        )
    existing = _snapshot(coordinator, context)
    if existing is not None:
        if existing["sealed"] is True:
            raise CodingWorkerResumeParentError(
                "coding_worker_resume_parent_already_sealed"
            )
        return existing
    state = coordinator.snapshot()
    revision = state.get("stateRevision")
    if type(revision) is not int or revision < 1:
        raise CodingWorkerResumeParentError("coding_worker_resume_parent_state_invalid")
    try:
        coordinator.enroll_resume_parent(
            context,
            policy=receipt.policy,
            expected_state_revision=revision,
        )
    except Exception:
        # A failed durable acknowledgement may still have committed the exact
        # parent. Re-read the original owner before deciding that it is unknown.
        recovered = _snapshot(coordinator, context)
        if recovered is None:
            raise
        if recovered["sealed"] is True:
            raise CodingWorkerResumeParentError(
                "coding_worker_resume_parent_already_sealed"
            )
        return recovered
    enrolled = _snapshot(coordinator, context)
    if enrolled is None:
        raise CodingWorkerResumeParentError(
            "coding_worker_resume_parent_enrollment_unknown"
        )
    return enrolled


def seal_coding_worker_resume_parent(
    *,
    coordinator: ProductWorkerActivationCoordinator,
    context: ResumeEffectParentContextV1 | None,
) -> Mapping[str, object] | None:
    """Seal the exact native membership after Worker C5 publication."""

    if context is None:
        return None
    snapshot = _snapshot(coordinator, context)
    if snapshot is None:
        raise CodingWorkerResumeParentError("coding_worker_resume_parent_missing")
    if snapshot["sealed"] is True:
        return snapshot
    native_attempts = snapshot["nativeAttempts"]
    if not isinstance(native_attempts, Mapping) or not native_attempts:
        raise CodingWorkerResumeParentError(
            "coding_worker_resume_parent_membership_empty"
        )
    revision = snapshot["stateRevision"]
    if type(revision) is not int or revision < 1:
        raise CodingWorkerResumeParentError("coding_worker_resume_parent_state_invalid")
    return coordinator.seal_resume_parent(
        context,
        expected_state_revision=revision,
    )


__all__ = [
    "CodingWorkerResumeParentError",
    "CodingWorkerResumeSettlementBinding",
    "enroll_coding_worker_resume_parent",
    "prepare_coding_worker_resume_effect_owner",
    "seal_coding_worker_resume_parent",
]

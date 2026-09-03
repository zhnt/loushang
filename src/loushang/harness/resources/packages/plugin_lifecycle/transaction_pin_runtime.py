"""Dark phase composition for the PLC9B transaction-pin boundary."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
    PackageLifecycleStatusV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinJournalError,
    PackageTransactionPinPort,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)


@dataclass(frozen=True, slots=True)
class PackageTransactionPinExecutionResult:
    status: PackageLifecycleStatusV1
    candidate: VerifiedPackageClosureCandidate | None = None
    receipt: PackageTransactionPinReceiptV1 | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, PackageLifecycleStatusV1):
            raise TypeError("Package lifecycle status is required")
        if self.candidate is not None and not isinstance(
            self.candidate,
            VerifiedPackageClosureCandidate,
        ):
            raise TypeError("Verified Package closure candidate is required")
        if self.receipt is not None and not isinstance(
            self.receipt,
            PackageTransactionPinReceiptV1,
        ):
            raise TypeError("Package transaction pin receipt is required")
        if self.candidate is not None and (
            self.status.disposition != "active"
            or self.status.phase != "transaction_pinned"
            or self.receipt is None
            or self.receipt.state != "acquired"
        ):
            raise ValueError("Pinned Package candidate lacks active pin evidence")


class PackageVerifiedClosurePlanEvidencePort(Protocol):
    """Read-only adjacent evidence; grants no resolver or journal authority."""

    def plan(
        self,
        *,
        operation_id: str,
        attempt_epoch: int,
    ) -> VerifiedClosurePlanV2 | None: ...


class PackageTransactionPinLifecycleOwner:
    """Acquire exact retention, journal it, then win the adjacent phase CAS."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        closure_plans: PackageVerifiedClosurePlanEvidencePort,
        retention: PackageTransactionPinPort,
        pin_journal: PackageTransactionPinJournal,
    ) -> None:
        if not isinstance(kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle owner is required")
        if not callable(getattr(retention, "acquire", None)) or not callable(
            getattr(retention, "release", None)
        ):
            raise TypeError("Package transaction retention owner is required")
        if not callable(getattr(closure_plans, "plan", None)):
            raise TypeError("Verified Package closure plan evidence is required")
        if not isinstance(pin_journal, PackageTransactionPinJournal):
            raise TypeError("Package transaction pin journal is required")
        self._kernel = kernel
        self._closure_plans = closure_plans
        self._retention = retention
        self._pin_journal = pin_journal

    def pin(
        self,
        candidate: VerifiedPackageClosureCandidate,
        *,
        recovery_identity: str,
    ) -> PackageTransactionPinExecutionResult:
        if not isinstance(candidate, VerifiedPackageClosureCandidate):
            raise TypeError("Verified Package closure candidate is required")
        plan = candidate.plan
        status = self._kernel.status(plan.operation_id)
        if status is None:
            candidate.suspend_for_recovery()
            raise PackageLifecycleJournalError(
                "Package operation does not exist",
                code="package_operation_not_found",
                path=self._kernel.journal.path,
            )
        if not _can_pin(status, candidate):
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        try:
            durable_plan = self._closure_plans.plan(
                operation_id=plan.operation_id,
                attempt_epoch=plan.attempt_epoch,
            )
        except Exception:
            candidate.suspend_for_recovery()
            raise
        if durable_plan != plan:
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        assert status.classification is not None
        current_request = PackageTransactionPinRequestV1.create(
            plan,
            request_fingerprint=status.request_fingerprint,
            classification_fingerprint=status.classification.evidence_ref,
            recovery_identity=recovery_identity,
        )
        try:
            durable = self._pin_journal.current_for_operation(status.operation_id)
        except PackageTransactionPinJournalError:
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if durable is not None and durable.state != "acquired":
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if durable is not None and not self._request_covers_current_attempt(
            durable.pin_request,
            current_request,
        ):
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        owner_request = current_request if durable is None else durable.pin_request
        try:
            receipt = self._retention.acquire(owner_request)
        except Exception:
            candidate.suspend_for_recovery()
            raise
        if (
            not isinstance(receipt, PackageTransactionPinReceiptV1)
            or receipt.state != "acquired"
            or (durable is not None and receipt != durable)
        ):
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if not self._request_covers_current_attempt(
            receipt.pin_request,
            current_request,
        ):
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        try:
            self._pin_journal.append(receipt)
        except PackageTransactionPinJournalError:
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                ),
                receipt=receipt,
            )
        if status.phase == "transaction_pinned":
            return PackageTransactionPinExecutionResult(
                status=status,
                candidate=candidate,
                receipt=receipt,
            )
        try:
            pinned = self._kernel.advance(
                status.operation_id,
                next_phase="transaction_pinned",
                expected_phase="closure_verified",
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
        except PackageLifecycleJournalError:
            current = self._kernel.status(status.operation_id)
            if current is not None and (
                current.disposition == "active"
                and current.phase == "transaction_pinned"
            ):
                return PackageTransactionPinExecutionResult(
                    status=current,
                    candidate=candidate,
                    receipt=receipt,
                )
            candidate.suspend_for_recovery()
            if current is None:
                raise
            return PackageTransactionPinExecutionResult(
                status=current,
                receipt=receipt,
            )
        if pinned.disposition != "active" or pinned.phase != "transaction_pinned":
            candidate.suspend_for_recovery()
            return PackageTransactionPinExecutionResult(
                status=pinned,
                receipt=receipt,
            )
        return PackageTransactionPinExecutionResult(
            status=pinned,
            candidate=candidate,
            receipt=receipt,
        )

    def recover(
        self,
        operation_id: str,
        *,
        recovery_identity: str,
    ) -> PackageTransactionPinExecutionResult:
        """Revalidate a durable pin without requiring an in-memory candidate."""

        status = self._kernel.status(operation_id)
        if status is None:
            raise PackageLifecycleJournalError(
                "Package operation does not exist",
                code="package_operation_not_found",
                path=self._kernel.journal.path,
            )
        if (
            status.phase != "transaction_pinned"
            or status.disposition not in {"active", "retryable_failure"}
            or status.classification is None
            or status.classification.decision != "plugin_bound"
            or status.classification.request_fingerprint != status.request_fingerprint
        ):
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        try:
            plan = self._closure_plans.plan(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
            )
            durable = self._pin_journal.current_for_operation(status.operation_id)
        except PackageTransactionPinJournalError:
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if plan is None or durable is None or durable.state != "acquired":
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        current_request = PackageTransactionPinRequestV1.create(
            plan,
            request_fingerprint=status.request_fingerprint,
            classification_fingerprint=status.classification.evidence_ref,
            recovery_identity=recovery_identity,
        )
        if not self._request_covers_current_attempt(
            durable.pin_request,
            current_request,
        ):
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        receipt = self._retention.acquire(durable.pin_request)
        if (
            not isinstance(receipt, PackageTransactionPinReceiptV1)
            or receipt != durable
            or receipt.state != "acquired"
        ):
            return PackageTransactionPinExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        return PackageTransactionPinExecutionResult(
            status=status,
            receipt=receipt,
        )

    def _request_covers_current_attempt(
        self,
        acquired: PackageTransactionPinRequestV1,
        current: PackageTransactionPinRequestV1,
    ) -> bool:
        if (
            acquired.operation_id != current.operation_id
            or acquired.attempt_epoch > current.attempt_epoch
            or acquired.request_fingerprint != current.request_fingerprint
            or acquired.classification_fingerprint != current.classification_fingerprint
            or acquired.prepublication_graph_digest
            != current.prepublication_graph_digest
            or acquired.recovery_identity != current.recovery_identity
            or acquired.root_target_id != current.root_target_id
            or acquired.targets != current.targets
            or acquired.pin_kind != current.pin_kind
        ):
            return False
        try:
            durable = self._closure_plans.plan(
                operation_id=acquired.operation_id,
                attempt_epoch=acquired.attempt_epoch,
            )
            if durable is None:
                return False
            expected = PackageTransactionPinRequestV1.create(
                durable,
                request_fingerprint=acquired.request_fingerprint,
                classification_fingerprint=acquired.classification_fingerprint,
                recovery_identity=acquired.recovery_identity,
            )
        except Exception:
            return False
        return expected == acquired


def _can_pin(
    status: PackageLifecycleStatusV1,
    candidate: VerifiedPackageClosureCandidate,
) -> bool:
    return bool(
        status.disposition == "active"
        and status.phase in {"closure_verified", "transaction_pinned"}
        and status.attempt_epoch == candidate.plan.attempt_epoch
        and status.classification is not None
        and status.classification.decision == "plugin_bound"
        and status.classification.request_fingerprint == status.request_fingerprint
    )


def _local_refusal(
    status: PackageLifecycleStatusV1,
    *,
    code: str,
) -> PackageLifecycleStatusV1:
    evidence_ref = sha256(
        canonical_json_bytes(
            {
                "attemptEpoch": status.attempt_epoch,
                "code": code,
                "operationId": status.operation_id,
                "requestFingerprint": status.request_fingerprint,
                "stage": status.phase,
            }
        )
    ).hexdigest()
    failure = PackageLifecycleFailureV1.for_operation(
        code,
        stage=cast(PackageLifecyclePhase, status.phase),
        operation_id=status.operation_id,
        evidence_ref=evidence_ref,
    )
    return PackageLifecycleStatusV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        phase=status.phase,
        disposition="rejected",
        attempt_epoch=status.attempt_epoch,
        journal_revision=status.journal_revision,
        attempt_revision=status.attempt_revision,
        classification=status.classification,
        failure=failure,
    )


__all__ = [
    "PackageTransactionPinExecutionResult",
    "PackageTransactionPinLifecycleOwner",
    "PackageVerifiedClosurePlanEvidencePort",
]

"""Dark lifecycle-phase owner for durable PLC9B closure verification."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageAcquisitionError,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    PackageClosureBudgetV1,
    PackageClosureVerificationError,
    PackageResolutionEnvironmentV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
    PackageClosureResolutionJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageClosureCleanupDebtError,
    PackageDependencyResolutionError,
    PackageRecursiveClosureRequestV2,
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageArtifactExecutionRequestV1,
    PackageArtifactExecutionResult,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageWheelVerificationError,
    VerifiedWheelCandidate,
)

PACKAGE_CLOSURE_EXECUTION_REQUEST_VERSION = 2


class PackageVerifiedRootOwnerPort(Protocol):
    def execute(
        self,
        execution: PackageArtifactExecutionRequestV1,
    ) -> PackageArtifactExecutionResult: ...

    def reacquire(
        self,
        execution: PackageArtifactExecutionRequestV1,
    ) -> PackageArtifactExecutionResult: ...


class PackageRecursiveClosureBuilderPort(Protocol):
    def build(
        self,
        root: VerifiedWheelCandidate,
        request: PackageRecursiveClosureRequestV2,
    ) -> VerifiedPackageClosureCandidate: ...

    def reacquire(
        self,
        root: VerifiedWheelCandidate,
        request: PackageRecursiveClosureRequestV2,
    ) -> VerifiedPackageClosureCandidate: ...


@dataclass(frozen=True, slots=True)
class PackageClosureExecutionRequestV2:
    artifact: PackageArtifactExecutionRequestV1
    resolution_environment: PackageResolutionEnvironmentV1
    budgets: PackageClosureBudgetV1
    root_extras: tuple[str, ...] = ()
    request_version: int = PACKAGE_CLOSURE_EXECUTION_REQUEST_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, PackageArtifactExecutionRequestV1):
            raise TypeError("Package artifact execution request is required")
        if not isinstance(self.resolution_environment, PackageResolutionEnvironmentV1):
            raise TypeError("Package resolution environment is required")
        if not isinstance(self.budgets, PackageClosureBudgetV1):
            raise TypeError("Package closure budgets are required")
        if self.root_extras != tuple(sorted(set(self.root_extras))):
            raise ValueError("Root Package extras must be canonical and unique")
        if self.root_extras:
            parsed = NormalizedPackageRequirementV1.parse(
                f"root[{','.join(self.root_extras)}]"
            )
            if parsed.extras != self.root_extras:
                raise ValueError("Root Package extras must be canonical and unique")
        if self.request_version != PACKAGE_CLOSURE_EXECUTION_REQUEST_VERSION:
            raise ValueError("Unsupported Package closure execution request")


@dataclass(frozen=True, slots=True)
class PackageClosureExecutionResult:
    status: PackageLifecycleStatusV1
    candidate: VerifiedPackageClosureCandidate | None = None
    cleanup_status: PackageQuarantineCleanupStatusV1 | None = None

    def __post_init__(self) -> None:
        if self.candidate is not None and not isinstance(
            self.candidate,
            VerifiedPackageClosureCandidate,
        ):
            raise ValueError("Package closure candidate has an invalid type")
        if (
            self.status.phase == "closure_verified"
            and self.status.disposition == "active"
        ):
            if self.candidate is None:
                raise ValueError("Verified closure status requires a candidate")
        elif self.candidate is not None and not (
            self.status.phase == "transaction_pinned"
            and self.status.disposition == "active"
        ):
            raise ValueError("Only verified closure status carries a candidate")
        if self.cleanup_status is not None and (
            self.status.disposition not in {"rejected", "retryable_failure"}
            or self.cleanup_status.target.operation_id != self.status.operation_id
        ):
            raise ValueError("Package closure cleanup status has no failed owner")


class PackageClosureLifecycleOwner:
    """Coordinate root replay, recursive proof, plan journal, and phase CAS."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        artifact_owner: PackageVerifiedRootOwnerPort,
        closure_builder: PackageRecursiveClosureBuilderPort,
        resolution_journal: PackageClosureResolutionJournal,
    ) -> None:
        if not isinstance(kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle kernel is required")
        if any(
            not callable(getattr(artifact_owner, method, None))
            for method in ("execute", "reacquire")
        ):
            raise TypeError("Verified root owner is required")
        if any(
            not callable(getattr(closure_builder, method, None))
            for method in ("build", "reacquire")
        ):
            raise TypeError("Recursive Package closure builder is required")
        if not isinstance(resolution_journal, PackageClosureResolutionJournal):
            raise TypeError("Package closure resolution journal is required")
        self._kernel = kernel
        self._artifact_owner = artifact_owner
        self._closure_builder = closure_builder
        self._resolution_journal = resolution_journal

    def execute(
        self,
        execution: PackageClosureExecutionRequestV2,
    ) -> PackageClosureExecutionResult:
        context = self._execution_context(execution)
        if isinstance(context, PackageClosureExecutionResult):
            return context
        status, request = context
        if (
            status.disposition == "active"
            and status.phase
            in {
                "classified",
                "acquiring",
                "acquired",
                "inspecting",
                "extracted",
                "resolving_closure",
                "closure_verified",
            }
            and status.classification is not None
            and status.classification.decision == "plugin_bound"
        ):
            try:
                self._resolution_journal.bind_basis(
                    PackageClosureResolutionBasisV1(
                        operation_id=status.operation_id,
                        attempt_epoch=status.attempt_epoch,
                        request_fingerprint=status.request_fingerprint,
                        policy_revision=request.policy_revision,
                        quota_profile_revision=request.quota_profile_revision,
                        resolution_environment=execution.resolution_environment,
                        budgets=execution.budgets,
                        root_extras=execution.root_extras,
                    )
                )
            except PackageClosureResolutionJournalError:
                return PackageClosureExecutionResult(
                    status=_local_refusal(
                        status,
                        code="package_operation_identity_conflict",
                    )
                )
        artifact_result = self._artifact_owner.execute(execution.artifact)
        status = artifact_result.status
        root = artifact_result.candidate
        if root is None:
            return PackageClosureExecutionResult(
                status=status,
                cleanup_status=artifact_result.cleanup_status,
            )
        if status.phase == "extracted":
            try:
                status = self._kernel.advance(
                    status.operation_id,
                    next_phase="resolving_closure",
                    expected_phase="extracted",
                    expected_journal_revision=status.journal_revision,
                    expected_attempt_epoch=status.attempt_epoch,
                )
            except PackageLifecycleJournalError:
                root.suspend_for_recovery()
                current = self._kernel.status(status.operation_id)
                if current is None:
                    raise
                if current.disposition == "active":
                    current = _local_refusal(
                        current,
                        code="package_operation_identity_conflict",
                    )
                return PackageClosureExecutionResult(status=current)
            if status.disposition != "active":
                root.suspend_for_recovery()
                return PackageClosureExecutionResult(status=status)
        if status.phase not in {"resolving_closure", "closure_verified"}:
            root.suspend_for_recovery()
            return PackageClosureExecutionResult(status=status)
        closure: VerifiedPackageClosureCandidate | None = None
        try:
            closure = self._closure_builder.build(
                root,
                PackageRecursiveClosureRequestV2(
                    operation_id=status.operation_id,
                    attempt_epoch=status.attempt_epoch,
                    request_fingerprint=status.request_fingerprint,
                    policy_revision=request.policy_revision,
                    resolution_environment=execution.resolution_environment,
                    budgets=execution.budgets,
                    root_extras=execution.root_extras,
                    credential_reference=execution.artifact.credential_reference,
                ),
            )
            durable = self._resolution_journal.plan(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
            )
            if durable is not None and durable != closure.plan:
                closure.suspend_for_recovery()
                return PackageClosureExecutionResult(
                    status=_local_refusal(
                        status,
                        code="package_operation_identity_conflict",
                    )
                )
            self._resolution_journal.append_plan(
                request_fingerprint=status.request_fingerprint,
                plan=closure.plan,
            )
        except PackageClosureResolutionJournalError:
            if closure is not None:
                closure.suspend_for_recovery()
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        except _CLOSURE_REJECTIONS as error:
            return PackageClosureExecutionResult(
                status=self._record_failure(
                    status,
                    code=_failure_code(error),
                ),
                cleanup_status=(
                    error.cleanup_status
                    if isinstance(error, PackageClosureCleanupDebtError)
                    else None
                ),
            )
        if status.phase == "resolving_closure":
            try:
                verified = self._kernel.advance(
                    status.operation_id,
                    next_phase="closure_verified",
                    expected_phase="resolving_closure",
                    expected_journal_revision=status.journal_revision,
                    expected_attempt_epoch=status.attempt_epoch,
                )
            except PackageLifecycleJournalError:
                current = self._kernel.status(status.operation_id)
                if current is not None and (
                    current.phase == "closure_verified"
                    and current.disposition == "active"
                ):
                    return PackageClosureExecutionResult(
                        status=current,
                        candidate=closure,
                    )
                closure.suspend_for_recovery()
                if current is None:
                    raise
                if current.disposition == "active":
                    current = _local_refusal(
                        current,
                        code="package_operation_identity_conflict",
                    )
                return PackageClosureExecutionResult(status=current)
            if verified.disposition != "active":
                closure.suspend_for_recovery()
                return PackageClosureExecutionResult(status=verified)
            status = verified
        return PackageClosureExecutionResult(status=status, candidate=closure)

    def reacquire(
        self,
        execution: PackageClosureExecutionRequestV2,
    ) -> PackageClosureExecutionResult:
        """Rebuild a pinned closure without resolver, Source, or phase authority."""

        context = self._execution_context(execution)
        if isinstance(context, PackageClosureExecutionResult):
            return context
        status, request = context
        if (
            status.disposition != "active"
            or status.phase != "transaction_pinned"
            or status.classification is None
            or status.classification.decision != "plugin_bound"
        ):
            return PackageClosureExecutionResult(status=status)

        expected_basis = PackageClosureResolutionBasisV1(
            operation_id=status.operation_id,
            attempt_epoch=status.attempt_epoch,
            request_fingerprint=status.request_fingerprint,
            policy_revision=request.policy_revision,
            quota_profile_revision=request.quota_profile_revision,
            resolution_environment=execution.resolution_environment,
            budgets=execution.budgets,
            root_extras=execution.root_extras,
        )
        try:
            durable_basis = self._resolution_journal.basis(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
            )
            durable_plan = self._resolution_journal.plan(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
            )
        except PackageClosureResolutionJournalError:
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if durable_basis != expected_basis or durable_plan is None:
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )

        artifact_result = self._artifact_owner.reacquire(execution.artifact)
        root = artifact_result.candidate
        if root is None:
            return PackageClosureExecutionResult(
                status=artifact_result.status,
                cleanup_status=artifact_result.cleanup_status,
            )
        if artifact_result.status != status:
            root.suspend_for_recovery()
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    artifact_result.status,
                    code="package_operation_identity_conflict",
                )
            )
        closure: VerifiedPackageClosureCandidate | None = None
        try:
            closure = self._closure_builder.reacquire(
                root,
                PackageRecursiveClosureRequestV2(
                    operation_id=status.operation_id,
                    attempt_epoch=status.attempt_epoch,
                    request_fingerprint=status.request_fingerprint,
                    policy_revision=request.policy_revision,
                    resolution_environment=execution.resolution_environment,
                    budgets=execution.budgets,
                    root_extras=execution.root_extras,
                    credential_reference=execution.artifact.credential_reference,
                ),
            )
        except PackageClosureResolutionJournalError:
            root.suspend_for_recovery()
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        except _CLOSURE_REJECTIONS as error:
            return PackageClosureExecutionResult(
                status=self._record_failure(
                    status,
                    code=_failure_code(error),
                ),
                cleanup_status=(
                    error.cleanup_status
                    if isinstance(error, PackageClosureCleanupDebtError)
                    else None
                ),
            )
        try:
            revalidated_basis = self._resolution_journal.basis(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
            )
            revalidated_plan = self._resolution_journal.plan(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
            )
        except PackageClosureResolutionJournalError:
            closure.suspend_for_recovery()
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if (
            revalidated_basis != expected_basis
            or revalidated_plan != durable_plan
            or closure.plan != revalidated_plan
        ):
            closure.suspend_for_recovery()
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        current = self._kernel.status(status.operation_id)
        if current != status:
            closure.suspend_for_recovery()
            if current is None:
                raise ValueError("Package lifecycle operation disappeared")
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    current,
                    code="package_operation_identity_conflict",
                )
            )
        return PackageClosureExecutionResult(status=status, candidate=closure)

    def _execution_context(
        self,
        execution: PackageClosureExecutionRequestV2,
    ) -> (
        tuple[PackageLifecycleStatusV1, PackageLifecycleRequestV1]
        | PackageClosureExecutionResult
    ):
        if not isinstance(execution, PackageClosureExecutionRequestV2):
            raise TypeError("Package closure execution request is required")
        status = self._kernel.status(execution.artifact.operation_id)
        request = self._kernel.journal.request(execution.artifact.operation_id)
        if status is None or request is None:
            raise ValueError("Package lifecycle operation does not exist")
        if execution.artifact.request_fingerprint != status.request_fingerprint:
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if execution.artifact.expected_attempt_epoch != status.attempt_epoch:
            return PackageClosureExecutionResult(
                status=_local_refusal(status, code="package_attempt_stale")
            )
        if (
            request.request_fingerprint != status.request_fingerprint
            or request.resolution_environment_fingerprint
            != execution.resolution_environment.fingerprint
        ):
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        try:
            requested = NormalizedPackageRequirementV1.parse(
                request.requested_package
            )
        except ValueError:
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if requested.extras != execution.root_extras:
            return PackageClosureExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        return status, request

    def _record_failure(
        self,
        status: PackageLifecycleStatusV1,
        *,
        code: str,
    ) -> PackageLifecycleStatusV1:
        evidence_ref = sha256(
            canonical_json_bytes(
                {
                    "code": code,
                    "operationId": status.operation_id,
                    "phase": status.phase,
                    "requestFingerprint": status.request_fingerprint,
                }
            )
        ).hexdigest()
        failure = PackageLifecycleFailureV1.for_operation(
            code,
            stage=cast(PackageLifecyclePhase, status.phase),
            operation_id=status.operation_id,
            evidence_ref=evidence_ref,
        )
        try:
            return self._kernel.record_failure(
                failure,
                expected_phase=status.phase,
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
        except PackageLifecycleJournalError:
            current = self._kernel.status(status.operation_id)
            if current is not None and current.disposition != "active":
                return current
            raise


_CLOSURE_REJECTIONS = (
    PackageAcquisitionError,
    PackageArtifactEvidenceJournalError,
    PackageClosureVerificationError,
    PackageClosureCleanupDebtError,
    PackageDependencyResolutionError,
    PackageWheelVerificationError,
)


def _failure_code(error: Exception) -> str:
    code = getattr(error, "code", "package_closure_artifact_invalid")
    if code in {
        "package_closure_conflict",
        "package_closure_evidence_unsupported",
        "package_operation_identity_conflict",
    }:
        return code
    if code in {
        "package_acquisition_limit_exceeded",
        "package_operation_timed_out",
        "package_resource_limit_exceeded",
    }:
        return "package_resource_limit_exceeded"
    return "package_closure_artifact_invalid"


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
    "PackageClosureExecutionRequestV2",
    "PackageClosureExecutionResult",
    "PackageClosureLifecycleOwner",
    "PackageRecursiveClosureBuilderPort",
    "PackageVerifiedRootOwnerPort",
]

"""Dark PLC9B2 artifact owner composition over the phase-CAS kernel."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageAcquisitionBudgetV1,
    PackageAcquisitionError,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
    PackageArtifactEvidenceJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
    PluginBoundPackageClassificationV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerificationError,
    PackageWheelVerifier,
    VerifiedWheelCandidate,
)

PACKAGE_ARTIFACT_EXECUTION_REQUEST_VERSION = 1


class PackageClassificationRecheckPort(Protocol):
    def recheck(
        self,
        request: PackageLifecycleRequestV1,
        prior: PluginBoundPackageClassificationV1,
    ) -> PluginBoundPackageClassificationV1: ...


@dataclass(frozen=True, slots=True)
class PackageArtifactExecutionRequestV1:
    operation_id: str
    request_fingerprint: str
    expected_attempt_epoch: int
    wheel_filename: str
    credential_reference: str | None = field(default=None, repr=False, compare=False)
    request_version: int = PACKAGE_ARTIFACT_EXECUTION_REQUEST_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ValueError("Package artifact operation id is required")
        if re.fullmatch(r"[0-9a-f]{64}", self.request_fingerprint) is None:
            raise ValueError("Package artifact request fingerprint must be SHA-256")
        if (
            not isinstance(self.expected_attempt_epoch, int)
            or isinstance(self.expected_attempt_epoch, bool)
            or self.expected_attempt_epoch < 1
        ):
            raise ValueError("Expected Package attempt epoch must be positive")
        if not isinstance(self.wheel_filename, str) or not self.wheel_filename:
            raise ValueError("Wheel filename is required")
        if self.credential_reference is not None and not self.credential_reference:
            raise ValueError("Credential reference cannot be empty")
        if self.request_version != PACKAGE_ARTIFACT_EXECUTION_REQUEST_VERSION:
            raise ValueError("Unsupported Package artifact execution request")


@dataclass(frozen=True, slots=True)
class PackageArtifactExecutionResult:
    status: PackageLifecycleStatusV1
    candidate: VerifiedWheelCandidate | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.status.phase == "extracted" and self.status.disposition == "active":
            if self.candidate is None:
                raise ValueError("Extracted Package status requires a candidate")
        elif self.candidate is not None:
            raise ValueError("Only an extracted Package status carries a candidate")


class PackageArtifactLifecycleOwner:
    """One dark owner for recheck, acquisition, wheel proof, and phase journal."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        classification_recheck: PackageClassificationRecheckPort,
        acquisition_owner: PackageAcquisitionOwner,
        evidence_journal: PackageArtifactEvidenceJournal,
        wheel_verifier: PackageWheelVerifier,
        acquisition_budgets: PackageAcquisitionBudgetV1,
        inspection_budgets: PackageInspectionBudgetV1,
        supported_tags: frozenset[str],
    ) -> None:
        if not isinstance(kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle kernel is required")
        if not callable(getattr(classification_recheck, "recheck", None)):
            raise TypeError("Package classification recheck port is required")
        if not isinstance(acquisition_owner, PackageAcquisitionOwner):
            raise TypeError("Package acquisition owner is required")
        if not isinstance(evidence_journal, PackageArtifactEvidenceJournal):
            raise TypeError("Package artifact evidence journal is required")
        if not isinstance(wheel_verifier, PackageWheelVerifier):
            raise TypeError("Package wheel verifier is required")
        if not isinstance(acquisition_budgets, PackageAcquisitionBudgetV1):
            raise TypeError("Package acquisition budgets are required")
        if not isinstance(inspection_budgets, PackageInspectionBudgetV1):
            raise TypeError("Package inspection budgets are required")
        if not supported_tags:
            raise ValueError("Supported wheel tags are required")
        self._kernel = kernel
        self._classification_recheck = classification_recheck
        self._acquisition_owner = acquisition_owner
        self._evidence_journal = evidence_journal
        self._wheel_verifier = wheel_verifier
        self._acquisition_budgets = acquisition_budgets
        self._inspection_budgets = inspection_budgets
        self._supported_tags = supported_tags

    def execute(
        self,
        execution: PackageArtifactExecutionRequestV1,
    ) -> PackageArtifactExecutionResult:
        if not isinstance(execution, PackageArtifactExecutionRequestV1):
            raise TypeError("Package artifact execution request is required")
        status = self._kernel.status(execution.operation_id)
        request = self._kernel.journal.request(execution.operation_id)
        if status is None or request is None:
            raise ValueError("Package lifecycle operation does not exist")
        if execution.request_fingerprint != status.request_fingerprint:
            return PackageArtifactExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                    evidence_ref=status.request_fingerprint,
                )
            )
        if execution.expected_attempt_epoch != status.attempt_epoch:
            return PackageArtifactExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_attempt_stale",
                    evidence_ref=status.request_fingerprint,
                )
            )
        if status.disposition != "active" or status.phase not in {
            "classified",
            "acquiring",
        }:
            return PackageArtifactExecutionResult(status=status)
        classification = status.classification
        if classification is None:
            raise RuntimeError("Classified Package status has no evidence")
        if classification.decision != "plugin_bound":
            return PackageArtifactExecutionResult(status=status)
        fresh = self._classification_recheck.recheck(request, classification)
        if not isinstance(fresh, PluginBoundPackageClassificationV1):
            raise TypeError("Classification recheck returned invalid evidence")
        if fresh != classification:
            failure = PackageLifecycleFailureV1.for_operation(
                "package_target_classification_changed",
                stage=status.phase,
                operation_id=status.operation_id,
                evidence_ref=fresh.evidence_ref,
            )
            return PackageArtifactExecutionResult(
                status=self._kernel.record_failure(
                    failure,
                    expected_phase=status.phase,
                    expected_journal_revision=status.journal_revision,
                    expected_attempt_epoch=status.attempt_epoch,
                )
            )
        acquiring = (
            self._kernel.advance(
                status.operation_id,
                next_phase="acquiring",
                expected_phase="classified",
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
            if status.phase == "classified"
            else status
        )
        if acquiring.disposition != "active":
            return PackageArtifactExecutionResult(status=acquiring)
        acquisition_request = PackageAcquisitionRequestV1(
            operation_id=request.operation_id,
            attempt_epoch=acquiring.attempt_epoch,
            node_id="root",
            canonical_source_identity=request.canonical_source_identity,
            request_fingerprint=request.request_fingerprint,
            requested_locator_digest=sha256(
                request.canonical_source_identity.encode("utf-8")
            ).hexdigest(),
            policy_revision=request.policy_revision,
            credential_reference=execution.credential_reference,
        )
        try:
            acquired_candidate = self._acquisition_owner.acquire(
                acquisition_request,
                budgets=self._acquisition_budgets,
            )
        except PackageAcquisitionError as error:
            failure = _acquisition_failure(acquiring, error)
            return PackageArtifactExecutionResult(
                status=self._kernel.record_failure(
                    failure,
                    expected_phase="acquiring",
                    expected_journal_revision=acquiring.journal_revision,
                    expected_attempt_epoch=acquiring.attempt_epoch,
                )
            )
        try:
            self._evidence_journal.append(
                request_fingerprint=request.request_fingerprint,
                evidence=acquired_candidate.receipt,
            )
        except PackageArtifactEvidenceJournalError:
            acquired_candidate.cleanup()
            failure = _identity_conflict(acquiring, stage="acquired")
            return PackageArtifactExecutionResult(
                status=self._kernel.record_failure(
                    failure,
                    expected_phase="acquiring",
                    expected_journal_revision=acquiring.journal_revision,
                    expected_attempt_epoch=acquiring.attempt_epoch,
                )
            )
        acquired = self._kernel.advance(
            acquiring.operation_id,
            next_phase="acquired",
            expected_phase="acquiring",
            expected_journal_revision=acquiring.journal_revision,
            expected_attempt_epoch=acquiring.attempt_epoch,
        )
        inspecting = self._kernel.advance(
            acquired.operation_id,
            next_phase="inspecting",
            expected_phase="acquired",
            expected_journal_revision=acquired.journal_revision,
            expected_attempt_epoch=acquired.attempt_epoch,
        )
        try:
            verified = self._wheel_verifier.verify(
                acquired_candidate,
                wheel_filename=execution.wheel_filename,
                supported_tags=self._supported_tags,
                budgets=self._inspection_budgets,
            )
        except PackageWheelVerificationError as error:
            failure = _wheel_failure(inspecting, error)
            return PackageArtifactExecutionResult(
                status=self._kernel.record_failure(
                    failure,
                    expected_phase="inspecting",
                    expected_journal_revision=inspecting.journal_revision,
                    expected_attempt_epoch=inspecting.attempt_epoch,
                )
            )
        try:
            self._evidence_journal.append(
                request_fingerprint=request.request_fingerprint,
                evidence=verified.evidence,
            )
        except PackageArtifactEvidenceJournalError:
            verified.cleanup()
            failure = _identity_conflict(inspecting, stage="extracted")
            return PackageArtifactExecutionResult(
                status=self._kernel.record_failure(
                    failure,
                    expected_phase="inspecting",
                    expected_journal_revision=inspecting.journal_revision,
                    expected_attempt_epoch=inspecting.attempt_epoch,
                )
            )
        extracted = self._kernel.advance(
            inspecting.operation_id,
            next_phase="extracted",
            expected_phase="inspecting",
            expected_journal_revision=inspecting.journal_revision,
            expected_attempt_epoch=inspecting.attempt_epoch,
        )
        return PackageArtifactExecutionResult(status=extracted, candidate=verified)


def _acquisition_failure(
    status: PackageLifecycleStatusV1,
    error: PackageAcquisitionError,
) -> PackageLifecycleFailureV1:
    stage = cast(PackageLifecyclePhase, error.stage)
    details = (
        ("condition:no_acquired_digest",)
        if error.code
        in {"package_acquisition_limit_exceeded", "package_operation_timed_out"}
        and error.stage == "acquiring"
        else ()
    )
    return PackageLifecycleFailureV1.for_operation(
        error.code,
        stage=stage,
        operation_id=status.operation_id,
        evidence_ref=_failure_evidence_ref(status, error.code, stage),
        details=details,
    )


def _wheel_failure(
    status: PackageLifecycleStatusV1,
    error: PackageWheelVerificationError,
) -> PackageLifecycleFailureV1:
    stage = cast(PackageLifecyclePhase, error.stage)
    return PackageLifecycleFailureV1.for_operation(
        error.code,
        stage=stage,
        operation_id=status.operation_id,
        evidence_ref=_failure_evidence_ref(status, error.code, stage),
    )


def _identity_conflict(
    status: PackageLifecycleStatusV1,
    *,
    stage: PackageLifecyclePhase,
) -> PackageLifecycleFailureV1:
    return PackageLifecycleFailureV1.for_operation(
        "package_operation_identity_conflict",
        stage=stage,
        operation_id=status.operation_id,
        evidence_ref=_failure_evidence_ref(
            status,
            "package_operation_identity_conflict",
            stage,
        ),
    )


def _failure_evidence_ref(
    status: PackageLifecycleStatusV1,
    code: str,
    stage: PackageLifecyclePhase,
) -> str:
    return sha256(
        canonical_json_bytes(
            {
                "attemptEpoch": status.attempt_epoch,
                "code": code,
                "operationId": status.operation_id,
                "requestFingerprint": status.request_fingerprint,
                "stage": stage,
            }
        )
    ).hexdigest()


def _local_refusal(
    status: PackageLifecycleStatusV1,
    *,
    code: str,
    evidence_ref: str,
) -> PackageLifecycleStatusV1:
    failure = PackageLifecycleFailureV1.for_operation(
        code,
        stage=status.phase,
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
    "PackageArtifactExecutionRequestV1",
    "PackageArtifactExecutionResult",
    "PackageArtifactLifecycleOwner",
    "PackageClassificationRecheckPort",
]

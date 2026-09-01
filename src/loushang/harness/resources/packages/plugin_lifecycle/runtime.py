"""Dark PLC9B2 artifact owner composition over the phase-CAS kernel."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AcquiredPackageCandidate,
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionReceiptV1,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionCleanupDebtError,
    PackageAcquisitionError,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageAuthenticatedSourceEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupOwner,
    PackageQuarantineCleanupStatusV1,
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
    VerifiedWheelArtifactV1,
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
    cleanup_status: PackageQuarantineCleanupStatusV1 | None = None

    def __post_init__(self) -> None:
        if self.status.phase == "extracted" and self.status.disposition == "active":
            if self.candidate is None:
                raise ValueError("Extracted Package status requires a candidate")
        elif self.candidate is not None:
            raise ValueError("Only an extracted Package status carries a candidate")
        if self.cleanup_status is not None and (
            self.status.disposition not in {"rejected", "retryable_failure"}
            or self.cleanup_status.target.operation_id != self.status.operation_id
        ):
            raise ValueError("Cleanup debt must accompany its rejected operation")


class PackageArtifactLifecycleOwner:
    """One dark owner for recheck, acquisition, wheel proof, and phase journal."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        classification_recheck: PackageClassificationRecheckPort,
        acquisition_owner: PackageAcquisitionOwner,
        evidence_journal: PackageArtifactEvidenceJournal,
        cleanup_owner: PackageQuarantineCleanupOwner,
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
        if not isinstance(cleanup_owner, PackageQuarantineCleanupOwner):
            raise TypeError("Package quarantine cleanup owner is required")
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
        self._cleanup_owner = cleanup_owner
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
            "acquired",
            "inspecting",
            "extracted",
        }:
            return PackageArtifactExecutionResult(status=status)
        classification = status.classification
        if classification is None:
            raise RuntimeError("Classified Package status has no evidence")
        if classification.decision != "plugin_bound":
            return PackageArtifactExecutionResult(status=status)
        acquisition_request = PackageAcquisitionRequestV1(
            operation_id=request.operation_id,
            attempt_epoch=status.attempt_epoch,
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
            source_record = self._evidence_journal.find(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
                node_id="root",
                kind="authenticated_source",
            )
            acquired_record = self._evidence_journal.find(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
                node_id="root",
                kind="bounded_acquisition",
            )
            verified_record = self._evidence_journal.find(
                operation_id=status.operation_id,
                attempt_epoch=status.attempt_epoch,
                node_id="root",
                kind="verified_wheel",
            )
        except PackageArtifactEvidenceJournalError:
            return self._record_identity_failure(status, stage=status.phase)
        if (
            source_record is not None
            and (
                source_record.request_fingerprint != request.request_fingerprint
                or not isinstance(
                    source_record.evidence,
                    PackageAuthenticatedSourceEvidenceV1,
                )
            )
        ) or (
            acquired_record is not None
            and (
                acquired_record.request_fingerprint != request.request_fingerprint
                or not isinstance(
                    acquired_record.evidence,
                    BoundedAcquisitionReceiptV1,
                )
            )
        ) or (
            verified_record is not None
            and (
                verified_record.request_fingerprint != request.request_fingerprint
                or not isinstance(verified_record.evidence, VerifiedWheelArtifactV1)
            )
        ):
            return self._record_identity_failure(status, stage=status.phase)
        source_evidence = (
            cast(PackageAuthenticatedSourceEvidenceV1, source_record.evidence)
            if source_record is not None
            else None
        )
        receipt = (
            cast(BoundedAcquisitionReceiptV1, acquired_record.evidence)
            if acquired_record is not None
            else None
        )
        durable_verified = (
            cast(VerifiedWheelArtifactV1, verified_record.evidence)
            if verified_record is not None
            else None
        )
        if durable_verified is not None and receipt is None:
            return self._record_identity_failure(status, stage=status.phase)

        acquired_candidate: AcquiredPackageCandidate | None = None
        classification_rechecked = False
        if status.phase == "classified":
            if (
                source_evidence is not None
                or receipt is not None
                or durable_verified is not None
            ):
                return self._record_identity_failure(status, stage="classified")
            changed = self._recheck_classification(status, request, classification)
            if changed is not None:
                return PackageArtifactExecutionResult(status=changed)
            classification_rechecked = True
            status = self._kernel.advance(
                status.operation_id,
                next_phase="acquiring",
                expected_phase="classified",
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
            if status.disposition != "active":
                return PackageArtifactExecutionResult(status=status)

        if status.phase == "acquiring":
            if durable_verified is not None:
                return self._record_identity_failure(status, stage="acquired")
            if receipt is None:
                if not classification_rechecked:
                    changed = self._recheck_classification(
                        status,
                        request,
                        classification,
                    )
                    if changed is not None:
                        return PackageArtifactExecutionResult(status=changed)
                try:
                    authorized = self._acquisition_owner.authorize_source(
                        acquisition_request,
                        expected_envelope=(
                            source_evidence.envelope
                            if source_evidence is not None
                            else None
                        ),
                    )
                    if source_evidence is None:
                        source_evidence = PackageAuthenticatedSourceEvidenceV1(
                            attempt_epoch=status.attempt_epoch,
                            envelope=authorized.envelope,
                        )
                        self._evidence_journal.append(
                            request_fingerprint=request.request_fingerprint,
                            evidence=source_evidence,
                        )
                    acquired_candidate = self._acquisition_owner.acquire_authorized(
                        acquisition_request,
                        authorized,
                        budgets=self._acquisition_budgets,
                    )
                except PackageArtifactEvidenceJournalError:
                    return self._record_identity_failure(status, stage="acquiring")
                except PackageAcquisitionCleanupDebtError as debt:
                    return self._record_acquisition_failure(status, debt=debt)
                except PackageAcquisitionError as error:
                    return self._record_acquisition_failure(status, error=error)
                receipt = acquired_candidate.receipt
                try:
                    self._evidence_journal.append(
                        request_fingerprint=request.request_fingerprint,
                        evidence=receipt,
                    )
                except PackageArtifactEvidenceJournalError:
                    acquired_candidate.cleanup()
                    return self._record_identity_failure(status, stage="acquired")
            else:
                reopened = self._reopen_candidate(
                    status,
                    acquisition_request,
                    receipt,
                    reset_extraction=False,
                    authenticated_envelope=(
                        source_evidence.envelope
                        if source_evidence is not None
                        else None
                    ),
                )
                if isinstance(reopened, PackageArtifactExecutionResult):
                    return reopened
                acquired_candidate = reopened
            status = self._kernel.advance(
                status.operation_id,
                next_phase="acquired",
                expected_phase="acquiring",
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
            if status.disposition != "active":
                if acquired_candidate is not None:
                    acquired_candidate.suspend_for_recovery()
                return PackageArtifactExecutionResult(status=status)

        if status.phase == "acquired":
            if receipt is None or durable_verified is not None:
                if acquired_candidate is not None:
                    acquired_candidate.suspend_for_recovery()
                return self._record_identity_failure(status, stage="acquired")
            if acquired_candidate is None:
                reopened = self._reopen_candidate(
                    status,
                    acquisition_request,
                    receipt,
                    reset_extraction=False,
                    authenticated_envelope=(
                        source_evidence.envelope
                        if source_evidence is not None
                        else None
                    ),
                )
                if isinstance(reopened, PackageArtifactExecutionResult):
                    return reopened
                acquired_candidate = reopened
            status = self._kernel.advance(
                status.operation_id,
                next_phase="inspecting",
                expected_phase="acquired",
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
            if status.disposition != "active":
                acquired_candidate.suspend_for_recovery()
                return PackageArtifactExecutionResult(status=status)

        if status.phase == "inspecting":
            if receipt is None:
                return self._record_identity_failure(status, stage="inspecting")
            if acquired_candidate is None:
                reopened = self._reopen_candidate(
                    status,
                    acquisition_request,
                    receipt,
                    reset_extraction=True,
                    authenticated_envelope=(
                        source_evidence.envelope
                        if source_evidence is not None
                        else None
                    ),
                )
                if isinstance(reopened, PackageArtifactExecutionResult):
                    return reopened
                acquired_candidate = reopened
            verified = self._verify_candidate(
                status,
                acquired_candidate,
                execution,
            )
            if isinstance(verified, PackageArtifactExecutionResult):
                return verified
            if durable_verified is not None and verified.evidence != durable_verified:
                verified.cleanup()
                return self._record_identity_failure(status, stage="extracted")
            try:
                self._evidence_journal.append(
                    request_fingerprint=request.request_fingerprint,
                    evidence=verified.evidence,
                )
            except PackageArtifactEvidenceJournalError:
                verified.cleanup()
                return self._record_identity_failure(status, stage="extracted")
            extracted = self._kernel.advance(
                status.operation_id,
                next_phase="extracted",
                expected_phase="inspecting",
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
            if extracted.disposition != "active":
                verified.suspend_for_recovery()
                return PackageArtifactExecutionResult(status=extracted)
            return PackageArtifactExecutionResult(status=extracted, candidate=verified)

        if status.phase == "extracted":
            if receipt is None or durable_verified is None:
                return self._record_identity_failure(status, stage="extracted")
            reopened = self._reopen_candidate(
                status,
                acquisition_request,
                receipt,
                reset_extraction=True,
                authenticated_envelope=(
                    source_evidence.envelope if source_evidence is not None else None
                ),
            )
            if isinstance(reopened, PackageArtifactExecutionResult):
                return reopened
            verified = self._verify_candidate(status, reopened, execution)
            if isinstance(verified, PackageArtifactExecutionResult):
                return verified
            if verified.evidence != durable_verified:
                verified.cleanup()
                return self._record_identity_failure(status, stage="extracted")
            return PackageArtifactExecutionResult(status=status, candidate=verified)
        raise RuntimeError("Unsupported active Package artifact phase")

    def _recheck_classification(
        self,
        status: PackageLifecycleStatusV1,
        request: PackageLifecycleRequestV1,
        classification: PluginBoundPackageClassificationV1,
    ) -> PackageLifecycleStatusV1 | None:
        fresh = self._classification_recheck.recheck(request, classification)
        if not isinstance(fresh, PluginBoundPackageClassificationV1):
            raise TypeError("Classification recheck returned invalid evidence")
        if fresh == classification:
            return None
        failure = PackageLifecycleFailureV1.for_operation(
            "package_target_classification_changed",
            stage=status.phase,
            operation_id=status.operation_id,
            evidence_ref=fresh.evidence_ref,
        )
        return self._kernel.record_failure(
            failure,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )

    def _record_identity_failure(
        self,
        status: PackageLifecycleStatusV1,
        *,
        stage: PackageLifecyclePhase,
    ) -> PackageArtifactExecutionResult:
        return PackageArtifactExecutionResult(
            status=self._kernel.record_failure(
                _identity_conflict(status, stage=stage),
                expected_phase=status.phase,
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
        )

    def _record_acquisition_failure(
        self,
        status: PackageLifecycleStatusV1,
        *,
        error: PackageAcquisitionError | None = None,
        debt: PackageAcquisitionCleanupDebtError | None = None,
    ) -> PackageArtifactExecutionResult:
        if (error is None) == (debt is None):
            raise ValueError("Exactly one acquisition rejection is required")
        rejection = debt.rejection if debt is not None else cast(
            PackageAcquisitionError,
            error,
        )
        cleanup_status = None
        if debt is not None:
            cleanup_status = self._cleanup_owner.record_pending(
                debt.target,
                rejection_code=rejection.code,
                rejection_stage=cast(PackageLifecyclePhase, rejection.stage),
            )
        rejection_stage = cast(PackageLifecyclePhase, rejection.stage)
        if status.phase not in {"acquiring", rejection_stage}:
            rejection_stage = status.phase
        failure = _acquisition_failure(
            status,
            rejection,
            stage=rejection_stage,
        )
        rejected = self._kernel.record_failure(
            failure,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
        return PackageArtifactExecutionResult(
            status=rejected,
            cleanup_status=cleanup_status,
        )

    def _reopen_candidate(
        self,
        status: PackageLifecycleStatusV1,
        request: PackageAcquisitionRequestV1,
        receipt: BoundedAcquisitionReceiptV1,
        *,
        reset_extraction: bool,
        authenticated_envelope: AuthenticatedSourceEnvelopeV1 | None,
    ) -> AcquiredPackageCandidate | PackageArtifactExecutionResult:
        try:
            return self._acquisition_owner.reopen_acquired(
                request,
                receipt,
                reset_extraction=reset_extraction,
                authenticated_envelope=authenticated_envelope,
            )
        except PackageAcquisitionCleanupDebtError as debt:
            return self._record_acquisition_failure(status, debt=debt)
        except PackageAcquisitionError as error:
            return self._record_acquisition_failure(status, error=error)

    def _verify_candidate(
        self,
        status: PackageLifecycleStatusV1,
        candidate: AcquiredPackageCandidate,
        execution: PackageArtifactExecutionRequestV1,
    ) -> VerifiedWheelCandidate | PackageArtifactExecutionResult:
        try:
            return self._wheel_verifier.verify(
                candidate,
                wheel_filename=execution.wheel_filename,
                supported_tags=self._supported_tags,
                budgets=self._inspection_budgets,
            )
        except PackageWheelVerificationError as error:
            cleanup_status = None
            rejection = error
            if error.code == "package_quarantine_cleanup_retryable":
                if error.rejection_code is None or error.rejection_stage is None:
                    raise RuntimeError("Cleanup debt lost its original rejection")
                target = candidate.cleanup_target()
                try:
                    cleanup_status = self._cleanup_owner.record_pending(
                        target,
                        rejection_code=error.rejection_code,
                        rejection_stage=cast(
                            PackageLifecyclePhase,
                            error.rejection_stage,
                        ),
                    )
                finally:
                    candidate.defer_cleanup()
                rejection = PackageWheelVerificationError(
                    "Package artifact was rejected",
                    code=error.rejection_code,
                    stage=error.rejection_stage,
                )
            rejection_stage = cast(PackageLifecyclePhase, rejection.stage)
            if status.phase == "extracted":
                rejection_stage = "extracted"
            failure = _wheel_failure(
                status,
                rejection,
                stage=rejection_stage,
            )
            rejected = self._kernel.record_failure(
                failure,
                expected_phase=status.phase,
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
            return PackageArtifactExecutionResult(
                status=rejected,
                cleanup_status=cleanup_status,
            )


def _acquisition_failure(
    status: PackageLifecycleStatusV1,
    error: PackageAcquisitionError,
    *,
    stage: PackageLifecyclePhase | None = None,
) -> PackageLifecycleFailureV1:
    stage = stage or cast(PackageLifecyclePhase, error.stage)
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
    *,
    stage: PackageLifecyclePhase | None = None,
) -> PackageLifecycleFailureV1:
    stage = stage or cast(PackageLifecyclePhase, error.stage)
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

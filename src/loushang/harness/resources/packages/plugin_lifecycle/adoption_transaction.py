"""Dark PLC9B4c4b adapter over the accepted complete B transaction owners.

The adapter is scoped to one operation.  Its private execution binding may
hold an opaque credential reference, while the adoption protocol remains
pathless and credential-free.  It owns no Source, filesystem, Store, journal,
or Product capability; effects remain with the injected lifecycle owners.
"""

from __future__ import annotations

from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyAdoptionRequestV1,
    PackageLegacyAdoptionTransactionResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_runtime import (
    PackageClosureExecutionRequestV2,
    PackageClosureExecutionResult,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitEvidenceError,
    PackagePublicationReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingSetExecutionResult,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pin_runtime import (
    PackageTransactionPinExecutionResult,
)

_CLOSURE_PHASES = frozenset(
    {
        "classified",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
    }
)
_STAGING_RECOVERY_PHASES = frozenset({"staging"})


class PackageLegacyClosureExecutionPort(Protocol):
    def execute(
        self,
        execution: PackageClosureExecutionRequestV2,
    ) -> PackageClosureExecutionResult: ...


class PackageLegacyPinExecutionPort(Protocol):
    def pin(
        self,
        candidate: VerifiedPackageClosureCandidate,
        *,
        recovery_identity: str,
    ) -> PackageTransactionPinExecutionResult: ...


class PackageLegacyStagingExecutionPort(Protocol):
    def stage_and_publish(
        self,
        candidate: VerifiedPackageClosureCandidate,
    ) -> PackageStagingSetExecutionResult: ...

    def resume(self, operation_id: str) -> PackageStagingSetExecutionResult: ...


class PackageLegacyCommitExecutionPort(Protocol):
    def commit(self, operation_id: str) -> PackagePublicationReceiptV1: ...


class PackageLegacyAdoptionTransactionAdapter:
    """Compose one authenticated reacquisition into an exact B publication."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        execution: PackageClosureExecutionRequestV2,
        recovery_identity: str,
        closure: PackageLegacyClosureExecutionPort,
        pins: PackageLegacyPinExecutionPort,
        staging: PackageLegacyStagingExecutionPort,
        commit: PackageLegacyCommitExecutionPort,
    ) -> None:
        if not isinstance(kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle owner is required")
        if not isinstance(execution, PackageClosureExecutionRequestV2):
            raise TypeError("Package closure execution binding is required")
        if not isinstance(recovery_identity, str) or not recovery_identity:
            raise ValueError("Package recovery identity is required")
        for owner, methods, name in (
            (closure, ("execute",), "closure execution owner"),
            (pins, ("pin",), "transaction pin owner"),
            (
                staging,
                ("stage_and_publish", "resume"),
                "staging-set owner",
            ),
            (commit, ("commit",), "commit owner"),
        ):
            if any(not callable(getattr(owner, method, None)) for method in methods):
                raise TypeError(f"Package {name} is required")
        self._kernel = kernel
        self._execution = execution
        self._recovery_identity = recovery_identity
        self._closure = closure
        self._pins = pins
        self._staging = staging
        self._commit = commit

    def adopt(
        self,
        request: PackageLegacyAdoptionRequestV1,
    ) -> PackageLegacyAdoptionTransactionResultV1:
        if not isinstance(request, PackageLegacyAdoptionRequestV1):
            raise TypeError("Legacy Package adoption request is required")
        status = self._kernel.status(request.operation_id)
        lifecycle_request = self._kernel.journal.request(request.operation_id)
        if status is None or lifecycle_request is None:
            raise ValueError("Legacy adoption Package operation does not exist")
        if not self._preflight_matches(request, status, lifecycle_request):
            return self._refused(request, status)
        if status.disposition != "active":
            return self._finish(request, status)

        if status.phase in _CLOSURE_PHASES:
            closure = self._closure.execute(self._execution)
            if not isinstance(closure, PackageClosureExecutionResult):
                return self._refused(request, status)
            status = closure.status
            candidate = closure.candidate
            current = self._kernel.status(request.operation_id)
            if current is None:
                _suspend(candidate)
                raise ValueError("Legacy adoption Package operation disappeared")
            if (
                current != status
                or not self._status_matches(request, status)
            ):
                _suspend(candidate)
                return self._refused(request, current)
            if candidate is None:
                return self._finish(request, status)
            if not _candidate_matches(candidate, request):
                candidate.suspend_for_recovery()
                return self._refused(request, status)

            try:
                pinned = self._pins.pin(
                    candidate,
                    recovery_identity=self._recovery_identity,
                )
            except Exception:
                candidate.suspend_for_recovery()
                raise
            if not isinstance(pinned, PackageTransactionPinExecutionResult):
                candidate.suspend_for_recovery()
                return self._refused(request, status)
            status = pinned.status
            current = self._kernel.status(request.operation_id)
            if current is None:
                _suspend(pinned.candidate)
                candidate.suspend_for_recovery()
                raise ValueError("Legacy adoption Package operation disappeared")
            if (
                current != status
                or not self._status_matches(request, status)
            ):
                _suspend(pinned.candidate)
                candidate.suspend_for_recovery()
                return self._refused(request, current)
            if pinned.candidate is None:
                candidate.suspend_for_recovery()
                return self._finish(request, status)
            if pinned.candidate is not candidate or pinned.receipt is None:
                _suspend(pinned.candidate)
                candidate.suspend_for_recovery()
                return self._refused(request, status)

            try:
                staged = self._staging.stage_and_publish(pinned.candidate)
            finally:
                pinned.candidate.suspend_for_recovery()
            return self._after_staging(request, staged)

        if status.phase == "transaction_pinned":
            # The accepted staging owner can resume without a live candidate
            # only after every staging receipt is durable, represented by the
            # later ``staging`` phase.  A bare durable pin is insufficient to
            # reconstruct the opaque verified candidates, so this candidate
            # slice must fail closed until a reacquisition seam exists.
            return self._unavailable(request, status)
        if status.phase in _STAGING_RECOVERY_PHASES:
            staged = self._staging.resume(request.operation_id)
            return self._after_staging(request, staged)
        if status.phase == "set_published":
            return self._commit_publication(request, status)
        return self._refused(request, status)

    def _after_staging(
        self,
        request: PackageLegacyAdoptionRequestV1,
        staged: object,
    ) -> PackageLegacyAdoptionTransactionResultV1:
        current = self._kernel.status(request.operation_id)
        if current is None:
            raise ValueError("Legacy adoption Package operation disappeared")
        if (
            not isinstance(staged, PackageStagingSetExecutionResult)
            or staged.status != current
        ):
            return self._refused(request, current)
        status = staged.status
        if not self._status_matches(request, status):
            return self._refused(request, status)
        if status.disposition != "active":
            return self._finish(request, status)
        if status.phase != "set_published" or staged.committed_set is None:
            return self._refused(request, status)
        return self._commit_publication(request, status)

    def _commit_publication(
        self,
        request: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> PackageLegacyAdoptionTransactionResultV1:
        try:
            publication = self._commit.commit(request.operation_id)
        except PackageCommitEvidenceError:
            return self._refused(request, status)
        committed = self._kernel.status(request.operation_id)
        if (
            committed is None
            or not self._status_matches(request, committed)
            or committed.disposition != "committed"
            or committed.phase != "committed"
        ):
            return self._refused(request, status)
        try:
            return PackageLegacyAdoptionTransactionResultV1(
                adoption_request_id=request.request_id,
                status=committed,
                publication=publication,
            )
        except (TypeError, ValueError):
            return self._refused(request, committed)

    def _finish(
        self,
        request: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> PackageLegacyAdoptionTransactionResultV1:
        if status.disposition == "committed" and status.phase == "committed":
            return self._commit_publication(request, status)
        if status.failure is not None and status.disposition in {
            "cancelled",
            "rejected",
            "retryable_failure",
        }:
            return PackageLegacyAdoptionTransactionResultV1(
                adoption_request_id=request.request_id,
                status=status,
                publication=None,
            )
        return self._refused(request, status)

    def _preflight_matches(
        self,
        request: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
        lifecycle_request: PackageLifecycleRequestV1,
    ) -> bool:
        artifact = self._execution.artifact
        return (
            self._status_matches(request, status)
            and lifecycle_request.operation_id == request.operation_id
            and lifecycle_request.request_fingerprint
            == request.transaction_request_fingerprint
            and lifecycle_request.action == "install"
            and lifecycle_request.product_id == request.product_id
            and lifecycle_request.scope_id == request.scope_id
            and lifecycle_request.requested_plugin_id == request.plugin_id
            and lifecycle_request.resolution_environment_fingerprint
            == self._execution.resolution_environment.fingerprint
            and artifact.operation_id == request.operation_id
            and artifact.request_fingerprint
            == request.transaction_request_fingerprint
            and artifact.expected_attempt_epoch == request.expected_attempt_epoch
        )

    @staticmethod
    def _status_matches(
        request: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> bool:
        classification = status.classification
        return (
            status.operation_id == request.operation_id
            and status.request_fingerprint
            == request.transaction_request_fingerprint
            and status.attempt_epoch == request.expected_attempt_epoch
            and classification is not None
            and classification.decision == "plugin_bound"
            and classification.evidence_ref
            == request.expected_classification_fingerprint
        )

    @staticmethod
    def _refused(
        request: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> PackageLegacyAdoptionTransactionResultV1:
        return PackageLegacyAdoptionTransactionAdapter._local_failure(
            request,
            status,
            code="package_operation_identity_conflict",
        )

    @staticmethod
    def _unavailable(
        request: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> PackageLegacyAdoptionTransactionResultV1:
        return PackageLegacyAdoptionTransactionAdapter._local_failure(
            request,
            status,
            code="package_route_unavailable",
        )

    @staticmethod
    def _local_failure(
        request: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
        *,
        code: str,
    ) -> PackageLegacyAdoptionTransactionResultV1:
        classification = status.classification
        phase: PackageLifecyclePhase = (
            "classified" if status.phase == "committed" else status.phase
        )
        failure = PackageLifecycleFailureV1.for_operation(
            code,
            stage=phase,
            operation_id=status.operation_id,
            evidence_ref=request.request_id,
        )
        refused = PackageLifecycleStatusV1(
            operation_id=status.operation_id,
            request_fingerprint=status.request_fingerprint,
            phase=phase,
            disposition="rejected",
            attempt_epoch=status.attempt_epoch,
            journal_revision=status.journal_revision,
            attempt_revision=status.attempt_revision,
            classification=classification,
            failure=failure,
        )
        return PackageLegacyAdoptionTransactionResultV1(
            adoption_request_id=request.request_id,
            status=refused,
            publication=None,
        )


def _candidate_matches(
    candidate: VerifiedPackageClosureCandidate,
    request: PackageLegacyAdoptionRequestV1,
) -> bool:
    return (
        candidate.plan.operation_id == request.operation_id
        and candidate.plan.attempt_epoch == request.expected_attempt_epoch
    )


def _suspend(candidate: VerifiedPackageClosureCandidate | None) -> None:
    if candidate is not None:
        candidate.suspend_for_recovery()


__all__ = ()

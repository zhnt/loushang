"""Dark application owner for the first PLC9B runtime slice."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
    PackageLifecycleJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageClassificationFactsV1,
    PackageLifecycleCancelRequestV1,
    PackageLifecycleFailureV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PackageLifecycleRetryRequestV1,
    PackageLifecycleStatusV1,
    classify_package_request,
)


class PackageClassificationAuthorityPort(Protocol):
    """Owner-revisioned facts; transports cannot submit a classification."""

    def classification_facts(
        self,
        request: PackageLifecycleIngressRequestV1,
    ) -> PackageClassificationFactsV1: ...


class PackageLifecycleOwner:
    """PLC9B1 owner kernel with no acquisition or publication capabilities."""

    def __init__(
        self,
        *,
        journal: PackageLifecycleJournal,
        classification_authority: PackageClassificationAuthorityPort,
        enabled: bool = False,
    ) -> None:
        if not isinstance(journal, PackageLifecycleJournal):
            raise TypeError("Package lifecycle journal is required")
        if not callable(
            getattr(classification_authority, "classification_facts", None)
        ):
            raise TypeError("Package classification authority is required")
        if type(enabled) is not bool:
            raise TypeError("Package lifecycle owner enabled state must be boolean")
        self._journal = journal
        self._classification_authority = classification_authority
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def journal(self) -> PackageLifecycleJournal:
        return self._journal

    @property
    def binding_id(self) -> str:
        """Opaque identity shared by adapters bound to this exact journal."""

        return sha256(str(self._journal.path).encode("utf-8")).hexdigest()

    def submit(
        self,
        ingress: PackageLifecycleIngressRequestV1,
    ) -> PackageLifecycleStatusV1:
        status = self.accept(ingress)
        if status.phase != "accepted" or status.disposition != "active":
            return status
        return self.classify(
            status.operation_id,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )

    def accept(
        self,
        ingress: PackageLifecycleIngressRequestV1,
    ) -> PackageLifecycleStatusV1:
        if not isinstance(ingress, PackageLifecycleIngressRequestV1):
            raise TypeError("Package lifecycle ingress request is required")
        facts = self._classification_authority.classification_facts(ingress)
        if not isinstance(facts, PackageClassificationFactsV1):
            raise TypeError("Classification authority returned invalid facts")
        request = ingress.bind_classification_facts(facts)
        if not self._enabled:
            return _disabled_status(request)
        try:
            return self._journal.accept(request)
        except PackageLifecycleJournalError as exc:
            if exc.code != "package_operation_identity_conflict":
                raise
            current = self._journal.status(request.operation_id)
            if current is None:
                raise
            classification = classify_package_request(request)
            failure = PackageLifecycleFailureV1.for_operation(
                "package_operation_identity_conflict",
                stage="classified",
                operation_id=request.operation_id,
                evidence_ref=request.request_fingerprint,
            )
            return PackageLifecycleStatusV1(
                operation_id=request.operation_id,
                request_fingerprint=request.request_fingerprint,
                phase="classified",
                disposition="rejected",
                attempt_epoch=current.attempt_epoch,
                journal_revision=current.journal_revision,
                attempt_revision=current.attempt_revision,
                classification=classification,
                failure=failure,
            )

    def classify(
        self,
        operation_id: str,
        *,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        request = self._journal.request(operation_id)
        if request is None:
            raise PackageLifecycleJournalError(
                "Package operation does not exist",
                code="package_operation_not_found",
                path=self._journal.path,
            )
        classification = classify_package_request(request)
        return self._journal.classify(
            operation_id,
            classification,
            expected_journal_revision=expected_journal_revision,
            expected_attempt_epoch=expected_attempt_epoch,
        )

    def status(self, operation_id: str) -> PackageLifecycleStatusV1 | None:
        return self._journal.status(operation_id)

    def advance(
        self,
        operation_id: str,
        *,
        next_phase: PackageLifecyclePhase,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        try:
            return self._journal.advance(
                operation_id,
                next_phase=next_phase,
                expected_phase=expected_phase,
                expected_journal_revision=expected_journal_revision,
                expected_attempt_epoch=expected_attempt_epoch,
            )
        except PackageLifecycleJournalError as exc:
            if exc.code != "package_attempt_stale":
                raise
            return self._stale_attempt_status(operation_id)

    def record_failure(
        self,
        failure: PackageLifecycleFailureV1,
        *,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        if not isinstance(failure, PackageLifecycleFailureV1):
            raise TypeError("Package lifecycle failure is required")
        try:
            return self._journal.record_failure(
                failure,
                expected_phase=expected_phase,
                expected_journal_revision=expected_journal_revision,
                expected_attempt_epoch=expected_attempt_epoch,
            )
        except PackageLifecycleJournalError as exc:
            if exc.code != "package_attempt_stale":
                raise
            return self._stale_attempt_status(failure.operation_id)

    def interrupt(
        self,
        operation_id: str,
        *,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        try:
            return self._journal.interrupt(
                operation_id,
                expected_phase=expected_phase,
                expected_journal_revision=expected_journal_revision,
                expected_attempt_epoch=expected_attempt_epoch,
            )
        except PackageLifecycleJournalError as exc:
            if exc.code != "package_attempt_stale":
                raise
            return self._stale_attempt_status(operation_id)

    def retry(
        self,
        request: PackageLifecycleRetryRequestV1,
    ) -> PackageLifecycleStatusV1:
        if not isinstance(request, PackageLifecycleRetryRequestV1):
            raise TypeError("Package lifecycle retry request is required")
        try:
            return self._journal.retry(
                request.operation_id,
                request_fingerprint=request.request_fingerprint,
                expected_attempt_epoch=request.expected_attempt_epoch,
            )
        except PackageLifecycleJournalError as exc:
            if exc.code != "package_attempt_stale":
                raise
            return self._stale_attempt_status(request.operation_id)

    def cancel(
        self,
        request: PackageLifecycleCancelRequestV1,
    ) -> PackageLifecycleStatusV1:
        if not isinstance(request, PackageLifecycleCancelRequestV1):
            raise TypeError("Package lifecycle cancel request is required")
        try:
            return self._journal.cancel(
                request.operation_id,
                request_fingerprint=request.request_fingerprint,
                expected_phase=request.expected_phase,
                expected_journal_revision=request.expected_journal_revision,
                expected_attempt_epoch=request.expected_attempt_epoch,
            )
        except PackageLifecycleJournalError as exc:
            if exc.code != "package_attempt_stale":
                raise
            return self._stale_attempt_status(request.operation_id)

    def _stale_attempt_status(
        self,
        operation_id: str,
    ) -> PackageLifecycleStatusV1:
        current = self._journal.status(operation_id)
        if current is None:
            raise PackageLifecycleJournalError(
                "Package operation does not exist",
                code="package_operation_not_found",
                path=self._journal.path,
            )
        failure = PackageLifecycleFailureV1.for_operation(
            "package_attempt_stale",
            stage=current.phase,
            operation_id=current.operation_id,
            evidence_ref=current.request_fingerprint,
        )
        return PackageLifecycleStatusV1(
            operation_id=current.operation_id,
            request_fingerprint=current.request_fingerprint,
            phase=current.phase,
            disposition="rejected",
            attempt_epoch=current.attempt_epoch,
            journal_revision=current.journal_revision,
            attempt_revision=current.attempt_revision,
            classification=current.classification,
            failure=failure,
        )


def _disabled_status(request: PackageLifecycleRequestV1) -> PackageLifecycleStatusV1:
    classification = classify_package_request(request)
    failure = PackageLifecycleFailureV1.for_operation(
        "package_route_unavailable",
        stage="classified",
        operation_id=request.operation_id,
        evidence_ref=classification.evidence_ref,
    )
    return PackageLifecycleStatusV1(
        operation_id=request.operation_id,
        request_fingerprint=request.request_fingerprint,
        phase="classified",
        disposition="rejected",
        attempt_epoch=1,
        journal_revision=0,
        attempt_revision=0,
        classification=classification,
        failure=failure,
    )


__all__ = [
    "PackageClassificationAuthorityPort",
    "PackageLifecycleOwner",
]

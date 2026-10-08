"""Sanitized A2 Package operation facts before or after A1 handoff."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleAction,
    PackageLifecycleDisposition,
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
)

PACKAGE_OPERATION_EXPLANATION_VERSION = 1


class PackageOperationReadPort(Protocol):
    def read_operation(
        self, operation_id: str
    ) -> tuple[PackageLifecycleRequestV1, PackageLifecycleStatusV1] | None: ...


@dataclass(frozen=True, slots=True)
class PackageOperationExplanationV1:
    operation_id: str
    observed_at_unix_ns: int
    owner: Literal["package_lifecycle"]
    status: Literal["observed", "unknown"]
    product_id: str | None
    scope_id: str | None
    action: PackageLifecycleAction | None
    requested_plugin_id: str | None
    policy_revision: str | None
    phase: PackageLifecyclePhase | None
    disposition: PackageLifecycleDisposition | None
    request_fingerprint: str | None
    journal_revision: int | None
    attempt_epoch: int | None
    failure_code: str | None
    operator_action: str | None
    failure_evidence_ref: str | None
    snapshot_status: Literal["partial_evidence"] = "partial_evidence"
    explanation_version: int = PACKAGE_OPERATION_EXPLANATION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ValueError("Package explanation operation id is required")
        if type(self.observed_at_unix_ns) is not int or self.observed_at_unix_ns < 0:
            raise ValueError("Package explanation observation time is invalid")
        if self.owner != "package_lifecycle":
            raise ValueError("Package explanation owner is invalid")
        if self.status not in {"observed", "unknown"}:
            raise ValueError("Package explanation status is invalid")
        if self.status == "unknown" and any(
            value is not None
            for value in (
                self.product_id,
                self.scope_id,
                self.action,
                self.requested_plugin_id,
                self.policy_revision,
                self.phase,
                self.disposition,
                self.request_fingerprint,
                self.journal_revision,
                self.attempt_epoch,
                self.failure_code,
                self.operator_action,
                self.failure_evidence_ref,
            )
        ):
            raise ValueError("Unknown Package operation cannot assert owner facts")
        if self.snapshot_status != "partial_evidence":
            raise ValueError("Package-only explanation is partial evidence")
        if self.status == "observed" and (
            self.request_fingerprint is None
            or len(self.request_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.request_fingerprint
            )
        ):
            raise ValueError("Package request fingerprint is invalid")
        if self.explanation_version != PACKAGE_OPERATION_EXPLANATION_VERSION:
            raise ValueError("Unsupported Package operation explanation")

    def to_dict(self) -> dict[str, object]:
        """Omit Source locator, requested Package, credentials and failure text."""

        return {
            "operationId": self.operation_id,
            "observedAtUnixNs": self.observed_at_unix_ns,
            "owner": self.owner,
            "status": self.status,
            "productId": self.product_id,
            "scopeId": self.scope_id,
            "action": self.action,
            "requestedPluginId": self.requested_plugin_id,
            "policyRevision": self.policy_revision,
            "phase": self.phase,
            "disposition": self.disposition,
            "requestFingerprint": self.request_fingerprint,
            "journalRevision": self.journal_revision,
            "attemptEpoch": self.attempt_epoch,
            "failureCode": self.failure_code,
            "operatorAction": self.operator_action,
            "failureEvidenceRef": self.failure_evidence_ref,
            "snapshotStatus": self.snapshot_status,
            "explanationVersion": self.explanation_version,
        }


class PackageOperationExplanationProjector:
    """Read only the A2 owner; no management or Product success is inferred."""

    def __init__(
        self,
        operations: PackageOperationReadPort,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not callable(getattr(operations, "read_operation", None)):
            raise TypeError("Package operation read port is required")
        if not callable(clock_ns):
            raise TypeError("Package explanation clock is required")
        self._operations = operations
        self._clock_ns = clock_ns

    def explain_operation(self, operation_id: str) -> PackageOperationExplanationV1:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        observed = self._operations.read_operation(operation_id)
        request, status = observed if observed is not None else (None, None)
        if request is not None and (
            status is None
            or request.operation_id != operation_id
            or status.operation_id != operation_id
            or status.request_fingerprint != request.request_fingerprint
        ):
            raise ValueError("Package operation read changed exact identity")
        failure = None if status is None else status.failure
        return PackageOperationExplanationV1(
            operation_id=operation_id,
            observed_at_unix_ns=self._clock_ns(),
            owner="package_lifecycle",
            status="unknown" if request is None else "observed",
            product_id=None if request is None else request.product_id,
            scope_id=None if request is None else request.scope_id,
            action=None if request is None else request.action,
            requested_plugin_id=(
                None if request is None else request.requested_plugin_id
            ),
            policy_revision=None if request is None else request.policy_revision,
            phase=None if status is None else status.phase,
            disposition=None if status is None else status.disposition,
            request_fingerprint=(
                None if status is None else status.request_fingerprint
            ),
            journal_revision=None if status is None else status.journal_revision,
            attempt_epoch=None if status is None else status.attempt_epoch,
            failure_code=None if failure is None else failure.code,
            operator_action=None if failure is None else failure.operator_action,
            failure_evidence_ref=(None if failure is None else failure.evidence_ref),
        )


__all__ = [
    "PACKAGE_OPERATION_EXPLANATION_VERSION",
    "PackageOperationExplanationProjector",
    "PackageOperationExplanationV1",
    "PackageOperationReadPort",
]

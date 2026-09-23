"""PLC9B Product transaction over the existing Package lifecycle owners.

The Product router owns ingress and classification. This adapter only
coordinates the accepted Package owners; it has no legacy materializer path.
"""

from __future__ import annotations

from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_runtime import (
    PackageClosureExecutionRequestV2,
    PackageClosureExecutionResult,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackagePublicationReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecycleRequestV2,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingSetExecutionResult,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pin_runtime import (
    PackageTransactionPinExecutionResult,
)
from loushang.harness.resources.packages.product_handoff import (
    PackageProductHandoffPort,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductRouteContractError,
    PackageProductRouteRequestV1,
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
        "transaction_pinned",
    }
)


class PackageProductExecutionPort(Protocol):
    def __call__(
        self,
        request: PackageProductRouteRequestV1,
        current: PackageLifecycleStatusV1,
    ) -> PackageClosureExecutionRequestV2: ...


class PackageProductClosurePort(Protocol):
    def execute(
        self, execution: PackageClosureExecutionRequestV2
    ) -> PackageClosureExecutionResult: ...

    def reacquire(
        self, execution: PackageClosureExecutionRequestV2
    ) -> PackageClosureExecutionResult: ...


class PackageProductPinPort(Protocol):
    def pin(
        self,
        candidate: VerifiedPackageClosureCandidate,
        *,
        recovery_identity: str,
    ) -> PackageTransactionPinExecutionResult: ...


class PackageProductStagingPort(Protocol):
    def stage_and_publish(
        self, candidate: VerifiedPackageClosureCandidate
    ) -> PackageStagingSetExecutionResult: ...

    def resume(self, operation_id: str) -> PackageStagingSetExecutionResult: ...


class PackageProductCommitPort(Protocol):
    def commit(self, operation_id: str) -> PackagePublicationReceiptV1: ...


class PackageProductLifecycleTransaction:
    """Run one admitted install through exact Package owners and real Stores."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        execution: PackageProductExecutionPort,
        recovery_identity: str,
        closure: PackageProductClosurePort,
        pins: PackageProductPinPort,
        staging: PackageProductStagingPort,
        commit: PackageProductCommitPort,
        handoff: PackageProductHandoffPort,
    ) -> None:
        if not isinstance(kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle owner is required")
        if not callable(execution):
            raise TypeError("Package Product execution factory is required")
        if not isinstance(recovery_identity, str) or not recovery_identity:
            raise ValueError("Package recovery identity is required")
        for owner, methods, name in (
            (closure, ("execute", "reacquire"), "closure owner"),
            (pins, ("pin",), "pin owner"),
            (staging, ("stage_and_publish", "resume"), "staging owner"),
            (commit, ("commit",), "commit owner"),
            (handoff, ("finalize",), "handoff owner"),
        ):
            if any(not callable(getattr(owner, method, None)) for method in methods):
                raise TypeError(f"Package Product {name} is required")
        self._kernel = kernel
        self._execution = execution
        self._recovery_identity = recovery_identity
        self._closure = closure
        self._pins = pins
        self._staging = staging
        self._commit = commit
        self._handoff = handoff

    @property
    def owner_binding_id(self) -> str:
        return self._kernel.binding_id

    def finalize_committed(
        self,
        request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> None:
        self._handoff.finalize(request, current=current)

    def execute(
        self,
        request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        if not isinstance(request, PackageProductRouteRequestV1):
            raise TypeError("Package Product route request is required")
        if not isinstance(current, PackageLifecycleStatusV1):
            raise TypeError("Package lifecycle status is required")
        if request.entrypoint not in {
            "cli", "rpc", "session", "startup", "operations"
        }:
            raise PackageProductRouteContractError(
                "Direct Package route cannot enter the Product transaction"
            )
        durable = self._kernel.status(current.operation_id)
        lifecycle_request = self._kernel.journal.request(current.operation_id)
        classification = current.classification
        if (
            durable != current
            or not isinstance(lifecycle_request, PackageLifecycleRequestV2)
            or classification is None
            or classification.decision != "plugin_bound"
            or lifecycle_request
            != request.ingress.bind_classification_facts(classification.basis_facts)
        ):
            raise PackageProductRouteContractError(
                "Product transaction lacks the exact admitted Package request"
            )
        if current.disposition != "active":
            return current
        if lifecycle_request.action != "install":
            return self._reject(current, code="package_route_unavailable")
        execution = self._execution(request, current)
        if not isinstance(execution, PackageClosureExecutionRequestV2):
            raise PackageProductRouteContractError(
                "Package Product execution factory returned invalid evidence"
            )
        artifact = execution.artifact
        if (
            artifact.operation_id != current.operation_id
            or artifact.request_fingerprint != current.request_fingerprint
            or artifact.expected_attempt_epoch != current.attempt_epoch
            or execution.resolution_environment.fingerprint
            != lifecycle_request.resolution_environment_fingerprint
        ):
            return self._reject(current, code="package_operation_identity_conflict")

        if current.phase in _CLOSURE_PHASES:
            closed = (
                self._closure.reacquire(execution)
                if current.phase == "transaction_pinned"
                else self._closure.execute(execution)
            )
            if not isinstance(closed, PackageClosureExecutionResult):
                raise PackageProductRouteContractError(
                    "Package closure owner returned invalid evidence"
                )
            status = closed.status
            candidate = closed.candidate
            try:
                self._require_durable(status, current)
                if candidate is None:
                    return self._require_terminal(status)
                pinned = self._pins.pin(
                    candidate, recovery_identity=self._recovery_identity
                )
                if not isinstance(pinned, PackageTransactionPinExecutionResult):
                    raise PackageProductRouteContractError(
                        "Package pin owner returned invalid evidence"
                    )
                status = pinned.status
                self._require_durable(status, current)
                if pinned.candidate is None:
                    return self._require_terminal(status)
                if pinned.candidate is not candidate or pinned.receipt is None:
                    raise PackageProductRouteContractError(
                        "Package pin owner changed the verified candidate"
                    )
                staged = self._staging.stage_and_publish(candidate)
            finally:
                if candidate is not None:
                    candidate.suspend_for_recovery()
            return self._after_staging(staged, current)
        if current.phase in {"staging", "set_published"}:
            return self._after_staging(
                self._staging.resume(current.operation_id), current
            )
        raise PackageProductRouteContractError(
            "Package Product transaction has no phase owner"
        )

    def _after_staging(
        self,
        staged: PackageStagingSetExecutionResult,
        initial: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        if not isinstance(staged, PackageStagingSetExecutionResult):
            raise PackageProductRouteContractError(
                "Package staging owner returned invalid evidence"
            )
        status = staged.status
        self._require_durable(status, initial)
        if status.disposition != "active":
            return self._require_terminal(status)
        if status.phase != "set_published" or staged.committed_set is None:
            raise PackageProductRouteContractError(
                "Package staging owner has not published an exact set"
            )
        publication = self._commit.commit(status.operation_id)
        committed = self._kernel.status(status.operation_id)
        if (
            not isinstance(publication, PackagePublicationReceiptV1)
            or committed is None
            or committed.phase != "committed"
            or committed.disposition != "committed"
            or committed.classification is None
            or publication.operation_id != committed.operation_id
            or publication.request_fingerprint != committed.request_fingerprint
            or publication.attempt_epoch != committed.attempt_epoch
            or publication.classification_fingerprint
            != committed.classification.evidence_ref
            or publication.committed_set != staged.committed_set
            or publication.commit_status_revision != committed.journal_revision
        ):
            raise PackageProductRouteContractError(
                "Package commit owner lacks an exact durable publication"
            )
        self._require_durable(committed, initial)
        return committed

    def _require_durable(
        self,
        status: PackageLifecycleStatusV1,
        initial: PackageLifecycleStatusV1,
    ) -> None:
        classification = initial.classification
        if (
            not isinstance(status, PackageLifecycleStatusV1)
            or self._kernel.status(initial.operation_id) != status
            or status.operation_id != initial.operation_id
            or status.request_fingerprint != initial.request_fingerprint
            or status.attempt_epoch != initial.attempt_epoch
            or status.classification != classification
        ):
            raise PackageProductRouteContractError(
                "Package transaction owner changed durable route identity"
            )

    @staticmethod
    def _require_terminal(status: PackageLifecycleStatusV1) -> PackageLifecycleStatusV1:
        if status.disposition == "active":
            raise PackageProductRouteContractError(
                "Package Product transaction stopped at an active phase"
            )
        return status

    def _reject(
        self, status: PackageLifecycleStatusV1, *, code: str
    ) -> PackageLifecycleStatusV1:
        classification = status.classification
        assert classification is not None
        return self._kernel.record_failure(
            PackageLifecycleFailureV1.for_operation(
                code,
                stage=status.phase,
                operation_id=status.operation_id,
                evidence_ref=classification.evidence_ref,
            ),
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )


__all__ = ["PackageProductLifecycleTransaction"]

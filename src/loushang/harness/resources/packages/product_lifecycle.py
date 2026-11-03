"""Product routing boundary for the PLC9B Package lifecycle.

The router is intentionally capability-poor.  Product transports submit one
unclassified ingress request, while the injected transaction Port is the only
object that can run a Plugin-bound Package transaction.  Direct materializer
and publication routes are refusals, never alternate implementations.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecycleIngressRequestV2,
    PackageLifecyclePinnedAdoptionRequestV1,
    PackageLifecycleRebindRequestV1,
    PackageLifecycleRequestV2,
    PackageLifecycleRetryRequestV1,
    PackageLifecycleStagingAdoptionRequestV1,
    PackageLifecycleStatusV1,
    canonicalize_source_identity,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductEntrypoint,
)

PACKAGE_PRODUCT_ROUTE_VERSION = 1
PACKAGE_PRODUCT_REBOUND_ROUTE_VERSION = 1
PACKAGE_PRODUCT_PINNED_ADOPTED_ROUTE_VERSION = 1
PACKAGE_PRODUCT_STAGING_ADOPTED_ROUTE_VERSION = 1
PACKAGE_PRODUCT_PUBLISH_ATTEMPT_VERSION = 1

_PRODUCT_ENTRYPOINTS = frozenset(
    {
        "cli",
        "rpc",
        "session",
        "startup",
        "operations",
        "direct_materializer",
    }
)
_TRANSACTION_ENTRYPOINTS = frozenset({"cli", "rpc", "session", "startup", "operations"})


@dataclass(frozen=True, slots=True)
class PackageProductRouteRequestV1:
    """Bind Product transport provenance to one pathless ingress request."""

    entrypoint: PackageProductEntrypoint
    ingress: PackageLifecycleIngressRequestV2
    admission: PackageEpochRuntimeAdmissionReceiptV1
    route_version: int = PACKAGE_PRODUCT_ROUTE_VERSION

    def __post_init__(self) -> None:
        if self.entrypoint not in _PRODUCT_ENTRYPOINTS:
            raise ValueError("Unsupported Package Product entrypoint")
        if not isinstance(self.ingress, PackageLifecycleIngressRequestV2):
            raise TypeError("Package lifecycle ingress request v2 is required")
        if not isinstance(self.admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Package runtime admission receipt is required")
        if (
            self.ingress.runtime_admission_request_id
            != self.admission.request.admission_request_id
        ):
            raise ValueError("Package runtime admission identity is inconsistent")
        if self.route_version != PACKAGE_PRODUCT_ROUTE_VERSION:
            raise ValueError("Unsupported Package Product route request")


@dataclass(frozen=True, slots=True)
class PackageProductReboundRouteRequestV1:
    """Preserve the original ingress while executing one selected admission."""

    entrypoint: PackageProductEntrypoint
    ingress: PackageLifecycleIngressRequestV2
    admission: PackageEpochRuntimeAdmissionReceiptV1
    decision: PackageLifecycleRebindRequestV1
    route_version: int = PACKAGE_PRODUCT_REBOUND_ROUTE_VERSION

    def __post_init__(self) -> None:
        if self.entrypoint not in _TRANSACTION_ENTRYPOINTS:
            raise ValueError("Rebound Package Product entrypoint is invalid")
        if not isinstance(self.ingress, PackageLifecycleIngressRequestV2):
            raise TypeError("Original Package lifecycle ingress is required")
        if not isinstance(self.admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Rebound Package runtime admission is required")
        if not isinstance(self.decision, PackageLifecycleRebindRequestV1):
            raise TypeError("Durable Package rebind decision is required")
        if (
            self.decision.operation_id != self.ingress.operation_id
            or self.decision.new_runtime_admission_request_id
            != self.admission.request.admission_request_id
            or self.ingress.runtime_admission_request_id
            == self.admission.request.admission_request_id
            or self.route_version != PACKAGE_PRODUCT_REBOUND_ROUTE_VERSION
        ):
            raise ValueError("Rebound Package Product route identity changed")


@dataclass(frozen=True, slots=True)
class PackageProductPinnedAdoptedRouteRequestV1:
    """Execute only the selected admission for an unchanged pinned attempt."""

    entrypoint: PackageProductEntrypoint
    ingress: PackageLifecycleIngressRequestV2
    admission: PackageEpochRuntimeAdmissionReceiptV1
    decision: PackageLifecyclePinnedAdoptionRequestV1
    route_version: int = PACKAGE_PRODUCT_PINNED_ADOPTED_ROUTE_VERSION

    def __post_init__(self) -> None:
        if self.entrypoint not in _TRANSACTION_ENTRYPOINTS:
            raise ValueError("Pinned Package Product entrypoint is invalid")
        if not isinstance(self.ingress, PackageLifecycleIngressRequestV2):
            raise TypeError("Original Package lifecycle ingress is required")
        if not isinstance(self.admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Pinned Package runtime admission is required")
        if not isinstance(self.decision, PackageLifecyclePinnedAdoptionRequestV1):
            raise TypeError("Durable pinned Package decision is required")
        if (
            self.decision.operation_id != self.ingress.operation_id
            or self.decision.new_runtime_admission_request_id
            != self.admission.request.admission_request_id
            or self.decision.lease_snapshot_id != self.admission.lease_snapshot_id
            or self.ingress.runtime_admission_request_id
            == self.admission.request.admission_request_id
            or self.route_version != PACKAGE_PRODUCT_PINNED_ADOPTED_ROUTE_VERSION
        ):
            raise ValueError("Pinned Package Product route identity changed")


@dataclass(frozen=True, slots=True)
class PackageProductStagingAdoptedRouteRequestV1:
    """Execute one verified staged prefix under its selected admission."""

    entrypoint: PackageProductEntrypoint
    ingress: PackageLifecycleIngressRequestV2
    admission: PackageEpochRuntimeAdmissionReceiptV1
    decision: PackageLifecycleStagingAdoptionRequestV1
    missing_node_ids: tuple[str, ...] = ()
    route_version: int = PACKAGE_PRODUCT_STAGING_ADOPTED_ROUTE_VERSION

    def __post_init__(self) -> None:
        if self.entrypoint not in _TRANSACTION_ENTRYPOINTS:
            raise ValueError("Staging Package Product entrypoint is invalid")
        if not isinstance(self.ingress, PackageLifecycleIngressRequestV2):
            raise TypeError("Original Package lifecycle ingress is required")
        if not isinstance(self.admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Staging Package runtime admission is required")
        if not isinstance(self.decision, PackageLifecycleStagingAdoptionRequestV1):
            raise TypeError("Durable staging Package decision is required")
        if (
            self.decision.operation_id != self.ingress.operation_id
            or self.decision.new_runtime_admission_request_id
            != self.admission.request.admission_request_id
            or self.decision.lease_snapshot_id != self.admission.lease_snapshot_id
            or self.ingress.runtime_admission_request_id
            == self.admission.request.admission_request_id
            or self.route_version != PACKAGE_PRODUCT_STAGING_ADOPTED_ROUTE_VERSION
        ):
            raise ValueError("Staging Package Product route identity changed")
        if (
            not isinstance(self.missing_node_ids, tuple)
            or any(
                not isinstance(node_id, str) or not node_id
                for node_id in self.missing_node_ids
            )
            or self.missing_node_ids != tuple(sorted(set(self.missing_node_ids)))
        ):
            raise ValueError("Staging Package missing nodes are not canonical")


PackageProductTransactionRoute = (
    PackageProductRouteRequestV1
    | PackageProductReboundRouteRequestV1
    | PackageProductPinnedAdoptedRouteRequestV1
    | PackageProductStagingAdoptedRouteRequestV1
)


@dataclass(frozen=True, slots=True)
class PackageProductPublishAttemptV1:
    """Describe a forbidden direct publication from an existing staging edge."""

    status: PackageLifecycleStatusV1
    attempt_version: int = PACKAGE_PRODUCT_PUBLISH_ATTEMPT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, PackageLifecycleStatusV1):
            raise TypeError("Package lifecycle staging status is required")
        if self.attempt_version != PACKAGE_PRODUCT_PUBLISH_ATTEMPT_VERSION:
            raise ValueError("Unsupported Package Product publish attempt")


class PackageProductLifecycleTransactionPort(Protocol):
    """The sole Product-facing capability that may run a PLC9B transaction."""

    @property
    def owner_binding_id(self) -> str: ...

    def execute(
        self,
        request: PackageProductTransactionRoute,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1: ...

    def finalize_committed(
        self,
        request: PackageProductTransactionRoute,
        *,
        current: PackageLifecycleStatusV1,
    ) -> None: ...


class PackageProductAdmissionBindingPort(Protocol):
    """Product sole writer for an accepted operation's original lease."""

    def bind(
        self,
        request: PackageLifecycleRequestV2,
        status: PackageLifecycleStatusV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> object: ...


class PackageProductRouteContractError(RuntimeError):
    """A configured transaction Port violated the Product routing contract."""

    def __init__(
        self, message: str, *, code: str = "package_product_route_contract_invalid"
    ) -> None:
        super().__init__(message)
        self.code = code


def require_rebound_decision(
    request: PackageProductTransactionRoute,
    current: PackageLifecycleStatusV1,
    journal: PackageLifecycleJournal,
) -> None:
    """Require the exact selected admission for a rebound or pinned attempt."""

    staged_selection = journal.latest_staging_adoption(request.ingress.operation_id)
    if isinstance(request, PackageProductStagingAdoptedRouteRequestV1):
        if (
            staged_selection is None
            or staged_selection.decision != request.decision
            or current.operation_id != request.decision.operation_id
            or current.request_fingerprint != request.decision.request_fingerprint
            or current.attempt_epoch != request.decision.expected_attempt_epoch
            or current.attempt_revision < staged_selection.record_revision
        ):
            raise PackageProductRouteContractError(
                "Staging Package transaction lacks the selected admission",
                code="package_staging_adoption_execution_not_available",
            )
        return
    if (
        staged_selection is not None
        and current.attempt_epoch == staged_selection.status.attempt_epoch
        and current.attempt_revision >= staged_selection.record_revision
    ):
        raise PackageProductRouteContractError(
            "Staged Package effects require their selected Product route",
            code="package_staging_adoption_route_required",
        )

    selected_adoption = (
        journal.latest_pinned_adoption(request.ingress.operation_id)
        if current.attempt_revision > 0
        and current.phase in {
            "transaction_pinned", "staging", "set_published", "committed"
        }
        else None
    )
    if isinstance(request, PackageProductPinnedAdoptedRouteRequestV1):
        if (
            selected_adoption is None
            or selected_adoption.decision != request.decision
            or current.operation_id != request.decision.operation_id
            or current.request_fingerprint != request.decision.request_fingerprint
            or current.attempt_epoch != request.decision.expected_attempt_epoch
            or current.attempt_revision < selected_adoption.record_revision
        ):
            raise PackageProductRouteContractError(
                "Pinned Package transaction lacks the selected admission",
                code="package_pinned_adoption_execution_not_available",
            )
        return
    if (
        selected_adoption is not None
        and current.attempt_epoch == selected_adoption.status.attempt_epoch
        and current.attempt_revision >= selected_adoption.record_revision
    ):
        raise PackageProductRouteContractError(
            "Pinned Package admission was adopted by another runtime",
            code="package_pinned_adoption_route_required",
        )
    if not isinstance(request, PackageProductReboundRouteRequestV1):
        return
    selected = journal.latest_rebind(request.ingress.operation_id)
    if (
        selected is None
        or selected.decision != request.decision
        or current.operation_id != request.decision.operation_id
        or current.request_fingerprint != request.decision.request_fingerprint
        or current.attempt_epoch != request.decision.expected_attempt_epoch + 1
        or current.attempt_revision <= selected.record_revision
    ):
        raise PackageProductRouteContractError(
            "Rebound Package transaction lacks the selected durable attempt",
            code="package_rebind_execution_not_available",
        )


@dataclass(frozen=True, slots=True)
class PackageProductLifecycleExecutionBinding:
    """Indivisible owner/transaction pair for one durable lifecycle journal."""

    owner: PackageLifecycleOwner
    transaction: PackageProductLifecycleTransactionPort

    def __post_init__(self) -> None:
        if not isinstance(self.owner, PackageLifecycleOwner):
            raise TypeError("Package lifecycle owner is required")
        if not callable(getattr(self.transaction, "execute", None)):
            raise TypeError("Package Product transaction Port is required")
        transaction_owner = getattr(self.transaction, "owner_binding_id", None)
        if transaction_owner != self.owner.binding_id:
            raise PackageProductRouteContractError(
                "Package Product transaction is bound to a different owner"
            )
        if not callable(getattr(self.transaction, "finalize_committed", None)):
            raise PackageProductRouteContractError(
                "Package Product transaction lacks a committed handoff"
            )


class PackageProductLifecycleRouter:
    """Route every Plugin-bound Product entrypoint to one transaction Port."""

    def __init__(
        self,
        *,
        execution: PackageProductLifecycleExecutionBinding,
        reference_guard: Callable[[], AbstractContextManager[object]] | None = None,
        update_preflight: Callable[[PackageProductRouteRequestV1], None] | None = None,
        admission_binding: PackageProductAdmissionBindingPort | None = None,
    ) -> None:
        if not isinstance(execution, PackageProductLifecycleExecutionBinding):
            raise TypeError("Package Product lifecycle execution binding is required")
        if reference_guard is not None and not callable(reference_guard):
            raise TypeError("Package Product reference guard is invalid")
        if admission_binding is not None and not callable(
            getattr(admission_binding, "bind", None)
        ):
            raise TypeError("Package Product admission binding is invalid")
        self._owner = execution.owner
        self._transaction = execution.transaction
        self._owner_binding_id = execution.owner.binding_id
        self._reference_guard = (
            reference_guard if reference_guard is not None else nullcontext
        )
        self._update_preflight = update_preflight
        self._admission_binding = admission_binding

    def route(
        self,
        request: PackageProductRouteRequestV1,
    ) -> PackageLifecycleStatusV1:
        """Classify once and route without owning a compatibility fallback."""

        with self._reference_guard():
            if not isinstance(request, PackageProductRouteRequestV1):
                raise TypeError("Package Product route request is required")
            if (
                request.ingress.action == "update"
                and request.entrypoint in _TRANSACTION_ENTRYPOINTS
                and self._update_preflight is not None
            ):
                self._update_preflight(request)
            status = self._owner.submit(request.ingress)
            require_rebound_decision(request, status, self._owner.journal)
            self._bind_original_admission(request, status)
            return self._route_status(request, status)

    def retry(
        self,
        request: PackageProductRouteRequestV1,
        *,
        request_fingerprint: str,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        """Resume one retryable owner attempt and run its Product transaction."""

        if not isinstance(request, PackageProductRouteRequestV1):
            raise TypeError("Package Product route request is required")
        retry = PackageLifecycleRetryRequestV1(
            operation_id=request.ingress.operation_id,
            request_fingerprint=request_fingerprint,
            expected_attempt_epoch=expected_attempt_epoch,
        )
        with self._reference_guard():
            if request.entrypoint not in _TRANSACTION_ENTRYPOINTS:
                raise PackageProductRouteContractError(
                    "Package Product retry requires a transaction entrypoint"
                )
            original = self._owner.journal.read_operation(request.ingress.operation_id)
            if original is not None:
                stored, observed = original
                if (
                    isinstance(stored, PackageLifecycleRequestV2)
                    and observed.disposition == "retryable_failure"
                    and observed.request_fingerprint == request_fingerprint
                    and observed.attempt_epoch == expected_attempt_epoch
                    and observed.failure is not None
                    and observed.failure.operator_action == "retry"
                    and stored.action == request.ingress.action
                    and stored.product_id == request.ingress.product_id
                    and stored.scope_id == request.ingress.scope_id
                    and stored.requested_package == request.ingress.requested_package
                    and stored.requested_plugin_id
                    == request.ingress.requested_plugin_id
                    and stored.canonical_source_identity
                    == canonicalize_source_identity(request.ingress.source_locator)
                    and stored.policy_revision == request.ingress.policy_revision
                    and stored.quota_profile_revision
                    == request.ingress.quota_profile_revision
                    and stored.resolution_environment_fingerprint
                    == request.ingress.resolution_environment_fingerprint
                    and stored.runtime_admission_request_id
                    != request.admission.request.admission_request_id
                ):
                    raise PackageProductRouteContractError(
                        "Package retry requires a durable runtime rebind",
                        code="package_retry_rebind_required",
                    )
            if (
                request.ingress.action == "update"
                and self._update_preflight is not None
            ):
                self._update_preflight(request)
            status = self._owner.submit(request.ingress)
            if (
                status.disposition != "retryable_failure"
                or status.request_fingerprint != request_fingerprint
                or status.attempt_epoch != expected_attempt_epoch
                or status.classification is None
                or status.classification.decision != "plugin_bound"
                or status.failure is None
                or status.failure.operator_action != "retry"
                or self._transaction.owner_binding_id != self._owner_binding_id
            ):
                raise PackageProductRouteContractError(
                    "Package Product retry changed owner or attempt evidence"
                )
            self._bind_original_admission(request, status)
            resumed = self._owner.retry(retry)
            if (
                resumed.disposition != "active"
                or resumed.attempt_epoch != expected_attempt_epoch + 1
                or resumed.request_fingerprint != request_fingerprint
            ):
                raise PackageProductRouteContractError(
                    "Package Product retry did not resume the exact attempt"
                )
            return self._route_status(request, resumed)

    def route_rebound(
        self,
        request: PackageProductReboundRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        """Execute only the exact already-resumed rebound attempt."""

        if not isinstance(request, PackageProductReboundRouteRequestV1):
            raise TypeError("Rebound Package Product route is required")
        with self._reference_guard():
            if self._owner.status(request.ingress.operation_id) != current:
                raise PackageProductRouteContractError(
                    "Rebound Package attempt changed before Product route"
                )
            require_rebound_decision(request, current, self._owner.journal)
            return self._route_status(request, current)

    def route_pinned_adopted(
        self,
        request: PackageProductPinnedAdoptedRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        """Run only the exact selected pinned attempt and admission."""

        if not isinstance(request, PackageProductPinnedAdoptedRouteRequestV1):
            raise TypeError("Pinned Package Product route is required")
        with self._reference_guard():
            if self._owner.status(request.ingress.operation_id) != current:
                raise PackageProductRouteContractError(
                    "Pinned Package attempt changed before Product route"
                )
            require_rebound_decision(request, current, self._owner.journal)
            return self._route_status(request, current)

    def route_staging_adopted(
        self,
        request: PackageProductStagingAdoptedRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        """Run only the exact selected staging checkpoint."""

        if not isinstance(request, PackageProductStagingAdoptedRouteRequestV1):
            raise TypeError("Staging Package Product route is required")
        with self._reference_guard():
            if self._owner.status(request.ingress.operation_id) != current:
                raise PackageProductRouteContractError(
                    "Staging Package attempt changed before Product route"
                )
            require_rebound_decision(request, current, self._owner.journal)
            return self._route_status(request, current)

    def _bind_original_admission(
        self,
        request: PackageProductRouteRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> None:
        binder = self._admission_binding
        if (
            binder is None
            or request.entrypoint not in _TRANSACTION_ENTRYPOINTS
            or status.classification is None
            or status.classification.decision != "plugin_bound"
            or status.disposition not in {"active", "retryable_failure", "committed"}
        ):
            return
        observed = self._owner.journal.read_operation(status.operation_id)
        if (
            observed is None
            or not isinstance(observed[0], PackageLifecycleRequestV2)
            or observed[1] != status
        ):
            raise PackageProductRouteContractError(
                "Package original admission lost its exact owner request",
                code="package_product_admission_binding_owner_changed",
            )
        binder.bind(observed[0], status, request.admission)

    def _route_status(
        self,
        request: PackageProductTransactionRoute,
        status: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        if status.disposition == "committed":
            self._finalize_committed(request, status)
            return status
        if status.disposition != "active":
            return status
        classification = status.classification
        if classification is None:
            raise PackageProductRouteContractError(
                "Classified Package route has no classification evidence"
            )
        if classification.decision != "plugin_bound":
            # A separately accepted non-Plugin authority may consume this
            # classification.  This router deliberately holds no such peer.
            return status
        if request.entrypoint == "direct_materializer":
            if status.phase != "classified":
                raise PackageProductRouteContractError(
                    "Direct Package materializer replay crossed a transaction edge"
                )
            return self._reject_direct_materializer(status)
        if request.entrypoint not in _TRANSACTION_ENTRYPOINTS:
            raise PackageProductRouteContractError(
                "Package Product entrypoint has no transaction route"
            )

        if self._transaction.owner_binding_id != self._owner_binding_id:
            raise PackageProductRouteContractError(
                "Package Product transaction owner changed after composition"
            )

        result = self._transaction.execute(request, current=status)
        if not isinstance(result, PackageLifecycleStatusV1):
            raise PackageProductRouteContractError(
                "Package Product transaction returned invalid status"
            )
        durable = self._owner.status(status.operation_id)
        if durable is None or durable != result:
            raise PackageProductRouteContractError(
                "Package Product transaction result is not durable"
            )
        if (
            result.operation_id != status.operation_id
            or result.request_fingerprint != status.request_fingerprint
            or result.classification != status.classification
            or result.disposition == "active"
        ):
            raise PackageProductRouteContractError(
                "Package Product transaction result changed route identity"
            )
        if result.disposition == "committed":
            self._finalize_committed(request, result)
        return result

    def _finalize_committed(
        self,
        request: PackageProductTransactionRoute,
        status: PackageLifecycleStatusV1,
    ) -> None:
        if (
            request.entrypoint not in _TRANSACTION_ENTRYPOINTS
            or status.classification is None
            or status.classification.decision != "plugin_bound"
            or self._transaction.owner_binding_id != self._owner_binding_id
        ):
            raise PackageProductRouteContractError(
                "Committed Package Product route changed transaction authority"
            )
        finalizer = getattr(self._transaction, "finalize_committed", None)
        if not callable(finalizer) or finalizer(request, current=status) is not None:
            raise PackageProductRouteContractError(
                "Package Product handoff finalizer returned invalid evidence"
            )
        if self._owner.status(status.operation_id) != status:
            raise PackageProductRouteContractError(
                "Package Product handoff changed committed Package evidence"
            )

    def refuse_direct_publish(
        self,
        attempt: PackageProductPublishAttemptV1,
    ) -> PackageLifecycleStatusV1:
        """Durably refuse publication without calling a publication Port."""

        if not isinstance(attempt, PackageProductPublishAttemptV1):
            raise TypeError("Package Product publish attempt is required")
        status = attempt.status
        if (
            status.phase != "staging"
            or status.disposition != "active"
            or status.classification is None
            or status.classification.decision != "plugin_bound"
        ):
            raise PackageProductRouteContractError(
                "Direct Package publication requires active Plugin staging evidence"
            )
        failure = PackageLifecycleFailureV1.for_operation(
            "package_route_unavailable",
            stage="staging",
            operation_id=status.operation_id,
            evidence_ref=status.classification.evidence_ref,
        )
        return self._owner.record_failure(
            failure,
            expected_phase="staging",
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )

    def _reject_direct_materializer(
        self,
        status: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        classification = status.classification
        assert classification is not None
        failure = PackageLifecycleFailureV1.for_operation(
            "package_route_unavailable",
            stage="classified",
            operation_id=status.operation_id,
            evidence_ref=classification.evidence_ref,
        )
        return self._owner.record_failure(
            failure,
            expected_phase="classified",
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )


__all__ = [
    "PACKAGE_PRODUCT_PINNED_ADOPTED_ROUTE_VERSION",
    "PACKAGE_PRODUCT_PUBLISH_ATTEMPT_VERSION",
    "PACKAGE_PRODUCT_REBOUND_ROUTE_VERSION",
    "PACKAGE_PRODUCT_ROUTE_VERSION",
    "PACKAGE_PRODUCT_STAGING_ADOPTED_ROUTE_VERSION",
    "PackageProductEntrypoint",
    "PackageProductLifecycleExecutionBinding",
    "PackageProductLifecycleRouter",
    "PackageProductPinnedAdoptedRouteRequestV1",
    "PackageProductLifecycleTransactionPort",
    "PackageProductPublishAttemptV1",
    "PackageProductReboundRouteRequestV1",
    "PackageProductRouteContractError",
    "PackageProductRouteRequestV1",
    "PackageProductStagingAdoptedRouteRequestV1",
    "PackageProductTransactionRoute",
    "require_rebound_decision",
]

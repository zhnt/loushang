"""Product routing boundary for the PLC9B Package lifecycle.

The router is intentionally capability-poor.  Product transports submit one
unclassified ingress request, while the injected transaction Port is the only
object that can run a Plugin-bound Package transaction.  Direct materializer
and publication routes are refusals, never alternate implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecycleIngressRequestV2,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductEntrypoint,
)

PACKAGE_PRODUCT_ROUTE_VERSION = 1
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
        request: PackageProductRouteRequestV1,
        *,
        current: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1: ...


class PackageProductRouteContractError(RuntimeError):
    """A configured transaction Port violated the Product routing contract."""


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


class PackageProductLifecycleRouter:
    """Route every Plugin-bound Product entrypoint to one transaction Port."""

    def __init__(
        self,
        *,
        execution: PackageProductLifecycleExecutionBinding,
    ) -> None:
        if not isinstance(execution, PackageProductLifecycleExecutionBinding):
            raise TypeError("Package Product lifecycle execution binding is required")
        self._owner = execution.owner
        self._transaction = execution.transaction
        self._owner_binding_id = execution.owner.binding_id

    def route(
        self,
        request: PackageProductRouteRequestV1,
    ) -> PackageLifecycleStatusV1:
        """Classify once and route without owning a compatibility fallback."""

        if not isinstance(request, PackageProductRouteRequestV1):
            raise TypeError("Package Product route request is required")
        status = self._owner.submit(request.ingress)
        if status.disposition == "committed":
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
        return result

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
    "PACKAGE_PRODUCT_PUBLISH_ATTEMPT_VERSION",
    "PACKAGE_PRODUCT_ROUTE_VERSION",
    "PackageProductEntrypoint",
    "PackageProductLifecycleExecutionBinding",
    "PackageProductLifecycleRouter",
    "PackageProductLifecycleTransactionPort",
    "PackageProductPublishAttemptV1",
    "PackageProductRouteContractError",
    "PackageProductRouteRequestV1",
]

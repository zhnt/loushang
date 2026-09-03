"""PLC9A2 composition root for the accepted Package Product owners."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
    PackageRetentionHandoffOwner,
    PackageRetentionHandoffReceiptV1,
)
from loushang.harness.resources.packages.product_activation import (
    PackageProductActivationError,
    PackageProductIngressFactoryPort,
    PackageProductLifecycleActivation,
    PackageProductRecoveryPort,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductLifecycleRouter,
    PackageProductLifecycleTransactionPort,
)


@dataclass(frozen=True, slots=True)
class PackageRetentionHandoffRecovery:
    """Resume every nonterminal retention handoff before Product activation."""

    journal: PackageRetentionHandoffJournal
    owner: PackageRetentionHandoffOwner

    def __post_init__(self) -> None:
        if not isinstance(self.journal, PackageRetentionHandoffJournal):
            raise TypeError("Package retention handoff journal is required")
        if not isinstance(self.owner, PackageRetentionHandoffOwner):
            raise TypeError("Package retention handoff owner is required")

    def recover(self) -> tuple[str, ...]:
        latest: dict[str, PackageRetentionHandoffReceiptV1] = {}
        for record in self.journal.records():
            if record.receipt is not None:
                latest[record.handoff_id] = record.receipt
        recovered: list[str] = []
        for handoff_id in sorted(latest):
            receipt = latest[handoff_id]
            if receipt.state in {"settled", "aborted"}:
                continue
            result = self.owner.execute(receipt.request, expected_receipt=receipt)
            if result.disposition == "retryable_failure" or (
                result.disposition == "rejected"
                and result.code == "package_retention_handoff_stale"
            ):
                raise PackageProductActivationError(
                    "Package retention handoff recovery remains incomplete",
                    code="package_product_recovery_incomplete",
                )
            recovered.append(handoff_id)
        return tuple(recovered)


def compose_package_product_lifecycle(
    *,
    product_id: str,
    owner: PackageLifecycleOwner,
    transaction: PackageProductLifecycleTransactionPort,
    ingress_factory: PackageProductIngressFactoryPort,
    runtime_admission: PackageEpochRuntimeAdmissionOwner,
    admission_request: PackageEpochRuntimeAdmissionRequestV1,
    recoveries: tuple[PackageProductRecoveryPort, ...] = (),
) -> PackageProductLifecycleActivation:
    """Build the sole Product router; the caller explicitly activates it."""

    return PackageProductLifecycleActivation(
        product_id=product_id,
        router=PackageProductLifecycleRouter(
            owner=owner,
            transaction=transaction,
        ),
        ingress_factory=ingress_factory,
        runtime_admission=runtime_admission,
        admission_request=admission_request,
        recoveries=recoveries,
    )


__all__ = [
    "PackageRetentionHandoffRecovery",
    "compose_package_product_lifecycle",
]

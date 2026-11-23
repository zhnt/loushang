"""Bind a Capability owner's policy reader to one selected Product Worker.

This private seam grants no Capability publication or Worker activation. The
Capability owner supplies its own exact binding and current policy reader;
Coding rechecks the selected Product launch material before each domain read.
"""

from __future__ import annotations

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.package_product._worker_product_authority import (
    _ProductWorkerCapabilityAuthority,
)
from loushang.harness.worker.capability_query import CapabilityWorkerBindingV1
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.facet_owner import (
    CapabilityWorkerFacetOwnerPolicy,
)
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .product_worker_query_consumer import bind_coding_worker_query_facet_owner
from .product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    CodingWorkerSelectedPayloadV1,
)
from .product_worker_windows_receipt import CodingWindowsWorkerProductReceiptOwner


class CodingWorkerCapabilityBindingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodingProductWorkerCapabilityAuthority(
    _ProductWorkerCapabilityAuthority[CodingWorkerSelectedPayloadV1]
):
    """Current Product selection joined to a separate Capability owner policy."""

    _capability_failure = staticmethod(
        lambda code: CodingWorkerCapabilityBindingError("coding_worker_" + code)
    )

    def __init__(
        self,
        *,
        receipt_owner: CodingWorkerProductReceiptOwner
        | CodingWindowsWorkerProductReceiptOwner,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        binding: CapabilityWorkerBindingV1,
        owner_policy: CapabilityWorkerFacetOwnerPolicy,
    ) -> None:
        if (
            type(receipt_owner)
            not in (
                CodingWorkerProductReceiptOwner,
                CodingWindowsWorkerProductReceiptOwner,
            )
            or not isinstance(receipt, ProductWorkerActivationReceiptV1)
            or (not isinstance(request, ManagedWorkerLaunchRequestV1))
            or (not isinstance(binding, CapabilityWorkerBindingV1))
            or (not isinstance(owner_policy, CapabilityWorkerFacetOwnerPolicy))
        ):
            raise TypeError("Coding Worker Capability authority inputs are invalid")
        self._initialize_capability(
            receipt_owner=receipt_owner,
            receipt=receipt,
            request=request,
            binding=binding,
            owner_policy=owner_policy,
        )


def _bind_query_authority(
    *,
    receipt_owner: CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    request: ManagedWorkerLaunchRequestV1,
    binding: CapabilityWorkerBindingV1,
    provider_owner: CapabilityProviderOwnerAuthority,
) -> CodingProductWorkerCapabilityAuthority:
    """Use the same exact query facet authority for both Session entry points."""
    return CodingProductWorkerCapabilityAuthority(
        receipt_owner=receipt_owner,
        receipt=receipt,
        request=request,
        binding=binding,
        owner_policy=bind_coding_worker_query_facet_owner(
            binding=binding,
            provider_owner=provider_owner,
            current_owner_snapshot=provider_owner.snapshot,
        ),
    )


__all__ = [
    "CodingProductWorkerCapabilityAuthority",
    "CodingWorkerCapabilityBindingError",
]

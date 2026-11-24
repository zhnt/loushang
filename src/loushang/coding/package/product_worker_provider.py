"""Rejoin a live Coding Product Worker receipt to inert Provider admission facts.

The Capability owner still decides eligibility. This bridge does not grant a
facet, start a Worker, construct a graph binding, or change Session routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from loushang.coding.composition.base_product import CodingBaseProductCompilation
from loushang.harness.capabilities.contracts import (
    CapabilityDefinition,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.package_product._worker_product_authority import (
    _ProductWorkerBaseCompositionPolicyMethods,
)
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .product_worker_query_consumer import (
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_PROVIDER_ID,
)
from .product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    CodingWorkerSelectedPayloadV1,
)
from .product_worker_windows_receipt import CodingWindowsWorkerProductReceiptOwner

_CodingWorkerReceiptOwner = (
    CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner
)


def _native_platform_for_receipt_owner(
    owner: _CodingWorkerReceiptOwner,
) -> Literal["linux-x86_64", "windows-amd64"]:
    if type(owner) is CodingWorkerProductReceiptOwner:
        return "linux-x86_64"
    if type(owner) is CodingWindowsWorkerProductReceiptOwner:
        return "windows-amd64"
    raise TypeError("Coding Worker Provider receipt owner is invalid")


class CodingWorkerProviderCandidateError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerBaseCompositionPolicyBinding(
    _ProductWorkerBaseCompositionPolicyMethods[CodingWorkerSelectedPayloadV1]
):
    """Product-owned bridge from a current base policy to one Worker receipt.

    The Worker activation policy remains distinct. Its receipt fingerprint is
    part of the Provider candidate, so changes to that policy stale admission.
    """

    base: CodingBaseProductCompilation = field(repr=False)
    receipt_owner: _CodingWorkerReceiptOwner = field(repr=False)
    receipt: ProductWorkerActivationReceiptV1 = field(repr=False)

    _base_policy_failure = staticmethod(
        lambda code: CodingWorkerProviderCandidateError(
            "coding_worker_provider_" + code
        )
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.base, CodingBaseProductCompilation)
            or type(self.receipt_owner)
            not in (
                CodingWorkerProductReceiptOwner,
                CodingWindowsWorkerProductReceiptOwner,
            )
            or not isinstance(self.receipt, ProductWorkerActivationReceiptV1)
            or self.base.plan.context.product_id != "coding"
            or self.base.plan.context.scope_id
            != f"session:{self.receipt.policy.session_id}"
            or self.base.selected_manifest.manifest.name != "coding.base"
            or self.receipt.policy.session_id
            != self.receipt_owner.product_runtime.session_id
            or self.receipt.policy.product_runtime_id
            != self.receipt_owner.product_runtime.product_runtime_id
        ):
            raise ValueError("Coding Worker base Product policy owners changed")
        self.assert_current()

    @property
    def policy_revision(self) -> str:
        return self.base.plan.context.policy_revision


def coding_worker_query_capability_provider(plugin_id: str) -> CapabilityBundleProvider:
    """Describe the one Coding-owned query Provider selected by a Product receipt."""

    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError("Coding Worker query Provider Plugin ID is invalid")
    return CapabilityBundleProvider.for_definition(
        CODING_WORKER_QUERY_DEFINITION,
        provider_id=CODING_WORKER_QUERY_PROVIDER_ID,
        implementation_version=1,
        source_id=f"plugin:{plugin_id}",
        selection_rule="product-selected-canary",
    )


def prepare_coding_selected_worker_provider_candidate(
    *,
    receipt_owner: _CodingWorkerReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    definition: CapabilityDefinition,
    provider: CapabilityBundleProvider,
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding | None = None,
) -> CapabilityProviderCandidateEnvelope:
    """Capture exact Product-selected bytes and form an owner-reviewable record."""
    if (
        type(receipt_owner)
        not in (CodingWorkerProductReceiptOwner, CodingWindowsWorkerProductReceiptOwner)
        or not isinstance(receipt, ProductWorkerActivationReceiptV1)
        or (not isinstance(definition, CapabilityDefinition))
        or (not isinstance(provider, CapabilityBundleProvider))
        or (
            base_policy_binding is not None
            and (
                not isinstance(
                    base_policy_binding, CodingWorkerBaseCompositionPolicyBinding
                )
                or base_policy_binding.receipt_owner is not receipt_owner
                or base_policy_binding.receipt != receipt
            )
        )
    ):
        raise TypeError("Coding Worker Provider candidate inputs are invalid")
    return receipt_owner.prepare_provider_candidate(
        receipt=receipt,
        definition=definition,
        provider=provider,
        base_policy_binding=base_policy_binding,
        error_type=CodingWorkerProviderCandidateError,
        error_prefix="coding_worker_provider",
    )


__all__ = [
    "CodingWorkerBaseCompositionPolicyBinding",
    "CodingWorkerProviderCandidateError",
    "coding_worker_query_capability_provider",
    "prepare_coding_selected_worker_provider_candidate",
]

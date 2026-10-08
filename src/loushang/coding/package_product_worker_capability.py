"""Bind a Capability owner's policy reader to one selected Product Worker.

This private seam grants no Capability publication or Worker activation. The
Capability owner supplies its own exact binding and current policy reader;
Coding rechecks the selected Product launch material before each domain read.
"""

from __future__ import annotations

from collections.abc import Callable

from loushang.harness.worker.capability_query import (
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    CapabilityWorkerFacetGrantV1,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.facet_owner import (
    CapabilityWorkerFacetOwnerError,
    CapabilityWorkerFacetOwnerPolicy,
)
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .package_product_worker_receipt import CodingWorkerProductReceiptOwner
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)


class CodingWorkerCapabilityBindingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodingProductWorkerCapabilityAuthority:
    """Current Product selection joined to a separate Capability owner policy."""

    def __init__(
        self,
        *,
        receipt_owner: (
            CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner
        ),
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
            or not isinstance(request, ManagedWorkerLaunchRequestV1)
            or not isinstance(binding, CapabilityWorkerBindingV1)
            or not isinstance(owner_policy, CapabilityWorkerFacetOwnerPolicy)
        ):
            raise TypeError("Coding Worker Capability authority inputs are invalid")
        identity = request.identity
        authority = binding.authority
        if (
            identity.plugin_id != receipt.policy.plugin_id
            or identity.plugin_revision_digest != receipt.policy.plugin_revision_digest
            or identity.contribution_id != receipt.policy.contribution_id
            or identity.product_id != receipt.policy.product_id
            or identity.scope_id != receipt.policy.product_scope_id
            or identity.owner_generation != receipt.policy.owner_selection_generation
            or identity.declaration_fingerprint
            != receipt.policy.declaration_fingerprint
            or identity.plugin_id != binding.plugin_id
            or identity.contribution_id != binding.contribution_id
            or identity.product_id != binding.product_id
            or identity.scope_id != binding.scope_id
            or identity.owner_id != binding.owner_id
            or identity.plugin_revision_digest != authority.plugin_revision_digest
            or identity.declaration_fingerprint != authority.declaration_fingerprint
            or identity.owner_generation != authority.owner_generation
            or receipt.policy.product_policy_revision
            != authority.product_policy_revision
            or owner_policy.binding != binding
        ):
            raise CodingWorkerCapabilityBindingError(
                "coding_worker_capability_identity_mismatch"
            )
        self._receipt_owner = receipt_owner
        self._receipt = receipt
        self._request = request
        self._binding = binding
        self._owner_policy = owner_policy
        self.current_authority()

    @property
    def binding(self) -> CapabilityWorkerBindingV1:
        return self._binding

    def issue_read_only_facet(
        self,
        *,
        capability_id: str,
        facet_id: str,
    ) -> tuple[CapabilityWorkerFacetGrantV1, Callable[[object], object]]:
        """Issue one owner-approved facet grant and its fixed result decoder."""

        current = self.current_authority()
        if current != self._binding.authority:
            raise CodingWorkerCapabilityBindingError(
                "coding_worker_capability_owner_authority_stale"
            )
        try:
            return self._owner_policy.issue_read_only_facet(
                capability_id=capability_id, facet_id=facet_id
            )
        except CapabilityWorkerFacetOwnerError as exc:
            raise CodingWorkerCapabilityBindingError(
                "coding_worker_capability_facet_not_approved"
            ) from exc

    def current_authority(self) -> CapabilityWorkerAuthorityV1:
        """Refuse changed Product selection before exposing owner authority."""

        self._request.validate_current()
        if self._receipt_owner.current_witness(self._receipt) != (
            self._receipt.authority_witness
        ):
            raise CodingWorkerCapabilityBindingError("coding_worker_receipt_stale")
        if self._receipt_owner.current_worker_owner_id(self._receipt) != (
            self._binding.owner_id
        ):
            raise CodingWorkerCapabilityBindingError(
                "coding_worker_capability_owner_changed"
            )
        try:
            authority = self._owner_policy.current_authority()
        except CapabilityWorkerFacetOwnerError as exc:
            raise CodingWorkerCapabilityBindingError(
                "coding_worker_capability_owner_authority_unavailable"
            ) from exc
        if not isinstance(authority, CapabilityWorkerAuthorityV1):
            raise CodingWorkerCapabilityBindingError(
                "coding_worker_capability_owner_authority_invalid"
            )
        return authority


__all__ = [
    "CodingProductWorkerCapabilityAuthority",
    "CodingWorkerCapabilityBindingError",
]

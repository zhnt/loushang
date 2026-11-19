"""Coding query policy and existing preparation component bindings.

Harness Receipt owners borrow the original payload, journal and evidence
constructors. No per-attempt source or activation object is created here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import ClassVar, cast

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_selection import ResolvedCapabilityProvider
from loushang.harness.session._worker_provider import _QueryAuthority
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerBindingV1,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .package_product_worker_activation_state import (
    open_coding_product_worker_activation_state_store,
    open_coding_windows_product_worker_activation_state_store,
)
from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_payload import (
    bind_coding_product_worker_launch_request,
    materialize_coding_product_worker_payload,
    open_coding_product_worker_supervisor_journal,
)
from .package_product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
    prepare_coding_selected_worker_provider_candidate,
)
from .package_product_worker_provider_host import (
    _read_coding_worker_provider_inputs,
)
from .package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_FACET_ID,
    bind_coding_worker_query_facet_owner,
)
from .package_product_worker_receipt import CodingWorkerProductReceiptOwner
from .package_product_worker_start_gate import CodingProductWorkerStartGate
from .package_product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_windows_launch_intent import (
    commit_coding_windows_product_worker_launch_intent,
)
from .package_product_worker_windows_payload import (
    bind_coding_windows_product_worker_launch_request,
    materialize_coding_windows_product_worker_payload,
)
from .package_product_worker_windows_provisioning import (
    open_coding_windows_product_worker_provisioning_state_store,
)
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)
from .package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)


@dataclass(frozen=True, slots=True)
class _CodingWorkerProviderPolicy:
    receipt_owner: (
        CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner
    )
    receipt: ProductWorkerActivationReceiptV1
    binding: CapabilityWorkerBindingV1
    provider_owner: CapabilityProviderOwnerAuthority
    clock: Callable[[], int]
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding
    capability_id: ClassVar[str] = CODING_WORKER_QUERY_CAPABILITY_ID
    facet_id: ClassVar[str] = CODING_WORKER_QUERY_FACET_ID

    def bind_authority(
        self, request: ManagedWorkerLaunchRequestV1
    ) -> CodingProductWorkerCapabilityAuthority:
        facet_owner = bind_coding_worker_query_facet_owner(
            binding=self.binding,
            provider_owner=self.provider_owner,
            current_owner_snapshot=self.provider_owner.snapshot,
        )
        return CodingProductWorkerCapabilityAuthority(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            request=request,
            binding=self.binding,
            owner_policy=facet_owner,
        )

    def capture(
        self,
        *,
        resolved: ResolvedCapabilityProvider,
        capability_authority: _QueryAuthority,
        adapter: CapabilityQueryWorkerAdapter,
        worker_admission: CapabilityWorkerAdmissionV1,
        graph_generation: int,
        release_attempt: Callable[[], Awaitable[None]],
        on_graph_publication: Callable[[], None],
    ) -> tuple[CapabilityProviderCandidateEnvelope, CapabilityWorkerBindingV1]:
        return _read_coding_worker_provider_inputs(
            resolved=resolved,
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            capability_authority=cast(
                CodingProductWorkerCapabilityAuthority, capability_authority
            ),
            adapter=adapter,
            worker_admission=worker_admission,
            graph_generation=graph_generation,
            clock=self.clock,
            release_attempt=release_attempt,
            base_policy_binding=self.base_policy_binding,
            renewing_provider_owner=self.provider_owner,
            on_graph_publication=on_graph_publication,
        )

    def read_candidate(
        self, resolved: ResolvedCapabilityProvider
    ) -> CapabilityProviderCandidateEnvelope:
        return prepare_coding_selected_worker_provider_candidate(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            definition=resolved.definition,
            provider=resolved.provider,
            base_policy_binding=self.base_policy_binding,
        )


# Native preparation borrows the actual Receipt owner and existing components.
# These are complete operation/constructor bindings, not another source object.
CodingWorkerProductReceiptOwner._worker_materialize_factory = staticmethod(
    materialize_coding_product_worker_payload
)
CodingWorkerProductReceiptOwner._worker_bind_factory = staticmethod(
    bind_coding_product_worker_launch_request
)
CodingWorkerProductReceiptOwner._worker_state_store_factory = staticmethod(
    open_coding_product_worker_activation_state_store
)
CodingWorkerProductReceiptOwner._worker_supervisor_factory = staticmethod(
    open_coding_product_worker_supervisor_journal
)
CodingWorkerProductReceiptOwner._worker_evidence_type = (
    CodingPosixWorkerCleanupEvidenceAuthority
)
CodingWorkerProductReceiptOwner._worker_start_gate_type = CodingProductWorkerStartGate
CodingWindowsWorkerProductReceiptOwner._worker_materialize_factory = staticmethod(
    materialize_coding_windows_product_worker_payload
)
CodingWindowsWorkerProductReceiptOwner._worker_bind_factory = staticmethod(
    bind_coding_windows_product_worker_launch_request
)
CodingWindowsWorkerProductReceiptOwner._worker_state_store_factory = staticmethod(
    open_coding_windows_product_worker_activation_state_store
)
CodingWindowsWorkerProductReceiptOwner._worker_supervisor_factory = staticmethod(
    open_coding_windows_product_worker_supervisor_journal
)
CodingWindowsWorkerProductReceiptOwner._worker_evidence_type = (
    CodingWindowsWorkerCleanupEvidenceAuthority
)
CodingWindowsWorkerProductReceiptOwner._worker_commit_intent_factory = staticmethod(
    commit_coding_windows_product_worker_launch_intent
)
CodingWindowsWorkerProductReceiptOwner._worker_provisioning_factory = staticmethod(
    open_coding_windows_product_worker_provisioning_state_store
)

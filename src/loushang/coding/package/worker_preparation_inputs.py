"""Coding query policy and existing preparation component bindings.

Harness Receipt owners borrow the original payload, journal and evidence
constructors. No per-attempt source or activation object is created here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from loushang.coding.package.product_worker_activation_state import (
    open_coding_product_worker_activation_state_store,
    open_coding_windows_product_worker_activation_state_store,
)
from loushang.coding.package.product_worker_capability import (
    CodingProductWorkerCapabilityAuthority,
)
from loushang.coding.package.product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from loushang.coding.package.product_worker_payload import (
    bind_coding_product_worker_launch_request,
    materialize_coding_product_worker_payload,
    open_coding_product_worker_supervisor_journal,
)
from loushang.coding.package.product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
    prepare_coding_selected_worker_provider_candidate,
)
from loushang.coding.package.product_worker_provider_host import (
    CodingPreparedWorkerProvider,
    _read_coding_worker_provider_inputs,
)
from loushang.coding.package.product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_FACET_ID,
    CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
    bind_coding_worker_query_facet_owner,
    coding_worker_query_owner_authority,
)
from loushang.coding.package.product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
)
from loushang.coding.package.product_worker_resume import (
    CodingWorkerResumeSettlementBinding,
    _parent_failure,
    _resume_parent_matches_settlement,
)
from loushang.coding.package.product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs,
)
from loushang.coding.package.product_worker_start_gate import (
    CodingProductWorkerStartGate,
)
from loushang.coding.package.product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
)
from loushang.coding.package.product_worker_windows_launch_intent import (
    commit_coding_windows_product_worker_launch_intent,
)
from loushang.coding.package.product_worker_windows_payload import (
    bind_coding_windows_product_worker_launch_request,
    materialize_coding_windows_product_worker_payload,
)
from loushang.coding.package.product_worker_windows_provisioning import (
    open_coding_windows_product_worker_provisioning_state_store,
)
from loushang.coding.package.product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)
from loushang.coding.package.product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProvider,
    ResolvedCapabilityProviderSet,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.session._worker_provider import (
    PendingWorkerSessionPolicy,
    _prepare_pending_worker_session_inputs,
    _QueryAuthority,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.worker._ordinary_prepare import (
    _NativeWorkerAttempt,
    _PendingLaunch,
)
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerBindingV1,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

if TYPE_CHECKING:
    from loushang.coding.package.product_worker_pending_host import (
        CodingProductWorkerPendingHost,
    )
    from loushang.coding.package.product_worker_windows_pending_host import (
        CodingWindowsProductWorkerPendingHost,
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


class _SelectedPendingLaunch(_PendingLaunch, Protocol):
    @property
    def receipt_fingerprint(self) -> str: ...


async def prepare_pending_provider(
    host: CodingProductWorkerPendingHost | CodingWindowsProductWorkerPendingHost,
    graph_generation: int,
    *,
    policy: PendingWorkerSessionPolicy,
    native_prepare: Callable[..., Coroutine[None, None, _NativeWorkerAttempt]],
    require_recovered: Callable[[], None] | None = None,
) -> CodingPreparedWorkerProvider:
    """Check the original preconditions and pass one native operation to the graph."""
    if type(graph_generation) is not int or graph_generation < 1:
        raise TypeError(policy.invalid_generation)
    if require_recovered is not None or host.base_policy_binding is not None:
        host.base_policy_binding.assert_current()
    if require_recovered is not None:
        require_recovered()
    return await CodingPreparedWorkerProvider._prepare_native(
        prepare_native=partial(
            native_prepare,
            launch_source=host.receipt_owner,
            activation=host.receipt_owner,
            pending_launch=host.pending_launch,
            receipt=host.receipt,
            resume_parent_context=host.resume_parent_context,
            resume_settlement=host.resume_settlement,
            failure=policy.failure,
            parent_failure=_parent_failure,
            failure_code_prefix=policy.error_prefix,
            task_name_prefix=policy.task_name_prefix,
            cleanup_note=policy.cleanup_note,
            correlation_id=policy.correlation_id,
        ),
        policy=_CodingWorkerProviderPolicy(
            host.receipt_owner,
            host.receipt,
            host.binding,
            host.provider_owner,
            host.clock,
            host.base_policy_binding,
        ),
        receipt=host.receipt,
        resolved_providers=host.resolved_providers,
        expected_admission=host.expected_admission,
        graph_generation=graph_generation,
        clock=host.clock,
        base_policy_binding=host.base_policy_binding,
        renewing_provider_owner=host.provider_owner,
        pending_failure=policy.failure,
        cleanup_note=policy.cleanup_note,
    )


def prepare_pending_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: object,
    receipt: ProductWorkerActivationReceiptV1,
    pending_launch: _SelectedPendingLaunch,
    evaluated_at: int,
    clock: Callable[[], int],
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding,
    resume_parent_context: ResumeEffectParentContextV1 | None,
    resume_settlement: CodingWorkerResumeSettlementBinding | None,
    host_type: Callable[
        ..., CodingProductWorkerPendingHost | CodingWindowsProductWorkerPendingHost
    ],
    policy: PendingWorkerSessionPolicy,
    require_bound_receipt_owner: bool = False,
) -> SessionCapabilityCompositionInputs:
    """Join the selected Worker, provider, and Resume facts before native preparation."""

    if (
        not _resume_parent_matches_settlement(
            receipt, resume_parent_context, resume_settlement
        )
        or pending_launch.receipt_fingerprint != receipt.fingerprint
        or not isinstance(base_policy_binding, CodingWorkerBaseCompositionPolicyBinding)
        or (
            require_bound_receipt_owner
            and base_policy_binding.receipt_owner is not receipt_owner
        )
        or len(resolved_providers.entries) != 1
        or resolved_providers.entries[0].capability_id
        != CODING_WORKER_QUERY_CAPABILITY_ID
        or resolved_providers.entries[0].definition != CODING_WORKER_QUERY_DEFINITION
        or provider_owner.policy != coding_worker_query_owner_authority().policy
    ):
        raise policy.failure("selection_invalid")
    return _prepare_pending_worker_session_inputs(
        resolved_providers=resolved_providers,
        provider_owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        pending_launch=pending_launch,
        evaluated_at=evaluated_at,
        clock=clock,
        base_policy_binding=base_policy_binding,
        resume_parent_context=resume_parent_context,
        resume_settlement=resume_settlement,
        capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
        owner_policy_revision=CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
        host_type=host_type,
        prepare_session_inputs=prepare_coding_product_worker_session_inputs,
    )

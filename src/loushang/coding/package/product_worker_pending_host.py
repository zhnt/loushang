"""Start a Product-selected Linux Worker only during async graph preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loushang.coding.harness.worker.pending_session import (
    PendingWorkerSessionPolicy,
    prepare_pending_provider,
    prepare_pending_session_inputs,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProviderSet,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.worker._ordinary_prepare import (
    _prepare_posix_native_worker,
)
from loushang.harness.worker.capability_query import (
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerBindingV1,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .product_worker_payload import CodingProductWorkerPendingLaunchV1
from .product_worker_provider import CodingWorkerBaseCompositionPolicyBinding
from .product_worker_provider_host import CodingPreparedWorkerProvider
from .product_worker_receipt import CodingWorkerProductReceiptOwner
from .product_worker_resume import (
    CodingWorkerResumeSettlementBinding,
)


class CodingWorkerPendingHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_PENDING_POLICY = PendingWorkerSessionPolicy(
    invalid_generation="Coding Worker graph generation is invalid",
    error_type=CodingWorkerPendingHostError,
    error_prefix="coding_worker",
    task_name_prefix="coding-worker-release-",
    correlation_id="coding-product-worker-ordinary-session",
    cleanup_note="Coding Worker pending graph cleanup also failed: ",
)


@dataclass(frozen=True, slots=True)
class CodingProductWorkerPendingHost:
    resolved_providers: ResolvedCapabilityProviderSet
    provider_owner: CapabilityProviderOwnerAuthority
    receipt_owner: CodingWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1
    pending_launch: CodingProductWorkerPendingLaunchV1
    expected_admission: CapabilityWorkerAdmissionV1
    binding: CapabilityWorkerBindingV1
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding
    clock: Callable[[], int]
    resume_parent_context: ResumeEffectParentContextV1 | None = None
    resume_settlement: CodingWorkerResumeSettlementBinding | None = None

    async def prepare(self, graph_generation: int) -> CodingPreparedWorkerProvider:
        """Own all effects from payload creation through graph disposal."""

        return await prepare_pending_provider(
            self,
            graph_generation,
            policy=_PENDING_POLICY,
            native_prepare=_prepare_posix_native_worker,
        )


def prepare_coding_product_worker_pending_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: CodingWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    pending_launch: CodingProductWorkerPendingLaunchV1,
    evaluated_at: int,
    clock: Callable[[], int],
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding,
    resume_parent_context: ResumeEffectParentContextV1 | None = None,
    resume_settlement: CodingWorkerResumeSettlementBinding | None = None,
) -> SessionCapabilityCompositionInputs:
    """Compile a Worker request whose native effects start during graph prepare."""

    if not isinstance(pending_launch, CodingProductWorkerPendingLaunchV1):
        raise _PENDING_POLICY.failure("selection_invalid")
    return prepare_pending_session_inputs(
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
        host_type=CodingProductWorkerPendingHost,
        policy=_PENDING_POLICY,
    )


__all__ = [
    "CodingProductWorkerPendingHost",
    "CodingWorkerPendingHostError",
    "prepare_coding_product_worker_pending_session_inputs",
]

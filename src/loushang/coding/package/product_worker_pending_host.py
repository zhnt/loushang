"""Start a Product-selected Linux Worker only during async graph preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loushang.coding.package.worker_preparation_inputs import (
    bind_pending_session_inputs,
    prepare_pending_provider,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProviderSet,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.session._worker_provider import (
    PendingWorkerSessionPolicy,
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


_PENDING_INPUTS = bind_pending_session_inputs(
    receipt_owner_type=CodingWorkerProductReceiptOwner,
    pending_launch_type=CodingProductWorkerPendingLaunchV1,
    host_type=CodingProductWorkerPendingHost,
    policy=_PENDING_POLICY,
)
prepare_coding_product_worker_pending_session_inputs = _PENDING_INPUTS.prepare


__all__ = [
    "CodingProductWorkerPendingHost",
    "CodingWorkerPendingHostError",
    "prepare_coding_product_worker_pending_session_inputs",
]

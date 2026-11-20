"""Start a Product-selected Linux Worker only during async graph preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial as partial

from loushang.coding.harness.worker import posix_pending_session as _session_programs
from loushang.coding.package.worker_preparation_inputs import (
    _CodingWorkerProviderPolicy as _CodingWorkerProviderPolicy,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProviderSet,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.session._worker_provider import (
    _prepare_pending_worker_session_inputs as _prepare_pending_worker_session_inputs,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.worker._ordinary_prepare import (
    _prepare_posix_native_worker as _prepare_posix_native_worker,
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
from .product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID as CODING_WORKER_QUERY_CAPABILITY_ID,
)
from .product_worker_query_consumer import (
    CODING_WORKER_QUERY_DEFINITION as CODING_WORKER_QUERY_DEFINITION,
)
from .product_worker_query_consumer import (
    CODING_WORKER_QUERY_OWNER_POLICY_REVISION as CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
)
from .product_worker_query_consumer import (
    coding_worker_query_owner_authority as coding_worker_query_owner_authority,
)
from .product_worker_receipt import CodingWorkerProductReceiptOwner
from .product_worker_resume import (
    CodingWorkerResumeSettlementBinding,
)
from .product_worker_resume import (
    _parent_failure as _parent_failure,
)
from .product_worker_resume import (
    _resume_parent_matches_settlement as _resume_parent_matches_settlement,
)
from .product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs as prepare_coding_product_worker_session_inputs,
)

_WORKER_SESSION_PROGRAM_VALUES = {
    "value_001": "Coding Worker graph generation is invalid",
    "value_002": "Coding Worker pending graph cleanup also failed: ",
    "value_003": "coding_worker",
    "value_004": "coding-worker-release-",
    "value_005": "coding-product-worker-ordinary-session",
    "value_006": "coding_worker_pending_",
    "value_007": "coding_worker_pending_selection_invalid",
}


class CodingWorkerPendingHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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

        return await _session_programs.prepare_native_provider(self, graph_generation)


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

    return _session_programs.prepare_pending_session_inputs(
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
    )


__all__ = [
    "CodingProductWorkerPendingHost",
    "CodingWorkerPendingHostError",
    "prepare_coding_product_worker_pending_session_inputs",
]

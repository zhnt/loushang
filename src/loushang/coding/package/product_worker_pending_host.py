"""Start a Product-selected Linux Worker only during async graph preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from loushang.coding.package.worker_preparation_inputs import (
    _CodingWorkerProviderPolicy,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProviderSet,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.session._worker_provider import (
    _prepare_pending_worker_session_inputs,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.worker._ordinary_prepare import _prepare_posix_native_worker
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
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
    coding_worker_query_owner_authority,
)
from .product_worker_receipt import CodingWorkerProductReceiptOwner
from .product_worker_resume import (
    CodingWorkerResumeSettlementBinding,
    _parent_failure,
    _resume_parent_matches_settlement,
)
from .product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs,
)


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
        if type(graph_generation) is not int or graph_generation < 1:
            raise TypeError("Coding Worker graph generation is invalid")
        if self.base_policy_binding is not None:
            self.base_policy_binding.assert_current()
        return await CodingPreparedWorkerProvider._prepare_native(
            prepare_native=partial(
                _prepare_posix_native_worker,
                launch_source=self.receipt_owner,
                activation=self.receipt_owner,
                pending_launch=self.pending_launch,
                receipt=self.receipt,
                resume_parent_context=self.resume_parent_context,
                resume_settlement=self.resume_settlement,
                failure=lambda suffix: CodingWorkerPendingHostError(
                    "coding_worker_pending_" + suffix
                ),
                parent_failure=_parent_failure,
                failure_code_prefix="coding_worker",
                task_name_prefix="coding-worker-release-",
                cleanup_note="Coding Worker pending graph cleanup also failed: ",
                correlation_id="coding-product-worker-ordinary-session",
            ),
            policy=_CodingWorkerProviderPolicy(
                self.receipt_owner,
                self.receipt,
                self.binding,
                self.provider_owner,
                self.clock,
                self.base_policy_binding,
            ),
            receipt=self.receipt,
            resolved_providers=self.resolved_providers,
            expected_admission=self.expected_admission,
            graph_generation=graph_generation,
            clock=self.clock,
            base_policy_binding=self.base_policy_binding,
            renewing_provider_owner=self.provider_owner,
            pending_failure=lambda suffix: CodingWorkerPendingHostError(
                "coding_worker_pending_" + suffix
            ),
            cleanup_note="Coding Worker pending graph cleanup also failed: ",
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

    if (
        not isinstance(pending_launch, CodingProductWorkerPendingLaunchV1)
        or not _resume_parent_matches_settlement(
            receipt, resume_parent_context, resume_settlement
        )
        or pending_launch.receipt_fingerprint != receipt.fingerprint
        or not isinstance(base_policy_binding, CodingWorkerBaseCompositionPolicyBinding)
        or len(resolved_providers.entries) != 1
        or resolved_providers.entries[0].capability_id
        != CODING_WORKER_QUERY_CAPABILITY_ID
        or resolved_providers.entries[0].definition != CODING_WORKER_QUERY_DEFINITION
        or provider_owner.policy != coding_worker_query_owner_authority().policy
    ):
        raise CodingWorkerPendingHostError("coding_worker_pending_selection_invalid")
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
        host_type=CodingProductWorkerPendingHost,
        prepare_session_inputs=prepare_coding_product_worker_session_inputs,
    )


__all__ = [
    "CodingProductWorkerPendingHost",
    "CodingWorkerPendingHostError",
    "prepare_coding_product_worker_pending_session_inputs",
]

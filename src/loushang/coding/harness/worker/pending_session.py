"""Shared pending Worker Session preparation using the existing provider owners."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Protocol

from loushang.coding.package.product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
)
from loushang.coding.package.product_worker_provider_host import (
    CodingPreparedWorkerProvider,
)
from loushang.coding.package.product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
    coding_worker_query_owner_authority,
)
from loushang.coding.package.product_worker_resume import (
    CodingWorkerResumeSettlementBinding,
    _parent_failure,
    _resume_parent_matches_settlement,
)
from loushang.coding.package.product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs,
)
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
from loushang.harness.worker._ordinary_prepare import (
    _NativeWorkerAttempt,
    _PendingLaunch,
)
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

if TYPE_CHECKING:
    from loushang.coding.package.product_worker_pending_host import (
        CodingProductWorkerPendingHost,
    )
    from loushang.coding.package.product_worker_windows_pending_host import (
        CodingWindowsProductWorkerPendingHost,
    )


class _SelectedPendingLaunch(_PendingLaunch, Protocol):
    @property
    def receipt_fingerprint(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PendingWorkerSessionPolicy:
    invalid_generation: str
    error_type: type[RuntimeError]
    error_prefix: str
    task_name_prefix: str
    correlation_id: str
    cleanup_note: str

    def failure(self, code: str) -> RuntimeError:
        return self.error_type(f"{self.error_prefix}_pending_{code}")


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

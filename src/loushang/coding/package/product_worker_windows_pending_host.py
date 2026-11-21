"""Start a selected Windows Worker during async Coding graph preparation."""

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
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.worker._ordinary_prepare import (
    _prepare_windows_native_worker,
)
from loushang.harness.worker.capability_query import (
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerBindingV1,
)
from loushang.harness.worker.history._windows_product_journals import (
    WindowsActivationStateJournal,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .product_worker_provider import CodingWorkerBaseCompositionPolicyBinding
from .product_worker_provider_host import CodingPreparedWorkerProvider
from .product_worker_resume import (
    CodingWorkerResumeSettlementBinding,
)
from .product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .product_worker_windows_payload import CodingWindowsProductWorkerPendingLaunchV1
from .product_worker_windows_receipt import CodingWindowsWorkerProductReceiptOwner


class CodingWindowsWorkerPendingHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_PENDING_POLICY = PendingWorkerSessionPolicy(
    invalid_generation="Windows Worker graph generation is invalid",
    error_type=CodingWindowsWorkerPendingHostError,
    error_prefix="coding_worker",
    task_name_prefix="coding-windows-worker-release-",
    correlation_id="coding-product-windows-worker-ordinary-session",
    cleanup_note="Windows Worker pending graph cleanup also failed: ",
)


def _require_windows_host_c5_recovered(
    product: WindowsLocalWheelProductSessionOwner,
) -> None:
    """Keep interrupted initialization and unfinished attempts out of a new Host."""

    WindowsActivationStateJournal.require_recovered(
        lambda: CodingWindowsWorkerActivationStateJournal(product),
        failure=lambda: CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_c5_owner_requires_recovery"
        ),
    )


@dataclass(frozen=True, slots=True)
class CodingWindowsProductWorkerPendingHost:
    resolved_providers: ResolvedCapabilityProviderSet
    provider_owner: CapabilityProviderOwnerAuthority
    receipt_owner: CodingWindowsWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1
    pending_launch: CodingWindowsProductWorkerPendingLaunchV1
    expected_admission: CapabilityWorkerAdmissionV1
    binding: CapabilityWorkerBindingV1
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding
    clock: Callable[[], int]
    resume_parent_context: ResumeEffectParentContextV1 | None = None
    resume_settlement: CodingWorkerResumeSettlementBinding | None = None

    async def prepare(self, graph_generation: int) -> CodingPreparedWorkerProvider:
        """Own the native attempt from payload creation through graph disposal."""

        return await prepare_pending_provider(
            self,
            graph_generation,
            policy=_PENDING_POLICY,
            native_prepare=_prepare_windows_native_worker,
            require_recovered=lambda: _require_windows_host_c5_recovered(
                self.receipt_owner.product_owner
            ),
        )


def prepare_coding_windows_product_worker_pending_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    pending_launch: CodingWindowsProductWorkerPendingLaunchV1,
    evaluated_at: int,
    clock: Callable[[], int],
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding,
    resume_parent_context: ResumeEffectParentContextV1 | None = None,
    resume_settlement: CodingWorkerResumeSettlementBinding | None = None,
) -> SessionCapabilityCompositionInputs:
    """Compile one Windows Worker whose effects begin during graph prepare."""

    if (
        type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or type(pending_launch) is not CodingWindowsProductWorkerPendingLaunchV1
    ):
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
        host_type=CodingWindowsProductWorkerPendingHost,
        policy=_PENDING_POLICY,
        require_bound_receipt_owner=True,
    )


__all__ = [
    "CodingWindowsProductWorkerPendingHost",
    "CodingWindowsWorkerPendingHostError",
    "prepare_coding_windows_product_worker_pending_session_inputs",
]

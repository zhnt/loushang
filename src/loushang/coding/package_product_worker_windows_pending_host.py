"""Start a selected Windows Worker during async Coding graph preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

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
from loushang.harness.session._worker_provider import _prepare_native_worker_component
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.worker._ordinary_prepare import _prepare_windows_native_worker
from loushang.harness.worker.capability_query import (
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerBindingV1,
    _admission_for_worker,
    _binding_for_worker,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from ._worker_preparation_inputs import (
    _CodingWorkerProviderPolicy,
    _WindowsActivationInputs,
    _WindowsLaunchInputs,
)
from .package_product_worker_provider import CodingWorkerBaseCompositionPolicyBinding
from .package_product_worker_provider_host import (
    CodingPreparedWorkerProvider,
    CodingWorkerProviderHostError,
    _WorkerAttemptRelease,
)
from .package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
    coding_worker_query_owner_authority,
)
from .package_product_worker_resume import (
    CodingWorkerResumeSettlementBinding,
    _parent_failure,
    _resume_parent_matches_settlement,
)
from .package_product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs,
)
from .package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .package_product_worker_windows_payload import (
    CodingWindowsProductWorkerPendingLaunchV1,
)
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)


class CodingWindowsWorkerPendingHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _require_uncoupled_windows_host_c5_absent(
    product: WindowsLocalWheelProductSessionOwner,
) -> None:
    """Refuse a retained C5 owner until this Host writes and settles C5 itself."""

    present, _state = CodingWindowsWorkerActivationStateJournal(
        product
    ).load_with_presence_read_only()
    if present:
        raise CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_c5_owner_requires_recovery"
        )


def _require_windows_host_c5_recovered(
    product: WindowsLocalWheelProductSessionOwner,
) -> None:
    """Keep interrupted initialization and unfinished attempts out of a new Host."""

    present, state = CodingWindowsWorkerActivationStateJournal(
        product
    ).load_with_presence_read_only()
    if present and state is None:
        raise CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_c5_owner_requires_recovery"
        )
    if state is not None and any(
        attempt.phase != "settled"
        for attempt in CodingWindowsWorkerActivationStateJournal(
            product
        ).retained_attempts_read_only()
    ):
        raise CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_c5_owner_requires_recovery"
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
        if type(graph_generation) is not int or graph_generation < 1:
            raise TypeError("Windows Worker graph generation is invalid")
        self.base_policy_binding.assert_current()
        _require_windows_host_c5_recovered(self.receipt_owner.product_owner)
        return await _prepare_native_worker_component(
            prepare_native=partial(
                _prepare_windows_native_worker,
                launch_source=_WindowsLaunchInputs(
                    self.receipt_owner, self.receipt, self.pending_launch
                ),
                activation=_WindowsActivationInputs(self.receipt_owner, self.receipt),
                pending_launch=self.pending_launch,
                receipt=self.receipt,
                resume_parent_context=self.resume_parent_context,
                resume_settlement=self.resume_settlement,
                failure=lambda suffix: CodingWindowsWorkerPendingHostError(
                    "coding_worker_pending_" + suffix
                ),
                parent_failure=_parent_failure,
                failure_code_prefix="coding_worker",
                task_name_prefix="coding-windows-worker-release-",
                cleanup_note="Windows Worker pending graph cleanup also failed: ",
                correlation_id="coding-product-windows-worker-ordinary-session",
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
            release_type=_WorkerAttemptRelease,
            prepared_factory=CodingPreparedWorkerProvider,
            pending_failure=lambda suffix: CodingWindowsWorkerPendingHostError(
                "coding_worker_pending_" + suffix
            ),
            provider_error_type=CodingWorkerProviderHostError,
            provider_error_prefix="coding_worker_provider",
            fingerprint_namespace=b"loushang.coding-worker-provider-binding/v1\x00",
            cleanup_note="Windows Worker pending graph cleanup also failed: ",
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
        or not _resume_parent_matches_settlement(
            receipt, resume_parent_context, resume_settlement
        )
        or pending_launch.receipt_fingerprint != receipt.fingerprint
        or not isinstance(base_policy_binding, CodingWorkerBaseCompositionPolicyBinding)
        or base_policy_binding.receipt_owner is not receipt_owner
        or len(resolved_providers.entries) != 1
        or resolved_providers.entries[0].capability_id
        != CODING_WORKER_QUERY_CAPABILITY_ID
        or resolved_providers.entries[0].definition != CODING_WORKER_QUERY_DEFINITION
        or provider_owner.policy != coding_worker_query_owner_authority().policy
    ):
        raise CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_selection_invalid"
        )
    base_policy_binding.assert_current()
    identity = pending_launch.identity
    binding = _binding_for_worker(
        identity,
        allowed_capability_ids=(CODING_WORKER_QUERY_CAPABILITY_ID,),
        product_policy_revision=lambda: receipt.policy.product_policy_revision,
        owner_policy_revision=CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
        revocation_epoch=0,
    )
    admission = _admission_for_worker(binding, identity)
    host = CodingWindowsProductWorkerPendingHost(
        resolved_providers=resolved_providers,
        provider_owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        pending_launch=pending_launch,
        expected_admission=admission,
        binding=binding,
        base_policy_binding=base_policy_binding,
        clock=clock,
        resume_parent_context=resume_parent_context,
        resume_settlement=resume_settlement,
    )
    return prepare_coding_product_worker_session_inputs(
        resolved_providers=resolved_providers,
        provider_owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        capability_authority=None,
        adapter=None,
        worker_admission=admission,
        evaluated_at=evaluated_at,
        clock=clock,
        release_attempt=None,
        base_policy_binding=base_policy_binding,
        deferred_prepare=host.prepare,
    )


__all__ = [
    "CodingWindowsProductWorkerPendingHost",
    "CodingWindowsWorkerPendingHostError",
    "prepare_coding_windows_product_worker_pending_session_inputs",
]

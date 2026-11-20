"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import product_worker_windows_pending_host as _binding


async def prepare_native_provider(
    self: _binding.CodingWindowsProductWorkerPendingHost, graph_generation: int
) -> _binding.CodingPreparedWorkerProvider:
    """Own the native attempt from payload creation through graph disposal."""
    if type(graph_generation) is not int or graph_generation < 1:
        raise TypeError(_binding._WORKER_SESSION_PROGRAM_VALUES["value_001"])
    self.base_policy_binding.assert_current()
    _binding._require_windows_host_c5_recovered(self.receipt_owner.product_owner)
    return await _binding.CodingPreparedWorkerProvider._prepare_native(
        prepare_native=_binding.partial(
            _binding._prepare_windows_native_worker,
            launch_source=self.receipt_owner,
            activation=self.receipt_owner,
            pending_launch=self.pending_launch,
            receipt=self.receipt,
            resume_parent_context=self.resume_parent_context,
            resume_settlement=self.resume_settlement,
            failure=lambda suffix: _binding.CodingWindowsWorkerPendingHostError(
                _binding._WORKER_SESSION_PROGRAM_VALUES["value_005"] + suffix
            ),
            parent_failure=_binding._parent_failure,
            failure_code_prefix=_binding._WORKER_SESSION_PROGRAM_VALUES["value_002"],
            task_name_prefix=_binding._WORKER_SESSION_PROGRAM_VALUES["value_003"],
            cleanup_note="Windows Worker pending graph cleanup also failed: ",
            correlation_id=_binding._WORKER_SESSION_PROGRAM_VALUES["value_004"],
        ),
        policy=_binding._CodingWorkerProviderPolicy(
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
        pending_failure=lambda suffix: _binding.CodingWindowsWorkerPendingHostError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_005"] + suffix
        ),
        cleanup_note="Windows Worker pending graph cleanup also failed: ",
    )


def prepare_pending_session_inputs(
    *,
    resolved_providers: _binding.ResolvedCapabilityProviderSet,
    provider_owner: _binding.CapabilityProviderOwnerAuthority,
    receipt_owner: _binding.CodingWindowsWorkerProductReceiptOwner,
    receipt: _binding.ProductWorkerActivationReceiptV1,
    pending_launch: _binding.CodingWindowsProductWorkerPendingLaunchV1,
    evaluated_at: int,
    clock: _binding.Callable[[], int],
    base_policy_binding: _binding.CodingWorkerBaseCompositionPolicyBinding,
    resume_parent_context: _binding.ResumeEffectParentContextV1 | None,
    resume_settlement: _binding.CodingWorkerResumeSettlementBinding | None,
) -> _binding.SessionCapabilityCompositionInputs:
    """Compile one Windows Worker whose effects begin during graph prepare."""

    if (
        type(receipt_owner) is not _binding.CodingWindowsWorkerProductReceiptOwner
        or type(pending_launch)
        is not _binding.CodingWindowsProductWorkerPendingLaunchV1
        or not _binding._resume_parent_matches_settlement(
            receipt, resume_parent_context, resume_settlement
        )
        or pending_launch.receipt_fingerprint != receipt.fingerprint
        or not isinstance(
            base_policy_binding, _binding.CodingWorkerBaseCompositionPolicyBinding
        )
        or base_policy_binding.receipt_owner is not receipt_owner
        or len(resolved_providers.entries) != 1
        or resolved_providers.entries[0].capability_id
        != _binding.CODING_WORKER_QUERY_CAPABILITY_ID
        or resolved_providers.entries[0].definition
        != _binding.CODING_WORKER_QUERY_DEFINITION
        or provider_owner.policy
        != _binding.coding_worker_query_owner_authority().policy
    ):
        raise _binding.CodingWindowsWorkerPendingHostError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_006"]
        )
    return _binding._prepare_pending_worker_session_inputs(
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
        capability_id=_binding.CODING_WORKER_QUERY_CAPABILITY_ID,
        owner_policy_revision=_binding.CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
        host_type=_binding.CodingWindowsProductWorkerPendingHost,
        prepare_session_inputs=_binding.prepare_coding_product_worker_session_inputs,
    )

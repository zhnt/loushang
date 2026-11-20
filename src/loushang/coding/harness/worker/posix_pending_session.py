"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import product_worker_pending_host as _binding


async def prepare_native_provider(
    self: _binding.CodingProductWorkerPendingHost, graph_generation: int
) -> _binding.CodingPreparedWorkerProvider:
    """Own all effects from payload creation through graph disposal."""
    if type(graph_generation) is not int or graph_generation < 1:
        raise TypeError(_binding._WORKER_SESSION_PROGRAM_VALUES["value_001"])
    if self.base_policy_binding is not None:
        self.base_policy_binding.assert_current()
    return await _binding.CodingPreparedWorkerProvider._prepare_native(
        prepare_native=_binding.partial(
            _binding._prepare_posix_native_worker,
            launch_source=self.receipt_owner,
            activation=self.receipt_owner,
            pending_launch=self.pending_launch,
            receipt=self.receipt,
            resume_parent_context=self.resume_parent_context,
            resume_settlement=self.resume_settlement,
            failure=lambda suffix: _binding.CodingWorkerPendingHostError(
                _binding._WORKER_SESSION_PROGRAM_VALUES["value_006"] + suffix
            ),
            parent_failure=_binding._parent_failure,
            failure_code_prefix=_binding._WORKER_SESSION_PROGRAM_VALUES["value_003"],
            task_name_prefix=_binding._WORKER_SESSION_PROGRAM_VALUES["value_004"],
            cleanup_note=_binding._WORKER_SESSION_PROGRAM_VALUES["value_002"],
            correlation_id=_binding._WORKER_SESSION_PROGRAM_VALUES["value_005"],
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
        pending_failure=lambda suffix: _binding.CodingWorkerPendingHostError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_006"] + suffix
        ),
        cleanup_note=_binding._WORKER_SESSION_PROGRAM_VALUES["value_002"],
    )


def prepare_pending_session_inputs(
    *,
    resolved_providers: _binding.ResolvedCapabilityProviderSet,
    provider_owner: _binding.CapabilityProviderOwnerAuthority,
    receipt_owner: _binding.CodingWorkerProductReceiptOwner,
    receipt: _binding.ProductWorkerActivationReceiptV1,
    pending_launch: _binding.CodingProductWorkerPendingLaunchV1,
    evaluated_at: int,
    clock: _binding.Callable[[], int],
    base_policy_binding: _binding.CodingWorkerBaseCompositionPolicyBinding,
    resume_parent_context: _binding.ResumeEffectParentContextV1 | None,
    resume_settlement: _binding.CodingWorkerResumeSettlementBinding | None,
) -> _binding.SessionCapabilityCompositionInputs:
    """Compile a Worker request whose native effects start during graph prepare."""

    if (
        not isinstance(pending_launch, _binding.CodingProductWorkerPendingLaunchV1)
        or not _binding._resume_parent_matches_settlement(
            receipt, resume_parent_context, resume_settlement
        )
        or pending_launch.receipt_fingerprint != receipt.fingerprint
        or not isinstance(
            base_policy_binding, _binding.CodingWorkerBaseCompositionPolicyBinding
        )
        or len(resolved_providers.entries) != 1
        or resolved_providers.entries[0].capability_id
        != _binding.CODING_WORKER_QUERY_CAPABILITY_ID
        or resolved_providers.entries[0].definition
        != _binding.CODING_WORKER_QUERY_DEFINITION
        or provider_owner.policy
        != _binding.coding_worker_query_owner_authority().policy
    ):
        raise _binding.CodingWorkerPendingHostError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_007"]
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
        host_type=_binding.CodingProductWorkerPendingHost,
        prepare_session_inputs=_binding.prepare_coding_product_worker_session_inputs,
    )

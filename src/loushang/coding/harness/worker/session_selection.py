"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import product_worker_ordinary_bootstrap as _binding


def prepare_worker_session(
    *,
    product_owner: _binding.PosixLocalWheelProductSessionOwner
    | _binding.WindowsLocalWheelProductSessionOwner,
    runtime: _binding.PackageProductRuntimeBindingV1,
    session_manager: _binding.SessionManager,
    plugin_id: str,
    ordinary: _binding.CodingBaseProductSessionAssembly,
    clock: _binding.Callable[[], int],
    resume_parent_context: _binding.ResumeEffectParentContextV1 | None,
) -> _binding.CodingProductWorkerOrdinarySessionBinding:
    """Join exact Product, transcript, base graph, and Worker authorities.

    This function does not launch a Worker. The returned graph request starts
    one only during async preparation and owns its subsequent cleanup.
    """

    if (
        type(product_owner)
        not in (
            _binding.PosixLocalWheelProductSessionOwner,
            _binding.WindowsLocalWheelProductSessionOwner,
        )
        or not isinstance(runtime, _binding.PackageProductRuntimeBindingV1)
        or not isinstance(session_manager, _binding.SessionManager)
        or not isinstance(ordinary, _binding.CodingBaseProductSessionAssembly)
        or not isinstance(plugin_id, str)
        or not plugin_id
        or plugin_id != plugin_id.strip()
        or not callable(clock)
        or (
            resume_parent_context is not None
            and type(resume_parent_context) is not _binding.ResumeEffectParentContextV1
        )
    ):
        raise TypeError(_binding._WORKER_SESSION_PROGRAM_VALUES["value_001"])
    if not session_manager.is_persisted():
        raise _binding.CodingWorkerOrdinaryBootstrapError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_002"]
        )
    base_context = ordinary.session_inputs.product_composition.authority_context
    if (
        runtime.session_id != session_manager.get_header().conversation_id
        or ordinary.compilation.plan.context.scope_id != f"session:{runtime.session_id}"
        or base_context.product_policy_revision
        != ordinary.compilation.plan.context.policy_revision
    ):
        raise _binding.CodingWorkerOrdinaryBootstrapError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_003"]
        )
    existing_startup = _binding.historical_startup_composition_record(
        session_manager.get_entries()
    )
    if existing_startup is None and session_manager.get_entries():
        raise _binding.CodingWorkerOrdinaryBootstrapError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_004"]
        )
    transcript_directory = _binding.AgentTranscriptDirectoryRuntime(
        session_dir=session_manager.get_session_dir()
    )
    receipt_owner: (
        _binding.CodingWorkerProductReceiptOwner
        | _binding.CodingWindowsWorkerProductReceiptOwner
    )
    if type(product_owner) is _binding.WindowsLocalWheelProductSessionOwner:
        receipt_owner = (
            _binding.open_coding_windows_product_selected_worker_receipt_owner(
                product_owner=product_owner,
                runtime=runtime,
                plugin_id=plugin_id,
                transcript_directory=transcript_directory,
                session_manager=session_manager,
                active_session=True,
            )
        )
    else:
        assert type(product_owner) is _binding.PosixLocalWheelProductSessionOwner
        receipt_owner = _binding.open_coding_product_selected_worker_receipt_owner(
            product_owner=product_owner,
            runtime=runtime,
            plugin_id=plugin_id,
            transcript_directory=transcript_directory,
            session_manager=session_manager,
            active_session=True,
        )
    receipt = receipt_owner.issue()
    if receipt is None:
        raise _binding.CodingWorkerOrdinaryBootstrapError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_005"]
        )
    resume_settlement = (
        _binding.CodingWorkerResumeSettlementBinding(
            receipt=receipt,
            context=resume_parent_context,
        )
        if resume_parent_context is not None
        else None
    )
    selected_worker = _binding.capture_worker_startup_selection(
        runtime=runtime,
        plugin_id=plugin_id,
        receipt=receipt,
        existing_startup=existing_startup,
        max_files=_binding._STARTUP_MAX_FILES,
        max_total_bytes=_binding._STARTUP_MAX_BYTES,
        failure=lambda code: _binding.CodingWorkerOrdinaryBootstrapError(
            _binding._WORKER_SESSION_PROGRAM_VALUES["value_006"] + code
        ),
    )
    base_policy = _binding.CodingWorkerBaseCompositionPolicyBinding(
        base=ordinary.compilation,
        receipt_owner=receipt_owner,
        receipt=receipt,
    )
    provider_owner = _binding.coding_worker_query_owner_authority()
    provider = _binding.coding_worker_query_capability_provider(plugin_id)
    candidate = _binding.prepare_coding_selected_worker_provider_candidate(
        receipt_owner=receipt_owner,
        receipt=receipt,
        definition=_binding.CODING_WORKER_QUERY_DEFINITION,
        provider=provider,
        base_policy_binding=base_policy,
    )
    evaluated_at = base_context.evaluated_at
    resolved = _binding._WORKER_SESSION_COMPOSITION.select_provider(
        owner=provider_owner,
        candidate=candidate,
        definition=_binding.CODING_WORKER_QUERY_DEFINITION,
        provider_id=lambda: provider.provider_id,
        policy_revision=lambda: base_policy.policy_revision,
        evaluated_at=evaluated_at,
        eligibility_duration=_binding._PROVIDER_ELIGIBILITY_DURATION,
        admission_duration=_binding._PROVIDER_ADMISSION_DURATION,
    )
    if type(product_owner) is _binding.WindowsLocalWheelProductSessionOwner:
        assert type(receipt_owner) is _binding.CodingWindowsWorkerProductReceiptOwner
        pending_windows = _binding.plan_coding_windows_product_worker_pending_launch(
            receipt_owner=receipt_owner,
            receipt=receipt,
            attempt_id=_binding.secrets.token_hex(16),
        )
        worker = _binding.prepare_coding_windows_product_worker_pending_session_inputs(
            resolved_providers=resolved,
            provider_owner=provider_owner,
            receipt_owner=receipt_owner,
            receipt=receipt,
            pending_launch=pending_windows,
            evaluated_at=evaluated_at,
            clock=clock,
            base_policy_binding=base_policy,
            resume_parent_context=resume_parent_context,
            resume_settlement=resume_settlement,
        )
    else:
        assert type(receipt_owner) is _binding.CodingWorkerProductReceiptOwner
        pending_linux = _binding.plan_coding_product_worker_pending_launch(
            receipt_owner=receipt_owner,
            receipt=receipt,
            attempt_id=_binding.secrets.token_hex(16),
        )
        worker = _binding.prepare_coding_product_worker_pending_session_inputs(
            resolved_providers=resolved,
            provider_owner=provider_owner,
            receipt_owner=receipt_owner,
            receipt=receipt,
            pending_launch=pending_linux,
            evaluated_at=evaluated_at,
            clock=clock,
            base_policy_binding=base_policy,
            resume_parent_context=resume_parent_context,
            resume_settlement=resume_settlement,
        )
    definitions = {
        item.capability_id: item
        for item in (
            _binding.MODEL_INPUT_CAPABILITY_DEFINITION,
            _binding.WORKSPACE_CAPABILITY_DEFINITION,
            _binding.CODING_WORKER_QUERY_DEFINITION,
            *(
                entry.definition
                for entry in ordinary.session_inputs.resolved_providers.entries
            ),
        )
    }
    combined = _binding.compose_coding_product_worker_with_ordinary_session(
        ordinary=ordinary.session_inputs,
        worker=worker,
        definitions=tuple(definitions.values()),
        workspace_binding=ordinary.workspace_binding,
    )
    return _binding.CodingProductWorkerOrdinarySessionBinding(
        ordinary=ordinary.session_inputs,
        combined=combined,
        workspace_binding=ordinary.workspace_binding,
        selected_worker_manifest=selected_worker,
        activation_receipt=receipt,
        resume_settlement=resume_settlement,
    )

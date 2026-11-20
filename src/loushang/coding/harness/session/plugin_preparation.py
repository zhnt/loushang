"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.composition import capability_plugins as _binding


def prepare_capability_plugins(
    request: _binding.CodingCapabilityPluginCompositionRequest,
    *,
    session_id: str,
    configurations: _binding.Mapping[str, _binding.CodingCapabilityPluginConfig],
    package_materializer: _binding.CodingPackageMaterializer,
    lifecycle: _binding.CodingPluginLifecycle | None,
    session_owner_id: str | None,
    management_state_cleanup: _binding.Callable[[], None] | None,
    state_root: str | _binding.Path,
    clock: _binding.Callable[[], int],
    coding_base_plugin_assembly: _binding.CodingBasePluginAssembly | None,
    coding_product_plan_seed: _binding.ProductPluginPlanSeed | None,
    state_cleanup: _binding.Callable[[], None] | None,
    private_state_cleanup: _binding.Callable[[], None] | None,
    legacy_disabled_plugin_ids: frozenset[str],
) -> _binding.CodingCapabilityPluginCompositionPreparation:
    """Resolve, approve and compile once without constructing host Providers."""

    _binding._validate_preparation_inputs(
        request,
        session_id=session_id,
        configurations=configurations,
        package_materializer=package_materializer,
        clock=clock,
        coding_base_plugin_assembly=coding_base_plugin_assembly,
        coding_product_plan_seed=coding_product_plan_seed,
    )
    _binding._read_clock(clock)
    if state_cleanup is not None and not callable(state_cleanup):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_002"])
    if private_state_cleanup is not None and not callable(private_state_cleanup):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_003"])
    if management_state_cleanup is not None and not callable(management_state_cleanup):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_004"])
    if not isinstance(legacy_disabled_plugin_ids, frozenset) or any(
        not isinstance(item, str) or not item for item in legacy_disabled_plugin_ids
    ):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_005"])
    if lifecycle is not None and not isinstance(
        lifecycle, _binding.CodingPluginLifecycle
    ):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_006"])
    resolved_state_root = _binding.Path(state_root).expanduser().resolve()
    scope_id = f"session:{session_id.strip()}"

    try:
        resolved_state_root.mkdir(parents=True, exist_ok=True)
        runtime, selected_configurations, management_leases = (
            _binding._resolve_managed_capability_plugins(
                configurations,
                session_id=session_id,
                package_materializer=package_materializer,
                lifecycle=lifecycle,
                session_owner_id=session_owner_id,
                legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
            )
        )
        if not selected_configurations:
            runtime.close()
            raise _binding.CodingCapabilityPluginCompositionError(
                _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_007"],
                code=_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_008"],
            )
    except BaseException as error:
        custodian = _binding.coding_capability_plugin_failure_custodian(error)
        if custodian is None:
            custodian = _binding.CodingCapabilityPluginCleanupCustodian(
                runtime=_binding.PluginRuntimeResolution((), (), ()),
                management_leases={},
            )
        custodian.adopt_cleanup_callbacks(
            management_state_cleanup=management_state_cleanup,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )
        _close_failed_preparation(error, custodian)
        raise
    try:
        resolved_product_seed = coding_product_plan_seed or (
            coding_base_plugin_assembly.plan_seed
            if coding_base_plugin_assembly is not None
            else None
        )
        tool_authority = _binding._tool_owner_authority(
            frozenset(selected_configurations)
        )
        plan_seed = _binding._prepare_selection_plan_seed(
            runtime,
            scope_id=scope_id,
            configurations=selected_configurations,
            management_leases=management_leases,
            coding_product_plan_seed=resolved_product_seed,
            tool_authority=tool_authority,
        )
        request = _binding._bind_default_approval_request_to_plan(request, plan_seed)
        selection = _binding._finalize_selection(
            plan_seed,
            request=request,
            scope_id=scope_id,
            state_root=resolved_state_root,
            clock=clock,
        )
        selection_seed = _binding.complete_coding_package_plugin_selection_seed(
            plan_seed,
            selection=selection,
        )
        provider_authorities = _binding._provider_owner_authorities(
            frozenset(selected_configurations)
        )
        product = _binding.prepare_product_plugin_composition(
            _binding._assembly_request(
                selection_seed,
                provider_authorities=provider_authorities,
            ),
            evaluated_at=_binding._read_clock(clock),
        )
        return _binding.CodingCapabilityPluginCompositionPreparation(
            request=request,
            runtime=runtime,
            selection=selection,
            product=product,
            provider_owner_authorities=provider_authorities,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=resolved_state_root,
            management_leases=management_leases,
            management_state_cleanup=management_state_cleanup,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )
    except BaseException as error:
        custodian = _binding.CodingCapabilityPluginCleanupCustodian(
            runtime=runtime,
            management_leases=dict(management_leases),
            management_state_cleanup=management_state_cleanup,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )
        _close_failed_preparation(error, custodian)
        raise


def require_resume_effect_settlement(
    attempt: _binding.CodingActivationAttemptV2,
    receipt: _binding.Mapping[str, object],
    *,
    state_root: _binding.Path,
    clock: _binding.Callable[[], int],
    allowed_external_owner_ids: frozenset[str],
) -> None:
    """Reconcile the audited first-party startup closure in original journals.

    This adapter covers only the checked-in LSP and Architecture declaration and
    factory closures. Their factories construct lazy in-memory owners: process
    launch, workspace scans and private-cache I/O begin only on later Tool use.
    The surrounding candidate gate must separately prove that the receipt still
    names the current Product-selected first-party package revisions.
    """

    if type(attempt) is not _binding.CodingActivationAttemptV2:
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_009"])
    if not isinstance(receipt, _binding.Mapping):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_010"])
    owners = {owner.owner_id: owner for owner in attempt.effect_owners}
    plugin_owner_ids = {"harness.plugin-activation", "harness.plugin-execution"}
    if (
        set(owners) != plugin_owner_ids | allowed_external_owner_ids
        or attempt.effect_classes
        or any(owner.effect_classes for owner in attempt.effect_owners)
    ):
        raise _binding.CodingResumeRecoveryRequired(
            _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_011"]
        )
    parents = _binding.CodingResumePluginParents(
        definition=attempt.parent_context(owners["harness.plugin-execution"]),
        activation=attempt.parent_context(owners["harness.plugin-activation"]),
    )
    try:
        definition, activation = parents._journals(
            session_id=attempt.session_id,
            state_root=state_root,
            clock=clock,
        )
        definition_snapshot = definition.resume_parent_snapshot(parents.definition)
        activation_snapshot = activation.resume_parent_snapshot(parents.activation)
    except (
        _binding.PluginExecutionJournalError,
        _binding.PluginActivationJournalError,
    ) as error:
        raise _binding.CodingResumeRecoveryRequired(
            _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_012"]
        ) from error
    if (
        not definition_snapshot.sealed
        or definition_snapshot.membership_digest is None
        or not activation_snapshot.sealed
        or activation_snapshot.membership_digest is None
        or activation_snapshot.unfenced_recovered_use_ids
        or not definition_snapshot.execution_uses
        or not activation_snapshot.activation_uses
        or any(use.state != "EVALUATED" for use in definition_snapshot.execution_uses)
        or any(use.state != "COMMITTED" for use in activation_snapshot.activation_uses)
    ):
        raise _binding.CodingResumeRecoveryRequired(
            _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_012"]
        )

    raw_revisions = receipt.get("selectedRevisions")
    if not isinstance(raw_revisions, list):
        raise _binding.CodingResumeRecoveryRequired(
            _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_012"]
        )
    selected: dict[str, _binding.PluginInstanceRevisionRef] = {}
    try:
        for raw in raw_revisions:
            if not isinstance(raw, _binding.Mapping) or set(raw) != {
                "pluginId",
                "packageRevisionFingerprint",
                "instanceRevisionRef",
            }:
                raise ValueError(
                    _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_013"]
                )
            plugin_id = raw["pluginId"]
            revision_fingerprint = raw["packageRevisionFingerprint"]
            if not isinstance(plugin_id, str) or not isinstance(
                revision_fingerprint, str
            ):
                raise ValueError(
                    _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_014"]
                )
            if plugin_id not in _binding.CODING_CAPABILITY_PLUGIN_IDS:
                continue
            revision = _binding.PluginInstanceRevisionRef.from_dict(
                raw["instanceRevisionRef"]
            )
            if revision.plugin_id != plugin_id or plugin_id in selected:
                raise ValueError(
                    _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_015"]
                )
            selected[plugin_id] = revision
    except (TypeError, ValueError) as error:
        raise _binding.CodingResumeRecoveryRequired(
            _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_012"]
        ) from error

    definition_refs = tuple(
        sorted(
            (use.instance_revision_ref for use in definition_snapshot.execution_uses),
            key=lambda ref: (ref.plugin_id, ref.instance_id, ref.revision),
        )
    )
    activation_refs = tuple(
        sorted(
            (use.instance_revision_ref for use in activation_snapshot.activation_uses),
            key=lambda ref: (ref.plugin_id, ref.instance_id, ref.revision),
        )
    )
    selected_refs = tuple(
        sorted(
            selected.values(),
            key=lambda ref: (ref.plugin_id, ref.instance_id, ref.revision),
        )
    )
    if (
        not selected_refs
        or definition_refs != selected_refs
        or activation_refs != selected_refs
    ):
        raise _binding.CodingResumeRecoveryRequired(
            _binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_012"]
        )


def _close_failed_preparation(
    error: BaseException,
    custodian: _binding.CodingCapabilityPluginCleanupCustodian,
) -> None:
    """Retain the original cleanup custodian when an abort fails."""
    try:
        custodian.close()
    except BaseException as cleanup_error:
        error.add_note(
            f"{_binding._PLUGIN_PREPARATION_PROGRAM_VALUES['value_001']}{cleanup_error}"
        )
        _binding._attach_failure_custodian(error, custodian)

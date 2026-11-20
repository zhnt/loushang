"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.composition import product_capability_plugins as _binding


def prepare_builtin_plugins(
    product_runtime: _binding.PackageProductRuntimeBindingV1,
    *,
    base_compilation: _binding.CodingBaseProductCompilation,
    session_id: str,
    configurations: _binding.Mapping[str, _binding.CodingCapabilityPluginConfig],
    external_data_plugin_ids: tuple[str, ...],
    state_root: _binding.Path,
    clock: _binding.Callable[[], int],
    resume_parents: _binding.CodingResumePluginParents | None,
) -> _binding.CodingBuiltinProductCompositionPreparation:
    """Compile all first-party Product selections before binding host Providers."""
    if not isinstance(base_compilation, _binding.CodingBaseProductCompilation):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_001"])
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_002"])
    if not isinstance(configurations, _binding.Mapping) or not configurations:
        raise ValueError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_003"])
    specs = _binding.ordered_coding_capability_plugin_specs(configurations)
    if any(
        (
            not isinstance(configurations[spec.plugin_id], spec.configuration_type)
            for spec in specs
        )
    ):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_004"])
    _binding._read_clock(clock)
    root = _binding._prepare_product_approval_state_root(state_root)
    with _binding.SelectedProductPreparationScope(
        product_runtime=product_runtime,
        open_runtime=lambda: _binding.open_coding_product_builtin_resolution(
            product_runtime,
            capability_plugin_ids=tuple((spec.plugin_id for spec in specs)),
            external_data_plugin_ids=external_data_plugin_ids,
        ),
        selection_id=lambda package: package.manifest.name,
        selection_items=lambda runtime: runtime.packages,
        maximum_files=lambda: _binding._MAX_FILES,
        maximum_bytes=lambda: _binding._MAX_BYTES,
        label=_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_006"],
    ) as (runtime, selected):
        by_id = {item.manifest.name: item for item in selected}
        base = by_id[_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_005"]]
        if (
            base != base_compilation.selected_manifest
            or base_compilation.plan.selected_plugin_ids
            != (_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_005"],)
            or base_compilation.plan.context.scope_id != f"session:{session_id.strip()}"
        ):
            raise ValueError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_007"])
        trust_revisions = {
            _binding._required_trust(item).source_trust_policy_revision
            for item in selected
        }
        if len(trust_revisions) != 1:
            raise ValueError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_008"])
        plugin_ids = frozenset(configurations)
        scope_id = base_compilation.plan.context.scope_id
        policy_revision = base_compilation.plan.context.policy_revision
        tool_authority = _binding._tool_owner_authority(plugin_ids)
        seed = _binding._builtin_plan_seed(
            runtime,
            selected,
            base_compilation=base_compilation,
            configurations=configurations,
            tool_authority=tool_authority,
        )
        request = _binding._bind_default_approval_request_to_plan(
            _binding.create_coding_capability_plugin_composition_request(
                clock=clock,
                plugin_ids=plugin_ids,
                product_policy_revision=policy_revision,
                source_trust_policy_revision=next(iter(trust_revisions)),
            ),
            seed,
        )
        selection = _binding._finalize_selection(
            seed,
            request=request,
            scope_id=scope_id,
            state_root=root,
            clock=clock,
            resume_parents=resume_parents,
        )
        provider_authorities = _binding._provider_owner_authorities(plugin_ids)
        selected_seed = _binding.complete_coding_package_plugin_selection_seed(
            seed, selection=selection
        )
        product = _binding.prepare_product_plugin_composition(
            _binding._assembly_request(
                selected_seed,
                provider_authorities=provider_authorities,
                owner_candidates=_binding._selected_store_owner_candidates(
                    selection,
                    base=base,
                    selected=tuple((by_id[item] for item in external_data_plugin_ids)),
                ),
            ),
            evaluated_at=_binding._read_clock(clock),
        )
        recheck_selected_revisions = _binding.selected_runtime_recheck(runtime)
        capability_preparation = _binding.CodingCapabilityPluginCompositionPreparation(
            request=request,
            runtime=runtime,
            selection=selection,
            product=product,
            provider_owner_authorities=provider_authorities,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=root,
            selection_recheck=recheck_selected_revisions,
            resume_parents=resume_parents,
        )
        combined_base = _binding.replace(
            base_compilation,
            plan=selection.plan,
            product_composition=product.product_composition,
            owner_bindings=selected_seed.owner_bindings,
            resource_bodies=_binding._resource_bodies(
                base,
                product.product_composition,
                external_selected=tuple(
                    (by_id[plugin_id] for plugin_id in external_data_plugin_ids)
                ),
            ),
            selected_capability_manifests=tuple(
                (by_id[plugin_id] for plugin_id in sorted(plugin_ids))
            ),
            selected_external_data_manifests=tuple(
                (by_id[plugin_id] for plugin_id in external_data_plugin_ids)
            ),
        )
        return _binding.CodingBuiltinProductCompositionPreparation(
            base_compilation=combined_base,
            capability_preparation=capability_preparation,
        )


def prepare_selected_plugins(
    product_runtime: _binding.PackageProductRuntimeBindingV1,
    *,
    session_id: str,
    configurations: _binding.Mapping[str, _binding.CodingCapabilityPluginConfig],
    state_root: _binding.Path,
    clock: _binding.Callable[[], int],
    product_policy_revision: str,
    resume_parents: _binding.CodingResumePluginParents | None,
) -> _binding.CodingCapabilityPluginCompositionPreparation:
    """Approve exact B-selected Definitions and compile inert Provider inputs.

    The Product runtime owns Store selection and its lease. This preparation
    owns only verified revision handles and Approval journals; activation still
    requires the normal host-Provider binding and Session graph publication.
    """
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_009"])
    if not isinstance(configurations, _binding.Mapping) or not configurations:
        raise ValueError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_003"])
    specs = _binding.ordered_coding_capability_plugin_specs(configurations)
    if any(
        (
            not isinstance(configurations[spec.plugin_id], spec.configuration_type)
            for spec in specs
        )
    ):
        raise TypeError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_004"])
    if not isinstance(product_policy_revision, str) or not product_policy_revision:
        raise ValueError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_010"])
    _binding._read_clock(clock)
    root = _binding._prepare_product_approval_state_root(state_root)
    with _binding.SelectedProductPreparationScope(
        product_runtime=product_runtime,
        open_runtime=lambda: _binding.open_coding_product_capability_resolution(
            product_runtime, plugin_ids=tuple((spec.plugin_id for spec in specs))
        ),
        selection_id=lambda spec: spec.plugin_id,
        selection_items=lambda runtime: specs,
        maximum_files=lambda: _binding._MAX_FILES,
        maximum_bytes=lambda: _binding._MAX_BYTES,
        label=_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_006"],
    ) as (runtime, selected):
        trust_revisions = {
            item.source_trust_snapshot.source_trust_policy_revision
            for item in selected
            if item.source_trust_snapshot is not None
        }
        if len(trust_revisions) != 1:
            raise ValueError(_binding._PLUGIN_PREPARATION_PROGRAM_VALUES["value_011"])
        plugin_ids = frozenset(configurations)
        scope_id = f"session:{session_id.strip()}"
        tool_authority = _binding._tool_owner_authority(plugin_ids)
        seed = _binding._product_plan_seed(
            runtime,
            selected,
            configurations=configurations,
            scope_id=scope_id,
            product_policy_revision=product_policy_revision,
            tool_authority=tool_authority,
        )
        request = _binding._bind_default_approval_request_to_plan(
            _binding.create_coding_capability_plugin_composition_request(
                clock=clock,
                plugin_ids=plugin_ids,
                product_policy_revision=product_policy_revision,
                source_trust_policy_revision=next(iter(trust_revisions)),
            ),
            seed,
        )
        selection = _binding._finalize_selection(
            seed,
            request=request,
            scope_id=scope_id,
            state_root=root,
            clock=clock,
            resume_parents=resume_parents,
        )
        provider_authorities = _binding._provider_owner_authorities(plugin_ids)
        product = _binding.prepare_product_plugin_composition(
            _binding._assembly_request(
                _binding.complete_coding_package_plugin_selection_seed(
                    seed, selection=selection
                ),
                provider_authorities=provider_authorities,
            ),
            evaluated_at=_binding._read_clock(clock),
        )
        recheck_selected_revisions = _binding.selected_runtime_recheck(runtime)
        return _binding.CodingCapabilityPluginCompositionPreparation(
            request=request,
            runtime=runtime,
            selection=selection,
            product=product,
            provider_owner_authorities=provider_authorities,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=root,
            selection_recheck=recheck_selected_revisions,
            resume_parents=resume_parents,
        )

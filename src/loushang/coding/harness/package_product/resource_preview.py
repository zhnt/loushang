"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.package import product_preview as _binding


def preview_current_resources(
    self: _binding.CodingFencedProductReadOnlyPreviewOwner,
    *,
    workspace: _binding.Path,
    composition_set_id: str,
    disabled_skills: tuple[str, ...] | None,
) -> _binding.CodingCurrentDataResourcePreviewV1:
    """Compile installed data under Product policy without live activation."""

    self.epoch_runtime.assert_current()
    if (
        not isinstance(workspace, _binding.Path)
        or not workspace.is_absolute()
        or workspace != workspace.resolve(strict=True)
        or self.policy.project_scope_id != _binding._workspace_scope_id(workspace)
    ):
        raise ValueError(_binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_001"])
    composition_set = _binding.resolve_coding_composition_set(composition_set_id)
    if disabled_skills is not None and any(
        not isinstance(item, str) or not item for item in disabled_skills
    ):
        raise ValueError(_binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_002"])
    desired = self.selected_manifests.root_reader.desired_state
    before, _ = desired.capture_read_only()
    base_key = _binding.PluginInstallationKeyV1(
        product_id=self.policy.product_id,
        installation_scope="workspace",
        scope_id=self.policy.project_scope_id,
        plugin_id=_binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_003"],
    )
    base_state = before.installation(base_key).selection.desired_state
    base_disabled = base_state == "installed_disabled"
    external_ids = self.selected_manifests.selected_external_data_plugin_ids()
    evaluated_at = int(_binding.time.time())
    compiled: (
        _binding.CodingBaseProductCompilation
        | _binding.CodingExternalDataProductCompilation
        | None
    ) = None
    compiled_plugin_ids: tuple[str, ...] = ()
    try:
        if base_state == "absent":
            raise _binding.CodingBasePluginAssemblyError(
                _binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_005"],
                code=_binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_006"],
            )
        if base_disabled:
            if external_ids:
                compiled_plugin_ids = external_ids
                compiled = _binding.compile_coding_external_data_product_selection(
                    tuple(
                        self.selected_manifests.capture_selected_manifest_for_plugin(
                            plugin_id,
                            max_files=_binding._RESOURCE_PREVIEW_MAX_FILES,
                            max_total_bytes=_binding._RESOURCE_PREVIEW_MAX_BYTES,
                        )
                        for plugin_id in external_ids
                    ),
                    composition_set=composition_set,
                    session_id=_binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_004"],
                    evaluated_at=evaluated_at,
                )
        else:
            base = self.selected_manifests.capture_selected_manifest_for_plugin(
                _binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_003"],
                max_files=_binding._RESOURCE_PREVIEW_MAX_FILES,
                max_total_bytes=_binding._RESOURCE_PREVIEW_MAX_BYTES,
            )
            base_compiled = _binding.compile_coding_base_product_selection(
                base,
                composition_set,
                installation_key=base.snapshot.installation_key,
                session_id=_binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_004"],
                host_environment=_binding.LocalHostEnvironmentProbe().detect(),
                evaluated_at=evaluated_at,
            )
            compiled_plugin_ids = base_compiled.plan.selected_plugin_ids
            if external_ids:
                compiled_plugin_ids = tuple(
                    sorted((*compiled_plugin_ids, *external_ids))
                )
                base_compiled = _binding.extend_coding_base_product_data_resources(
                    base_compiled,
                    tuple(
                        self.selected_manifests.capture_selected_manifest_for_plugin(
                            plugin_id,
                            max_files=_binding._RESOURCE_PREVIEW_MAX_FILES,
                            max_total_bytes=_binding._RESOURCE_PREVIEW_MAX_BYTES,
                        )
                        for plugin_id in external_ids
                    ),
                    evaluated_at=evaluated_at,
                )
                compiled_plugin_ids = base_compiled.plan.selected_plugin_ids
            compiled = base_compiled
    except (
        _binding.CodingBasePluginAssemblyError,
        _binding.ProductCompositionError,
    ) as exc:
        after, _ = desired.capture_read_only()
        self.epoch_runtime.assert_current()
        executable, gaps = _binding._selection_evidence(
            self.policy,
            before,
            tuple(item.plugin_id for item in composition_set.plugin_requests),
        )
        if disabled_skills is not None:
            gaps.discard("disabled_skill_settings")
        gaps.add("resource_catalog_not_reached")
        if before.inventory_revision != after.inventory_revision:
            gaps.add("stale_snapshot")
        return _binding.CodingCurrentDataResourcePreviewV1(
            product_id=self.policy.product_id,
            scope_id=self.policy.project_scope_id,
            composition_set_id=composition_set.set_id,
            observed_at_unix_ns=_binding.time.time_ns(),
            desired_inventory_revision=before.inventory_revision,
            product_policy_revision=self.policy.policy_revision,
            product_authority_revision=self.policy.authority_revision,
            compiled_plugin_ids=compiled_plugin_ids,
            admitted_resources=(),
            catalog_resources=(),
            catalog_diagnostic_codes=(),
            requires_authorized_preflight=tuple(sorted(executable)),
            evidence_gaps=tuple(sorted(gaps)),
            disposition="blocked",
            blocking_owner="product_composition",
            blocking_code=exc.code,
            blocking_admission_fingerprints=(
                exc.admission_fingerprints
                if isinstance(exc, _binding.ProductCompositionError)
                else ()
            ),
        )
    loader = _binding.CodingResourceLoader(workspace_root=workspace)
    receipt = loader.prepare_catalog_input_receipt(workspace)
    product_inputs = compiled.product_resource_inputs() if compiled is not None else ()
    adapter = _binding.build_coding_initial_resource_catalog_adapter(
        receipt,
        product_scope_id=_binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_004"],
        product_composition=(
            compiled.product_composition if compiled is not None else None
        ),
        product_snapshot_resources=(product_inputs if compiled is not None else None),
        package_admission_now=evaluated_at,
        disabled_skills=disabled_skills or (),
        source_policy=(
            _binding.CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
            if compiled is None
            else _binding.CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
        ),
    )
    catalog_result = adapter.prepare_bootstrap_projection_with_receipt(
        product_id=self.policy.product_id,
        session_id=_binding._RESOURCE_PREVIEW_PROGRAM_VALUES["value_004"],
        cwd=workspace,
    )
    bundle = catalog_result.bundle
    catalog = catalog_result.catalog
    selections = _binding.project_current_product_resource_selections(
        catalog, product_inputs
    )
    after, _ = desired.capture_read_only()
    self.epoch_runtime.assert_current()
    executable, gaps = _binding._selection_evidence(
        self.policy,
        before,
        tuple(item.plugin_id for item in composition_set.plugin_requests),
    )
    if disabled_skills is not None:
        gaps.discard("disabled_skill_settings")
    if before.inventory_revision != after.inventory_revision:
        gaps.add("stale_snapshot")
    admissions, catalog_resources = _binding.project_current_product_resource_facts(
        (
            compiled.product_composition.resource_admissions
            if compiled is not None
            else ()
        ),
        bundle,
    )
    return _binding.CodingCurrentDataResourcePreviewV1(
        product_id=self.policy.product_id,
        scope_id=self.policy.project_scope_id,
        composition_set_id=composition_set.set_id,
        observed_at_unix_ns=_binding.time.time_ns(),
        desired_inventory_revision=before.inventory_revision,
        product_policy_revision=self.policy.policy_revision,
        product_authority_revision=self.policy.authority_revision,
        compiled_plugin_ids=compiled_plugin_ids,
        admitted_resources=admissions,
        catalog_resources=catalog_resources,
        catalog_diagnostic_codes=tuple(
            sorted({item.code for item in bundle.diagnostics})
        ),
        catalog_generation=catalog.catalog_generation,
        catalog_snapshot_fingerprint=catalog.snapshot_fingerprint,
        selected_resources=tuple(
            sorted(
                selections,
                key=lambda item: (
                    item.installation_key.plugin_id,
                    item.contribution_id,
                ),
            )
        ),
        requires_authorized_preflight=tuple(sorted(executable)),
        evidence_gaps=tuple(sorted(gaps)),
    )

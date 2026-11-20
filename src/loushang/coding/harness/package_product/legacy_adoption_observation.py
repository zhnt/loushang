"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import legacy_local_adoption_read as _binding

from .reviewed_plugin_adoption import reviewed_disabled_ids


def adoption_settled(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
    workspace: _binding.Path,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> bool:
    """Check one typed old local adoption without mutating Product state."""

    if resource_kind not in {
        _binding._LEGACY_PROGRAM_VALUES["value_001"],
        _binding._LEGACY_PROGRAM_VALUES["value_002"],
        _binding._LEGACY_PROGRAM_VALUES["value_003"],
    }:
        raise ValueError(_binding._LEGACY_PROGRAM_VALUES["value_004"])

    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    runtime = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs(), read_only=True
    )
    try:
        _binding.require_coding_fenced_single_legacy_skill_snapshot(
            lifecycle, runtime, plugin_id=plugin_id
        )
        accepted = _binding.reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            runtime,
            plugin_id=plugin_id,
            policy_revision=_binding.CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        )
        source_consumed = (
            False
            if accepted is None or accepted.resource_kind != resource_kind
            else _binding.coding_accepted_legacy_local_source_consumed(
                lifecycle,
                runtime,
                accepted,
                _binding.SettingsManager(
                    global_settings_path=_binding.default_global_settings_path(),
                    project_settings_path=_binding.default_project_settings_path(
                        workspace
                    ),
                ),
            )
        )
    finally:
        runtime.close()
    if accepted is None or not source_consumed:
        return False

    with _binding.CodingFencedProductReadOnlyPreviewOwner.open(lifecycle) as preview:
        matches = tuple(
            item
            for item in preview.policy.bindings
            if item.plugin_id == plugin_id
            and item.source_trust_class
            == _binding.trust_class_for_legacy_data_resource(resource_kind)
        )
        if (
            len(matches) != 1
            or matches[0].artifact_digest != accepted.review.wheel_artifact_digest
            or _binding.Path(matches[0].source_identity).name
            != accepted.review.wheel_filename
        ):
            return False
        handoffs = _binding.PackageRetentionHandoffJournal(
            epoch.control_root
            / "product-state"
            / _binding._LEGACY_PROGRAM_VALUES["value_005"]
        )
        desired = preview.selected_manifests.root_reader.desired_state
        disabled_builtins = reviewed_disabled_ids(accepted.review)
        selection = _binding._LegacyAdoptionSelection(
            key=_binding.PluginInstallationKeyV1(
                product_id=_binding._LEGACY_PROGRAM_VALUES["value_007"],
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=plugin_id,
            ),
            source_identity=matches[0].source_identity,
            install_operation_id=_binding._install_operation_id(
                accepted.review.store_id, accepted.acceptance_id
            ),
            enable_operation_id=(
                _binding._enable_operation_id(
                    accepted.review.store_id, accepted.acceptance_id
                )
                if accepted.review.desired_state == "installed_enabled"
                else None
            ),
            builtin_ids=_binding._BUILTINS,
            disabled_builtin_ids=frozenset(disabled_builtins),
            removed_builtin_operations={
                name: accepted.review.removed_builtin_operation_id(name)
                for name in _binding._BUILTINS
                if name in accepted.review.removed_builtin_ids
            },
        )
        return selection.settled(
            desired,
            preview.epoch_runtime,
            handoffs,
            preview.policy.bindings,
            store_id=epoch.store_id,
            bootstrap_policy=_binding._CODING_BUILTIN_BOOTSTRAP_POLICY,
            handoff_error=_binding._LEGACY_PROGRAM_VALUES["value_006"],
        )

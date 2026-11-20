"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import legacy_local_adoption as _binding


def adopt_local_review(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    workspace: _binding.Path,
    plugin_id: str,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> _binding.CodingLegacyLocalDataAdoptionV1:
    """Finish one type-selected, reviewed local data Resource adoption."""

    if resource_kind not in {
        _binding._LEGACY_ADOPTION_VALUES["value_001"],
        _binding._LEGACY_ADOPTION_VALUES["value_002"],
        _binding._LEGACY_ADOPTION_VALUES["value_003"],
    }:
        raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_004"])

    settle_removed_before_adoption(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs()
    )
    admission_checked = False
    try:
        acceptance = _binding.reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            epoch_runtime,
            plugin_id=plugin_id,
            policy_revision=_binding.CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        )
        if acceptance is None:
            _binding.require_coding_fenced_single_legacy_data(
                lifecycle,
                epoch_runtime,
                plugin_id=plugin_id,
                resource_kind=resource_kind,
            )
            admission_checked = True
            acceptance = _binding.accept_coding_legacy_installed_local_review(
                lifecycle,
                epoch_runtime,
                plugin_id=plugin_id,
                policy_revision=_binding.CODING_PACKAGE_PRODUCT_POLICY_REVISION,
                accepted_review_id=accepted_review_id,
                resource_kind=resource_kind,
            )
        elif acceptance.review.review_id != accepted_review_id:
            raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_010"])
        else:
            _binding.require_coding_fenced_single_legacy_skill_snapshot(
                lifecycle, epoch_runtime, plugin_id=plugin_id
            )
        if acceptance.resource_kind != resource_kind:
            raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_005"])
        _binding.consume_coding_accepted_legacy_local_source(
            lifecycle,
            epoch_runtime,
            acceptance,
            _binding.SettingsManager(
                global_settings_path=_binding.default_global_settings_path(),
                project_settings_path=_binding.default_project_settings_path(workspace),
            ),
        )
    finally:
        epoch_runtime.close()

    product_owner = _binding.open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        bound = tuple(
            item
            for item in product_owner.runtime_owner.product_owner.policy.bindings
            if item.plugin_id == plugin_id
            and item.source_trust_class in _binding.LEGACY_LOCAL_DATA_TRUST_CLASSES
        )
        expected_trust = _binding.trust_class_for_legacy_data_resource(resource_kind)
        if bound and (
            len(bound) != 1
            or bound[0].source_trust_class != expected_trust
            or bound[0].artifact_digest != acceptance.review.wheel_artifact_digest
            or _binding.Path(bound[0].source_identity).name
            != acceptance.review.wheel_filename
        ):
            raise RuntimeError(_binding._LEGACY_ADOPTION_VALUES["value_006"])
    finally:
        product_owner.close()
    if not bound:
        epoch_runtime = _binding.PackageProductPosixFencedRuntimeOwner.open(
            **epoch.fenced_runtime_open_kwargs()
        )
        try:
            if not admission_checked:
                _binding.require_coding_fenced_single_legacy_data(
                    lifecycle,
                    epoch_runtime,
                    plugin_id=plugin_id,
                    resource_kind=resource_kind,
                )
            _binding.bind_coding_accepted_legacy_local_source(
                lifecycle,
                epoch_runtime,
                plugin_id=plugin_id,
                policy_revision=_binding.CODING_PACKAGE_PRODUCT_POLICY_REVISION,
            )
        finally:
            epoch_runtime.close()

    installation = _binding.install_coding_accepted_legacy_local_plugin(
        lifecycle,
        workspace=workspace,
        plugin_id=plugin_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    enablement = (
        _binding.enable_coding_accepted_legacy_local_data_plugin(
            lifecycle,
            workspace=workspace,
            plugin_id=plugin_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            resource_kind=resource_kind,
        )
        if acceptance.review.desired_state == "installed_enabled"
        else None
    )
    product_owner = _binding.open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        disabled_builtins = {
            item.plugin_id for item in acceptance.review.disabled_plugins
        }
        disabled_builtins.update(
            item.plugin_id
            for item in acceptance.review.builtin_intent
            if item.desired_state == "installed_disabled"
        )
        product = product_owner.runtime_owner.product_owner
        for builtin_id in acceptance.review.removed_builtin_ids:
            _binding._preserve_removed_builtin(product_owner, acceptance, builtin_id)
        _binding.bootstrap_reviewed_product_plugins(
            product,
            (
                _binding._LEGACY_ADOPTION_VALUES["value_007"],
                _binding._LEGACY_ADOPTION_VALUES["value_008"],
                _binding._LEGACY_ADOPTION_VALUES["value_009"],
            ),
            disabled_ids=disabled_builtins,
            removed_ids=acceptance.review.removed_builtin_ids,
            policy=_binding._CODING_BUILTIN_BOOTSTRAP_POLICY,
            strict_history=False,
        )
    finally:
        product_owner.close()
    return _binding.CodingLegacyLocalSkillAdoptionV1(
        acceptance=acceptance,
        installation=installation,
        enablement=enablement,
    )


def settle_removed_before_adoption(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    workspace: _binding.Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> None:
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    owner = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs(), read_only=True
    )
    settings = _binding.SettingsManager(
        global_settings_path=_binding.default_global_settings_path(),
        project_settings_path=_binding.default_project_settings_path(workspace),
    )
    try:
        inventory = _binding.read_coding_legacy_installation_inventory(
            lifecycle, owner
        ).inventory
        if not inventory.unselected_source_identities:
            return
        accepted = _binding.read_coding_first_b_removed_local_acceptance(
            lifecycle, owner, settings_manager=settings
        )
        if accepted is None:
            raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_011"])
    finally:
        owner.close()
    _binding.adopt_coding_first_b_removed_local(
        lifecycle,
        settings,
        workspace=workspace,
        accepted_review_id=accepted.review.review_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )

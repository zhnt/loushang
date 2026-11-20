"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import legacy_local_installation as _binding


def enable_accepted_data_plugin(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    workspace: _binding.Path,
    plugin_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> _binding.CodingLegacyLocalEnablementReceiptV1:
    """Enable one accepted, installed data Resource of the selected type."""

    owner = _binding.open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        product = owner.runtime_owner.product_owner
        if not isinstance(
            owner.epoch_runtime, _binding.PackageProductPosixFencedRuntimeOwner
        ):
            raise _binding.CodingLegacyLocalInstallationError(
                _binding._LEGACY_ADOPTION_VALUES["value_001"]
            )
        accepted = _binding.reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            owner.epoch_runtime,
            plugin_id=plugin_id,
            policy_revision=_binding.CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        )
        if (
            accepted is None
            or accepted.resource_kind != resource_kind
            or accepted.review.desired_state != "installed_enabled"
        ):
            raise _binding.CodingLegacyLocalInstallationError(
                _binding._LEGACY_ADOPTION_VALUES["value_002"]
            )
        source = _binding._accepted_source(owner, plugin_id, accepted)
        install_id = _binding._install_operation_id(
            accepted.review.store_id, accepted.acceptance_id
        )
        key = _binding.PluginInstallationKeyV1(
            product_id=_binding._LEGACY_ADOPTION_VALUES["value_003"],
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
        )
        installation = _binding._installation(
            product,
            key,
            source.source_identity,
            accepted,
            install_operation_id=install_id,
        )
        install_command_id, revision = installation.enable()
        enable_id = installation.enable_operation_id
        owner.epoch_runtime.assert_current()
        return _binding.CodingLegacyLocalEnablementReceiptV1(
            acceptance_id=accepted.acceptance_id,
            install_operation_id=install_id,
            install_command_id=install_command_id,
            enable_operation_id=enable_id,
            plugin_id=plugin_id,
            package_revision=revision,
        )
    finally:
        owner.close()


def install_accepted_plugin(
    owner: _binding.CodingFencedProductApplicationOwner,
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
) -> _binding.CodingLegacyLocalInstallReceiptV1:
    product = owner.runtime_owner.product_owner
    if not isinstance(
        owner.epoch_runtime, _binding.PackageProductPosixFencedRuntimeOwner
    ):
        raise _binding.CodingLegacyLocalInstallationError(
            _binding._LEGACY_ADOPTION_VALUES["value_001"]
        )
    accepted = _binding.reopen_coding_legacy_installed_local_acceptance(
        lifecycle,
        owner.epoch_runtime,
        plugin_id=plugin_id,
        policy_revision=_binding.CODING_PACKAGE_PRODUCT_POLICY_REVISION,
    )
    if accepted is None:
        raise _binding.CodingLegacyLocalInstallationError(
            _binding._LEGACY_ADOPTION_VALUES["value_004"]
        )
    source = _binding._accepted_source(owner, plugin_id, accepted)
    operation_id = _binding._install_operation_id(
        accepted.review.store_id, accepted.acceptance_id
    )
    key = _binding.PluginInstallationKeyV1(
        product_id=_binding._LEGACY_ADOPTION_VALUES["value_003"],
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    installation = _binding._installation(
        product,
        key,
        source.source_identity,
        accepted,
        install_operation_id=operation_id,
    )
    command_id, revision = installation.install(
        allow_enabled=accepted.review.desired_state == "installed_enabled"
    )
    owner.epoch_runtime.assert_current()
    return _binding.CodingLegacyLocalInstallReceiptV1(
        acceptance_id=accepted.acceptance_id,
        operation_id=operation_id,
        desired_command_id=command_id,
        plugin_id=plugin_id,
        package_revision=revision,
    )


def accepted_source(
    owner: _binding.CodingFencedProductApplicationOwner,
    plugin_id: str,
    accepted: _binding.CodingLegacyLocalAcceptanceV1,
) -> _binding.PackageProductLocalWheelBindingV1:
    sources = tuple(
        item
        for item in owner.runtime_owner.product_owner.policy.bindings
        if item.plugin_id == plugin_id
        and item.source_trust_class
        == _binding.trust_class_for_legacy_data_resource(accepted.resource_kind)
        and item.artifact_digest == accepted.review.wheel_artifact_digest
        and _binding.Path(item.source_identity).name == accepted.review.wheel_filename
    )
    if len(sources) != 1:
        raise _binding.CodingLegacyLocalInstallationError(
            _binding._LEGACY_CHAIN_VALUES["value_001"]
        )
    return sources[0]

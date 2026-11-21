"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from loushang.coding.package import legacy_builtin_adoption as _binding
from loushang.harness.package_product._plugin_bootstrap import (
    bootstrap_reviewed_product_plugins,
)

from .reviewed_plugin_adoption import replay_reviewed_removals, reviewed_disabled_ids


def adopt_builtin_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    settings_manager: _binding.SettingsManager,
    *,
    workspace: _binding.Path,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    windows_candidate: bool,
) -> _binding.CodingLegacyBuiltinOnlyAcceptanceV1:
    """Accept the old review once and seed only its builtin Product choices."""

    if type(windows_candidate) is not bool:
        raise TypeError(_binding._LEGACY_ADOPTION_VALUES["value_001"])
    if _binding.os.name == "nt" and not windows_candidate:
        raise RuntimeError(_binding._LEGACY_ADOPTION_VALUES["value_002"])
    if _binding.os.name != "nt" and windows_candidate:
        raise ValueError(_binding._LEGACY_ADOPTION_VALUES["value_003"])
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    epoch_owner_type = (
        _binding.PackageProductWindowsFencedRuntimeOwner
        if _binding.os.name == "nt"
        else _binding.PackageProductPosixFencedRuntimeOwner
    )
    epoch_runtime = epoch_owner_type.open(**epoch.fenced_runtime_open_kwargs())
    try:
        receipt = _binding.accept_coding_first_b_builtin_only(
            lifecycle,
            epoch_runtime,
            settings_manager=settings_manager,
            accepted_review_id=accepted_review_id,
        )
    finally:
        epoch_runtime.close()
    owner = _binding.open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        windows_candidate=windows_candidate,
    )
    try:
        product = owner.runtime_owner.product_owner
        disabled = reviewed_disabled_ids(receipt.review)
        replay_reviewed_removals(
            product,
            receipt.review.removed_builtin_ids,
            product_id=_binding._CODING_BUILTIN_BOOTSTRAP_POLICY.product_id,
            operation_id_for=receipt.review.removed_builtin_operation_id,
            error_prefix=_binding._REMOVAL_LABEL,
        )
        bootstrap_reviewed_product_plugins(
            product,
            _binding._BUILTINS,
            disabled_ids=disabled,
            removed_ids=receipt.review.removed_builtin_ids,
            policy=_binding._CODING_BUILTIN_BOOTSTRAP_POLICY,
            strict_history=True,
            history_label=_binding._LEGACY_ADOPTION_VALUES["value_004"],
        )
        return receipt
    finally:
        owner.close()

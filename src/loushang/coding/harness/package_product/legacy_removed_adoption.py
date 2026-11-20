"""Complete Legacy evidence programs borrowing original Product declarations.

Existing snapshots, journals and parsing/retirement owners remain authoritative;
Product policy and nominal contracts are explicit intermediate dependencies.
"""

from __future__ import annotations

from functools import partial

from loushang.coding.package import legacy_removed_adoption as _binding
from loushang.harness.package_product._plugin_bootstrap import (
    bootstrap_reviewed_product_plugins,
)

from .reviewed_plugin_adoption import replay_reviewed_removals, reviewed_disabled_ids


def adopt_removed_snapshot(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    settings_manager: _binding.SettingsManager,
    *,
    workspace: _binding.Path,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> _binding.CodingLegacyRemovedAcceptanceV1:
    """Write the accepted absent choices and bootstrap current builtin choices."""

    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs()
    )
    try:
        receipt = _binding.accept_coding_first_b_removed_local(
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
    )
    try:
        product = owner.runtime_owner.product_owner
        removed_ids = {
            *(item.plugin_id for item in receipt.review.removed_local),
            *receipt.review.removed_builtin_ids,
        }
        replay_reviewed_removals(
            product,
            sorted(removed_ids),
            product_id=_binding._CODING_BUILTIN_BOOTSTRAP_POLICY.product_id,
            operation_id_for=partial(_binding._removed_operation_id, receipt),
            error_prefix=_binding._REMOVAL_LABEL,
        )
        disabled = reviewed_disabled_ids(receipt.review)
        bootstrap_reviewed_product_plugins(
            product,
            _binding._BUILTINS,
            disabled_ids=disabled,
            removed_ids=removed_ids,
            policy=_binding._CODING_BUILTIN_BOOTSTRAP_POLICY,
            strict_history=True,
            history_label=_binding._LEGACY_ADOPTION_VALUES["value_001"],
        )
        return receipt
    finally:
        owner.close()

"""Replayable Product Desired adoption for a reviewed old builtin-only state."""

from __future__ import annotations

import os
from pathlib import Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._plugin_bootstrap import (
    bootstrap_reviewed_product_plugins,
    preserve_removed_product_plugin,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from .epoch_layout import resolve_coding_package_epoch_layout
from .legacy_builtin_acceptance import (
    CodingLegacyBuiltinOnlyAcceptanceV1,
    accept_coding_first_b_builtin_only,
)
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY,
    CodingFencedProductApplicationOwner,
    open_coding_fenced_product_application_owner,
)

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


def adopt_coding_first_b_builtin_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    windows_candidate: bool = False,
) -> CodingLegacyBuiltinOnlyAcceptanceV1:
    """Accept the old review once and seed only its builtin Product choices."""

    if type(windows_candidate) is not bool:
        raise TypeError("Windows builtin migration candidate must be explicit")
    if os.name == "nt" and not windows_candidate:
        raise RuntimeError("Windows builtin migration candidate is not admitted")
    if os.name != "nt" and windows_candidate:
        raise ValueError("Windows builtin migration candidate requires Windows")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_owner_type = (
        PackageProductWindowsFencedRuntimeOwner
        if os.name == "nt"
        else PackageProductPosixFencedRuntimeOwner
    )
    epoch_runtime = epoch_owner_type.open(**epoch.fenced_runtime_open_kwargs())
    try:
        receipt = accept_coding_first_b_builtin_only(
            lifecycle,
            epoch_runtime,
            settings_manager=settings_manager,
            accepted_review_id=accepted_review_id,
        )
    finally:
        epoch_runtime.close()
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        windows_candidate=windows_candidate,
    )
    try:
        product = owner.runtime_owner.product_owner
        disabled = {item.plugin_id for item in receipt.review.disabled_plugins}
        disabled.update(
            item.plugin_id
            for item in receipt.review.builtin_intent
            if item.desired_state == "installed_disabled"
        )
        for plugin_id in receipt.review.removed_builtin_ids:
            _preserve_removed_builtin(owner, receipt, plugin_id)
        bootstrap_reviewed_product_plugins(
            product,
            _BUILTINS,
            disabled_ids=disabled,
            removed_ids=receipt.review.removed_builtin_ids,
            policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            strict_history=True,
            history_label="Coding builtin-only Product",
        )
        return receipt
    finally:
        owner.close()


def _key(
    owner: CodingFencedProductApplicationOwner, plugin_id: str
) -> PluginInstallationKeyV1:
    product = owner.runtime_owner.product_owner
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=product.policy.project_scope_id,
        plugin_id=plugin_id,
    )


def _preserve_removed_builtin(
    owner: CodingFencedProductApplicationOwner,
    receipt: CodingLegacyBuiltinOnlyAcceptanceV1,
    plugin_id: str,
) -> None:
    product = owner.runtime_owner.product_owner
    key = _key(owner, plugin_id)
    operation_id = receipt.review.removed_builtin_operation_id(plugin_id)
    preserve_removed_product_plugin(
        product,
        key,
        operation_id,
        error_prefix="Coding removed builtin Product",
    )


__all__ = ["adopt_coding_first_b_builtin_only"]

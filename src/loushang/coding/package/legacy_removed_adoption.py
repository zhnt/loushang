"""Replay accepted old local removals into Product Desired State."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._plugin_bootstrap import (
    bootstrap_reviewed_product_plugins,
    preserve_removed_product_plugin,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .epoch_layout import resolve_coding_package_epoch_layout
from .legacy_builtin_adoption import _key
from .legacy_removed_acceptance import (
    CodingLegacyRemovedAcceptanceV1,
    accept_coding_first_b_removed_local,
)
from .legacy_review import shared_coding_legacy_builtin_removal_operation_id
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY,
    CodingFencedProductApplicationOwner,
    open_coding_fenced_product_application_owner,
)

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


def adopt_coding_first_b_removed_local(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingLegacyRemovedAcceptanceV1:
    """Write the accepted absent choices and bootstrap current builtin choices."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs()
    )
    try:
        receipt = accept_coding_first_b_removed_local(
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
    )
    try:
        product = owner.runtime_owner.product_owner
        removed_ids = {
            *(item.plugin_id for item in receipt.review.removed_local),
            *receipt.review.removed_builtin_ids,
        }
        for plugin_id in sorted(removed_ids):
            _preserve_removed(owner, receipt, plugin_id)
        disabled = {item.plugin_id for item in receipt.review.disabled_plugins}
        disabled.update(
            item.plugin_id
            for item in receipt.review.builtin_intent
            if item.desired_state == "installed_disabled"
        )
        bootstrap_reviewed_product_plugins(
            product,
            _BUILTINS,
            disabled_ids=disabled,
            removed_ids=removed_ids,
            policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            strict_history=True,
            history_label="Coding builtin-only Product",
        )
        return receipt
    finally:
        owner.close()


def _removed_operation_id(
    receipt: CodingLegacyRemovedAcceptanceV1, plugin_id: str
) -> str:
    if plugin_id == "coding.base":
        # Base first becomes removable in this migration slice. Reuse the
        # active-local fence identity without changing old local/LSP/Arch IDs.
        return shared_coding_legacy_builtin_removal_operation_id(
            receipt.review.first_fence_id, plugin_id
        )
    return (
        "coding-legacy-local-remove:"
        + sha256(
            f"{receipt.review.store_id}\0{receipt.review.review_id}\0{plugin_id}".encode()
        ).hexdigest()
    )


def _preserve_removed(
    owner: CodingFencedProductApplicationOwner,
    receipt: CodingLegacyRemovedAcceptanceV1,
    plugin_id: str,
) -> None:
    product = owner.runtime_owner.product_owner
    key = _key(owner, plugin_id)
    operation_id = _removed_operation_id(receipt, plugin_id)
    preserve_removed_product_plugin(
        product,
        key,
        operation_id,
        error_prefix="Coding removed local Product",
    )


__all__ = ["adopt_coding_first_b_removed_local"]

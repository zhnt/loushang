"""Replay accepted old local removals into Product Desired State."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from loushang.coding.harness.package_product import legacy_removed_adoption as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner as PackageProductPosixFencedRuntimeOwner,
)

from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_removed_acceptance import (
    CodingLegacyRemovedAcceptanceV1,
)
from .legacy_removed_acceptance import (
    accept_coding_first_b_removed_local as accept_coding_first_b_removed_local,
)
from .legacy_review import shared_coding_legacy_builtin_removal_operation_id
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY as _CODING_BUILTIN_BOOTSTRAP_POLICY,
)
from .product_runtime import (
    open_coding_fenced_product_application_owner as open_coding_fenced_product_application_owner,
)

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


_REMOVAL_LABEL = "Coding removed local Product"

_LEGACY_ADOPTION_VALUES = {"value_001": "Coding builtin-only Product"}


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

    return _programs.adopt_removed_snapshot(
        lifecycle,
        settings_manager,
        workspace=workspace,
        accepted_review_id=accepted_review_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )


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


__all__ = ["adopt_coding_first_b_removed_local"]

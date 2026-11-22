"""Replay accepted old local removals into Product Desired State."""

from __future__ import annotations

from functools import partial
from hashlib import sha256
from pathlib import Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._application_runtime import (
    hold_accepted_product_adoption,
)
from loushang.harness.package_product._plugin_bootstrap import (
    replay_reviewed_product_plugins,
)
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
from .legacy_review import (
    _reviewed_disabled_ids,
    shared_coding_legacy_builtin_removal_operation_id,
)
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY as _CODING_BUILTIN_BOOTSTRAP_POLICY,
)
from .product_runtime import (
    _CODING_BUILTIN_PLUGIN_IDS,
)
from .product_runtime import (
    open_coding_fenced_product_application_owner as open_coding_fenced_product_application_owner,
)

_REMOVAL_LABEL = "Coding removed local Product"


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
    with hold_accepted_product_adoption(
        open_epoch=lambda: PackageProductPosixFencedRuntimeOwner.open(
            **epoch.fenced_runtime_open_kwargs()
        ),
        accept_review=lambda epoch_runtime: accept_coding_first_b_removed_local(
            lifecycle,
            epoch_runtime,
            settings_manager=settings_manager,
            accepted_review_id=accepted_review_id,
        ),
        open_application=lambda: open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        ),
    ) as (receipt, owner):
        product = owner.runtime_owner.product_owner
        removed_ids = {
            *(item.plugin_id for item in receipt.review.removed_local),
            *receipt.review.removed_builtin_ids,
        }
        disabled = _reviewed_disabled_ids(receipt.review)
        replay_reviewed_product_plugins(
            product,
            _CODING_BUILTIN_PLUGIN_IDS,
            disabled_ids=disabled,
            removed_ids=sorted(removed_ids),
            operation_id_for=partial(_removed_operation_id, receipt),
            removal_label=_REMOVAL_LABEL,
            policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            strict_history=True,
            history_label="Coding builtin-only Product",
        )
        return receipt


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

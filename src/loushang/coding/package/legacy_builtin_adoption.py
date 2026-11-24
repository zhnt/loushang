"""Replayable Product Desired adoption for a reviewed old builtin-only state."""

from __future__ import annotations

import os as os
from pathlib import Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._plugin_bootstrap import (
    ReviewedPluginChoices,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner as PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner as PackageProductWindowsFencedRuntimeOwner,
)

from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_builtin_acceptance import (
    CodingLegacyBuiltinOnlyAcceptanceV1,
)
from .legacy_builtin_acceptance import (
    accept_coding_first_b_builtin_only as accept_coding_first_b_builtin_only,
)
from .legacy_review import _reviewed_disabled_ids
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY as _CODING_BUILTIN_BOOTSTRAP_POLICY,
)
from .product_runtime import (
    _adopt_coding_reviewed_plugins,
)
from .product_runtime import (
    open_coding_fenced_product_application_owner as open_coding_fenced_product_application_owner,
)

_REMOVAL_LABEL = "Coding removed builtin Product"


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
    epoch_owner_type = (
        PackageProductWindowsFencedRuntimeOwner
        if os.name == "nt"
        else PackageProductPosixFencedRuntimeOwner
    )
    return _adopt_coding_reviewed_plugins(
        lifecycle, settings_manager, workspace=workspace, accepted_review_id=accepted_review_id,
        runtime_version=runtime_version, runtime_protocol_epoch=runtime_protocol_epoch,
        windows_candidate=windows_candidate, open_epoch=epoch_owner_type.open,
        open_application=open_coding_fenced_product_application_owner,
        accept_review=accept_coding_first_b_builtin_only,
        removal_label=_REMOVAL_LABEL,
        reviewed_choices=lambda receipt: ReviewedPluginChoices(
            disabled_ids=_reviewed_disabled_ids(receipt.review),
            removed_ids=receipt.review.removed_builtin_ids,
            operation_id_for=receipt.review.removed_builtin_operation_id,
        ),
    )


__all__ = ["adopt_coding_first_b_builtin_only"]

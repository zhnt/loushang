"""Replayable Product Desired adoption for a reviewed old builtin-only state."""

from __future__ import annotations

import os as os
from pathlib import Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._plugin_bootstrap import (
    bootstrap_reviewed_product_plugins,
    replay_reviewed_removals,
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
    open_coding_fenced_product_application_owner as open_coding_fenced_product_application_owner,
)

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


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
        disabled = _reviewed_disabled_ids(receipt.review)
        replay_reviewed_removals(
            product,
            receipt.review.removed_builtin_ids,
            product_id=_CODING_BUILTIN_BOOTSTRAP_POLICY.product_id,
            operation_id_for=receipt.review.removed_builtin_operation_id,
            error_prefix=_REMOVAL_LABEL,
        )
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


__all__ = ["adopt_coding_first_b_builtin_only"]

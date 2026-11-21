"""Replayable Product Desired adoption for a reviewed old builtin-only state."""

from __future__ import annotations

import os as os
from pathlib import Path

from loushang.coding.harness.package_product import legacy_builtin_adoption as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
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
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY as _CODING_BUILTIN_BOOTSTRAP_POLICY,
)
from .product_runtime import (
    open_coding_fenced_product_application_owner as open_coding_fenced_product_application_owner,
)

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


_REMOVAL_LABEL = "Coding removed builtin Product"

_LEGACY_ADOPTION_VALUES = {
    "value_001": "Windows builtin migration candidate must be explicit",
    "value_002": "Windows builtin migration candidate is not admitted",
    "value_003": "Windows builtin migration candidate requires Windows",
    "value_004": "Coding builtin-only Product",
}


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

    return _programs.adopt_builtin_snapshot(
        lifecycle,
        settings_manager,
        workspace=workspace,
        accepted_review_id=accepted_review_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        windows_candidate=windows_candidate,
    )


__all__ = ["adopt_coding_first_b_builtin_only"]

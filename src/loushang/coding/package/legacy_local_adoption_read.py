"""Read-only proof that an explicitly accepted old Skill finished Product adoption."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from loushang.coding.harness.package_product import (
    legacy_adoption_observation as _programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager as SettingsManager
from loushang.harness.package_product._legacy_local_migration import (
    _LegacyAdoptionSelection as _LegacyAdoptionSelection,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal as PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner as PackageProductPosixFencedRuntimeOwner,
)

from ..control.settings_store import (
    default_global_settings_path as default_global_settings_path,
)
from ..control.settings_store import (
    default_project_settings_path as default_project_settings_path,
)
from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_data_trust import (
    trust_class_for_legacy_data_resource as trust_class_for_legacy_data_resource,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_local_installation import _enable_operation_id as _enable_operation_id
from .legacy_local_installation import _install_operation_id as _install_operation_id
from .legacy_skill_cutover_admission import (
    require_coding_fenced_single_legacy_skill_snapshot as require_coding_fenced_single_legacy_skill_snapshot,
)
from .legacy_source_consumption import (
    coding_accepted_legacy_local_source_consumed as coding_accepted_legacy_local_source_consumed,
)
from .product_preview import (
    CodingFencedProductReadOnlyPreviewOwner as CodingFencedProductReadOnlyPreviewOwner,
)
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY as _CODING_BUILTIN_BOOTSTRAP_POLICY,
)
from .product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION as CODING_PACKAGE_PRODUCT_POLICY_REVISION,
)

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


_LEGACY_PROGRAM_VALUES = {
    "value_001": "skill",
    "value_002": "prompt",
    "value_003": "theme",
    "value_004": "Unsupported legacy Resource type",
    "value_005": "handoff.jsonl",
    "value_006": "Coding legacy adoption handoff changed",
    "value_007": "coding",
}


def coding_legacy_local_skill_adoption_settled(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
    workspace: Path,
) -> bool:
    """Join frozen acceptance to Product handoffs and Desired history only.

    A later operator disable or remove does not erase a completed adoption.
    Missing or partial evidence returns false; corrupt evidence raises.
    """

    return coding_legacy_local_data_adoption_settled(
        lifecycle, plugin_id=plugin_id, workspace=workspace, resource_kind="skill"
    )


def coding_legacy_local_data_adoption_settled(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
    workspace: Path,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> bool:
    """Check one typed old local adoption without mutating Product state."""

    return _programs.adoption_settled(
        lifecycle, plugin_id=plugin_id, workspace=workspace, resource_kind=resource_kind
    )


__all__ = [
    "coding_legacy_local_data_adoption_settled",
    "coding_legacy_local_skill_adoption_settled",
]

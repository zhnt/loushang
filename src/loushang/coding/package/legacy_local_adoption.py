"""Explicit Product orchestration for one reviewed old local Skill."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding.harness.package_product import legacy_adoption as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager as SettingsManager
from loushang.harness.package_product._plugin_bootstrap import (
    bootstrap_reviewed_product_plugins as bootstrap_reviewed_product_plugins,
)
from loushang.harness.package_product._plugin_bootstrap import (
    preserve_removed_product_plugin,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
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
    LEGACY_LOCAL_DATA_TRUST_CLASSES as LEGACY_LOCAL_DATA_TRUST_CLASSES,
)
from .legacy_data_trust import (
    trust_class_for_legacy_data_resource as trust_class_for_legacy_data_resource,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
)
from .legacy_local_acceptance import (
    accept_coding_legacy_installed_local_review as accept_coding_legacy_installed_local_review,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_local_binding_owner import (
    bind_coding_accepted_legacy_local_source as bind_coding_accepted_legacy_local_source,
)
from .legacy_local_installation import (
    CodingLegacyLocalEnablementReceiptV1,
    CodingLegacyLocalInstallReceiptV1,
)
from .legacy_local_installation import (
    enable_coding_accepted_legacy_local_data_plugin as enable_coding_accepted_legacy_local_data_plugin,
)
from .legacy_local_installation import (
    install_coding_accepted_legacy_local_plugin as install_coding_accepted_legacy_local_plugin,
)
from .legacy_removed_acceptance import (
    read_coding_first_b_removed_local_acceptance as read_coding_first_b_removed_local_acceptance,
)
from .legacy_removed_adoption import (
    adopt_coding_first_b_removed_local as adopt_coding_first_b_removed_local,
)
from .legacy_skill_cutover_admission import (
    require_coding_fenced_single_legacy_data as require_coding_fenced_single_legacy_data,
)
from .legacy_skill_cutover_admission import (
    require_coding_fenced_single_legacy_skill_snapshot as require_coding_fenced_single_legacy_skill_snapshot,
)
from .legacy_source_consumption import (
    consume_coding_accepted_legacy_local_source as consume_coding_accepted_legacy_local_source,
)
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY as _CODING_BUILTIN_BOOTSTRAP_POLICY,
)
from .product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION as CODING_PACKAGE_PRODUCT_POLICY_REVISION,
)
from .product_runtime import (
    CodingFencedProductApplicationOwner,
)
from .product_runtime import (
    open_coding_fenced_product_application_owner as open_coding_fenced_product_application_owner,
)

_LEGACY_ADOPTION_VALUES = {
    "value_001": "skill",
    "value_002": "prompt",
    "value_003": "theme",
    "value_004": "Unsupported legacy Resource type",
    "value_005": "Coding legacy data adoption requires a matching Resource receipt",
    "value_006": "Coding legacy local Product Source binding changed",
    "value_007": "coding.base",
    "value_008": "coding.lsp.default",
    "value_009": "coding.arch.default",
    "value_010": "Coding legacy local review ID changed",
    "value_011": "Coding old local removals need explicit adoption before active locals",
}


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalSkillAdoptionV1:
    acceptance: CodingLegacyLocalAcceptanceV1
    installation: CodingLegacyLocalInstallReceiptV1
    enablement: CodingLegacyLocalEnablementReceiptV1 | None


CodingLegacyLocalDataAdoptionV1 = CodingLegacyLocalSkillAdoptionV1


def adopt_coding_legacy_local_skill_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_id: str,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingLegacyLocalSkillAdoptionV1:
    """Accept exact old evidence, install one Skill, then seed checked-in base.

    Each transition is independently replayable. An already accepted review
    can finish after its original Source disappears if its Wheel was bound.
    """

    return adopt_coding_legacy_local_data_review(
        lifecycle,
        workspace=workspace,
        plugin_id=plugin_id,
        accepted_review_id=accepted_review_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        resource_kind="skill",
    )


def adopt_coding_legacy_local_data_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_id: str,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> CodingLegacyLocalDataAdoptionV1:
    """Finish one type-selected, reviewed local data Resource adoption."""

    return _programs.adopt_local_review(
        lifecycle,
        workspace=workspace,
        plugin_id=plugin_id,
        accepted_review_id=accepted_review_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        resource_kind=resource_kind,
    )


def _settle_reviewed_removed_local_before_active_adoption(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> None:
    return _programs.settle_removed_before_adoption(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )


def _preserve_removed_builtin(
    owner: CodingFencedProductApplicationOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    plugin_id: str,
) -> None:
    """Write one reviewed absent tombstone through Product management."""

    product = owner.runtime_owner.product_owner
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=product.policy.project_scope_id,
        plugin_id=plugin_id,
    )
    operation_id = acceptance.review.removed_builtin_operation_id(plugin_id)
    preserve_removed_product_plugin(
        product,
        key,
        operation_id,
        error_prefix="Coding removed builtin Product",
    )


__all__ = [
    "CodingLegacyLocalDataAdoptionV1",
    "CodingLegacyLocalSkillAdoptionV1",
    "adopt_coding_legacy_local_data_review",
    "adopt_coding_legacy_local_skill_review",
]

"""Pre-fence admission for old local Skills under the frozen B snapshot."""

from __future__ import annotations

import json as json
import zipfile as zipfile
from dataclasses import dataclass
from typing import Literal

from loushang.coding.harness.package_product import legacy_data_admission as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.plugin_authoring.resource_item import (
    _inspect_legacy_local_data_wheel,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackagePosixEpochCutoverError as PackagePosixEpochCutoverError,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .legacy_desired_evidence import (
    parse_coding_legacy_desired_evidence as parse_coding_legacy_desired_evidence,
)
from .legacy_desired_evidence import (
    read_coding_legacy_desired_evidence as read_coding_legacy_desired_evidence,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_installations as classify_coding_legacy_installations,
)
from .legacy_installation_inventory import (
    classify_coding_legacy_removed_local_installations as classify_coding_legacy_removed_local_installations,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_instance_evidence import (
    parse_coding_legacy_retired_instance_capture as parse_coding_legacy_retired_instance_capture,
)
from .legacy_local_wheel import (
    CodingLegacyLocalWheelCandidateV1,
)
from .legacy_lock_evidence import (
    parse_coding_legacy_local_binding_heads as parse_coding_legacy_local_binding_heads,
)
from .legacy_lock_evidence import (
    read_coding_legacy_local_binding_heads as read_coding_legacy_local_binding_heads,
)
from .legacy_operation_evidence import (
    CodingLegacyRetirementCaptureV1 as CodingLegacyRetirementCaptureV1,
)
from .legacy_operation_evidence import (
    classify_coding_legacy_management_members as classify_coding_legacy_management_members,
)
from .legacy_operation_evidence import (
    parse_coding_legacy_operation_evidence as parse_coding_legacy_operation_evidence,
)
from .legacy_reacquisition import (
    reacquire_coding_legacy_installed_local_source as reacquire_coding_legacy_installed_local_source,
)
from .legacy_snapshot_member import (
    CodingLegacyEvidenceDomain as CodingLegacyEvidenceDomain,
)
from .legacy_snapshot_member import (
    CodingLegacyInventoryDomain as CodingLegacyInventoryDomain,
)
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_snapshot_member import (
    read_coding_first_b_snapshot_member as read_coding_first_b_snapshot_member,
)
from .pre_b_snapshot import CodingPreBSnapshotPreparation

# Each member is reacquired and rebuilt while the first-fence lock is held.
_MAX_LOCAL_DATA_PLUGINS = 16
_REMOVABLE_BUILTIN_PLUGIN_IDS = frozenset(
    {"coding.base", "coding.lsp.default", "coding.arch.default"}
)


_LEGACY_PROGRAM_VALUES = {
    "value_001": "Coding lifecycle layout is required",
    "value_002": "Coding pre-B snapshot preparation is required",
    "value_003": "Package snapshot receipt is required",
    "value_004": "Coding legacy Plugin identity is required",
    "value_005": "skill",
    "value_006": "prompt",
    "value_007": "theme",
    "value_008": "Unsupported legacy Resource type",
    "value_009": "Legacy Skill snapshot shape is unsupported",
    "value_010": "package-lock.json.lock",
    "value_011": "Legacy Package lock changed",
    "value_012": "coding-source-configuration.json",
    "value_013": "package-lock.json",
    "value_014": "desired-state.jsonl",
    "value_015": "Legacy Skill snapshot members are incomplete",
    "value_018": "Legacy data Installation set is unsupported",
    "value_019": "Coding legacy data snapshot cannot be admitted before first fence",
    "value_025": "Legacy management operation journal is missing",
    "value_026": "Legacy Skill Source is not local",
    "value_027": "Legacy data Resource type changed",
    "value_028": "Legacy data names conflict across Installations",
    "value_031": "Legacy management lock changed",
    "value_033": "Legacy retirement journals are missing",
    "value_034": "Legacy Instance evidence is missing",
    "value_035": "coding_legacy_skill_snapshot_refused",
    "value_036": "coding_legacy_prompt_snapshot_refused",
    "value_037": "coding_legacy_theme_snapshot_refused",
    "value_038": "Coding first-B Source configuration is missing",
    "value_039": "Coding first-B Installation set is unsupported",
    "value_040": "Coding first-B local Skill snapshot is unsupported",
    "value_041": "Coding first-B Desired history is missing",
}


_LEGACY_CHAIN_VALUES = {
    "value_001": "skill",
    "value_002": "prompt",
    "value_003": "theme",
    "value_004": "Unsupported legacy Resource type",
    "value_005": "Legacy data Resource type changed",
}


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalDataWheelInspectionV1:
    resource_kind: Literal["skill", "prompt", "theme"]
    canonical_name: str


def admit_coding_single_legacy_skill_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    prepared: CodingPreBSnapshotPreparation,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"] = "skill",
) -> None:
    """Verify the whole old data Resource set while cutover holds quiescence.

    The function name predates multi-Skill admission; ``plugin_id`` must name
    one member of the verified set before its review command continues.
    """

    return _programs.admit_local_snapshot(
        lifecycle, prepared, snapshot, plugin_id=plugin_id, resource_kind=resource_kind
    )


def require_coding_fenced_single_legacy_skill_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
) -> None:
    """Check frozen old inputs without depending on the original live Source."""

    return _programs.require_fenced_local_snapshot(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )


def require_coding_fenced_single_legacy_skill(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
) -> None:
    """Also reacquire the exact live Skill before first public acceptance."""

    require_coding_fenced_single_legacy_data(
        lifecycle,
        epoch_runtime,
        plugin_id=plugin_id,
        resource_kind="skill",
    )


def require_coding_fenced_single_legacy_data(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
    """Reacquire exact live bytes and enforce the operator's selected type."""

    return _programs.require_data_kind(
        lifecycle, epoch_runtime, plugin_id=plugin_id, resource_kind=resource_kind
    )


def inspect_coding_legacy_local_data_wheel(
    wheel: CodingLegacyLocalWheelCandidateV1,
) -> CodingLegacyLocalDataWheelInspectionV1:
    """Inspect inert reacquired bytes; Product migration still needs its own gate."""
    if not isinstance(wheel, CodingLegacyLocalWheelCandidateV1):
        raise ValueError("Legacy data Wheel digest is invalid")
    return CodingLegacyLocalDataWheelInspectionV1(
        *_inspect_legacy_local_data_wheel(wheel)
    )


__all__ = [
    "CodingLegacyLocalDataWheelInspectionV1",
    "admit_coding_single_legacy_skill_snapshot",
    "require_coding_fenced_single_legacy_skill",
    "require_coding_fenced_single_legacy_data",
    "require_coding_fenced_single_legacy_skill_snapshot",
    "inspect_coding_legacy_local_data_wheel",
]

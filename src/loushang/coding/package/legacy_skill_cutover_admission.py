"""Pre-fence admission for old local Skills under the frozen B snapshot."""

from __future__ import annotations

import zipfile as zipfile
from dataclasses import dataclass
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_data_admission import (
    LegacyDataAdmissionEvidence,
    LegacyDataSnapshotAdmission,
    verify_legacy_data_wheels,
)
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

from .legacy_configured_source import _index_configured_sources
from .legacy_desired_evidence import (
    parse_coding_legacy_desired_evidence as parse_coding_legacy_desired_evidence,
)
from .legacy_desired_evidence import (
    read_coding_legacy_desired_evidence as read_coding_legacy_desired_evidence,
)
from .legacy_installation_inventory import (
    _BUILTINS,
    _MAX_REMOVAL_BINDINGS,
    _legacy_inventory_reader,
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
    _new_wheel_candidate,
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
from .legacy_snapshot_member import _snapshot_reader
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_snapshot_member import (
    read_coding_first_b_snapshot_member as read_coding_first_b_snapshot_member,
)
from .pre_b_snapshot import CodingPreBSnapshotPreparation
from .source_snapshot import _PROJECTION_NAME

# Each member is reacquired and rebuilt while the first-fence lock is held.
_MAX_LOCAL_DATA_PLUGINS = 16
_REMOVABLE_BUILTIN_PLUGIN_IDS = _BUILTINS


_RESOURCE_REFUSAL_CODES = {
    "skill": "coding_legacy_skill_snapshot_refused",
    "prompt": "coding_legacy_prompt_snapshot_refused",
    "theme": "coding_legacy_theme_snapshot_refused",
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

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding lifecycle layout is required")
    if not isinstance(prepared, CodingPreBSnapshotPreparation):
        raise TypeError("Coding pre-B snapshot preparation is required")
    if not isinstance(snapshot, PackageEpochCutoverSnapshotReceiptV1):
        raise TypeError("Package snapshot receipt is required")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError("Coding legacy Plugin identity is required")
    if resource_kind not in _RESOURCE_REFUSAL_CODES:
        raise ValueError("Unsupported legacy Resource type")
    try:
        evidence = _data_snapshot_admission(lifecycle).before_fence(
            prepared.owner,
            snapshot,
            has_legacy_state=prepared.legacy_classification.kind == "legacy_state",
        )
        identities = _adoptable_source_identities(
            evidence, plugin_id, "Legacy data Installation set is unsupported"
        )
        if not identities[0].startswith("local:/"):
            raise ValueError("Legacy Skill Source is not local")
        _index_configured_sources(evidence.source_projection, identities)
        verify_legacy_data_wheels(
            evidence,
            legacy_package_root=lifecycle.package_root,
            plugin_id=plugin_id,
            required_kind=resource_kind,
            result_factory=_new_wheel_candidate,
        )
    except PackagePosixEpochCutoverError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        raise PackagePosixEpochCutoverError(
            "Coding legacy data snapshot cannot be admitted before first fence",
            code=_RESOURCE_REFUSAL_CODES[resource_kind],
        ) from exc


def require_coding_fenced_single_legacy_skill_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
) -> None:
    """Check frozen old inputs without depending on the original live Source."""

    reader = _snapshot_reader(lifecycle, epoch_runtime)
    evidence = _data_snapshot_admission(lifecycle).after_fence(reader)
    identities = _adoptable_source_identities(
        evidence, plugin_id, "Coding first-B Installation set is unsupported"
    )
    _index_configured_sources(evidence.source_projection, identities)
    epoch_runtime.assert_current()


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

    if resource_kind not in _RESOURCE_REFUSAL_CODES:
        raise ValueError("Unsupported legacy Resource type")
    require_coding_fenced_single_legacy_skill_snapshot(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    reacquired = reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    inspected = inspect_coding_legacy_local_data_wheel(reacquired.wheel)
    if inspected.resource_kind != resource_kind:
        raise ValueError("Legacy data Resource type changed")
    epoch_runtime.assert_current()


def _data_snapshot_admission(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> LegacyDataSnapshotAdmission:
    return LegacyDataSnapshotAdmission(
        source_member=_PROJECTION_NAME,
        inventory_reader=_legacy_inventory_reader(lifecycle),
        maximum_bindings=_MAX_REMOVAL_BINDINGS,
    )


def _adoptable_source_identities(
    evidence: LegacyDataAdmissionEvidence, plugin_id: str, message: str
) -> tuple[str, ...]:
    inventory = evidence.inventory
    if (
        not 0 < len(inventory.active_local) <= _MAX_LOCAL_DATA_PLUGINS
        or plugin_id
        not in {binding.plugin_id for binding, _, _ in inventory.active_local}
        or any(
            item not in _REMOVABLE_BUILTIN_PLUGIN_IDS | evidence.removed_local_ids
            for item in inventory.removed_plugin_ids
        )
    ):
        raise ValueError(message)
    return tuple(binding.source_identity for binding, _, _ in inventory.active_local)


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

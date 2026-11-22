"""Reacquire one installed legacy Source selected by the first-B snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_inventory import (
    reacquire_legacy_bound_wheel,
    reacquire_legacy_inventory_source,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .legacy_installation_inventory import (
    CodingLegacyInstallationInventoryEvidenceV1,
    CodingLegacyLocalInstallationV1,
    _legacy_inventory_query,
    _project_inventory_evidence,
)
from .legacy_installation_inventory import (
    CodingLegacyInventoryError as CodingLegacyInventoryError,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_local_wheel import (
    CodingLegacyLocalWheelCandidateV1,
    _new_wheel_candidate,
)
from .legacy_local_wheel import (
    reacquire_coding_legacy_local_plugin_wheel as reacquire_coding_legacy_local_plugin_wheel,
)


@dataclass(frozen=True, slots=True)
class CodingLegacyReacquiredInstallationV1:
    """Inert review payload; this is not approval or a Product publication."""

    inventory_evidence: CodingLegacyInstallationInventoryEvidenceV1
    installation: CodingLegacyLocalInstallationV1
    wheel: CodingLegacyLocalWheelCandidateV1


def reacquire_coding_legacy_installed_local_source(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
) -> CodingLegacyReacquiredInstallationV1:
    """Fetch the live original Source for one exact installed old revision.

    The old Store snapshot corroborates selection but never supplies bytes for
    the Wheel. An operator approval and Product transaction remain separate.
    """

    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError("Coding legacy Plugin identity is required")
    evidence, position, wheel = reacquire_legacy_inventory_source(
        _legacy_inventory_query(lifecycle, epoch_runtime),
        epoch_runtime,
        legacy_package_root=lifecycle.package_root,
        plugin_id=plugin_id,
        staging_prefix="loushang-legacy-review-",
        error_type=CodingLegacyInventoryError,
        label="Coding",
        result_factory=_new_wheel_candidate,
    )
    inventory = _project_inventory_evidence(evidence)
    return CodingLegacyReacquiredInstallationV1(
        inventory, inventory.inventory.active_local[position], wheel
    )


def _reacquire_bound_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    installation: CodingLegacyLocalInstallationV1,
    *,
    staging_prefix: str,
) -> CodingLegacyLocalWheelCandidateV1:
    return reacquire_legacy_bound_wheel(
        installation.binding,
        legacy_package_root=lifecycle.package_root,
        staging_prefix=staging_prefix,
        result_factory=_new_wheel_candidate,
    )


__all__ = [
    "CodingLegacyReacquiredInstallationV1",
    "reacquire_coding_legacy_installed_local_source",
]

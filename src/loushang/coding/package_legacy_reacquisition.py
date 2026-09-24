"""Reacquire one installed legacy Source selected by the first-B snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_installation_inventory import (
    CodingLegacyInstallationInventoryEvidenceV1,
    CodingLegacyInventoryError,
    CodingLegacyLocalInstallationV1,
    read_coding_legacy_installation_inventory,
)
from .package_legacy_local_wheel import (
    CodingLegacyLocalWheelCandidateV1,
    reacquire_coding_legacy_local_plugin_wheel,
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
    inventory = read_coding_legacy_installation_inventory(lifecycle, epoch_runtime)
    installation = next(
        (
            item
            for item in inventory.inventory.active_local
            if item.binding.plugin_id == plugin_id
        ),
        None,
    )
    if installation is None:
        raise CodingLegacyInventoryError(
            "Coding legacy Plugin is not an installed local candidate"
        )
    binding = installation.binding
    if not binding.source_identity.startswith("local:/"):
        raise CodingLegacyInventoryError("Coding legacy local Source changed")
    wheel = reacquire_coding_legacy_local_plugin_wheel(
        Path(binding.source_identity.removeprefix("local:")),
        legacy_package_root=lifecycle.package_root,
        staging_parent=epoch_runtime.prepare_product_source_root(),
        plugin_id=binding.plugin_id,
        expected_source_identity=binding.source_identity,
        expected_content_digest=binding.content_digest,
        expected_manifest_digest=binding.manifest_digest,
        expected_dependency_lock=binding.dependency_lock,
    )
    if read_coding_legacy_installation_inventory(lifecycle, epoch_runtime) != inventory:
        raise CodingLegacyInventoryError(
            "Coding legacy Installation snapshot changed during Source reacquisition"
        )
    epoch_runtime.assert_current()
    return CodingLegacyReacquiredInstallationV1(inventory, installation, wheel)


__all__ = [
    "CodingLegacyReacquiredInstallationV1",
    "reacquire_coding_legacy_installed_local_source",
]

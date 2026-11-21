"""Reacquire one installed legacy Source selected by the first-B snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path as Path
from tempfile import TemporaryDirectory as TemporaryDirectory

from loushang.coding.harness.package_product import legacy_reacquisition as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .legacy_installation_inventory import (
    CodingLegacyInstallationInventoryEvidenceV1,
    CodingLegacyLocalInstallationV1,
)
from .legacy_installation_inventory import (
    CodingLegacyInventoryError as CodingLegacyInventoryError,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_local_wheel import (
    CodingLegacyLocalWheelCandidateV1,
)
from .legacy_local_wheel import (
    reacquire_coding_legacy_local_plugin_wheel as reacquire_coding_legacy_local_plugin_wheel,
)

_LEGACY_ADOPTION_VALUES = {
    "value_001": "Coding legacy Plugin identity is required",
    "value_002": "Coding legacy Plugin is not an installed local candidate",
    "value_003": "Coding legacy local Source changed",
    "value_004": "Coding legacy Installation snapshot changed during Source reacquisition",
}


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

    return _programs.reacquire_installed_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )


__all__ = [
    "CodingLegacyReacquiredInstallationV1",
    "reacquire_coding_legacy_installed_local_source",
]

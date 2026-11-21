"""Match the selected fenced runtime to its declared epoch layout."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loushang.coding.package.epoch_layout import CodingPackageEpochLayoutV1
    from loushang.harness.resources.packages.product_epoch_guard import (
        PackageProductPosixFencedRuntimeOwner,
    )
    from loushang.harness.resources.packages.product_windows_epoch_guard import (
        PackageProductWindowsFencedRuntimeOwner,
    )


def matches_epoch_layout(
    runtime: PackageProductPosixFencedRuntimeOwner
    | PackageProductWindowsFencedRuntimeOwner,
    epoch: CodingPackageEpochLayoutV1,
) -> bool:
    return not (
        runtime.registry.store_id != epoch.store_id
        or runtime.control_root != epoch.control_root
    )

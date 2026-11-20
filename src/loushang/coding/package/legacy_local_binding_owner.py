"""Product-only Source binding for one accepted old local Installation."""

from __future__ import annotations

from loushang.coding.harness.package_product import legacy_binding as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_binding_catalog import (
    CodingLegacyBindingError as CodingLegacyBindingError,
)
from .legacy_binding_catalog import (
    CodingLegacyLocalBindingCatalog as CodingLegacyLocalBindingCatalog,
)
from .legacy_binding_catalog import (
    CodingLegacyLocalBindingV1,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_reacquisition import (
    reacquire_coding_legacy_installed_local_source as reacquire_coding_legacy_installed_local_source,
)
from .legacy_skill_cutover_admission import (
    inspect_coding_legacy_local_data_wheel as inspect_coding_legacy_local_data_wheel,
)

_LEGACY_ADOPTION_VALUES = {
    "value_001": "Legacy local Source has no accepted review",
    "value_002": "Legacy local Source differs from accepted review",
    "value_003": "Legacy local Source Product authority changed",
    "value_004": "legacy-local-bindings.jsonl",
    "value_005": "Legacy local Source Resource type is unsupported",
}


def bind_coding_accepted_legacy_local_source(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalBindingV1:
    """Bind only exact accepted bytes; do not install or enable the Plugin."""

    return _programs.bind_accepted_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )


__all__ = ["bind_coding_accepted_legacy_local_source"]

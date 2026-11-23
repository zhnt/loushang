"""Product-only Source binding for one accepted old local Installation."""

from __future__ import annotations

from functools import partial

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_binding_catalog import (
    _BINDINGS_JOURNAL as _BINDINGS_JOURNAL,
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


def bind_coding_accepted_legacy_local_source(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalBindingV1:
    """Bind only exact accepted bytes; do not install or enable the Plugin."""

    accepted = reopen_coding_legacy_installed_local_acceptance(
        lifecycle,
        epoch_runtime,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
    )
    if accepted is None:
        raise CodingLegacyBindingError("Legacy local Source has no accepted review")
    reacquired = reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    selected = reacquired.installation
    binding = selected.binding
    candidate = reacquired.wheel
    try:
        inspected = inspect_coding_legacy_local_data_wheel(candidate)
    except (OSError, ValueError) as exc:
        raise CodingLegacyBindingError(
            "Legacy local Source Resource type is unsupported"
        ) from exc
    return CodingLegacyLocalBindingCatalog.publish_from_accepted_review(
        candidate,
        accepted=accepted,
        binding=binding,
        desired_state=selected.desired_state,
        inspected_kind=inspected.resource_kind,
        epoch_runtime=epoch_runtime,
        resolve_epoch=partial(resolve_coding_package_epoch_layout, lifecycle),
        scope_id=lifecycle.scope_id,
        policy_revision=policy_revision,
        acceptance_reader=lambda selected_plugin: (
            reopen_coding_legacy_installed_local_acceptance(
                lifecycle,
                epoch_runtime,
                plugin_id=selected_plugin,
                policy_revision=policy_revision,
            )
        ),
    )


__all__ = ["bind_coding_accepted_legacy_local_source"]

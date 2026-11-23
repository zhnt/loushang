"""Product-only Source binding for one accepted old local Installation."""

from __future__ import annotations

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_local_migration import (
    verify_accepted_legacy_wheel,
)
from loushang.harness.package_product._legacy_runtime import matches_epoch_layout
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

_BINDINGS_JOURNAL = "legacy-local-bindings.jsonl"


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
    review = accepted.review
    selected = reacquired.installation
    binding = selected.binding
    candidate = reacquired.wheel
    try:
        inspected = inspect_coding_legacy_local_data_wheel(candidate)
    except (OSError, ValueError) as exc:
        raise CodingLegacyBindingError(
            "Legacy local Source Resource type is unsupported"
        ) from exc
    verify_accepted_legacy_wheel(
        accepted,
        binding,
        candidate,
        desired_state=selected.desired_state,
        inspected_kind=inspected.resource_kind,
        error_type=CodingLegacyBindingError,
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    switch = epoch_runtime.cutover_result.switch_receipt
    if (
        switch is None
        or not matches_epoch_layout(epoch_runtime, epoch)
        or switch.namespace_id != review.namespace_id
        or lifecycle.scope_id != review.scope_id
        or policy_revision != review.policy_revision
    ):
        raise CodingLegacyBindingError("Legacy local Source Product authority changed")
    epoch_runtime.assert_current()
    source_root = epoch_runtime.prepare_product_source_root()
    state_root = epoch_runtime.prepare_product_state_root()
    catalog = CodingLegacyLocalBindingCatalog(
        state_root / _BINDINGS_JOURNAL,
        source_root=source_root,
        store_id=epoch.store_id,
        namespace_id=switch.namespace_id,
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
    return catalog.publish_accepted_candidate(
        candidate,
        epoch_runtime=epoch_runtime,
        legacy_source_identity=review.legacy_source_identity,
        legacy_binding_digest=review.legacy_binding_digest,
        dependency_lock_digest=review.dependency_lock_digest,
        approval_id=accepted.acceptance_id,
        resource_kind=accepted.resource_kind,
    )


__all__ = ["bind_coding_accepted_legacy_local_source"]

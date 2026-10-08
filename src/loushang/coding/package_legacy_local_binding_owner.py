"""Product-only Source binding for one accepted old local Installation."""

from __future__ import annotations

from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_binding_catalog import (
    CodingLegacyBindingError,
    CodingLegacyLocalBindingCatalog,
    CodingLegacyLocalBindingV1,
)
from .package_legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance,
)
from .package_legacy_reacquisition import (
    reacquire_coding_legacy_installed_local_source,
)
from .package_legacy_skill_cutover_admission import (
    inspect_coding_legacy_local_data_wheel,
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
    if (
        inspected.resource_kind != accepted.resource_kind
        or selected.desired_state != review.desired_state
        or binding.plugin_id != review.plugin_id
        or binding.source_identity != review.legacy_source_identity
        or binding.binding_digest != review.legacy_binding_digest
        or binding.content_digest != review.source_content_digest
        or binding.manifest_digest != review.manifest_digest
        or binding.dependency_lock.digest != review.dependency_lock_digest
        or candidate.plugin_id != review.plugin_id
        or candidate.original_source_identity != review.legacy_source_identity
        or candidate.source_content_digest != review.source_content_digest
        or candidate.manifest_digest != review.manifest_digest
        or candidate.filename != review.wheel_filename
        or candidate.artifact_digest != review.wheel_artifact_digest
    ):
        raise CodingLegacyBindingError(
            "Legacy local Source differs from accepted review"
        )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    switch = epoch_runtime.cutover_result.switch_receipt
    if (
        switch is None
        or epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
        or switch.namespace_id != review.namespace_id
        or lifecycle.scope_id != review.scope_id
        or policy_revision != review.policy_revision
    ):
        raise CodingLegacyBindingError("Legacy local Source Product authority changed")
    epoch_runtime.assert_current()
    source_root = epoch_runtime.prepare_product_source_root()
    state_root = epoch_runtime.prepare_product_state_root()
    catalog = CodingLegacyLocalBindingCatalog(
        state_root / "legacy-local-bindings.jsonl",
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
    catalog.publish_candidate(candidate, epoch_runtime=epoch_runtime)
    committed = catalog.append(
        candidate,
        legacy_source_identity=review.legacy_source_identity,
        legacy_binding_digest=review.legacy_binding_digest,
        dependency_lock_digest=review.dependency_lock_digest,
        approval_id=accepted.acceptance_id,
        resource_kind=accepted.resource_kind,
    )
    catalog._require_accepted_binding(committed)
    epoch_runtime.assert_current()
    return committed


__all__ = ["bind_coding_accepted_legacy_local_source"]

"""Read-only proof that an explicitly accepted old Skill finished Product adoption."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_local_migration import (
    read_settled_legacy_local_adoption,
    require_legacy_local_resource_kind,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner as PackageProductPosixFencedRuntimeOwner,
)

from ..control.settings_store import open_coding_workspace_settings
from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_data_trust import (
    trust_class_for_legacy_data_resource as trust_class_for_legacy_data_resource,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_local_installation import _INSTALL_POLICY
from .legacy_review import _reviewed_local_builtin_choices
from .legacy_skill_cutover_admission import (
    require_coding_fenced_single_legacy_skill_snapshot as require_coding_fenced_single_legacy_skill_snapshot,
)
from .legacy_source_consumption import (
    coding_accepted_legacy_local_source_consumed as coding_accepted_legacy_local_source_consumed,
)
from .product_preview import (
    CodingFencedProductReadOnlyPreviewOwner as CodingFencedProductReadOnlyPreviewOwner,
)
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY as _CODING_BUILTIN_BOOTSTRAP_POLICY,
)
from .product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION as CODING_PACKAGE_PRODUCT_POLICY_REVISION,
)


def coding_legacy_local_skill_adoption_settled(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
    workspace: Path,
) -> bool:
    """Join frozen acceptance to Product handoffs and Desired history only.

    A later operator disable or remove does not erase a completed adoption.
    Missing or partial evidence returns false; corrupt evidence raises.
    """

    return coding_legacy_local_data_adoption_settled(
        lifecycle, plugin_id=plugin_id, workspace=workspace, resource_kind="skill"
    )


def coding_legacy_local_data_adoption_settled(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
    workspace: Path,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> bool:
    """Check one typed old local adoption without mutating Product state."""

    require_legacy_local_resource_kind(resource_kind)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    runtime = PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs(), read_only=True
    )
    try:
        require_coding_fenced_single_legacy_skill_snapshot(
            lifecycle, runtime, plugin_id=plugin_id
        )
        accepted = reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            runtime,
            plugin_id=plugin_id,
            policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        )
        source_consumed = (
            False
            if accepted is None or accepted.resource_kind != resource_kind
            else coding_accepted_legacy_local_source_consumed(
                lifecycle,
                runtime,
                accepted,
                open_coding_workspace_settings(workspace),
            )
        )
    finally:
        runtime.close()
    if accepted is None or not source_consumed:
        return False

    with CodingFencedProductReadOnlyPreviewOwner.open(lifecycle) as preview:
        return read_settled_legacy_local_adoption(
            accepted,
            desired=preview.selected_manifests.root_reader.desired_state,
            epoch_runtime=preview.epoch_runtime,
            bindings=preview.policy.bindings,
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
            source_trust_class=trust_class_for_legacy_data_resource(resource_kind),
            install_policy=_INSTALL_POLICY,
            choices=_reviewed_local_builtin_choices(accepted.review),
            bootstrap_policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            handoff_error="Coding legacy adoption handoff changed",
        )


__all__ = [
    "coding_legacy_local_data_adoption_settled",
    "coding_legacy_local_skill_adoption_settled",
]

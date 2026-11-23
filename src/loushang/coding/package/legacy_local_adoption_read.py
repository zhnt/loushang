"""Read-only proof that an explicitly accepted old Skill finished Product adoption."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager as SettingsManager
from loushang.harness.package_product._legacy_local_migration import (
    _LegacyAdoptionSelection as _LegacyAdoptionSelection,
)
from loushang.harness.package_product._legacy_local_migration import (
    match_legacy_replay_source,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal as PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner as PackageProductPosixFencedRuntimeOwner,
)

from ..control.settings_store import (
    default_global_settings_path as default_global_settings_path,
)
from ..control.settings_store import (
    default_project_settings_path as default_project_settings_path,
)
from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_data_trust import (
    trust_class_for_legacy_data_resource as trust_class_for_legacy_data_resource,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_local_installation import _enable_operation_id as _enable_operation_id
from .legacy_local_installation import _install_operation_id as _install_operation_id
from .legacy_review import _reviewed_disabled_ids
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

_BUILTINS = ("coding.base", "coding.lsp.default", "coding.arch.default")


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

    if resource_kind not in {
        "skill",
        "prompt",
        "theme",
    }:
        raise ValueError("Unsupported legacy Resource type")

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
                SettingsManager(
                    global_settings_path=default_global_settings_path(),
                    project_settings_path=default_project_settings_path(workspace),
                ),
            )
        )
    finally:
        runtime.close()
    if accepted is None or not source_consumed:
        return False

    with CodingFencedProductReadOnlyPreviewOwner.open(lifecycle) as preview:
        trust_class = trust_class_for_legacy_data_resource(resource_kind)
        matches, bound = match_legacy_replay_source(
            preview.policy.bindings,
            accepted,
            plugin_id=plugin_id,
            trust_classes=(trust_class,),
            expected_trust=trust_class,
        )
        if not matches or bound is None:
            return False
        handoffs = PackageRetentionHandoffJournal(
            epoch.control_root / "product-state" / "handoff.jsonl"
        )
        desired = preview.selected_manifests.root_reader.desired_state
        disabled_builtins = _reviewed_disabled_ids(accepted.review)
        selection = _LegacyAdoptionSelection(
            key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=plugin_id,
            ),
            source_identity=bound.source_identity,
            install_operation_id=_install_operation_id(
                accepted.review.store_id, accepted.acceptance_id
            ),
            enable_operation_id=(
                _enable_operation_id(accepted.review.store_id, accepted.acceptance_id)
                if accepted.review.desired_state == "installed_enabled"
                else None
            ),
            builtin_ids=_BUILTINS,
            disabled_builtin_ids=frozenset(disabled_builtins),
            removed_builtin_operations={
                name: accepted.review.removed_builtin_operation_id(name)
                for name in _BUILTINS
                if name in accepted.review.removed_builtin_ids
            },
        )
        return selection.settled(
            desired,
            preview.epoch_runtime,
            handoffs,
            preview.policy.bindings,
            store_id=epoch.store_id,
            bootstrap_policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            handoff_error="Coding legacy adoption handoff changed",
        )


__all__ = [
    "coding_legacy_local_data_adoption_settled",
    "coding_legacy_local_skill_adoption_settled",
]

"""Explicit Product orchestration for one reviewed old local Skill."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager as SettingsManager
from loushang.harness.package_product._application_runtime import (
    hold_accepted_product_adoption,
)
from loushang.harness.package_product._legacy_local_migration import (
    match_legacy_replay_source,
)
from loushang.harness.package_product._plugin_bootstrap import (
    replay_reviewed_product_plugins,
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
    LEGACY_LOCAL_DATA_TRUST_CLASSES as LEGACY_LOCAL_DATA_TRUST_CLASSES,
)
from .legacy_data_trust import (
    trust_class_for_legacy_data_resource as trust_class_for_legacy_data_resource,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
)
from .legacy_local_acceptance import (
    accept_coding_legacy_installed_local_review as accept_coding_legacy_installed_local_review,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_local_binding_owner import (
    bind_coding_accepted_legacy_local_source as bind_coding_accepted_legacy_local_source,
)
from .legacy_local_installation import (
    CodingLegacyLocalEnablementReceiptV1,
    CodingLegacyLocalInstallReceiptV1,
)
from .legacy_local_installation import (
    enable_coding_accepted_legacy_local_data_plugin as enable_coding_accepted_legacy_local_data_plugin,
)
from .legacy_local_installation import (
    install_coding_accepted_legacy_local_plugin as install_coding_accepted_legacy_local_plugin,
)
from .legacy_removed_acceptance import (
    read_coding_first_b_removed_local_acceptance as read_coding_first_b_removed_local_acceptance,
)
from .legacy_removed_adoption import (
    adopt_coding_first_b_removed_local as adopt_coding_first_b_removed_local,
)
from .legacy_review import _reviewed_disabled_ids
from .legacy_skill_cutover_admission import (
    require_coding_fenced_single_legacy_data as require_coding_fenced_single_legacy_data,
)
from .legacy_skill_cutover_admission import (
    require_coding_fenced_single_legacy_skill_snapshot as require_coding_fenced_single_legacy_skill_snapshot,
)
from .legacy_source_consumption import (
    consume_coding_accepted_legacy_local_source as consume_coding_accepted_legacy_local_source,
)
from .product_runtime import (
    _CODING_BUILTIN_BOOTSTRAP_POLICY as _CODING_BUILTIN_BOOTSTRAP_POLICY,
)
from .product_runtime import (
    _CODING_BUILTIN_PLUGIN_IDS,
)
from .product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION as CODING_PACKAGE_PRODUCT_POLICY_REVISION,
)
from .product_runtime import (
    open_coding_fenced_product_application_owner as open_coding_fenced_product_application_owner,
)

_REMOVAL_LABEL = "Coding removed builtin Product"


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalSkillAdoptionV1:
    acceptance: CodingLegacyLocalAcceptanceV1
    installation: CodingLegacyLocalInstallReceiptV1
    enablement: CodingLegacyLocalEnablementReceiptV1 | None


CodingLegacyLocalDataAdoptionV1 = CodingLegacyLocalSkillAdoptionV1


def adopt_coding_legacy_local_skill_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_id: str,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingLegacyLocalSkillAdoptionV1:
    """Accept exact old evidence, install one Skill, then seed checked-in base.

    Each transition is independently replayable. An already accepted review
    can finish after its original Source disappears if its Wheel was bound.
    """

    return adopt_coding_legacy_local_data_review(
        lifecycle,
        workspace=workspace,
        plugin_id=plugin_id,
        accepted_review_id=accepted_review_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        resource_kind="skill",
    )


def adopt_coding_legacy_local_data_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_id: str,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> CodingLegacyLocalDataAdoptionV1:
    """Finish one type-selected, reviewed local data Resource adoption."""

    if resource_kind not in {
        "skill",
        "prompt",
        "theme",
    }:
        raise ValueError("Unsupported legacy Resource type")

    _settle_removed_before_adoption(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    open_application = partial(
        open_coding_fenced_product_application_owner,
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )

    def accept_and_consume(
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> tuple[CodingLegacyLocalAcceptanceV1, bool]:
        admission_checked = False
        acceptance = reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            epoch_runtime,
            plugin_id=plugin_id,
            policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        )
        if acceptance is None:
            require_coding_fenced_single_legacy_data(
                lifecycle,
                epoch_runtime,
                plugin_id=plugin_id,
                resource_kind=resource_kind,
            )
            admission_checked = True
            acceptance = accept_coding_legacy_installed_local_review(
                lifecycle,
                epoch_runtime,
                plugin_id=plugin_id,
                policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
                accepted_review_id=accepted_review_id,
                resource_kind=resource_kind,
            )
        elif acceptance.review.review_id != accepted_review_id:
            raise ValueError("Coding legacy local review ID changed")
        else:
            require_coding_fenced_single_legacy_skill_snapshot(
                lifecycle, epoch_runtime, plugin_id=plugin_id
            )
        if acceptance.resource_kind != resource_kind:
            raise ValueError(
                "Coding legacy data adoption requires a matching Resource receipt"
            )
        consume_coding_accepted_legacy_local_source(
            lifecycle,
            epoch_runtime,
            acceptance,
            SettingsManager(
                global_settings_path=default_global_settings_path(),
                project_settings_path=default_project_settings_path(workspace),
            ),
        )
        return acceptance, admission_checked

    open_epoch = partial(
        PackageProductPosixFencedRuntimeOwner.open,
        **epoch.fenced_runtime_open_kwargs(),
    )
    with hold_accepted_product_adoption(
        open_epoch=open_epoch,
        accept_review=accept_and_consume,
        open_application=open_application,
    ) as ((acceptance, admission_checked), product_owner):
        matches, bound = match_legacy_replay_source(
            product_owner.runtime_owner.product_owner.policy.bindings,
            acceptance,
            plugin_id=plugin_id,
            trust_classes=LEGACY_LOCAL_DATA_TRUST_CLASSES,
            expected_trust=trust_class_for_legacy_data_resource(resource_kind),
        )
        if not matches:
            raise RuntimeError("Coding legacy local Product Source binding changed")
    if bound is None:
        with closing(open_epoch()) as epoch_runtime:
            if not admission_checked:
                require_coding_fenced_single_legacy_data(
                    lifecycle,
                    epoch_runtime,
                    plugin_id=plugin_id,
                    resource_kind=resource_kind,
                )
            bind_coding_accepted_legacy_local_source(
                lifecycle,
                epoch_runtime,
                plugin_id=plugin_id,
                policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
            )

    installation = install_coding_accepted_legacy_local_plugin(
        lifecycle,
        workspace=workspace,
        plugin_id=plugin_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    enablement = (
        enable_coding_accepted_legacy_local_data_plugin(
            lifecycle,
            workspace=workspace,
            plugin_id=plugin_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            resource_kind=resource_kind,
        )
        if acceptance.review.desired_state == "installed_enabled"
        else None
    )
    with closing(open_application()) as product_owner:
        disabled_builtins = _reviewed_disabled_ids(acceptance.review)
        product = product_owner.runtime_owner.product_owner
        replay_reviewed_product_plugins(
            product,
            _CODING_BUILTIN_PLUGIN_IDS,
            disabled_ids=disabled_builtins,
            removed_ids=acceptance.review.removed_builtin_ids,
            operation_id_for=acceptance.review.removed_builtin_operation_id,
            removal_label=_REMOVAL_LABEL,
            policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            strict_history=False,
        )
    return CodingLegacyLocalSkillAdoptionV1(
        acceptance=acceptance,
        installation=installation,
        enablement=enablement,
    )


def _settle_removed_before_adoption(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> None:
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    owner = PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs(), read_only=True
    )
    settings = SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(workspace),
    )
    try:
        inventory = read_coding_legacy_installation_inventory(
            lifecycle, owner
        ).inventory
        if not inventory.unselected_source_identities:
            return
        accepted = read_coding_first_b_removed_local_acceptance(
            lifecycle, owner, settings_manager=settings
        )
        if accepted is None:
            raise ValueError(
                "Coding old local removals need explicit adoption before active locals"
            )
    finally:
        owner.close()
    adopt_coding_first_b_removed_local(
        lifecycle,
        settings,
        workspace=workspace,
        accepted_review_id=accepted.review.review_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )


__all__ = [
    "CodingLegacyLocalDataAdoptionV1",
    "CodingLegacyLocalSkillAdoptionV1",
    "adopt_coding_legacy_local_data_review",
    "adopt_coding_legacy_local_skill_review",
]

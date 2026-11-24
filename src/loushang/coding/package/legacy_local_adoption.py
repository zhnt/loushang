"""Explicit Product orchestration for one reviewed old local Skill."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager as SettingsManager
from loushang.harness.package_product._legacy_local_migration import (
    adopt_legacy_local_data,
    replay_posix_legacy_product_cutover,
)
from loushang.harness.package_product._legacy_runtime import FencedRuntimeOpenKwargs
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner as PackageProductPosixFencedRuntimeOwner,
)

from ..control.settings_store import open_coding_workspace_settings
from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .legacy_builtin_acceptance import read_coding_first_b_builtin_only_acceptance
from .legacy_builtin_adoption import adopt_coding_first_b_builtin_only
from .legacy_data_trust import (
    LEGACY_LOCAL_DATA_TRUST_CLASSES as LEGACY_LOCAL_DATA_TRUST_CLASSES,
)
from .legacy_data_trust import (
    trust_class_for_legacy_data_resource as trust_class_for_legacy_data_resource,
)
from .legacy_disabled_acceptance import read_coding_first_b_disabled_only_acceptance
from .legacy_installation_inventory import _legacy_inventory_query
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
from .legacy_local_adoption_read import coding_legacy_local_data_adoption_settled
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
from .legacy_review import _reviewed_local_builtin_choices
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
    CODING_PACKAGE_PRODUCT_POLICY_REVISION as CODING_PACKAGE_PRODUCT_POLICY_REVISION,
)
from .product_runtime import (
    bootstrap_coding_accepted_disabled_only_product_plugins,
    bootstrap_coding_builtin_product_plugins,
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

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    replay_coding_posix_legacy_product_cutover(
        lifecycle,
        partial(open_coding_workspace_settings, workspace),
        roots=epoch.fenced_runtime_open_kwargs(),
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        before_local_adoption=True,
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
            open_coding_workspace_settings(workspace),
        )
        return acceptance, admission_checked

    def bind_source(
        epoch_runtime: PackageProductPosixFencedRuntimeOwner, admission_checked: bool
    ) -> None:
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

    acceptance, installation, enablement = adopt_legacy_local_data(
        open_epoch=partial(
            PackageProductPosixFencedRuntimeOwner.open,
            **epoch.fenced_runtime_open_kwargs(),
        ),
        open_application=open_application,
        accept_and_consume=accept_and_consume,
        bind_source=bind_source,
        plugin_id=plugin_id,
        trust_classes=LEGACY_LOCAL_DATA_TRUST_CLASSES,
        expected_trust=partial(trust_class_for_legacy_data_resource, resource_kind),
        changed_message="Coding legacy local Product Source binding changed",
        install=lambda: install_coding_accepted_legacy_local_plugin(
            lifecycle,
            workspace=workspace,
            plugin_id=plugin_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        ),
        enable=lambda: enable_coding_accepted_legacy_local_data_plugin(
            lifecycle,
            workspace=workspace,
            plugin_id=plugin_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            resource_kind=resource_kind,
        ),
        reviewed_choices=lambda accepted: _reviewed_local_builtin_choices(accepted.review),
        bootstrap_policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
        removal_label=_REMOVAL_LABEL,
    )
    return CodingLegacyLocalSkillAdoptionV1(
        acceptance=acceptance,
        installation=installation,
        enablement=enablement,
    )


def replay_coding_posix_legacy_product_cutover(
    lifecycle: CodingPluginLifecycleStateLayout,
    open_settings: Callable[[], SettingsManager],
    *,
    roots: FencedRuntimeOpenKwargs,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    before_local_adoption: bool = False,
) -> None:
    replay_posix_legacy_product_cutover(
        lifecycle,
        open_settings,
        roots=roots,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        inventory_query=_legacy_inventory_query,
        read_local_acceptance=reopen_coding_legacy_installed_local_acceptance,
        local_adoption_settled=coding_legacy_local_data_adoption_settled,
        policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        disabled=(
            read_coding_first_b_disabled_only_acceptance,
            bootstrap_coding_accepted_disabled_only_product_plugins,
        ),
        builtin=(
            read_coding_first_b_builtin_only_acceptance,
            adopt_coding_first_b_builtin_only,
        ),
        removed=(
            read_coding_first_b_removed_local_acceptance,
            adopt_coding_first_b_removed_local,
        ),
        bootstrap=bootstrap_coding_builtin_product_plugins,
        default_local_kind="skill",
        removals_pending=(
            "Coding old local removals need explicit adoption before active locals"
            if before_local_adoption
            else "Coding old local removals need explicit adoption or retry"
        ),
        sources_pending="Coding old local Skills need explicit adoption or retry",
        before_local_adoption=before_local_adoption,
    )


__all__ = [
    "CodingLegacyLocalDataAdoptionV1",
    "CodingLegacyLocalSkillAdoptionV1",
    "adopt_coding_legacy_local_data_review",
    "adopt_coding_legacy_local_skill_review",
]

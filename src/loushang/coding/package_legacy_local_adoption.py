"""Explicit Product orchestration for one reviewed old local Skill."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_data_trust import (
    LEGACY_LOCAL_DATA_TRUST_CLASSES,
    trust_class_for_legacy_data_resource,
)
from .package_legacy_installation_inventory import (
    read_coding_legacy_installation_inventory,
)
from .package_legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
    accept_coding_legacy_installed_local_review,
    reopen_coding_legacy_installed_local_acceptance,
)
from .package_legacy_local_binding_owner import (
    bind_coding_accepted_legacy_local_source,
)
from .package_legacy_local_installation import (
    CodingLegacyLocalEnablementReceiptV1,
    CodingLegacyLocalInstallReceiptV1,
    enable_coding_accepted_legacy_local_data_plugin,
    install_coding_accepted_legacy_local_plugin,
)
from .package_legacy_removed_acceptance import (
    read_coding_first_b_removed_local_acceptance,
)
from .package_legacy_removed_adoption import adopt_coding_first_b_removed_local
from .package_legacy_skill_cutover_admission import (
    require_coding_fenced_single_legacy_data,
    require_coding_fenced_single_legacy_skill_snapshot,
)
from .package_legacy_source_consumption import (
    consume_coding_accepted_legacy_local_source,
)
from .package_product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION,
    CodingFencedProductApplicationOwner,
    _bootstrap_coding_builtin_plugin,
    open_coding_fenced_product_application_owner,
)


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

    if resource_kind not in {"skill", "prompt", "theme"}:
        raise ValueError("Unsupported legacy Resource type")

    _settle_reviewed_removed_local_before_active_adoption(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    admission_checked = False
    try:
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
    finally:
        epoch_runtime.close()

    product_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        bound = tuple(
            item
            for item in product_owner.runtime_owner.product_owner.policy.bindings
            if item.plugin_id == plugin_id
            and item.source_trust_class
            in LEGACY_LOCAL_DATA_TRUST_CLASSES
        )
        expected_trust = trust_class_for_legacy_data_resource(resource_kind)
        if bound and (
            len(bound) != 1
            or bound[0].source_trust_class != expected_trust
            or bound[0].artifact_digest != acceptance.review.wheel_artifact_digest
            or Path(bound[0].source_identity).name != acceptance.review.wheel_filename
        ):
            raise RuntimeError("Coding legacy local Product Source binding changed")
    finally:
        product_owner.close()
    if not bound:
        epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
        )
        try:
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
        finally:
            epoch_runtime.close()

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
    product_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        disabled_builtins = {
            item.plugin_id for item in acceptance.review.disabled_plugins
        }
        disabled_builtins.update(
            item.plugin_id
            for item in acceptance.review.builtin_intent
            if item.desired_state == "installed_disabled"
        )
        product = product_owner.runtime_owner.product_owner
        for builtin_id in acceptance.review.removed_builtin_ids:
            _preserve_removed_builtin(product_owner, acceptance, builtin_id)
        for builtin_id in (
            "coding.base",
            "coding.lsp.default",
            "coding.arch.default",
        ):
            if builtin_id in acceptance.review.removed_builtin_ids:
                continue
            history = tuple(
                item
                for item in product.desired_state.transitions()
                if item.mutation.installation_key.plugin_id == builtin_id
            )
            if (
                history
                and getattr(history[-1].mutation, "actor_id", None) != product.actor_id
            ):
                # A later operator choice owns this builtin's current state.
                continue
            _bootstrap_coding_builtin_plugin(
                product_owner,
                builtin_id,
                enable=builtin_id not in disabled_builtins,
            )
    finally:
        product_owner.close()
    return CodingLegacyLocalSkillAdoptionV1(
        acceptance=acceptance,
        installation=installation,
        enablement=enablement,
    )


def _settle_reviewed_removed_local_before_active_adoption(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> None:
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
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


def _preserve_removed_builtin(
    owner: CodingFencedProductApplicationOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    plugin_id: str,
) -> None:
    """Write one reviewed absent tombstone through Product management."""

    product = owner.runtime_owner.product_owner
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=product.policy.project_scope_id,
        plugin_id=plugin_id,
    )
    operation_id = acceptance.review.removed_builtin_operation_id(plugin_id)
    history = tuple(
        item
        for item in product.desired_state.transitions()
        if item.mutation.installation_key == key
    )
    if history:
        first = history[0]
        if (
            first.mutation.operation_id != operation_id
            or not isinstance(first.mutation, PluginDesiredStateMutationV1)
            or first.mutation.actor_id != product.actor_id
            or first.committed_state.selection.desired_state != "absent"
        ):
            raise RuntimeError("Coding removed builtin Product history changed")
        return
    command = PluginManagementCommandV1(
        action="remove",
        mutation=PluginDesiredStateMutationV1(
            operation_id=operation_id,
            idempotency_key=operation_id,
            expected_inventory_revision=(
                product.desired_state.snapshot().inventory_revision
            ),
            installation_key=key,
            desired_state="absent",
            package_revision=None,
            actor_id=product.actor_id,
            policy_revision=product.desired_policy_revision,
        ),
    )
    result = product.management.submit(command)
    if result.result is None or result.result.disposition != "succeeded":
        raise RuntimeError("Coding removed builtin Product tombstone refused")


__all__ = [
    "CodingLegacyLocalDataAdoptionV1",
    "CodingLegacyLocalSkillAdoptionV1",
    "adopt_coding_legacy_local_data_review",
    "adopt_coding_legacy_local_skill_review",
]

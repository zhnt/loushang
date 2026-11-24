"""Coding-owned preparation of the complete pre-B Package snapshot."""

from __future__ import annotations

import json as json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from loushang.coding.package.epoch_layout import (
    CodingPackageEpochLayoutV1,
    resolve_coding_package_epoch_layout,
)
from loushang.coding.package.epoch_layout import (
    resolve_coding_lifecycle_pre_b_members as resolve_coding_lifecycle_pre_b_members,
)
from loushang.coding.package.epoch_layout import (
    resolve_coding_package_pre_b_store_members as resolve_coding_package_pre_b_store_members,
)
from loushang.coding.package.legacy_classification import (
    CodingLegacyWorkspaceClassificationV1,
)
from loushang.coding.package.legacy_classification import (
    classify_coding_legacy_workspace as classify_coding_legacy_workspace,
)
from loushang.coding.package.product_runtime import (
    _require_current_coding_product_admission,
    bootstrap_coding_builtin_product_plugins,
    require_fresh_coding_product_inputs,
)
from loushang.coding.package.source_snapshot import (
    _PROJECTION_NAME,
    require_coding_fresh_settings_without_writes,
)
from loushang.coding.package.source_snapshot import (
    hold_coding_pre_b_source_configuration as hold_coding_pre_b_source_configuration,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_runtime import (
    bind_legacy_pre_b_snapshot_owner,
    legacy_product_projection_parent,
    prepare_legacy_product_cutover_roots,
    reopen_legacy_product_cutover,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackagePosixEpochCutoverResultV1,
    PackageProductPosixCutoverAttemptV1,
    PackageProductPreBSnapshotOwner,
    hold_legacy_product_projection_root,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackageProductPreBSnapshotSharedMemberV1 as PackageProductPreBSnapshotSharedMemberV1,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    read_legacy_product_projection as read_legacy_product_projection,
)
from loushang.harness.resources.packages.product_windows_pre_b_snapshot import (
    PackageProductWindowsCutoverAttemptV1,
    PackageProductWindowsPreBSnapshotOwner,
)

_FRESH_SETTINGS_PATHS_REQUIRED = "Coding fresh Product settings paths are required"


@dataclass(frozen=True, slots=True)
class CodingPreBSnapshotPreparation:
    """Keep the private Source projection alive until native cutover returns."""

    owner: PackageProductPreBSnapshotOwner | PackageProductWindowsPreBSnapshotOwner
    source_configuration_root: Path
    legacy_classification: CodingLegacyWorkspaceClassificationV1


@dataclass(frozen=True, slots=True)
class CodingPackagePreBCutover:
    attempt: PackageProductPosixCutoverAttemptV1 | PackageProductWindowsCutoverAttemptV1
    snapshots: PackageProductPreBSnapshotOwner | PackageProductWindowsPreBSnapshotOwner


CodingCutoverSnapshotAdmission = Callable[
    [CodingPreBSnapshotPreparation, PackageEpochCutoverSnapshotReceiptV1], None
]


def prepare_coding_package_cutover_roots(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> CodingPackageEpochLayoutV1:
    """Prepare only missing private roots for an offline first B cutover."""

    return prepare_legacy_product_cutover_roots(
        lifecycle,
        resolve_epoch=partial(resolve_coding_package_epoch_layout, lifecycle),
        label="Coding Package",
    )


def prepare_and_cutover_coding_package_store_from_legacy(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    namespace_id: str,
    minimum_runtime_version: str,
    minimum_runtime_protocol_epoch: int,
    snapshot_admission: CodingCutoverSnapshotAdmission | None = None,
    fresh_only: bool = False,
) -> CodingPackagePreBCutover:
    """Run one offline B cutover from an empty or existing Coding workspace."""

    if type(fresh_only) is not bool:
        raise TypeError("Coding fresh Product cutover policy is invalid")
    require_fresh = fresh_only or (os.name == "nt" and snapshot_admission is None)
    if require_fresh:
        if (
            settings_manager.global_settings_path is None
            or settings_manager.project_settings_path is None
        ):
            raise RuntimeError(_FRESH_SETTINGS_PATHS_REQUIRED)
        require_coding_fresh_settings_without_writes(
            settings_manager.global_settings_path,
            settings_manager.project_settings_path,
        )
        require_fresh_coding_product_inputs(
            lifecycle, settings_manager, roots_may_be_absent=True
        )
    prepare_coding_package_cutover_roots(lifecycle)
    if require_fresh:
        require_fresh_coding_product_inputs(lifecycle, settings_manager)
    with hold_legacy_product_projection_root(
        legacy_product_projection_parent(lifecycle.root),
        prefix="coding-pre-b-projection-",
        projection_name=_PROJECTION_NAME,
        projection_label="Coding Source projection",
    ) as projection_parent:
        return cutover_coding_package_store_from_legacy(
            lifecycle,
            settings_manager,
            projection_parent=projection_parent,
            namespace_id=namespace_id,
            minimum_runtime_version=minimum_runtime_version,
            minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
            snapshot_admission=snapshot_admission,
        )


def cutover_and_bootstrap_coding_package_product(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    namespace_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    windows_candidate: bool = False,
    require_current_admission: Callable[[], None] | None = None,
) -> CodingPackagePreBCutover:
    """Offline first B cutover of a fresh workspace, then install builtins.

    A failed Product bootstrap leaves the durable B fence in force. The caller
    may retry bootstrap, but may not resume a pre-fence writer against it.
    Windows uses an explicit candidate flag until native Product evidence
    admits the ordinary Session route.
    """

    if type(windows_candidate) is not bool or os.name not in {"posix", "nt"}:
        raise RuntimeError(
            "Coding Product bootstrap requires a native Package runtime owner"
        )
    if os.name == "nt" and not windows_candidate:
        raise RuntimeError("Coding Windows fresh Product bootstrap is not yet admitted")
    _require_current_coding_product_admission(require_current_admission)
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings_manager,
        namespace_id=namespace_id,
        minimum_runtime_version=runtime_version,
        minimum_runtime_protocol_epoch=runtime_protocol_epoch,
        fresh_only=True,
    )
    if cutover.attempt.result.disposition != "fenced":
        raise RuntimeError("Coding Package Product cutover refused")
    bootstrap_coding_builtin_product_plugins(
        lifecycle,
        settings_manager,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )
    return cutover


def reopen_coding_package_cutover(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    read_only: bool = False,
    expected_namespace: str | None = None,
) -> PackagePosixEpochCutoverResultV1:
    """Reopen the current B root without reading legacy Coding Source state."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    return reopen_legacy_product_cutover(
        **epoch.fenced_runtime_open_kwargs(),
        read_only=read_only,
        expected_namespace=expected_namespace,
        label="Coding Product",
    )


def cutover_coding_package_store_from_legacy(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    projection_parent: Path,
    namespace_id: str,
    minimum_runtime_version: str,
    minimum_runtime_protocol_epoch: int,
    snapshot_admission: CodingCutoverSnapshotAdmission | None = None,
) -> CodingPackagePreBCutover:
    """Hold real Coding Source state until Product finishes the first B fence."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    with hold_coding_pre_b_snapshot_owner(
        lifecycle, settings_manager, projection_parent=projection_parent
    ) as prepared:
        attempt = prepared.owner.cutover_from_legacy(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            legacy_root_name=epoch.legacy_root_name,
            epochs_root_name=epoch.epochs_root_name,
            namespace_id=namespace_id,
            minimum_runtime_version=minimum_runtime_version,
            minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
            snapshot_admission=(
                None
                if snapshot_admission is None
                else lambda snapshot: snapshot_admission(prepared, snapshot)
            ),
        )
        return CodingPackagePreBCutover(
            attempt=attempt,
            snapshots=prepared.owner,
        )


@contextmanager
def hold_coding_pre_b_snapshot_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    projection_parent: Path,
) -> Iterator[CodingPreBSnapshotPreparation]:
    """Pin real settings and map every deployed Coding pre-B state member."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if not isinstance(settings_manager, SettingsManager):
        raise TypeError("Coding settings manager is required")
    global_path = settings_manager.global_settings_path
    project_path = settings_manager.project_settings_path
    if not isinstance(global_path, Path) or not isinstance(project_path, Path):
        raise ValueError("Coding pre-B Source settings paths are required")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    with hold_coding_pre_b_source_configuration(
        settings_manager,
        global_settings_path=global_path,
        project_settings_path=project_path,
        projection_parent=projection_parent,
    ) as source_root:
        with hold_legacy_product_projection_root(
            projection_parent,
            prefix="coding-pre-b-legacy-pointer-",
            projection_name=_PROJECTION_NAME,
            projection_label="Coding Source projection",
        ) as pointer_root:
            package = resolve_coding_package_pre_b_store_members(lifecycle)
            state = resolve_coding_lifecycle_pre_b_members(lifecycle)
            source_projection = json.loads(
                read_legacy_product_projection(source_root, name=_PROJECTION_NAME)
            )
            legacy_classification = classify_coding_legacy_workspace(
                source_projection,
                lifecycle=state,
                package=package,
            )
            shared_members = (
                (
                    PackageProductPreBSnapshotSharedMemberV1(
                        source_root=package.source_root,
                        member_name="package-lock.json",
                        domains=("binding_history", "lock_history"),
                    ),
                )
                if package.binding_history
                else ()
            )
            owner = bind_legacy_pre_b_snapshot_owner(
                epoch.snapshot_root,
                store_id=epoch.store_id,
                observed_roots=(
                    (package.source_root, package.domain_members()),
                    (state.source_root, state.domain_members()),
                ),
                fence_root=epoch.control_root,
                source_configuration_root=source_root,
                legacy_pointer_root=pointer_root,
                legacy_root_pointer_name=epoch.legacy_root_name,
                shared_members=shared_members,
            )
            yield CodingPreBSnapshotPreparation(
                owner=owner,
                source_configuration_root=source_root,
                legacy_classification=legacy_classification,
            )


__all__ = [
    "CodingPackagePreBCutover",
    "CodingPreBSnapshotPreparation",
    "cutover_and_bootstrap_coding_package_product",
    "cutover_coding_package_store_from_legacy",
    "hold_coding_pre_b_snapshot_owner",
    "prepare_and_cutover_coding_package_store_from_legacy",
    "prepare_coding_package_cutover_roots",
    "reopen_coding_package_cutover",
]

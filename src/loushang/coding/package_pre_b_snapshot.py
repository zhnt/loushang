"""Coding-owned preparation of the complete pre-B Package snapshot."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.coding._plugin_lifecycle import CodingPluginLifecycleStateLayout
from loushang.coding.package_epoch_layout import (
    CodingPackageEpochLayoutV1,
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
    resolve_coding_package_pre_b_store_members,
)
from loushang.coding.package_source_snapshot import (
    hold_coding_pre_b_source_configuration,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.private_directory import create_private_directory_chain
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackagePosixEpochCutoverResultV1,
    PackageProductPosixCutoverAttemptV1,
    PackageProductPreBSnapshotOwner,
    PackageProductPreBSnapshotSharedMemberV1,
    reopen_posix_product_cutover,
)


@dataclass(frozen=True, slots=True)
class CodingPreBSnapshotPreparation:
    """Keep the private Source projection alive until native cutover returns."""

    owner: PackageProductPreBSnapshotOwner
    source_configuration_root: Path


@dataclass(frozen=True, slots=True)
class CodingPackagePreBCutover:
    attempt: PackageProductPosixCutoverAttemptV1
    snapshots: PackageProductPreBSnapshotOwner


def prepare_coding_package_cutover_roots(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> CodingPackageEpochLayoutV1:
    """Prepare only missing private roots for an offline first B cutover."""

    if os.name != "posix":
        raise RuntimeError("POSIX Package cutover preparation is required")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    for root, private_base in (
        (lifecycle.root, lifecycle.private_state_base),
        (epoch.control_root, lifecycle.private_state_base),
        (epoch.snapshot_root, lifecycle.private_state_base),
        (lifecycle.package_root, lifecycle.private_data_base),
        (epoch.epochs_root, lifecycle.private_data_base),
    ):
        _prepare_private_cutover_root(root, private_base=private_base)
    return epoch


def prepare_and_cutover_coding_package_store_from_legacy(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    namespace_id: str,
    minimum_runtime_version: str,
    minimum_runtime_protocol_epoch: int,
) -> CodingPackagePreBCutover:
    """Run one offline B cutover from an empty or existing Coding workspace."""

    prepare_coding_package_cutover_roots(lifecycle)
    with TemporaryDirectory(
        prefix="coding-pre-b-projection-", dir=lifecycle.root.parent
    ) as projection_parent:
        return cutover_coding_package_store_from_legacy(
            lifecycle,
            settings_manager,
            projection_parent=Path(projection_parent),
            namespace_id=namespace_id,
            minimum_runtime_version=minimum_runtime_version,
            minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
        )


def _prepare_private_cutover_root(root: Path, *, private_base: Path) -> None:
    if not private_base.is_absolute() or not root.is_absolute():
        raise ValueError("Coding Package cutover roots must be absolute")
    try:
        relative = root.relative_to(private_base)
    except ValueError:
        raise ValueError("Coding Package cutover root is outside its private base") from None
    create_private_directory_chain(private_base)
    current = private_base
    _require_private_cutover_directory(current)
    for part in relative.parts:
        current /= part
        create_private_directory_chain(current)
        _require_private_cutover_directory(current)


def _require_private_cutover_directory(path: Path) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError("Coding Package cutover directory is not private")


def reopen_coding_package_cutover(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> PackagePosixEpochCutoverResultV1:
    """Reopen the current B root without reading legacy Coding Source state."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    return reopen_posix_product_cutover(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )


def cutover_coding_package_store_from_legacy(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    projection_parent: Path,
    namespace_id: str,
    minimum_runtime_version: str,
    minimum_runtime_protocol_epoch: int,
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
        with TemporaryDirectory(
            prefix="coding-pre-b-legacy-pointer-", dir=projection_parent
        ) as pointer_root:
            package = resolve_coding_package_pre_b_store_members(lifecycle)
            state = resolve_coding_lifecycle_pre_b_members(lifecycle)
            domain_roots = {
                "store_bytes": package.source_root,
                "binding_history": package.source_root,
                "lock_history": package.source_root,
                "desired_state": state.source_root,
                "enablement_state": state.source_root,
                "instance_state": state.source_root,
                "fence_record": epoch.control_root,
                "source_configuration": source_root,
                "legacy_root_pointer": Path(pointer_root),
            }
            domain_members: dict[str, tuple[str, ...] | None] = {
                domain: None for domain in domain_roots
            }
            domain_members.update(package.domain_members())
            domain_members.update(state.domain_members())
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
            owner = PackageProductPreBSnapshotOwner(
                epoch.snapshot_root,
                store_id=epoch.store_id,
                domain_roots=domain_roots,
                domain_members=domain_members,
                legacy_root_pointer_name=epoch.legacy_root_name,
                shared_members=shared_members,
            )
            yield CodingPreBSnapshotPreparation(
                owner=owner,
                source_configuration_root=source_root,
            )


__all__ = [
    "CodingPackagePreBCutover",
    "CodingPreBSnapshotPreparation",
    "cutover_coding_package_store_from_legacy",
    "hold_coding_pre_b_snapshot_owner",
    "prepare_and_cutover_coding_package_store_from_legacy",
    "prepare_coding_package_cutover_roots",
    "reopen_coding_package_cutover",
]

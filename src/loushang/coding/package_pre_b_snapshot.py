"""Coding-owned preparation of the complete pre-B Package snapshot."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.coding._plugin_lifecycle import CodingPluginLifecycleStateLayout
from loushang.coding.package_epoch_layout import (
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
    resolve_coding_package_pre_b_store_members,
)
from loushang.coding.package_source_snapshot import (
    hold_coding_pre_b_source_configuration,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackageProductPreBSnapshotOwner,
    PackageProductPreBSnapshotSharedMemberV1,
)


@dataclass(frozen=True, slots=True)
class CodingPreBSnapshotPreparation:
    """Keep the private Source projection alive until native cutover returns."""

    owner: PackageProductPreBSnapshotOwner
    source_configuration_root: Path


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


__all__ = ["CodingPreBSnapshotPreparation", "hold_coding_pre_b_snapshot_owner"]

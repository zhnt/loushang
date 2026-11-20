"""Product-bound Windows candidate backup for the current Coding Arch shape.

This owner retains and verifies bytes. It grants no deletion, restore, expiry,
or ordinary Session routing authority. An incomplete stage stays as debt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product._backup_topology import (
    read_windows_private_backup_retention,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_backup_windows import (
    WindowsPrivateArchiveIO,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionSnapshotV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._tree_observation import logical_tree_members
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    prepare_windows_product_private_directory_chain,
)

from .epoch_layout import resolve_coding_package_epoch_layout
from .installation_private_data import (
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    _backup_receipt,
    _backup_retention_revision,
    _WindowsArchBackupCodec,
    backup_parent,
)
from .private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1
from .private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
    _native_io,
)
from .product_backup_types import require_coding_arch_backup_writer

_archive_io = WindowsPrivateArchiveIO(
    _native_io,
    _WindowsArchBackupCodec(),
    lambda path, expected: _capture_windows_target_snapshot(
        path, expected_root=expected
    ),
)


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataBackupOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        require_coding_arch_backup_writer(self.product)
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)

    def retain(
        self, key: PluginInstallationKeyV1
    ) -> CodingArchPrivateDataBackupReceiptV1:
        preview = CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        source_root = coding_arch_installation_private_data_root(self.layout, key)
        state_root = (
            resolve_coding_package_epoch_layout(self.layout).control_root
            / "product-state"
        )
        with preview._offline():
            state = self.product.desired_state.snapshot().installation(key)
            if state.latest_instance_revision_ref is None:
                raise ValueError(
                    "Coding Arch backup Installation has no Product history"
                )
            expected_root = inspect_coding_windows_arch_installation_root(
                self.layout, key, state_root=state_root
            )
            if expected_root is None:
                raise ValueError("Coding Arch private-data source is absent")
            source = _capture_windows_target_snapshot(
                source_root, expected_root=expected_root
            )
            receipt = _backup_receipt(key, source)
            parent_path = backup_parent(self.layout, key)
            prepare_windows_product_private_directory_chain(
                self.layout.package_root, "installation-backups", parent_path.name
            )
            return _archive_io.retain(
                source_root,
                source,
                receipt,
                key,
                parent_path,
                source_is_current=lambda: (
                    not (
                        _capture_windows_target_snapshot(
                            source_root, expected_root=expected_root
                        )
                        != source
                        or inspect_coding_windows_arch_installation_root(
                            self.layout, key, state_root=state_root
                        )
                        != expected_root
                    )
                ),
            )

    def verify(
        self, key: PluginInstallationKeyV1, backup_id_value: str
    ) -> CodingArchPrivateDataBackupReceiptV1:
        preview = CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        coding_arch_installation_private_data_root(self.layout, key)
        if len(backup_id_value) != 64 or any(
            character not in "0123456789abcdef" for character in backup_id_value
        ):
            raise ValueError("Coding Arch backup ID is invalid")
        with preview._offline(), WindowsPrivateDirectoryAcl() as acl:
            state = self.product.desired_state.snapshot().installation(key)
            if state.latest_instance_revision_ref is None:
                raise ValueError(
                    "Coding Arch backup Installation has no Product history"
                )
            parent_path = backup_parent(self.layout, key)
            return _archive_io.verify_retained(parent_path, backup_id_value, key, acl)

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        """Project verified archives and receipt-backed expiry conservatively."""

        from .private_data_backup_expiry_records import _tombstone_name
        from .private_data_windows_backup_expiry_journal import (
            CodingWindowsArchBackupExpiryTransaction,
        )
        from .private_data_windows_restore_journal import (
            CodingWindowsArchPrivateDataRestoreTransaction,
        )

        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id="coding.arch.default",
        )
        return read_windows_private_backup_retention(
            self,
            key,
            tree_io=_native_io,
            restore_factory=lambda fd: CodingWindowsArchPrivateDataRestoreTransaction(
                self.layout, self.product, fd
            ),
            scan_expiry=lambda restore: CodingWindowsArchBackupExpiryTransaction(
                self.layout, self.product, restore
            )._scan(),
            tombstone_name=lambda latest: _tombstone_name(
                latest.plan, latest.confirmation
            ),
            retained_receipts=lambda key, tombstone, pending: _retained_receipts(
                self.layout,
                key,
                allowed_tombstone=tombstone,
                pending_backup_id=pending,
            ),
            revision_for=lambda status, receipt_id, receipts, trust: (
                _backup_retention_revision(status, receipt_id, receipts, trust)
            ),
            revision_prefix="coding-arch-backup:",
            label="Windows Coding Arch",
        )


_logical_members = logical_tree_members


def _retained_receipts(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    allowed_tombstone: str | None = None,
    pending_backup_id: str | None = None,
) -> tuple[CodingArchPrivateDataBackupReceiptV1, ...]:
    return _archive_io.retained_receipts(
        backup_parent(layout, key),
        key,
        package_root=lambda: layout.package_root,
        is_archive_name=lambda name: (
            not (
                len(name) != 64
                or any(character not in "0123456789abcdef" for character in name)
            )
        ),
        allowed_tombstone=allowed_tombstone,
        pending_backup_id=pending_backup_id,
    )


_open_or_create_directory = _native_io.open_or_create_directory


_copy_members = _native_io.copy_members


def _read_archive_manifest(
    parent_fd: int, name: str, acl: WindowsPrivateDirectoryAcl
) -> tuple[CodingArchPrivateDataBackupReceiptV1, CodingArchPrivateDataTargetSnapshotV1]:
    return _archive_io.read_manifest(parent_fd, name, acl)


def _verify_archive(
    parent_fd: int,
    parent_path: Path,
    name: str,
    key: PluginInstallationKeyV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    _archive_io.verify_archive(parent_fd, parent_path, name, key, source, receipt, acl)


__all__ = ["CodingWindowsArchPrivateDataBackupOwner"]

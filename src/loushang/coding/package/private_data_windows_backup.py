"""Product-bound Windows candidate backup for the current Coding Arch shape.

This owner retains and verifies bytes. It grants no deletion, restore, expiry,
or ordinary Session routing authority. An incomplete stage stays as debt.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    prepare_windows_product_private_directory_chain,
)

from .epoch_layout import resolve_coding_package_epoch_layout
from .installation_private_data import (
    coding_arch_installation_private_data_root,
    coding_arch_workspace_installation_key,
    inspect_coding_windows_arch_installation_root,
)
from .private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    _backup_retention_revision,
    _digest,
    backup_manifest_codec,
    backup_parent,
    make_backup_receipt,
)
from .private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
    _native_io,
)
from .product_backup_types import require_coding_arch_backup_writer

_archive_io = WindowsPrivateArchiveIO(
    _native_io,
    backup_manifest_codec(windows=True),
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
                raise ValueError("Coding Arch backup Installation has no Product history")
            expected_root = inspect_coding_windows_arch_installation_root(
                self.layout, key, state_root=state_root
            )
            if expected_root is None:
                raise ValueError("Coding Arch private-data source is absent")
            source = _archive_io.capture(source_root, expected_root)
            receipt = make_backup_receipt(key, source)
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
                expected_source_root=expected_root,
                source_binding_is_current=lambda: (
                    inspect_coding_windows_arch_installation_root(
                        self.layout, key, state_root=state_root
                    ) == expected_root
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
                raise ValueError("Coding Arch backup Installation has no Product history")
            return _archive_io.verify_retained(
                backup_parent(self.layout, key), backup_id_value, key, acl
            )

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        """Project verified archives and receipt-backed expiry conservatively."""

        from .private_data_backup_expiry_records import _tombstone_name
        from .private_data_windows_backup_expiry_journal import (
            CodingWindowsArchBackupExpiryTransaction,
        )
        from .private_data_windows_restore_journal import (
            CodingWindowsArchPrivateDataRestoreTransaction,
        )

        key = coding_arch_workspace_installation_key(self.layout.scope_id)
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
            revision_for=_backup_retention_revision,
            revision_prefix="coding-arch-backup:",
            label="Windows Coding Arch",
        )


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
        is_archive_name=_digest,
        allowed_tombstone=allowed_tombstone,
        pending_backup_id=pending_backup_id,
    )


__all__ = ["CodingWindowsArchPrivateDataBackupOwner"]

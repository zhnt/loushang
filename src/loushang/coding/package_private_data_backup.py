"""Independent retained backup owner for one Coding Arch Installation.

The archive is a private immutable file tree with its own manifest. It never
deletes source data or expires backups, and Package removal/GC cannot infer
retention from their own receipts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionRecordV1,
    PluginBackupRetentionSnapshotV1,
    PluginBackupRetentionStatus,
)
from loushang.harness.plugin_management.private_data_backup import (
    enumerate_private_archives,
    read_private_archive,
    retain_private_archive,
    verify_private_archive,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages._private_tree_posix import (
    PrivatePosixTreeIO,
    verify_private_tree,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout, _prepare_private_tree
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    _ArchBackupCodec,
    _backup_receipt,
    _backup_retention_revision,
)
from .package_private_data_backup_records import (
    backup_parent as _backup_parent,
)
from .package_private_data_deletion_preview import _MAX_TOTAL_BYTES as _MAX_READ_BYTES
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
    _capture_target_snapshot,
)
from .package_product_backup_types import require_coding_arch_backup_writer

_PLUGIN_ID = "coding.arch.default"
_private_io = PrivatePosixTreeIO("Coding Arch", _MAX_READ_BYTES)
_open_chain = _private_io.open_chain
_mkdir_at = _private_io.mkdir
_open_private_dir = _private_io.open_directory
_open_private_path = _private_io.open_path
_write_or_verify_file = _private_io.write_file


_archive_codec = _ArchBackupCodec()


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupOwner:
    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Arch POSIX backup owner is unavailable")
        require_coding_arch_backup_writer(self.product)
        CodingArchPrivateDataDeletionPreview(self.layout, self.product)

    def retain(
        self, key: PluginInstallationKeyV1
    ) -> CodingArchPrivateDataBackupReceiptV1:
        source_root = coding_arch_installation_private_data_root(self.layout, key)
        preview = CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        with preview._offline():
            state = self.product.desired_state.snapshot().installation(key)
            if state.latest_instance_revision_ref is None:
                raise ValueError(
                    "Coding Arch backup Installation has no Product history"
                )
            source = _capture_target_snapshot(
                source_root, private_base=self.layout.private_data_base
            )
            if source.root_identity is None:
                raise ValueError("Coding Arch private-data source is absent")
            receipt = _backup_receipt(key, source)
            return retain_private_archive(
                source_root,
                source,
                receipt,
                key,
                private_base=self.layout.private_data_base,
                backup_parent=_backup_parent(self.layout, key),
                io=_private_io,
                codec=_archive_codec,
                recapture=lambda: _capture_target_snapshot(
                    source_root, private_base=self.layout.private_data_base
                ),
                prepare=_prepare_private_tree,
                write_file=_write_or_verify_file,
            )

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        preview = CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        with preview._offline():
            return CodingArchPrivateDataBackupReadSource(
                self.layout, self.product.epoch_runtime
            ).snapshot()

    def verify(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataBackupReceiptV1:
        """Reopen one exact archive without requiring its source to survive."""

        if not _digest(backup_id):
            raise ValueError("Coding Arch backup ID is invalid")
        parent = _backup_parent(self.layout, key)
        preview = CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        with preview._offline():
            with closing_descriptor(
                _open_private_path(self.layout.private_data_base, parent)
            ) as parent_fd:
                receipt, source = _read_manifest(parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch backup Installation changed")
                _verify_archive(parent_fd, backup_id, key, source, receipt)
                return receipt


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupReadSource:
    """Read-only Product projection of verified per-Installation backups."""

    layout: CodingPluginLifecycleStateLayout
    epoch_runtime: PackageProductPosixFencedRuntimeOwner

    def __post_init__(self) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Arch POSIX backup source is unavailable")
        epoch = resolve_coding_package_epoch_layout(self.layout)
        if (
            not isinstance(self.epoch_runtime, PackageProductPosixFencedRuntimeOwner)
            or self.epoch_runtime.registry.store_id != epoch.store_id
            or self.epoch_runtime.control_root != epoch.control_root
        ):
            raise ValueError("Coding Arch backup Product authority changed")

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        from .package_private_data_backup_expiry_journal import (
            CodingArchPrivateDataBackupExpiryJournal,
        )
        from .package_private_data_backup_expiry_records import _tombstone_name

        self.epoch_runtime.assert_current()
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id=_PLUGIN_ID,
        )
        expiry_phase: PluginBackupRetentionStatus = "unknown"
        expiry_receipt_id: str | None = None
        try:
            events = CodingArchPrivateDataBackupExpiryJournal(
                self.epoch_runtime.control_root / "product-state"
            ).events()
            latest = events[-1] if events else None
            pending = latest is not None and latest.phase in {"started", "renamed"}
            allowed_tombstone = (
                _tombstone_name(latest.plan, latest.confirmation)
                if pending and latest is not None
                else None
            )
            receipts = _retained_receipts(
                self.layout, key, allowed_tombstone=allowed_tombstone
            )
            if (
                latest is not None
                and latest.phase == "completed"
                and any(item.backup_id == latest.plan.backup_id for item in receipts)
            ):
                raise ValueError("Coding Arch expired backup reappeared")
            if pending:
                expiry_phase = "expiry_pending"
            elif receipts:
                expiry_phase = "retained"
            elif latest is not None and latest.phase == "completed":
                if latest.receipt is None or latest.plan.installation_key != key:
                    raise ValueError("Coding Arch backup expiry receipt changed")
                expiry_phase = "expired"
                expiry_receipt_id = latest.receipt.receipt_id
            trust = "verified"
        except (OSError, ValueError):
            receipts = ()
            trust = "untrusted"
            expiry_phase = "unknown"
        self.epoch_runtime.assert_current()
        revision = _backup_retention_revision(
            expiry_phase, expiry_receipt_id, receipts, trust
        )
        return PluginBackupRetentionSnapshotV1(
            owner_revision="coding-arch-backup:" + revision,
            records=(
                PluginBackupRetentionRecordV1(
                    installation_key=key,
                    status=expiry_phase,
                    expiry_receipt_id=expiry_receipt_id,
                ),
            ),
        )


def _retained_receipts(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    allowed_tombstone: str | None = None,
) -> tuple[CodingArchPrivateDataBackupReceiptV1, ...]:
    parent = _backup_parent(layout, key)
    return enumerate_private_archives(
        layout.private_data_base,
        parent,
        key,
        io=_private_io,
        codec=_archive_codec,
        is_archive_name=_digest,
        staging_suffix=".staging",
        allowed_tombstone=allowed_tombstone,
    )


def _verify_archive(
    parent_fd: int,
    name: str,
    key: PluginInstallationKeyV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
) -> None:
    verify_private_archive(
        parent_fd, name, key, source, receipt, io=_private_io, codec=_archive_codec
    )


def _read_manifest(
    parent_fd: int, name: str
) -> tuple[CodingArchPrivateDataBackupReceiptV1, CodingArchPrivateDataTargetSnapshotV1]:
    return read_private_archive(parent_fd, name, io=_private_io, codec=_archive_codec)


def _verify_files(root_fd: int, source: CodingArchPrivateDataTargetSnapshotV1) -> None:
    verify_private_tree(
        root_fd, source.members, label="Coding Arch", max_read_bytes=_MAX_READ_BYTES
    )


__all__ = [
    "CodingArchPrivateDataBackupOwner",
    "CodingArchPrivateDataBackupReadSource",
    "CodingArchPrivateDataBackupReceiptV1",
]

"""Offline Windows candidate for receipt-backed Arch backup expiry.

The archive is renamed through its verified handle before individual members
are deleted. Durable Product receipts permit exact retry after either effect.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    windows_delete_open_entry,
    windows_flush_directory,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_rename_open_directory_at,
    windows_stat_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from .package_private_data_backup_records import backup_parent
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
    _identity,
)
from .package_private_data_windows_archive_snapshot import (
    CodingWindowsArchBackupArchiveSnapshotV1,
    capture_windows_arch_backup_archive,
)
from .package_private_data_windows_backup import (
    _directory_identity,
    _read_archive_manifest,
)
from .package_private_data_windows_backup_expiry_journal import (
    CodingWindowsArchBackupExpiryEventV1,
    CodingWindowsArchBackupExpiryJournal,
    CodingWindowsArchBackupExpiryTransaction,
)
from .package_private_data_windows_backup_expiry_preview import (
    CodingWindowsArchPrivateDataBackupExpiryPreview,
)
from .package_private_data_windows_backup_expiry_recovery import (
    require_windows_arch_backup_expiry_recovery_authority,
)
from .package_private_data_windows_deletion_owner import (
    _remove_members,
    _require_directory,
    _require_remaining_subset,
)
from .package_private_data_windows_preview import (
    _capture_windows_target_snapshot,
    _require_simple_windows_metadata,
)

_READ_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataBackupExpiryOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchBackupExpiryJournal(self.layout, self.product)

    def confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        with CodingWindowsArchBackupExpiryJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return transaction.confirm(
                plan, actor_id=actor_id, policy_revision=policy_revision
            )

    def expire(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        if (
            not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or not isinstance(
                confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1
            )
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Windows Coding Arch backup expiry acceptance is invalid")
        with CodingWindowsArchBackupExpiryJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return self._expire_locked(transaction, plan, confirmation)

    def _expire_locked(
        self,
        transaction: CodingWindowsArchBackupExpiryTransaction,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        events, staged = transaction._scan()
        if not events or (
            events[-1].plan != plan or events[-1].confirmation != confirmation
        ):
            raise ValueError("Windows Coding Arch backup expiry is not confirmed")
        current = events[-1]
        parent_path = backup_parent(self.layout, plan.installation_key)
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )
        tombstone = _tombstone_name(plan, confirmation)
        with WindowsPrivateDirectoryAcl() as acl:
            parent_fd = open_windows_directory(
                parent_path, share_delete=False, read_control=True
            )
            try:
                acl.validate(parent_fd)
                if _directory_identity(parent_fd) != parent_identity:
                    raise ValueError("Windows Coding Arch backup parent changed")
                names = set(windows_listdir_at(parent_fd))
                if plan.backup_id in names and tombstone in names:
                    raise ValueError("Windows Coding Arch expiry tombstone collides")
                if current.phase == "completed":
                    if (
                        staged is not None
                        or plan.backup_id in names
                        or tombstone in names
                    ):
                        raise ValueError(
                            "Windows Coding Arch expired archive reappeared"
                        )
                    self._require_recovery_authority(transaction, plan)
                    assert current.receipt is not None
                    return current.receipt
                if current.phase == "confirmed" or (
                    current.phase == "started" and plan.backup_id in names
                ):
                    archive = self._require_pre_effect_archive(
                        transaction, plan, parent_fd, acl
                    )
                    if current.phase == "confirmed":
                        current = transaction.begin(plan, confirmation, archive)
                    elif current.archive != archive:
                        raise ValueError("Windows Coding Arch backup archive changed")
                self._require_recovery_authority(transaction, plan)
                if current.phase == "started":
                    current = self._rename_or_recover(
                        transaction, current, parent_fd, tombstone, acl
                    )
                if current.phase != "renamed" or current.archive is None:
                    raise ValueError("Windows Coding Arch expiry checkpoint changed")
                names = set(windows_listdir_at(parent_fd))
                if plan.backup_id in names:
                    raise ValueError("Windows Coding Arch backup archive reappeared")
                if tombstone in names:
                    _remove_tombstone(
                        parent_fd,
                        parent_path / tombstone,
                        tombstone,
                        current.archive,
                        acl,
                    )
                if (
                    _directory_identity(parent_fd) != parent_identity
                    or plan.backup_id in windows_listdir_at(parent_fd)
                    or tombstone in windows_listdir_at(parent_fd)
                ):
                    raise ValueError("Windows Coding Arch backup expiry did not settle")
                completed = transaction.advance(current, "completed")
                assert completed.receipt is not None
                if (
                    _directory_identity(parent_fd) != parent_identity
                    or plan.backup_id in windows_listdir_at(parent_fd)
                    or tombstone in windows_listdir_at(parent_fd)
                ):
                    raise ValueError("Windows Coding Arch backup expiry did not settle")
                return completed.receipt
            finally:
                os.close(parent_fd)

    def _require_pre_effect_archive(
        self,
        transaction: CodingWindowsArchBackupExpiryTransaction,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        parent_fd: int,
        acl: WindowsPrivateDirectoryAcl,
    ) -> CodingWindowsArchBackupArchiveSnapshotV1:
        current = CodingWindowsArchPrivateDataBackupExpiryPreview(
            self.layout, self.product
        )._preview_locked(
            transaction.restore,
            plan.installation_key,
            plan.backup_id,
            plan.confirmation_id,
        )
        if current != plan:
            raise ValueError("Windows Coding Arch backup expiry plan changed")
        receipt, source = _read_archive_manifest(parent_fd, plan.backup_id, acl)
        archive = capture_windows_arch_backup_archive(
            self.layout, plan.installation_key, plan.backup_id, source, receipt
        )
        if archive.target_id != plan.archive_target_id:
            raise ValueError("Windows Coding Arch backup archive changed")
        return archive

    def _require_recovery_authority(
        self,
        transaction: CodingWindowsArchBackupExpiryTransaction,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
    ) -> None:
        require_windows_arch_backup_expiry_recovery_authority(
            self.layout, self.product, transaction.restore, plan
        )

    def _rename_or_recover(
        self,
        transaction: CodingWindowsArchBackupExpiryTransaction,
        started: CodingWindowsArchBackupExpiryEventV1,
        parent_fd: int,
        tombstone: str,
        acl: WindowsPrivateDirectoryAcl,
    ) -> CodingWindowsArchBackupExpiryEventV1:
        archive = started.archive
        if archive is None:
            raise ValueError("Windows Coding Arch expiry archive is missing")
        names = set(windows_listdir_at(parent_fd))
        original_visible = started.plan.backup_id in names
        tombstone_visible = tombstone in names
        if original_visible and tombstone_visible:
            raise ValueError("Windows Coding Arch expiry tombstone collides")
        if original_visible:
            source_fd = open_windows_deletion_entry_at(
                parent_fd, started.plan.backup_id, directory=True
            )
            try:
                _require_directory(source_fd, archive.root_identity[:2], acl)
                windows_rename_open_directory_at(
                    parent_fd,
                    source_fd,
                    tombstone,
                    expected_identity=archive.root_identity,
                )
            finally:
                os.close(source_fd)
            windows_flush_directory(parent_fd)
        elif not tombstone_visible:
            raise ValueError("Windows Coding Arch backup archive disappeared")
        _require_tombstone_subset(
            parent_fd,
            backup_parent(self.layout, started.plan.installation_key) / tombstone,
            tombstone,
            archive,
            acl,
        )
        return transaction.advance(started, "renamed")


def _tombstone_name(
    plan: CodingArchPrivateDataBackupExpiryPlanV1,
    confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
) -> str:
    return (
        ".expiring-"
        + sha256(
            b"loushang.coding-arch-backup-expiry-tombstone/v1\0"
            + canonical_json_bytes(
                {
                    "confirmationId": confirmation.confirmation_id,
                    "planFingerprint": plan.fingerprint,
                }
            )
        ).hexdigest()
    )


def _require_tombstone_subset(
    parent_fd: int,
    tombstone_path: Path,
    tombstone: str,
    archive: CodingWindowsArchBackupArchiveSnapshotV1,
    acl: WindowsPrivateDirectoryAcl,
) -> CodingArchPrivateDataTargetSnapshotV1 | None:
    if archive.files.root_identity is None:
        raise ValueError("Windows Coding Arch expiry files identity is missing")
    descriptor = open_windows_directory(
        tombstone, dir_fd=parent_fd, share_delete=False, read_control=True
    )
    try:
        _require_directory(descriptor, archive.root_identity[:2], acl)
        if (
            _identity(windows_stat_at(parent_fd, tombstone))[:3]
            != archive.root_identity[:3]
        ):
            raise ValueError("Windows Coding Arch expiry tombstone changed")
        names = set(windows_listdir_at(descriptor))
        if not names <= {"files", "manifest.json"}:
            raise ValueError("Windows Coding Arch expiry tombstone gained members")
        if "manifest.json" in names:
            manifest_fd = open_windows_deletion_entry_at(
                descriptor, "manifest.json", directory=False
            )
            try:
                _require_manifest(manifest_fd, descriptor, archive, acl)
            finally:
                os.close(manifest_fd)
        if "files" in names:
            remaining = _capture_windows_target_snapshot(
                tombstone_path / "files",
                expected_root=archive.files.root_identity[:2],
            )
            _require_remaining_subset(remaining, archive.files)
            return remaining
        return None
    finally:
        os.close(descriptor)


def _remove_tombstone(
    parent_fd: int,
    tombstone_path: Path,
    tombstone: str,
    archive: CodingWindowsArchBackupArchiveSnapshotV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    if archive.files.root_identity is None:
        raise ValueError("Windows Coding Arch expiry files identity is missing")
    remaining = _require_tombstone_subset(
        parent_fd, tombstone_path, tombstone, archive, acl
    )
    if remaining is not None:
        _remove_members(tombstone_path / "files", remaining.members, archive.files)
        tombstone_fd = open_windows_directory(
            tombstone, dir_fd=parent_fd, share_delete=False, read_control=True
        )
        try:
            files_fd = open_windows_deletion_entry_at(
                tombstone_fd, "files", directory=True
            )
            try:
                _require_directory(files_fd, archive.files.root_identity[:2], acl)
                if windows_listdir_at(files_fd):
                    raise ValueError("Windows Coding Arch expiry files are not empty")
                windows_delete_open_entry(
                    files_fd,
                    expected_identity=archive.files.root_identity,
                    directory=True,
                )
            finally:
                os.close(files_fd)
            windows_flush_directory(tombstone_fd)
        finally:
            os.close(tombstone_fd)
    tombstone_fd = open_windows_directory(
        tombstone, dir_fd=parent_fd, share_delete=False, read_control=True
    )
    try:
        if "manifest.json" in windows_listdir_at(tombstone_fd):
            manifest_fd = open_windows_deletion_entry_at(
                tombstone_fd, "manifest.json", directory=False
            )
            try:
                _require_manifest(manifest_fd, tombstone_fd, archive, acl)
                windows_delete_open_entry(
                    manifest_fd,
                    expected_identity=archive.manifest.identity,
                    directory=False,
                )
            finally:
                os.close(manifest_fd)
            windows_flush_directory(tombstone_fd)
        if windows_listdir_at(tombstone_fd):
            raise ValueError("Windows Coding Arch expiry tombstone is not empty")
    finally:
        os.close(tombstone_fd)
    root_fd = open_windows_deletion_entry_at(parent_fd, tombstone, directory=True)
    try:
        _require_directory(root_fd, archive.root_identity[:2], acl)
        if windows_listdir_at(root_fd):
            raise ValueError("Windows Coding Arch expiry tombstone is not empty")
        windows_delete_open_entry(
            root_fd, expected_identity=archive.root_identity, directory=True
        )
    finally:
        os.close(root_fd)
    windows_flush_directory(parent_fd)


def _require_manifest(
    descriptor: int,
    parent_fd: int,
    archive: CodingWindowsArchBackupArchiveSnapshotV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    acl.validate(descriptor)
    before = os.fstat(descriptor)
    _require_simple_windows_metadata(before, directory=False)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or _identity(before) != archive.manifest.identity
        or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
    ):
        raise ValueError("Windows Coding Arch expiry manifest changed")
    digest = sha256()
    size = 0
    while chunk := os.read(descriptor, _READ_CHUNK):
        size += len(chunk)
        if size > archive.manifest.identity[3]:
            raise ValueError("Windows Coding Arch expiry manifest changed")
        digest.update(chunk)
    after = os.fstat(descriptor)
    visible = windows_stat_at(parent_fd, "manifest.json")
    if (
        size != archive.manifest.identity[3]
        or digest.hexdigest() != archive.manifest.content_sha256
        or _identity(after) != archive.manifest.identity
        or _identity(visible) != archive.manifest.identity
    ):
        raise ValueError("Windows Coding Arch expiry manifest changed")


__all__ = ["CodingWindowsArchPrivateDataBackupExpiryOwner"]

"""Exact offline preview and independently journaled Arch backup expiry."""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _rename_directory_noreplace,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup import (
    _backup_parent,
    _digest,
    _exists_at,
    _open_private_dir,
    _open_private_path,
    _read_manifest,
    _verify_archive,
)
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from .package_private_data_deletion_owner import (
    _remove_members,
    _require_remaining_subset,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
    _capture_target_snapshot,
    _identity,
)
from .package_private_data_restore import CodingArchPrivateDataRestoreOwner
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
)
from .package_private_data_restore_journal import CodingArchPrivateDataRestoreJournal

if TYPE_CHECKING:
    from .package_private_data_backup_expiry_journal import (
        CodingArchPrivateDataBackupExpiryConfirmationV1,
        CodingArchPrivateDataBackupExpiryEventV1,
        CodingArchPrivateDataBackupExpiryJournal,
        CodingArchPrivateDataBackupExpiryReceiptV1,
    )


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupExpiryOwner:
    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingArchPrivateDataDeletionPreview(self.layout, self.product)

    def preview(
        self,
        key: PluginInstallationKeyV1,
        backup_id: str,
        confirmation_id: str,
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        """Read the exact restore and archive evidence under offline quiescence."""

        if not _digest(backup_id):
            raise ValueError("Coding Arch backup expiry ID is invalid")
        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            restore = CodingArchPrivateDataRestoreOwner(self.layout, self.product)
            completion, target_id = restore._current_completed_restore(key, backup_id)
            confirmations = CodingArchPrivateDataRestoreConfirmationJournal(
                self.product.state_root
            ).records()
            confirmation = next(
                (
                    item
                    for item in reversed(confirmations)
                    if item.confirmation_id == confirmation_id
                ),
                None,
            )
            if (
                confirmation is None
                or confirmation.installation_key != key
                or confirmation.backup_id != backup_id
                or confirmation.restore_id != completion.restore_id
                or confirmation.deletion_receipt_id != completion.deletion_receipt_id
                or confirmation.restore_completion_digest != completion.record_digest
                or confirmation.restored_target_id != target_id
            ):
                raise ValueError("Coding Arch backup expiry confirmation is stale")
            desired = self.product.desired_state.snapshot()
            if desired.installation(key).selection.desired_state != "absent":
                raise ValueError("Coding Arch backup expiry requires removal")
            parent_fd = _open_private_path(
                self.layout.private_data_base, _backup_parent(self.layout, key)
            )
            try:
                receipt, source = _read_manifest(parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch backup expiry Installation changed")
                _verify_archive(parent_fd, backup_id, key, source, receipt)
                archive_fd = _open_private_dir(parent_fd, backup_id)
                try:
                    identity = _identity(os.fstat(archive_fd))
                    if identity != _identity(
                        os.stat(backup_id, dir_fd=parent_fd, follow_symlinks=False)
                    ):
                        raise ValueError("Coding Arch backup expiry archive changed")
                finally:
                    os.close(archive_fd)
            finally:
                os.close(parent_fd)
            archive_snapshot = _capture_target_snapshot(
                _backup_parent(self.layout, key) / backup_id,
                private_base=self.layout.private_data_base,
            )
            if (
                archive_snapshot.root_identity != identity
                or archive_snapshot.root_identity is None
            ):
                raise ValueError("Coding Arch backup expiry archive changed")
            return CodingArchPrivateDataBackupExpiryPlanV1(
                installation_key=key,
                backup_id=backup_id,
                backup_receipt_id=receipt.receipt_id,
                source_target_id=source.target_id,
                confirmation_id=confirmation.confirmation_id,
                restore_completion_digest=completion.record_digest,
                restored_target_id=target_id,
                desired_inventory_revision=desired.inventory_revision,
                archive_root_identity=identity,
                archive_target_id=archive_snapshot.target_id,
            )

    def confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        """Record independent operator acceptance of one current exact plan."""

        from .package_private_data_backup_expiry_journal import (
            CodingArchPrivateDataBackupExpiryJournal,
        )

        if not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1):
            raise TypeError("Coding Arch backup expiry plan is required")
        current = self.preview(
            plan.installation_key, plan.backup_id, plan.confirmation_id
        )
        if current != plan:
            raise ValueError("Coding Arch backup expiry plan changed")
        return CodingArchPrivateDataBackupExpiryJournal(
            self.product.state_root
        ).confirm(plan, actor_id=actor_id, policy_revision=policy_revision)

    def expire(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        """Delete one reviewed archive through durable, offline checkpoints."""

        from .package_private_data_backup_expiry_journal import (
            CodingArchPrivateDataBackupExpiryConfirmationV1,
            CodingArchPrivateDataBackupExpiryJournal,
        )

        if (
            not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or not isinstance(
                confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1
            )
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Coding Arch backup expiry acceptance is invalid")
        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            journal = CodingArchPrivateDataBackupExpiryJournal(self.product.state_root)
            events = journal.events()
            if not events or (
                events[-1].plan != plan or events[-1].confirmation != confirmation
            ):
                raise ValueError("Coding Arch backup expiry is not confirmed")
            current = events[-1]
            parent_path = _backup_parent(self.layout, plan.installation_key)
            parent_fd = _open_private_path(self.layout.private_data_base, parent_path)
            tombstone = _tombstone_name(plan, confirmation)
            try:
                if _identity(os.fstat(parent_fd)) != _identity(parent_path.lstat()):
                    raise ValueError("Coding Arch backup expiry parent changed")
                if current.phase == "completed":
                    if _exists_at(parent_fd, plan.backup_id) or _exists_at(
                        parent_fd, tombstone
                    ):
                        raise ValueError("Coding Arch expired backup reappeared")
                    assert current.receipt is not None
                    return current.receipt
                if current.phase == "confirmed" or (
                    current.phase == "started" and _exists_at(parent_fd, plan.backup_id)
                ):
                    archive = self._require_pre_effect_plan(plan)
                    if current.phase == "confirmed":
                        current = journal.begin(plan, confirmation, archive)
                    elif current.archive != archive:
                        raise ValueError("Coding Arch backup expiry archive changed")
                self._require_recovery_authority(plan)
                if current.phase == "started":
                    current = self._rename_or_recover(
                        journal, current, parent_fd, tombstone
                    )
                if current.phase != "renamed" or current.archive is None:
                    raise ValueError("Coding Arch backup expiry checkpoint changed")
                if _exists_at(parent_fd, tombstone):
                    _remove_tombstone(
                        self.layout,
                        parent_fd,
                        tombstone,
                        current.archive,
                        plan.installation_key,
                        plan.backup_id,
                    )
                elif _exists_at(parent_fd, plan.backup_id):
                    raise ValueError("Coding Arch backup expiry archive reappeared")
                completed = journal.advance(current, "completed")
                assert completed.receipt is not None
                return completed.receipt
            finally:
                os.close(parent_fd)

    def _require_pre_effect_plan(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        """Recheck every preview authority while the offline fence is held."""

        key = plan.installation_key
        completion, target_id = CodingArchPrivateDataRestoreOwner(
            self.layout, self.product
        )._current_completed_restore(key, plan.backup_id)
        if (
            completion.record_digest != plan.restore_completion_digest
            or target_id != plan.restored_target_id
        ):
            raise ValueError("Coding Arch backup expiry restore changed")
        self._require_recovery_authority(plan)
        path = _backup_parent(self.layout, key) / plan.backup_id
        snapshot = _capture_target_snapshot(
            path, private_base=self.layout.private_data_base
        )
        if (
            snapshot.root_identity != plan.archive_root_identity
            or snapshot.target_id != plan.archive_target_id
        ):
            raise ValueError("Coding Arch backup expiry archive changed")
        return snapshot

    def _require_recovery_authority(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> None:
        key = plan.installation_key
        desired = self.product.desired_state.snapshot()
        if (
            desired.inventory_revision != plan.desired_inventory_revision
            or desired.installation(key).selection.desired_state != "absent"
        ):
            raise ValueError("Coding Arch backup expiry Desired State changed")
        confirmations = CodingArchPrivateDataRestoreConfirmationJournal(
            self.product.state_root
        ).records()
        if not any(
            item.installation_key == key
            and item.backup_id == plan.backup_id
            and item.confirmation_id == plan.confirmation_id
            and item.restore_completion_digest == plan.restore_completion_digest
            and item.restored_target_id == plan.restored_target_id
            for item in confirmations
        ):
            raise ValueError("Coding Arch backup expiry confirmation changed")
        if not any(
            item.phase == "completed"
            and item.installation_key == key
            and item.backup_id == plan.backup_id
            and item.record_digest == plan.restore_completion_digest
            for item in CodingArchPrivateDataRestoreJournal(
                self.product.state_root
            ).events()
        ):
            raise ValueError("Coding Arch backup expiry restore history changed")
        restored = _capture_target_snapshot(
            coding_arch_installation_private_data_root(self.layout, key),
            private_base=self.layout.private_data_base,
        )
        if restored.target_id != plan.restored_target_id:
            raise ValueError("Coding Arch backup expiry restored data changed")

    def _rename_or_recover(
        self,
        journal: CodingArchPrivateDataBackupExpiryJournal,
        started: CodingArchPrivateDataBackupExpiryEventV1,
        parent_fd: int,
        tombstone: str,
    ) -> CodingArchPrivateDataBackupExpiryEventV1:
        plan = started.plan
        assert started.archive is not None
        original_visible = _exists_at(parent_fd, plan.backup_id)
        tombstone_visible = _exists_at(parent_fd, tombstone)
        if original_visible and tombstone_visible:
            raise ValueError("Coding Arch backup expiry tombstone collides")
        if original_visible:
            archive_fd = _open_private_dir(parent_fd, plan.backup_id)
            try:
                if _identity(os.fstat(archive_fd)) != plan.archive_root_identity:
                    raise ValueError("Coding Arch backup expiry archive changed")
                _rename_directory_noreplace(
                    parent_fd, plan.backup_id, parent_fd, tombstone
                )
                os.fsync(parent_fd)
                if (
                    _identity(os.fstat(archive_fd))[:3]
                    != _identity(
                        os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False)
                    )[:3]
                ):
                    raise ValueError("Coding Arch backup expiry rename changed")
            finally:
                os.close(archive_fd)
        elif not tombstone_visible:
            raise ValueError("Coding Arch backup expiry archive disappeared")
        _require_tombstone_subset(
            self.layout,
            parent_fd,
            tombstone,
            started.archive,
            plan.installation_key,
        )
        return journal.advance(started, "renamed")


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
    layout: CodingPluginLifecycleStateLayout,
    parent_fd: int,
    tombstone: str,
    original: CodingArchPrivateDataTargetSnapshotV1,
    key: PluginInstallationKeyV1,
) -> CodingArchPrivateDataTargetSnapshotV1:
    if original.root_identity is None:
        raise ValueError("Coding Arch backup expiry archive was absent")
    tombstone_fd = _open_private_dir(parent_fd, tombstone)
    try:
        if (
            _identity(os.fstat(tombstone_fd))[:3] != original.root_identity[:3]
            or _identity(os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False))[
                :3
            ]
            != original.root_identity[:3]
        ):
            raise ValueError("Coding Arch backup expiry tombstone changed")
    finally:
        os.close(tombstone_fd)
    remaining = _capture_target_snapshot(
        _backup_parent(layout, key) / tombstone,
        private_base=layout.private_data_base,
    )
    _require_remaining_subset(remaining, original)
    return remaining


def _remove_tombstone(
    layout: CodingPluginLifecycleStateLayout,
    parent_fd: int,
    tombstone: str,
    original: CodingArchPrivateDataTargetSnapshotV1,
    key: PluginInstallationKeyV1,
    backup_id: str,
) -> None:
    if _exists_at(parent_fd, backup_id):
        raise ValueError("Coding Arch backup expiry archive reappeared")
    remaining = _require_tombstone_subset(layout, parent_fd, tombstone, original, key)
    tombstone_fd = _open_private_dir(parent_fd, tombstone)
    try:
        if (
            original.root_identity is None
            or _identity(os.fstat(tombstone_fd))[:3] != (original.root_identity[:3])
        ):
            raise ValueError("Coding Arch backup expiry tombstone changed")
        _remove_members(tombstone_fd, remaining.members, original)
        if os.listdir(tombstone_fd):
            raise ValueError("Coding Arch backup expiry tombstone is not empty")
        os.fsync(tombstone_fd)
    finally:
        os.close(tombstone_fd)
    if (
        original.root_identity is None
        or _identity(os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False))[:3]
        != original.root_identity[:3]
    ):
        raise ValueError("Coding Arch backup expiry tombstone changed")
    os.rmdir(tombstone, dir_fd=parent_fd)
    os.fsync(parent_fd)
    if _exists_at(parent_fd, backup_id):
        raise ValueError("Coding Arch backup expiry archive reappeared")


__all__ = [
    "CodingArchPrivateDataBackupExpiryOwner",
    "CodingArchPrivateDataBackupExpiryPlanV1",
]

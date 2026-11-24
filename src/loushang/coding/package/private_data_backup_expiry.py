"""Exact offline preview and independently journaled Arch backup expiry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_backup import (
    execute_posix_expiry as execute_posix_expiry,
)
from loushang.harness.plugin_management.private_data_backup import (
    inspect_private_expiry_archive as inspect_private_expiry_archive,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .private_data_backup import _archive_codec as _archive_codec
from .private_data_backup import _backup_parent as _backup_parent
from .private_data_backup import _digest as _digest
from .private_data_backup import _private_io as _private_io
from .private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryPlanV1,
    require_expiry_acceptance,
)
from .private_data_backup_expiry_records import (
    _tombstone_name as _tombstone_name,
)
from .private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
)
from .private_data_deletion_preview import (
    _capture_target_snapshot as _capture_target_snapshot,
)
from .private_data_restore import (
    CodingArchPrivateDataRestoreOwner as CodingArchPrivateDataRestoreOwner,
)
from .private_data_restore import (
    _archive_restore,
)
from .private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal as CodingArchPrivateDataRestoreConfirmationJournal,
)

if TYPE_CHECKING:
    from .private_data_backup_expiry_journal import (
        CodingArchPrivateDataBackupExpiryConfirmationV1,
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
            return restore._archive().preview_expiry(
                key,
                backup_id,
                confirmation_id,
                confirmation_journal=restore._confirmation_journal,
                create_plan=CodingArchPrivateDataBackupExpiryPlanV1,
            )

    def confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        """Record independent operator acceptance of one current exact plan."""

        from loushang.coding.package.private_data_backup_expiry_journal import (
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

        from loushang.coding.package.private_data_backup_expiry_journal import (
            CodingArchPrivateDataBackupExpiryJournal,
        )

        require_expiry_acceptance(plan, confirmation, label="Coding Arch")
        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            journal = CodingArchPrivateDataBackupExpiryJournal(self.product.state_root)
            return cast(
                "CodingArchPrivateDataBackupExpiryReceiptV1",
                execute_posix_expiry(
                    plan,
                    confirmation,
                    journal,
                    authority=self,
                    io=_private_io,
                    private_base=lambda: self.layout.private_data_base,
                    backup_parent=lambda key: _backup_parent(self.layout, key),
                    tombstone_name=lambda: _tombstone_name(plan, confirmation),
                    capture=lambda key, name: _capture_target_snapshot(
                        _backup_parent(self.layout, key) / name,
                        private_base=self.layout.private_data_base,
                    ),
                ),
            )

    def _require_pre_effect_plan(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        restore = CodingArchPrivateDataRestoreOwner(self.layout, self.product)
        return restore._archive().require_current_expiry_archive(
            plan, confirmation_journal=restore._confirmation_journal
        )

    def _require_recovery_authority(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> None:
        archive = _archive_restore(
            self.layout, self.product.state_root, self.product.desired_state.snapshot
        )
        archive.require_expiry_recovery(
            plan,
            confirmation_journal=lambda: CodingArchPrivateDataRestoreConfirmationJournal(
                self.product.state_root
            ),
        )


__all__ = [
    "CodingArchPrivateDataBackupExpiryOwner",
    "CodingArchPrivateDataBackupExpiryPlanV1",
]

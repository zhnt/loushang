"""Exact offline preview and independently journaled Arch backup expiry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.private_data_backup import (
    execute_posix_expiry,
    inspect_private_expiry_archive,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup import (
    _archive_codec,
    _backup_parent,
    _digest,
    _private_io,
)
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryPlanV1,
    _tombstone_name,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
    _capture_target_snapshot,
)
from .package_private_data_restore import CodingArchPrivateDataRestoreOwner
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
    _require_restore_confirmation,
)
from .package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
    CodingArchPrivateDataRestoreJournal,
)

if TYPE_CHECKING:
    from .package_private_data_backup_expiry_journal import (
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
            return _expiry_preview(
                self.layout,
                self.product.state_root,
                key,
                backup_id,
                confirmation_id,
                completed_restore=lambda: restore._current_completed_restore(
                    key, backup_id
                ),
                desired_snapshot=self.product.desired_state.snapshot,
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


def _expiry_preview(
    layout: CodingPluginLifecycleStateLayout,
    state_root: Path,
    key: PluginInstallationKeyV1,
    backup_id: str,
    confirmation_id: str,
    *,
    completed_restore: Callable[[], tuple[CodingArchPrivateDataRestoreEventV1, str]],
    desired_snapshot: Callable[[], PluginDesiredStateSnapshotV1],
) -> CodingArchPrivateDataBackupExpiryPlanV1:
    completion, target_id = completed_restore()
    confirmations = CodingArchPrivateDataRestoreConfirmationJournal(
        state_root
    ).records()
    confirmation = _require_restore_confirmation(
        confirmations,
        confirmation_id,
        key,
        backup_id,
        completion,
        target_id,
        message="Coding Arch backup expiry confirmation is stale",
    )
    desired = desired_snapshot()
    if desired.installation(key).selection.desired_state != "absent":
        raise ValueError("Coding Arch backup expiry requires removal")
    receipt, source, identity, archive_snapshot = inspect_private_expiry_archive(
        layout.private_data_base,
        _backup_parent(layout, key),
        backup_id,
        key,
        io=_private_io,
        codec=_archive_codec,
        recapture=lambda: _capture_target_snapshot(
            _backup_parent(layout, key) / backup_id,
            private_base=layout.private_data_base,
        ),
        installation_error="Coding Arch backup expiry Installation changed",
        changed_error="Coding Arch backup expiry archive changed",
    )
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


__all__ = [
    "CodingArchPrivateDataBackupExpiryOwner",
    "CodingArchPrivateDataBackupExpiryPlanV1",
]

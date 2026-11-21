"""Complete private-data programs using existing storage/history owners.

Temporary Product binding imports preserve original nominal and fault seams;
they are tracked intermediate dependencies, not final Harness neutrality.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from loushang.coding.package import private_data_backup_expiry as _binding
from loushang.coding.package.private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1


def preview(
    self: _binding.CodingArchPrivateDataBackupExpiryOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    confirmation_id: str,
) -> _binding.CodingArchPrivateDataBackupExpiryPlanV1:
    """Read the exact restore and archive evidence under offline quiescence."""

    if not _binding._digest(backup_id):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_01"])
    with _binding.CodingArchPrivateDataDeletionPreview(
        self.layout, self.product
    )._offline():
        restore = _binding.CodingArchPrivateDataRestoreOwner(self.layout, self.product)
        return preview_expiry(
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


def expire(
    self: _binding.CodingArchPrivateDataBackupExpiryOwner,
    plan: _binding.CodingArchPrivateDataBackupExpiryPlanV1,
    confirmation: _binding.CodingArchPrivateDataBackupExpiryConfirmationV1,
) -> _binding.CodingArchPrivateDataBackupExpiryReceiptV1:
    """Delete one reviewed archive through durable, offline checkpoints."""

    from loushang.coding.package.private_data_backup_expiry_journal import (
        CodingArchPrivateDataBackupExpiryConfirmationV1,
        CodingArchPrivateDataBackupExpiryJournal,
    )

    if (
        not isinstance(plan, _binding.CodingArchPrivateDataBackupExpiryPlanV1)
        or not isinstance(confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1)
        or confirmation.plan_fingerprint != plan.fingerprint
    ):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_02"])
    with _binding.CodingArchPrivateDataDeletionPreview(
        self.layout, self.product
    )._offline():
        journal = CodingArchPrivateDataBackupExpiryJournal(self.product.state_root)
        return cast(
            "_binding.CodingArchPrivateDataBackupExpiryReceiptV1",
            _binding.execute_posix_expiry(
                plan,
                confirmation,
                journal,
                authority=self,
                io=_binding._private_io,
                private_base=lambda: self.layout.private_data_base,
                backup_parent=lambda key: _binding._backup_parent(self.layout, key),
                tombstone_name=lambda: _binding._tombstone_name(plan, confirmation),
                capture=lambda key, name: _binding._capture_target_snapshot(
                    _binding._backup_parent(self.layout, key) / name,
                    private_base=self.layout.private_data_base,
                ),
            ),
        )


def require_pre_effect_plan(
    self: _binding.CodingArchPrivateDataBackupExpiryOwner,
    plan: _binding.CodingArchPrivateDataBackupExpiryPlanV1,
) -> _binding.CodingArchPrivateDataTargetSnapshotV1:
    """Recheck every preview authority while the offline fence is held."""

    key = plan.installation_key
    completion, target_id = _binding.CodingArchPrivateDataRestoreOwner(
        self.layout, self.product
    )._current_completed_restore(key, plan.backup_id)
    if (
        completion.record_digest != plan.restore_completion_digest
        or target_id != plan.restored_target_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_03"])
    self._require_recovery_authority(plan)
    path = _binding._backup_parent(self.layout, key) / plan.backup_id
    snapshot = _binding._capture_target_snapshot(
        path, private_base=self.layout.private_data_base
    )
    if (
        snapshot.root_identity != plan.archive_root_identity
        or snapshot.target_id != plan.archive_target_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_04"])
    return snapshot


def require_recovery_authority(
    self: _binding.CodingArchPrivateDataBackupExpiryOwner,
    plan: _binding.CodingArchPrivateDataBackupExpiryPlanV1,
) -> None:
    key = plan.installation_key
    desired = self.product.desired_state.snapshot()
    if (
        desired.inventory_revision != plan.desired_inventory_revision
        or desired.installation(key).selection.desired_state != "absent"
    ):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_05"])
    confirmations = _binding.CodingArchPrivateDataRestoreConfirmationJournal(
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
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_06"])
    if not any(
        item.phase == "completed"
        and item.installation_key == key
        and item.backup_id == plan.backup_id
        and item.record_digest == plan.restore_completion_digest
        for item in _binding.CodingArchPrivateDataRestoreJournal(
            self.product.state_root
        ).events()
    ):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_07"])
    restored = _binding._capture_target_snapshot(
        _binding.coding_arch_installation_private_data_root(self.layout, key),
        private_base=self.layout.private_data_base,
    )
    if restored.target_id != plan.restored_target_id:
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_08"])


def preview_expiry(
    layout: _binding.CodingPluginLifecycleStateLayout,
    state_root: Path,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    confirmation_id: str,
    *,
    completed_restore: Callable[[], tuple[CodingArchPrivateDataRestoreEventV1, str]],
    desired_snapshot: Callable[[], PluginDesiredStateSnapshotV1],
) -> _binding.CodingArchPrivateDataBackupExpiryPlanV1:
    completion, target_id = completed_restore()
    confirmation = _binding.CodingArchPrivateDataRestoreConfirmationJournal(
        state_root
    ).require_current(
        confirmation_id,
        key,
        backup_id,
        completion,
        target_id,
        message=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_09"],
    )
    desired = desired_snapshot()
    if desired.installation(key).selection.desired_state != "absent":
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_10"])
    receipt, source, identity, archive_snapshot = (
        _binding.inspect_private_expiry_archive(
            layout.private_data_base,
            _binding._backup_parent(layout, key),
            backup_id,
            key,
            io=_binding._private_io,
            codec=_binding._archive_codec,
            recapture=lambda: _binding._capture_target_snapshot(
                _binding._backup_parent(layout, key) / backup_id,
                private_base=layout.private_data_base,
            ),
            installation_error=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_11"],
            changed_error=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_04"],
        )
    )
    return _binding.CodingArchPrivateDataBackupExpiryPlanV1(
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
    self: _binding.CodingArchPrivateDataBackupExpiryOwner,
    plan: _binding.CodingArchPrivateDataBackupExpiryPlanV1,
    *,
    actor_id: str,
    policy_revision: str,
) -> _binding.CodingArchPrivateDataBackupExpiryConfirmationV1:
    """Record independent operator acceptance of one current exact plan."""

    from loushang.coding.package.private_data_backup_expiry_journal import (
        CodingArchPrivateDataBackupExpiryJournal,
    )

    if not isinstance(plan, _binding.CodingArchPrivateDataBackupExpiryPlanV1):
        raise TypeError(_binding._PRIVATE_DATA_ATTESTATION_VALUES["message_01"])
    current = self.preview(plan.installation_key, plan.backup_id, plan.confirmation_id)
    if current != plan:
        raise ValueError(_binding._PRIVATE_DATA_ATTESTATION_VALUES["message_02"])
    return CodingArchPrivateDataBackupExpiryJournal(self.product.state_root).confirm(
        plan, actor_id=actor_id, policy_revision=policy_revision
    )

"""Original read-only/native custody over borrowed existing authorities.

Product factories, nominal types and diagnostics remain explicit temporary
binding dependencies. Resource and transaction instances stay single-owned.
"""

from __future__ import annotations

from loushang.coding.package import private_data_read_owner as _binding

from . import (
    private_data_backup_expiry,
    private_data_restore,
    private_data_restore_confirmation,
)


def verify_restore_confirmation(
    self: _binding.CodingArchPrivateDataReadOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    confirmation_id: str,
) -> _binding.CodingArchPrivateDataRestoreConfirmationV1:
    with self.offline():
        completion, target_id = self._current_completed_restore(key, backup_id)
        return private_data_restore_confirmation.require_current_confirmation(
            self.state_root,
            confirmation_id,
            key,
            backup_id,
            completion,
            target_id,
            message=_binding._PRIVATE_DATA_QUERY_VALUES["message_03"],
        )


def restore_preview(
    self: _binding.CodingArchPrivateDataReadOwner, key: _binding.PluginInstallationKeyV1, backup_id: str
) -> _binding.CodingArchPrivateDataRestorePlanV1:
    source_root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    if not _binding._digest(backup_id):
        raise ValueError(_binding._PRIVATE_DATA_QUERY_VALUES["invalid_restore_backup"])
    with self.offline():
        return private_data_restore.preview_restore(
            self.layout,
            self.state_root,
            source_root,
            key,
            backup_id,
            desired_snapshot=lambda: self.desired_state.capture_read_only()[0],
        )


def expiry_preview(
    self: _binding.CodingArchPrivateDataReadOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    confirmation_id: str,
) -> _binding.CodingArchPrivateDataBackupExpiryPlanV1:
    if not _binding._digest(backup_id):
        raise ValueError(_binding._PRIVATE_DATA_QUERY_VALUES["invalid_expiry_backup"])
    with self.offline():
        return private_data_backup_expiry.preview_expiry(
            self.layout,
            self.state_root,
            key,
            backup_id,
            confirmation_id,
            completed_restore=lambda: self._current_completed_restore(key, backup_id),
            desired_snapshot=lambda: self.desired_state.capture_read_only()[0],
        )


def current_completed_restore(
    self: _binding.CodingArchPrivateDataReadOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
) -> tuple[_binding.CodingArchPrivateDataRestoreEventV1, str]:
    return private_data_restore.current_completed_restore(
        self.layout,
        self.state_root,
        key,
        backup_id,
        desired_snapshot=lambda: self.desired_state.capture_read_only()[0],
    )

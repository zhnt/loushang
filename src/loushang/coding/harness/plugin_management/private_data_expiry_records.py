"""Private-data record and proof programs over original nominal values."""

from __future__ import annotations

from loushang.coding.package import private_data_backup_expiry_records as _binding


def validate_plan(self: _binding.CodingArchPrivateDataBackupExpiryPlanV1) -> None:
    if (
        not isinstance(self.installation_key, _binding.PluginInstallationKeyV1)
        or self.installation_key.plugin_id
        != _binding._PRIVATE_DATA_RECORD_VALUES["value_01"]
        or not _binding._digest(self.backup_id)
        or self.backup_receipt_id
        != _binding._PRIVATE_DATA_RECORD_VALUES["value_03"] + self.backup_id
        or not isinstance(self.source_target_id, str)
        or not self.source_target_id.startswith("present:")
        or not isinstance(self.confirmation_id, str)
        or not self.confirmation_id.startswith(
            _binding._PRIVATE_DATA_RECORD_VALUES["value_04"]
        )
        or not _binding._digest(self.restore_completion_digest)
        or not isinstance(self.restored_target_id, str)
        or not self.restored_target_id.startswith("present:")
        or type(self.desired_inventory_revision) is not int
        or self.desired_inventory_revision < 0
        or type(self.archive_root_identity) is not tuple
        or len(self.archive_root_identity) != 5
        or any(type(item) is not int or item < 0 for item in self.archive_root_identity)
        or not isinstance(self.archive_target_id, str)
        or not self.archive_target_id.startswith("present:")
        or self.plan_version != 1
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_02"])


def validate_confirmation(
    self: _binding.CodingArchPrivateDataBackupExpiryConfirmationV1,
) -> None:
    if (
        not _binding._digest(self.plan_fingerprint)
        or not _binding._label(self.actor_id)
        or not _binding._label(self.policy_revision)
        or self.confirmation_id
        != _binding._confirmation_id(
            self.plan_fingerprint, self.actor_id, self.policy_revision
        )
        or self.confirmation_version != 1
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_05"])


def validate_receipt(self: _binding.CodingArchPrivateDataBackupExpiryReceiptV1) -> None:
    if (
        not isinstance(self.installation_key, _binding.PluginInstallationKeyV1)
        or self.installation_key.plugin_id
        != _binding._PRIVATE_DATA_RECORD_VALUES["value_01"]
        or not _binding._digest(self.backup_id)
        or not _binding._digest(self.plan_fingerprint)
        or not isinstance(self.confirmation_id, str)
        or not self.confirmation_id.startswith(
            _binding._PRIVATE_DATA_RECORD_VALUES["value_07"]
        )
        or self.receipt_id
        != _binding._receipt_id(self.plan_fingerprint, self.confirmation_id)
        or self.receipt_version != 1
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_06"])

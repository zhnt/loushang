"""Private-data record and proof programs over original nominal values."""

from __future__ import annotations

from loushang.coding.package import private_data_backup_expiry_journal as _binding


def validate_event(self: _binding.CodingArchPrivateDataBackupExpiryEventV1) -> None:
    if (
        type(self.revision) is not int
        or self.revision < 1
        or self.phase not in {"confirmed", "started", "renamed", "completed"}
        or not isinstance(self.plan, _binding.CodingArchPrivateDataBackupExpiryPlanV1)
        or not isinstance(
            self.confirmation, _binding.CodingArchPrivateDataBackupExpiryConfirmationV1
        )
        or self.confirmation.plan_fingerprint != self.plan.fingerprint
        or self.record_version != 1
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_01"])
    if self.phase == "confirmed":
        if self.archive is not None or self.receipt is not None:
            raise ValueError("Unstarted backup expiry has effects")
        return
    if (
        not isinstance(self.archive, _binding.CodingArchPrivateDataTargetSnapshotV1)
        or self.archive.root_identity != self.plan.archive_root_identity
        or self.archive.target_id != self.plan.archive_target_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_02"])
    if self.phase == "completed":
        if not isinstance(
            self.receipt, _binding.CodingArchPrivateDataBackupExpiryReceiptV1
        ) or self.receipt != _binding.CodingArchPrivateDataBackupExpiryReceiptV1.create(
            self.plan, self.confirmation
        ):
            raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_03"])
    elif self.receipt is not None:
        raise ValueError("Unfinished backup expiry cannot claim a receipt")

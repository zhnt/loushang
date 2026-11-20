"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from loushang.coding.package import (
    private_data_windows_backup_expiry_journal as _binding,
)


def require_pre_effect_archive(
    self: _binding.CodingWindowsArchBackupExpiryTransaction,
    plan: _binding.CodingArchPrivateDataBackupExpiryPlanV1,
    parent_fd: int,
    acl: _binding.WindowsPrivateDirectoryAcl,
) -> _binding.CodingWindowsArchBackupArchiveSnapshotV1:
    self._require_current_plan(plan)
    receipt, source = _binding._read_archive_manifest(parent_fd, plan.backup_id, acl)
    archive = _binding.capture_windows_arch_backup_archive(
        self.layout, plan.installation_key, plan.backup_id, source, receipt
    )
    if archive.target_id != plan.archive_target_id:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    return archive


def validate_event(self: _binding.CodingWindowsArchBackupExpiryEventV1) -> None:
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
            raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_03"])
        return
    if (
        not isinstance(self.archive, _binding.CodingWindowsArchBackupArchiveSnapshotV1)
        or self.archive.root_identity != self.plan.archive_root_identity
        or self.archive.target_id != self.plan.archive_target_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_02"])
    if self.phase == "completed":
        if self.receipt != _binding.CodingArchPrivateDataBackupExpiryReceiptV1.create(
            self.plan, self.confirmation
        ):
            raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_04"])
    elif self.receipt is not None:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_05"])


def decode_event(
    cls: type[_binding.CodingWindowsArchBackupExpiryEventV1], value: object
) -> _binding.CodingWindowsArchBackupExpiryEventV1:
    if type(value) is not dict or set(value) != {
        "archive",
        "confirmation",
        "phase",
        "plan",
        "receipt",
        "recordVersion",
        "revision",
    }:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_06"])
    archive = value["archive"]
    receipt = value["receipt"]
    return cls(
        revision=value["revision"],
        phase=value["phase"],
        plan=_binding.CodingArchPrivateDataBackupExpiryPlanV1.from_dict(value["plan"]),
        confirmation=_binding.CodingArchPrivateDataBackupExpiryConfirmationV1.from_dict(
            value["confirmation"]
        ),
        archive=(
            None
            if archive is None
            else _binding.CodingWindowsArchBackupArchiveSnapshotV1.from_dict(archive)
        ),
        receipt=(
            None
            if receipt is None
            else _binding.CodingArchPrivateDataBackupExpiryReceiptV1.from_dict(receipt)
        ),
        record_version=value["recordVersion"],
    )

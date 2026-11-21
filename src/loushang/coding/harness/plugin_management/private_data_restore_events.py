"""Private-data record and proof programs over original nominal values."""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import private_data_restore_journal as _binding


def validate_event(self: _binding.CodingArchPrivateDataRestoreEventV1) -> None:
    if (
        type(self.revision) is not int
        or self.revision < 1
        or self.phase not in {"started", "completed"}
        or not isinstance(self.installation_key, _binding.PluginInstallationKeyV1)
        or self.installation_key.plugin_id
        != _binding._PRIVATE_DATA_RECORD_VALUES["value_01"]
        or not _binding._digest(self.backup_id)
        or not isinstance(self.deletion_receipt_id, str)
        or not self.deletion_receipt_id
        or self.restore_id
        != _binding.restore_id_for(
            self.installation_key, self.backup_id, self.deletion_receipt_id
        )
        or self.record_version != 1
        or self.record_digest
        != _binding.sha256(_binding.canonical_json_bytes(self._unsigned())).hexdigest()
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_02"])


def create_event(
    cls: type[_binding.CodingArchPrivateDataRestoreEventV1],
    *,
    revision: int,
    phase: Literal["started", "completed"],
    installation_key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    deletion_receipt_id: str,
) -> _binding.CodingArchPrivateDataRestoreEventV1:
    restore_id = _binding.restore_id_for(
        installation_key, backup_id, deletion_receipt_id
    )
    unsigned = {
        "backupId": backup_id,
        "deletionReceiptId": deletion_receipt_id,
        "installationKey": installation_key.to_dict(),
        "phase": phase,
        "recordVersion": 1,
        "restoreId": restore_id,
        "revision": revision,
    }
    return cls(
        revision=revision,
        phase=phase,
        installation_key=installation_key,
        backup_id=backup_id,
        deletion_receipt_id=deletion_receipt_id,
        restore_id=restore_id,
        record_digest=_binding.sha256(
            _binding.canonical_json_bytes(unsigned)
        ).hexdigest(),
    )

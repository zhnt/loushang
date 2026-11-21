"""Private-data record and proof programs over original nominal values."""

from __future__ import annotations

from loushang.coding.package import private_data_restore_records as _binding


def validate_plan(self: _binding.CodingArchPrivateDataRestorePlanV1) -> None:
    if (
        not isinstance(self.installation_key, _binding.PluginInstallationKeyV1)
        or self.installation_key.plugin_id
        != _binding._PRIVATE_DATA_RECORD_VALUES["value_01"]
        or not _binding._digest(self.backup_id)
        or not isinstance(self.deletion_receipt_id, str)
        or not self.deletion_receipt_id
        or not isinstance(self.source_target_id, str)
        or not self.source_target_id.startswith("present:")
        or type(self.desired_inventory_revision) is not int
        or self.desired_inventory_revision < 0
        or self.target_state not in {"absent", "same_bytes"}
        or self.plan_version != 1
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_02"])

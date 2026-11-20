"""Private-data record and proof programs over original nominal values."""

from __future__ import annotations

from loushang.coding.package import private_data_restore_confirmation as _binding


def validate_confirmation(
    self: _binding.CodingArchPrivateDataRestoreConfirmationV1,
) -> None:
    if (
        type(self.revision) is not int
        or self.revision < 1
        or not isinstance(self.installation_key, _binding.PluginInstallationKeyV1)
        or self.installation_key.plugin_id
        != _binding._PRIVATE_DATA_RECORD_VALUES["value_01"]
        or not _binding._digest(self.backup_id)
        or not isinstance(self.deletion_receipt_id, str)
        or not self.deletion_receipt_id
        or not isinstance(self.restore_id, str)
        or self.restore_id
        != _binding.restore_id_for(
            self.installation_key, self.backup_id, self.deletion_receipt_id
        )
        or not _binding._digest(self.restore_completion_digest)
        or not isinstance(self.restored_target_id, str)
        or not self.restored_target_id.startswith("present:")
        or self.record_version != 1
        or self.confirmation_id != self._expected_id()
        or self.record_digest
        != _binding.sha256(_binding.canonical_json_bytes(self._unsigned())).hexdigest()
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_02"])


def create_confirmation(
    cls: type[_binding.CodingArchPrivateDataRestoreConfirmationV1],
    *,
    revision: int,
    installation_key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    deletion_receipt_id: str,
    restore_id: str,
    restore_completion_digest: str,
    restored_target_id: str,
) -> _binding.CodingArchPrivateDataRestoreConfirmationV1:
    facts = {
        "backupId": backup_id,
        "deletionReceiptId": deletion_receipt_id,
        "installationKey": installation_key.to_dict(),
        "restoreCompletionDigest": restore_completion_digest,
        "restoredTargetId": restored_target_id,
        "restoreId": restore_id,
    }
    confirmation_id = (
        _binding._PRIVATE_DATA_RECORD_VALUES["value_03"]
        + _binding.sha256(
            _binding._PRIVATE_DATA_RECORD_BYTES["value_04"]
            + _binding.canonical_json_bytes(facts)
        ).hexdigest()
    )
    unsigned = {
        **facts,
        "confirmationId": confirmation_id,
        "recordVersion": 1,
        "revision": revision,
    }
    return cls(
        revision=revision,
        installation_key=installation_key,
        backup_id=backup_id,
        deletion_receipt_id=deletion_receipt_id,
        restore_id=restore_id,
        restore_completion_digest=restore_completion_digest,
        restored_target_id=restored_target_id,
        confirmation_id=confirmation_id,
        record_digest=_binding.sha256(
            _binding.canonical_json_bytes(unsigned)
        ).hexdigest(),
    )


def matches_restore_result(
    self: _binding.CodingArchPrivateDataRestoreConfirmationV1,
    other: _binding.CodingArchPrivateDataRestoreConfirmationV1,
) -> bool:
    return (
        self.to_dict()
        == {
            **other.to_dict(),
            "revision": self.revision,
            "recordDigest": self.record_digest,
        }
        and self.confirmation_id == other.confirmation_id
    )


def require_restore_confirmation(
    records: tuple[_binding.CodingArchPrivateDataRestoreConfirmationV1, ...],
    confirmation_id: str,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    completion: _binding.CodingArchPrivateDataRestoreEventV1,
    target_id: str,
    *,
    message: str,
) -> _binding.CodingArchPrivateDataRestoreConfirmationV1:
    matched = next(
        (item for item in reversed(records) if item.confirmation_id == confirmation_id),
        None,
    )
    if (
        matched is None
        or matched.installation_key != key
        or matched.backup_id != backup_id
        or matched.restore_id != completion.restore_id
        or matched.deletion_receipt_id != completion.deletion_receipt_id
        or matched.restore_completion_digest != completion.record_digest
        or matched.restored_target_id != target_id
    ):
        raise ValueError(message)
    return matched

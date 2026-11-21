"""Private-data record and proof programs over original nominal values."""

from __future__ import annotations

from loushang.coding.package import private_data_backup_records as _binding


def validate_receipt(self: _binding.CodingArchPrivateDataBackupReceiptV1) -> None:
    if (
        not isinstance(self.installation_key, _binding.PluginInstallationKeyV1)
        or self.installation_key.plugin_id != _binding._PLUGIN_ID
        or not isinstance(self.source_target_id, str)
        or not self.source_target_id.startswith("present:")
        or not _binding._digest(self.backup_id)
        or type(self.file_count) is not int
        or self.file_count < 0
        or type(self.byte_count) is not int
        or self.byte_count < 0
        or self.receipt_id
        != _binding._PRIVATE_DATA_RECORD_VALUES["value_02"] + self.backup_id
        or self.receipt_version != 1
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_01"])


def decode_manifest(
    self: _binding._BackupManifestCodec, document: object, *, identity_error: str
) -> tuple[
    _binding.CodingArchPrivateDataBackupReceiptV1,
    _binding.CodingArchPrivateDataTargetSnapshotV1,
]:
    if type(document) is not dict or set(document) != {"receipt", "source"}:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_03"])
    source = _binding.CodingArchPrivateDataTargetSnapshotV1.from_dict(
        document["source"]
    )
    receipt = _binding.CodingArchPrivateDataBackupReceiptV1.from_dict(
        document["receipt"]
    )
    if (
        receipt.source_target_id != source.target_id
        or receipt.backup_id != _binding.backup_id(receipt.installation_key, source)
    ):
        raise ValueError(identity_error)
    return receipt, source


def decode_posix_archive(
    self: _binding._ArchBackupCodec, raw: bytes
) -> tuple[
    _binding.CodingArchPrivateDataBackupReceiptV1,
    _binding.CodingArchPrivateDataTargetSnapshotV1,
]:
    document = _binding.json.loads(
        raw.decode("utf-8"), object_pairs_hook=_binding._posix_unique_object
    )
    return self._decode_backup_manifest(
        document, identity_error=_binding._PRIVATE_DATA_RECORD_VALUES["value_04"]
    )


def decode_windows_archive(
    self: _binding._WindowsArchBackupCodec, raw: bytes
) -> tuple[
    _binding.CodingArchPrivateDataBackupReceiptV1,
    _binding.CodingArchPrivateDataTargetSnapshotV1,
]:
    try:
        document = _binding.json.loads(
            bytes(raw).decode("utf-8"),
            object_pairs_hook=_binding._windows_unique_object,
        )
    except (UnicodeError, _binding.json.JSONDecodeError) as exc:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_06"]) from exc
    receipt, source = self._decode_backup_manifest(
        document, identity_error=_binding._PRIVATE_DATA_RECORD_VALUES["value_05"]
    )
    if bytes(raw) != _binding.canonical_json_bytes(document) + b"\n":
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_05"])
    return receipt, source


def make_backup_receipt(
    key: _binding.PluginInstallationKeyV1,
    source: _binding.CodingArchPrivateDataTargetSnapshotV1,
) -> _binding.CodingArchPrivateDataBackupReceiptV1:
    identity = _binding.backup_id(key, source)
    return _binding.CodingArchPrivateDataBackupReceiptV1(
        installation_key=key,
        source_target_id=source.target_id,
        backup_id=identity,
        file_count=sum(item.kind == "file" for item in source.members),
        byte_count=sum(
            item.identity[3] for item in source.members if item.kind == "file"
        ),
        receipt_id=_binding._PRIVATE_DATA_RECORD_VALUES["value_02"] + identity,
    )

"""Platform-neutral identity and receipt for one Coding Arch backup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1

if TYPE_CHECKING:
    from loushang.harness.plugin_management.application import (
        PluginBackupRetentionStatus,
    )

_PLUGIN_ID = "coding.arch.default"


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupReceiptV1:
    installation_key: PluginInstallationKeyV1
    source_target_id: str
    backup_id: str
    file_count: int
    byte_count: int
    receipt_id: str
    receipt_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.installation_key, PluginInstallationKeyV1)
            or self.installation_key.plugin_id != _PLUGIN_ID
            or not isinstance(self.source_target_id, str)
            or not self.source_target_id.startswith("present:")
            or not _digest(self.backup_id)
            or type(self.file_count) is not int
            or self.file_count < 0
            or type(self.byte_count) is not int
            or self.byte_count < 0
            or self.receipt_id != "arch-backup:" + self.backup_id
            or self.receipt_version != 1
        ):
            raise ValueError("Coding Arch backup receipt is invalid")

    def to_dict(self) -> dict[str, object]:
        return _SCHEMA_BACKUP_RECEIPT_V1.encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataBackupReceiptV1:
        if type(value) is not dict or set(value) != _SCHEMA_BACKUP_RECEIPT_V1.keys:
            raise ValueError("Coding Arch backup receipt fields are invalid")
        return _SCHEMA_BACKUP_RECEIPT_V1.decode(cls, value)


def backup_parent(
    layout: CodingPluginLifecycleStateLayout, key: PluginInstallationKeyV1
) -> Path:
    installation_id = coding_arch_installation_private_data_root(layout, key).name
    return layout.package_root / "installation-backups" / installation_id


def backup_id(
    key: PluginInstallationKeyV1, target: CodingArchPrivateDataTargetSnapshotV1
) -> str:
    return sha256(
        b"loushang.coding-arch-private-data-backup/v1\0"
        + canonical_json_bytes(
            {"installationKey": key.to_dict(), "sourceTargetId": target.target_id}
        )
    ).hexdigest()


def _backup_receipt(
    key: PluginInstallationKeyV1, source: CodingArchPrivateDataTargetSnapshotV1
) -> CodingArchPrivateDataBackupReceiptV1:
    identity = backup_id(key, source)
    return CodingArchPrivateDataBackupReceiptV1(
        installation_key=key,
        source_target_id=source.target_id,
        backup_id=identity,
        file_count=sum(item.kind == "file" for item in source.members),
        byte_count=sum(
            item.identity[3] for item in source.members if item.kind == "file"
        ),
        receipt_id="arch-backup:" + identity,
    )


class _BackupManifestCodec:
    max_manifest_bytes = 4 * 1024 * 1024
    files_name = "files"
    manifest_name = "manifest.json"
    stage_suffix = ".staging"

    def encode(
        self,
        key: PluginInstallationKeyV1,
        source: CodingArchPrivateDataTargetSnapshotV1,
        receipt: CodingArchPrivateDataBackupReceiptV1,
    ) -> bytes:
        facts = {"receipt": receipt.to_dict(), "source": source.to_dict()}
        return canonical_json_bytes(facts) + b"\n"

    def _decode_backup_manifest(
        self, document: object, *, identity_error: str
    ) -> tuple[
        CodingArchPrivateDataBackupReceiptV1, CodingArchPrivateDataTargetSnapshotV1
    ]:
        if type(document) is not dict or set(document) != {"receipt", "source"}:
            raise ValueError("Coding Arch backup manifest fields are invalid")
        source = CodingArchPrivateDataTargetSnapshotV1.from_dict(document["source"])
        receipt = CodingArchPrivateDataBackupReceiptV1.from_dict(document["receipt"])
        if (
            receipt.source_target_id != source.target_id
            or receipt.backup_id != backup_id(receipt.installation_key, source)
        ):
            raise ValueError(identity_error)
        return receipt, source


class _ArchBackupCodec(_BackupManifestCodec):
    def encode(
        self,
        key: PluginInstallationKeyV1,
        source: CodingArchPrivateDataTargetSnapshotV1,
        receipt: CodingArchPrivateDataBackupReceiptV1,
    ) -> bytes:
        if receipt.installation_key != key:
            raise ValueError("Coding Arch backup Installation changed")
        return super().encode(key, source, receipt)

    def decode(
        self, raw: bytes
    ) -> tuple[
        CodingArchPrivateDataBackupReceiptV1, CodingArchPrivateDataTargetSnapshotV1
    ]:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_posix_unique_object
        )
        return self._decode_backup_manifest(
            document, identity_error="Coding Arch backup manifest target changed"
        )


class _WindowsArchBackupCodec(_BackupManifestCodec):
    def decode(
        self, raw: bytes
    ) -> tuple[
        CodingArchPrivateDataBackupReceiptV1, CodingArchPrivateDataTargetSnapshotV1
    ]:
        try:
            document = json.loads(
                bytes(raw).decode("utf-8"), object_pairs_hook=_windows_unique_object
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Coding Arch backup manifest is invalid") from exc
        receipt, source = self._decode_backup_manifest(
            document, identity_error="Coding Arch backup manifest identity changed"
        )
        if bytes(raw) != canonical_json_bytes(document) + b"\n":
            raise ValueError("Coding Arch backup manifest identity changed")
        return receipt, source


_posix_unique_object = _unique_json_object_hook(
    lambda: "Coding Arch backup manifest has a duplicate JSON key",
)
_windows_unique_object = _unique_json_object_hook(
    lambda: "Coding Arch backup manifest has duplicate fields",
)


def _backup_retention_revision(
    status: PluginBackupRetentionStatus,
    expiry_receipt_id: str | None,
    receipts: tuple[CodingArchPrivateDataBackupReceiptV1, ...],
    trust: str,
) -> str:
    facts = {
        "expiryPhase": status,
        "expiryReceiptId": expiry_receipt_id,
        "receipts": [item.to_dict() for item in receipts],
        "trust": trust,
    }
    return sha256(
        b"loushang.coding-arch-backup-retention/v1\0" + canonical_json_bytes(facts)
    ).hexdigest()


_SCHEMA_BACKUP_RECEIPT_V1 = RecordSchema.for_dataclass(
    CodingArchPrivateDataBackupReceiptV1,
    lambda value: value,
    RecordField(
        "installation_key",
        decoder=PluginInstallationKeyV1.from_dict,
        encoder=PluginInstallationKeyV1.to_dict,
    ),
)

__all__ = [
    "CodingArchPrivateDataBackupReceiptV1",
    "backup_id",
    "backup_parent",
]

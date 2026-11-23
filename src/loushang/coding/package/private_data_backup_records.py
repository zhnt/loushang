"""Platform-neutral identity and receipt for one Coding Arch backup."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.plugin_management._private_data_records import (
    PRIVATE_DATA_INSTALLATION_KEY_FIELD,
    PrivateDataRecordWire,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,
)
from loushang.harness.plugin_management.private_data_backup import (
    PrivateArchiveManifestCodec,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .installation_private_data import coding_arch_installation_private_data_root
from .private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1

if TYPE_CHECKING:
    from loushang.harness.plugin_management.application import (
        PluginBackupRetentionStatus,
    )

_PLUGIN_ID = "coding.arch.default"


_RECEIPT_PREFIX = "arch-backup:"


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupReceiptV1(PrivateDataRecordWire):
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
            or self.receipt_id != _RECEIPT_PREFIX + self.backup_id
            or self.receipt_version != 1
        ):
            raise ValueError("Coding Arch backup receipt is invalid")

    _invalid_fields = "Coding Arch backup receipt fields are invalid"


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


def make_backup_receipt(
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
        receipt_id=_RECEIPT_PREFIX + identity,
    )


def backup_manifest_codec(
    *, windows: bool
) -> PrivateArchiveManifestCodec[
    CodingArchPrivateDataTargetSnapshotV1, CodingArchPrivateDataBackupReceiptV1
]:
    return PrivateArchiveManifestCodec(
        CodingArchPrivateDataTargetSnapshotV1,
        CodingArchPrivateDataBackupReceiptV1,
        backup_id,
        label="Coding Arch",
        windows=windows,
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


_SCHEMA_BACKUP_RECEIPT_V1 = CodingArchPrivateDataBackupReceiptV1._bind_wire_schema(
    PRIVATE_DATA_INSTALLATION_KEY_FIELD,
)

__all__ = [
    "CodingArchPrivateDataBackupReceiptV1",
    "backup_id",
    "backup_parent",
]

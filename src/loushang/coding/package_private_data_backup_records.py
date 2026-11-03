"""Platform-neutral identity and receipt for one Coding Arch backup."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1

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
        return {
            "backupId": self.backup_id,
            "byteCount": self.byte_count,
            "fileCount": self.file_count,
            "installationKey": self.installation_key.to_dict(),
            "receiptId": self.receipt_id,
            "receiptVersion": self.receipt_version,
            "sourceTargetId": self.source_target_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataBackupReceiptV1:
        if type(value) is not dict or set(value) != {
            "backupId",
            "byteCount",
            "fileCount",
            "installationKey",
            "receiptId",
            "receiptVersion",
            "sourceTargetId",
        }:
            raise ValueError("Coding Arch backup receipt fields are invalid")
        return cls(
            installation_key=PluginInstallationKeyV1.from_dict(
                value["installationKey"]
            ),
            source_target_id=value["sourceTargetId"],
            backup_id=value["backupId"],
            file_count=value["fileCount"],
            byte_count=value["byteCount"],
            receipt_id=value["receiptId"],
            receipt_version=value["receiptVersion"],
        )


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


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "CodingArchPrivateDataBackupReceiptV1",
    "backup_id",
    "backup_parent",
]

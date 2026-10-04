"""Platform-neutral plan and result records for Coding Arch backup restore."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_private_data_backup_records import _digest


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestorePlanV1:
    installation_key: PluginInstallationKeyV1
    backup_id: str
    deletion_receipt_id: str
    source_target_id: str
    desired_inventory_revision: int
    target_state: Literal["absent", "same_bytes"]
    plan_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.installation_key, PluginInstallationKeyV1)
            or self.installation_key.plugin_id != "coding.arch.default"
            or not _digest(self.backup_id)
            or not isinstance(self.deletion_receipt_id, str)
            or not self.deletion_receipt_id
            or not isinstance(self.source_target_id, str)
            or not self.source_target_id.startswith("present:")
            or type(self.desired_inventory_revision) is not int
            or self.desired_inventory_revision < 0
            or self.target_state not in {"absent", "same_bytes"}
            or self.plan_version != 1
        ):
            raise ValueError("Coding Arch restore plan is invalid")

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-arch-restore-plan/v1\0"
            + canonical_json_bytes(self.to_dict())
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "backupId": self.backup_id,
            "deletionReceiptId": self.deletion_receipt_id,
            "desiredInventoryRevision": self.desired_inventory_revision,
            "installationKey": self.installation_key.to_dict(),
            "planVersion": self.plan_version,
            "sourceTargetId": self.source_target_id,
            "targetState": self.target_state,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataRestorePlanV1:
        if type(value) is not dict or set(value) != {
            "backupId",
            "deletionReceiptId",
            "desiredInventoryRevision",
            "installationKey",
            "planVersion",
            "sourceTargetId",
            "targetState",
        }:
            raise ValueError("Coding Arch restore plan fields are invalid")
        return cls(
            installation_key=PluginInstallationKeyV1.from_dict(
                value["installationKey"]
            ),
            backup_id=value["backupId"],
            deletion_receipt_id=value["deletionReceiptId"],
            source_target_id=value["sourceTargetId"],
            desired_inventory_revision=value["desiredInventoryRevision"],
            target_state=value["targetState"],
            plan_version=value["planVersion"],
        )


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreResultV1:
    backup_id: str
    disposition: str
    restore_id: str


__all__ = ["CodingArchPrivateDataRestorePlanV1", "CodingArchPrivateDataRestoreResultV1"]

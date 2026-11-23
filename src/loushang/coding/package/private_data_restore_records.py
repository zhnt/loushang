"""Platform-neutral plan and result records for Coding Arch backup restore."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from loushang.harness.plugin_management._private_data_records import (
    PRIVATE_DATA_INSTALLATION_KEY_FIELD,
    PrivateDataRecordWire,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .private_data_backup_records import _digest as _digest


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestorePlanV1(PrivateDataRecordWire):
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

    _invalid_fields = "Coding Arch restore plan fields are invalid"


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreResultV1:
    backup_id: str
    disposition: str
    restore_id: str


_SCHEMA_RESTORE_PLAN_V1 = CodingArchPrivateDataRestorePlanV1._bind_wire_schema(
    PRIVATE_DATA_INSTALLATION_KEY_FIELD,
)

__all__ = ["CodingArchPrivateDataRestorePlanV1", "CodingArchPrivateDataRestoreResultV1"]

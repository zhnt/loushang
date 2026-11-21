"""Platform-neutral plan and result records for Coding Arch backup restore."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from loushang.coding.harness.plugin_management import (
    private_data_restore_records as _record_programs,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .private_data_backup_records import _digest as _digest

_PRIVATE_DATA_RECORD_VALUES = {
    "value_01": "coding.arch.default",
    "value_02": "Coding Arch restore plan is invalid",
}


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
        return _record_programs.validate_plan(self)

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-arch-restore-plan/v1\0"
            + canonical_json_bytes(self.to_dict())
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return _SCHEMA_RESTORE_PLAN_V1.encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataRestorePlanV1:
        if type(value) is not dict or set(value) != _SCHEMA_RESTORE_PLAN_V1.keys:
            raise ValueError("Coding Arch restore plan fields are invalid")
        return _SCHEMA_RESTORE_PLAN_V1.decode(cls, value)


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreResultV1:
    backup_id: str
    disposition: str
    restore_id: str


_SCHEMA_RESTORE_PLAN_V1 = RecordSchema.for_dataclass(
    CodingArchPrivateDataRestorePlanV1,
    lambda value: value,
    RecordField(
        "installation_key",
        decoder=PluginInstallationKeyV1.from_dict,
        encoder=PluginInstallationKeyV1.to_dict,
    ),
)

__all__ = ["CodingArchPrivateDataRestorePlanV1", "CodingArchPrivateDataRestoreResultV1"]

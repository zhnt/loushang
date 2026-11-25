"""Product-private start and completion evidence for Arch backup restoration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
)
from loushang.harness.plugin_management._private_data_records import (
    PrivateDataRestoreRecordWire,
    private_data_identity_digest,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,
)
from loushang.harness.plugin_management.private_data_restore_journal import (
    PrivateDataRestoreJournal,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

_JOURNAL_NAME = "private-data-restores.jsonl"
_MAX_EVENTS = 4096
_MAX_JOURNAL_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreEventV1(PrivateDataRestoreRecordWire):
    revision: int
    phase: Literal["started", "completed"]
    installation_key: PluginInstallationKeyV1
    backup_id: str
    deletion_receipt_id: str
    restore_id: str
    record_digest: str
    record_version: int = 1

    _unsigned_order = (
        "backupId",
        "deletionReceiptId",
        "installationKey",
        "phase",
        "recordVersion",
        "restoreId",
        "revision",
    )
    _invalid_fields = "Coding Arch restore event fields are invalid"

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int
            or self.revision < 1
            or self.phase not in {"started", "completed"}
            or not isinstance(self.installation_key, PluginInstallationKeyV1)
            or self.installation_key.plugin_id != "coding.arch.default"
            or not _digest(self.backup_id)
            or not isinstance(self.deletion_receipt_id, str)
            or not self.deletion_receipt_id
            or self.restore_id
            != restore_id_for(
                self.installation_key, self.backup_id, self.deletion_receipt_id
            )
            or self.record_version != 1
            or self.record_digest != self._digest_document(self._unsigned())
        ):
            raise ValueError("Coding Arch restore event is invalid")

    @classmethod
    def create(
        cls,
        *,
        revision: int,
        phase: Literal["started", "completed"],
        installation_key: PluginInstallationKeyV1,
        backup_id: str,
        deletion_receipt_id: str,
    ) -> CodingArchPrivateDataRestoreEventV1:
        return cls._seal(
            revision=revision,
            phase=phase,
            installation_key=installation_key,
            backup_id=backup_id,
            deletion_receipt_id=deletion_receipt_id,
            restore_id=restore_id_for(installation_key, backup_id, deletion_receipt_id),
            record_version=1,
        )


def restore_id_for(
    key: PluginInstallationKeyV1, backup_id: str, deletion_receipt_id: str
) -> str:
    if (
        not isinstance(key, PluginInstallationKeyV1)
        or not _digest(backup_id)
        or not isinstance(deletion_receipt_id, str)
        or not deletion_receipt_id
    ):
        raise ValueError("Coding Arch restore identity is invalid")
    return "arch-restore:" + private_data_identity_digest(
        b"loushang.coding-arch-private-data-restore/v1\0",
        {
            "backupId": backup_id,
            "deletionReceiptId": deletion_receipt_id,
            "installationKey": key.to_dict(),
        },
    )


_CODEC = FunctionalJournalRecordCodec.with_decode_error(
    encoder=CodingArchPrivateDataRestoreEventV1.to_dict,
    decoder=lambda value: CodingArchPrivateDataRestoreEventV1.from_dict(value),
    message="Coding Arch restore event is invalid",
    code="coding_arch_restore_event_invalid",
)


class CodingArchPrivateDataRestoreJournal(
    PrivateDataRestoreJournal[CodingArchPrivateDataRestoreEventV1]
):
    def __init__(self, state_root: Path) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or ".." in state_root.parts
        ):
            raise ValueError("Coding Arch restore state root is invalid")
        super().__init__(
            state_root / _JOURNAL_NAME,
            event_type=CodingArchPrivateDataRestoreEventV1,
            identity_for=restore_id_for,
            codec=_CODEC,
            label="Coding Arch",
            max_events=_MAX_EVENTS,
            max_bytes=_MAX_JOURNAL_BYTES,
        )


_SCHEMA_RESTORE_EVENT_V1 = (
    CodingArchPrivateDataRestoreEventV1._bind_restore_wire_schema()
)

__all__ = [
    "CodingArchPrivateDataRestoreEventV1",
    "CodingArchPrivateDataRestoreJournal",
    "restore_id_for",
]

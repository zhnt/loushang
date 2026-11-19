"""Product-private start and completion evidence for Arch backup restoration."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,
)
from loushang.harness.plugin_management.private_data_restore_journal import (
    PrivateDataRestoreJournal,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

_JOURNAL_NAME = "private-data-restores.jsonl"
_MAX_EVENTS = 4096
_MAX_JOURNAL_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreEventV1:
    revision: int
    phase: Literal["started", "completed"]
    installation_key: PluginInstallationKeyV1
    backup_id: str
    deletion_receipt_id: str
    restore_id: str
    record_digest: str
    record_version: int = 1

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
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned())).hexdigest()
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
        restore_id = restore_id_for(installation_key, backup_id, deletion_receipt_id)
        unsigned = {
            "backupId": backup_id,
            "deletionReceiptId": deletion_receipt_id,
            "installationKey": installation_key.to_dict(),
            "phase": phase,
            "recordVersion": 1,
            "restoreId": restore_id,
            "revision": revision,
        }
        return cls(
            revision=revision,
            phase=phase,
            installation_key=installation_key,
            backup_id=backup_id,
            deletion_receipt_id=deletion_receipt_id,
            restore_id=restore_id,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _unsigned(self) -> dict[str, object]:
        return {
            "backupId": self.backup_id,
            "deletionReceiptId": self.deletion_receipt_id,
            "installationKey": self.installation_key.to_dict(),
            "phase": self.phase,
            "recordVersion": self.record_version,
            "restoreId": self.restore_id,
            "revision": self.revision,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "recordDigest": self.record_digest}

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataRestoreEventV1:
        if type(value) is not dict or set(value) != _SCHEMA_RESTORE_EVENT_V1.keys:
            raise ValueError("Coding Arch restore event fields are invalid")
        return _SCHEMA_RESTORE_EVENT_V1.decode(cls, value)


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
    return (
        "arch-restore:"
        + sha256(
            b"loushang.coding-arch-private-data-restore/v1\0"
            + canonical_json_bytes(
                {
                    "backupId": backup_id,
                    "deletionReceiptId": deletion_receipt_id,
                    "installationKey": key.to_dict(),
                }
            )
        ).hexdigest()
    )


def _decode(value: object) -> CodingArchPrivateDataRestoreEventV1:
    try:
        return CodingArchPrivateDataRestoreEventV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Arch restore event is invalid",
            code="coding_arch_restore_event_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingArchPrivateDataRestoreEventV1.to_dict,
    decoder=_decode,
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


_SCHEMA_RESTORE_EVENT_V1 = RecordSchema.for_dataclass(
    CodingArchPrivateDataRestoreEventV1,
    lambda value: value,
    RecordField(
        "installation_key",
        decoder=PluginInstallationKeyV1.from_dict,
        encoder=PluginInstallationKeyV1.to_dict,
    ),
)

__all__ = [
    "CodingArchPrivateDataRestoreEventV1",
    "CodingArchPrivateDataRestoreJournal",
    "restore_id_for",
]

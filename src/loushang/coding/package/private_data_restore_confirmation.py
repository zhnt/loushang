"""Durable confirmation of one verified Coding Arch private-data restore."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.coding.harness.plugin_management import (
    private_data_restore_confirmation as _record_programs,
)
from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,  # noqa: F401
)
from loushang.harness.plugin_management.private_data_restore_journal import (
    PrivateDataRestoreConfirmationJournal,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .private_data_restore_journal import (
    restore_id_for as restore_id_for,
)

_JOURNAL_NAME = "private-data-restore-confirmations.jsonl"
_MAX_RECORDS = 4096
_MAX_BYTES = 32 * 1024 * 1024


_PRIVATE_DATA_RECORD_VALUES = {
    "value_01": "coding.arch.default",
    "value_02": "Coding Arch restore confirmation is invalid",
    "value_03": "arch-restore-confirm:",
}

_PRIVATE_DATA_RECORD_BYTES = {
    "value_04": b"loushang.coding-arch-restore-confirmation/v1\x00"
}


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreConfirmationV1:
    revision: int
    installation_key: PluginInstallationKeyV1
    backup_id: str
    deletion_receipt_id: str
    restore_id: str
    restore_completion_digest: str
    restored_target_id: str
    confirmation_id: str
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        return _record_programs.validate_confirmation(self)

    @classmethod
    def create(
        cls,
        *,
        revision: int,
        installation_key: PluginInstallationKeyV1,
        backup_id: str,
        deletion_receipt_id: str,
        restore_id: str,
        restore_completion_digest: str,
        restored_target_id: str,
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        return _record_programs.create_confirmation(
            cls,
            revision=revision,
            installation_key=installation_key,
            backup_id=backup_id,
            deletion_receipt_id=deletion_receipt_id,
            restore_id=restore_id,
            restore_completion_digest=restore_completion_digest,
            restored_target_id=restored_target_id,
        )

    def _facts(self) -> dict[str, object]:
        return {
            "backupId": self.backup_id,
            "deletionReceiptId": self.deletion_receipt_id,
            "installationKey": self.installation_key.to_dict(),
            "restoreCompletionDigest": self.restore_completion_digest,
            "restoredTargetId": self.restored_target_id,
            "restoreId": self.restore_id,
        }

    def _expected_id(self) -> str:
        return (
            "arch-restore-confirm:"
            + sha256(
                b"loushang.coding-arch-restore-confirmation/v1\0"
                + canonical_json_bytes(self._facts())
            ).hexdigest()
        )

    def _unsigned(self) -> dict[str, object]:
        return {
            **self._facts(),
            "confirmationId": self.confirmation_id,
            "recordVersion": self.record_version,
            "revision": self.revision,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "recordDigest": self.record_digest}

    def matches_restore_result(
        self, other: CodingArchPrivateDataRestoreConfirmationV1
    ) -> bool:
        return _record_programs.matches_restore_result(self, other)

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataRestoreConfirmationV1:
        if (
            type(value) is not dict
            or set(value) != _SCHEMA_RESTORE_CONFIRMATION_V1.keys
        ):
            raise ValueError("Coding Arch restore confirmation fields are invalid")
        return _SCHEMA_RESTORE_CONFIRMATION_V1.decode(cls, value)


def _decode(value: object) -> CodingArchPrivateDataRestoreConfirmationV1:
    try:
        return CodingArchPrivateDataRestoreConfirmationV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Arch restore confirmation is invalid",
            code="coding_arch_restore_confirmation_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingArchPrivateDataRestoreConfirmationV1.to_dict,
    decoder=_decode,
)


class CodingArchPrivateDataRestoreConfirmationJournal(
    PrivateDataRestoreConfirmationJournal[CodingArchPrivateDataRestoreConfirmationV1]
):
    def __init__(self, state_root: Path) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or ".." in state_root.parts
        ):
            raise ValueError("Coding Arch restore confirmation root is invalid")
        super().__init__(
            state_root / _JOURNAL_NAME,
            record_type=CodingArchPrivateDataRestoreConfirmationV1,
            codec=_CODEC,
            label="Coding Arch",
            max_records=_MAX_RECORDS,
            max_bytes=_MAX_BYTES,
        )


_SCHEMA_RESTORE_CONFIRMATION_V1 = RecordSchema.for_dataclass(
    CodingArchPrivateDataRestoreConfirmationV1,
    lambda value: value,
    RecordField(
        "installation_key",
        decoder=PluginInstallationKeyV1.from_dict,
        encoder=PluginInstallationKeyV1.to_dict,
    ),
)

__all__ = [
    "CodingArchPrivateDataRestoreConfirmationJournal",
    "CodingArchPrivateDataRestoreConfirmationV1",
]

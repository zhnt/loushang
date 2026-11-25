"""Durable confirmation of one verified Coding Arch private-data restore."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    PrivateDataRestoreConfirmationJournal,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from .private_data_restore_journal import (
    restore_id_for as restore_id_for,
)

_JOURNAL_NAME = "private-data-restore-confirmations.jsonl"
_MAX_RECORDS = 4096
_MAX_BYTES = 32 * 1024 * 1024
_CONFIRMATION_FIELDS = (
    "backupId",
    "deletionReceiptId",
    "installationKey",
    "restoreCompletionDigest",
    "restoredTargetId",
    "restoreId",
)


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreConfirmationV1(PrivateDataRestoreRecordWire):
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

    _unsigned_order = (
        *_CONFIRMATION_FIELDS,
        "confirmationId",
        "recordVersion",
        "revision",
    )
    _invalid_fields = "Coding Arch restore confirmation fields are invalid"

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int
            or self.revision < 1
            or not isinstance(self.installation_key, PluginInstallationKeyV1)
            or self.installation_key.plugin_id != "coding.arch.default"
            or not _digest(self.backup_id)
            or not isinstance(self.deletion_receipt_id, str)
            or not self.deletion_receipt_id
            or not isinstance(self.restore_id, str)
            or self.restore_id
            != restore_id_for(
                self.installation_key, self.backup_id, self.deletion_receipt_id
            )
            or not _digest(self.restore_completion_digest)
            or not isinstance(self.restored_target_id, str)
            or not self.restored_target_id.startswith("present:")
            or self.record_version != 1
            or self.confirmation_id != self._expected_id()
            or self.record_digest != self._digest_document(self._unsigned())
        ):
            raise ValueError("Coding Arch restore confirmation is invalid")

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
        values: dict[str, object] = {
            "installation_key": installation_key,
            "backup_id": backup_id,
            "deletion_receipt_id": deletion_receipt_id,
            "restore_id": restore_id,
            "restore_completion_digest": restore_completion_digest,
            "restored_target_id": restored_target_id,
        }
        return cls._seal(
            **values,
            revision=revision,
            record_version=1,
            confirmation_id=_confirmation_id(cls._encode_values(values)),
        )

    def _facts(self) -> dict[str, object]:
        document = self._unsigned()
        return {key: document[key] for key in _CONFIRMATION_FIELDS}

    def _expected_id(self) -> str:
        return _confirmation_id(self._facts())

    def matches_restore_result(
        self, other: CodingArchPrivateDataRestoreConfirmationV1
    ) -> bool:
        return (
            self.to_dict()
            == {
                **other.to_dict(),
                "revision": self.revision,
                "recordDigest": self.record_digest,
            }
            and self.confirmation_id == other.confirmation_id
        )


def _confirmation_id(facts: dict[str, object]) -> str:
    return "arch-restore-confirm:" + private_data_identity_digest(
        b"loushang.coding-arch-restore-confirmation/v1\0", facts
    )


_CODEC = FunctionalJournalRecordCodec.with_decode_error(
    encoder=CodingArchPrivateDataRestoreConfirmationV1.to_dict,
    decoder=lambda value: CodingArchPrivateDataRestoreConfirmationV1.from_dict(value),
    message="Coding Arch restore confirmation is invalid",
    code="coding_arch_restore_confirmation_invalid",
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


_SCHEMA_RESTORE_CONFIRMATION_V1 = (
    CodingArchPrivateDataRestoreConfirmationV1._bind_restore_wire_schema()
)

__all__ = [
    "CodingArchPrivateDataRestoreConfirmationJournal",
    "CodingArchPrivateDataRestoreConfirmationV1",
]

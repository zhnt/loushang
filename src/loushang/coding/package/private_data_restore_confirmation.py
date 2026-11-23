"""Durable confirmation of one verified Coding Arch private-data restore."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
)
from loushang.harness.plugin_management._private_data_records import (
    PRIVATE_DATA_INSTALLATION_KEY_FIELD,
    PrivateDataRecordWire,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,
)
from loushang.harness.plugin_management.private_data_restore_journal import (
    PrivateDataRestoreConfirmationJournal,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .private_data_restore_journal import (
    restore_id_for as restore_id_for,
)

_JOURNAL_NAME = "private-data-restore-confirmations.jsonl"
_MAX_RECORDS = 4096
_MAX_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreConfirmationV1(PrivateDataRecordWire):
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
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned())).hexdigest()
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
        facts = _confirmation_facts(
            installation_key,
            backup_id,
            deletion_receipt_id,
            restore_id,
            restore_completion_digest,
            restored_target_id,
        )
        confirmation_id = _confirmation_id(facts)
        unsigned = _confirmation_fields(facts, confirmation_id, revision, 1)
        return cls(
            revision=revision,
            installation_key=installation_key,
            backup_id=backup_id,
            deletion_receipt_id=deletion_receipt_id,
            restore_id=restore_id,
            restore_completion_digest=restore_completion_digest,
            restored_target_id=restored_target_id,
            confirmation_id=confirmation_id,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _facts(self) -> dict[str, object]:
        return _confirmation_facts(
            self.installation_key,
            self.backup_id,
            self.deletion_receipt_id,
            self.restore_id,
            self.restore_completion_digest,
            self.restored_target_id,
        )

    def _expected_id(self) -> str:
        return _confirmation_id(self._facts())

    def _unsigned(self) -> dict[str, object]:
        return _confirmation_fields(
            self._facts(), self.confirmation_id, self.revision, self.record_version
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "recordDigest": self.record_digest}

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

    _invalid_fields = "Coding Arch restore confirmation fields are invalid"


def _confirmation_facts(
    installation_key: PluginInstallationKeyV1,
    backup_id: str,
    deletion_receipt_id: str,
    restore_id: str,
    restore_completion_digest: str,
    restored_target_id: str,
) -> dict[str, object]:
    return {
        "backupId": backup_id,
        "deletionReceiptId": deletion_receipt_id,
        "installationKey": installation_key.to_dict(),
        "restoreCompletionDigest": restore_completion_digest,
        "restoredTargetId": restored_target_id,
        "restoreId": restore_id,
    }


def _confirmation_id(facts: dict[str, object]) -> str:
    return (
        "arch-restore-confirm:"
        + sha256(
            b"loushang.coding-arch-restore-confirmation/v1\0"
            + canonical_json_bytes(facts)
        ).hexdigest()
    )


def _confirmation_fields(
    facts: dict[str, object], confirmation_id: str, revision: int, record_version: int
) -> dict[str, object]:
    return {
        **facts,
        "confirmationId": confirmation_id,
        "recordVersion": record_version,
        "revision": revision,
    }


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
    CodingArchPrivateDataRestoreConfirmationV1._bind_wire_schema(
        PRIVATE_DATA_INSTALLATION_KEY_FIELD,
    )
)

__all__ = [
    "CodingArchPrivateDataRestoreConfirmationJournal",
    "CodingArchPrivateDataRestoreConfirmationV1",
]

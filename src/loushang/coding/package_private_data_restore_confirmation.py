"""Durable confirmation of one verified Coding Arch private-data restore."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,
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

from .package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
    restore_id_for,
)

_JOURNAL_NAME = "private-data-restore-confirmations.jsonl"
_MAX_RECORDS = 4096
_MAX_BYTES = 32 * 1024 * 1024


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
        facts = {
            "backupId": backup_id,
            "deletionReceiptId": deletion_receipt_id,
            "installationKey": installation_key.to_dict(),
            "restoreCompletionDigest": restore_completion_digest,
            "restoredTargetId": restored_target_id,
            "restoreId": restore_id,
        }
        confirmation_id = (
            "arch-restore-confirm:"
            + sha256(
                b"loushang.coding-arch-restore-confirmation/v1\0"
                + canonical_json_bytes(facts)
            ).hexdigest()
        )
        unsigned = {
            **facts,
            "confirmationId": confirmation_id,
            "recordVersion": 1,
            "revision": revision,
        }
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
        return (
            self.to_dict()
            == {
                **other.to_dict(),
                "revision": self.revision,
                "recordDigest": self.record_digest,
            }
            and self.confirmation_id == other.confirmation_id
        )

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


def _require_restore_confirmation(
    records: tuple[CodingArchPrivateDataRestoreConfirmationV1, ...],
    confirmation_id: str,
    key: PluginInstallationKeyV1,
    backup_id: str,
    completion: CodingArchPrivateDataRestoreEventV1,
    target_id: str,
    *,
    message: str,
) -> CodingArchPrivateDataRestoreConfirmationV1:
    matched = next(
        (item for item in reversed(records) if item.confirmation_id == confirmation_id),
        None,
    )
    if (
        matched is None
        or matched.installation_key != key
        or matched.backup_id != backup_id
        or matched.restore_id != completion.restore_id
        or matched.deletion_receipt_id != completion.deletion_receipt_id
        or matched.restore_completion_digest != completion.record_digest
        or matched.restored_target_id != target_id
    ):
        raise ValueError(message)
    return matched


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

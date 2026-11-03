"""Durable confirmation of one verified Coding Arch private-data restore."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_private_data_restore_journal import restore_id_for

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

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataRestoreConfirmationV1:
        if type(value) is not dict or set(value) != {
            "backupId",
            "confirmationId",
            "deletionReceiptId",
            "installationKey",
            "recordDigest",
            "recordVersion",
            "restoreCompletionDigest",
            "restoredTargetId",
            "restoreId",
            "revision",
        }:
            raise ValueError("Coding Arch restore confirmation fields are invalid")
        return cls(
            revision=value["revision"],
            installation_key=PluginInstallationKeyV1.from_dict(
                value["installationKey"]
            ),
            backup_id=value["backupId"],
            deletion_receipt_id=value["deletionReceiptId"],
            restore_id=value["restoreId"],
            restore_completion_digest=value["restoreCompletionDigest"],
            restored_target_id=value["restoredTargetId"],
            confirmation_id=value["confirmationId"],
            record_digest=value["recordDigest"],
            record_version=value["recordVersion"],
        )


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


class CodingArchPrivateDataRestoreConfirmationJournal:
    """Append one exact verified tree confirmation per completed restore."""

    def __init__(self, state_root: Path) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or ".." in state_root.parts
        ):
            raise ValueError("Coding Arch restore confirmation root is invalid")
        self._path = state_root / _JOURNAL_NAME
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

    @property
    def path(self) -> Path:
        return self._path

    def records(self) -> tuple[CodingArchPrivateDataRestoreConfirmationV1, ...]:
        self._require_private_parent()
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            return self._load_unlocked()

    def record(
        self, confirmation: CodingArchPrivateDataRestoreConfirmationV1
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        if not isinstance(confirmation, CodingArchPrivateDataRestoreConfirmationV1):
            raise TypeError("Coding Arch restore confirmation is required")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            records = self._load_unlocked()
            previous = next(
                (
                    item
                    for item in reversed(records)
                    if item.restore_id == confirmation.restore_id
                ),
                None,
            )
            if previous is not None:
                if (
                    previous.to_dict()
                    != {
                        **confirmation.to_dict(),
                        "revision": previous.revision,
                        "recordDigest": previous.record_digest,
                    }
                    or previous.confirmation_id != confirmation.confirmation_id
                ):
                    raise ValueError("Coding Arch restore confirmation changed")
                return previous
            if (
                len(records) >= _MAX_RECORDS
                or confirmation.revision != len(records) + 1
            ):
                raise ValueError("Coding Arch restore confirmation revision changed")
            append_jsonl_record(
                self._path,
                confirmation,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
            )
            return confirmation

    def _load_unlocked(self) -> tuple[CodingArchPrivateDataRestoreConfirmationV1, ...]:
        try:
            metadata = self._path.lstat()
        except FileNotFoundError:
            return ()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or metadata.st_size > _MAX_BYTES
        ):
            raise ValueError("Coding Arch restore confirmation journal is unsafe")
        loaded: JsonlSnapshot[None, CodingArchPrivateDataRestoreConfirmationV1] = (
            load_jsonl(
                self._path,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
                load_policy=self._load_policy,
            )
        )
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line, object_pairs_hook=_unique_object)
        records = loaded.records
        if len(records) > _MAX_RECORDS:
            raise ValueError("Coding Arch restore confirmation journal is full")
        seen: set[str] = set()
        for revision, record in enumerate(records, 1):
            if record.revision != revision or record.restore_id in seen:
                raise ValueError("Coding Arch restore confirmations changed")
            seen.add(record.restore_id)
        return records

    def _require_private_parent(self) -> None:
        metadata = self._path.parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("Coding Arch restore confirmation root is not private")


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Coding Arch restore confirmation repeats a field")
        result[key] = value
    return result


__all__ = [
    "CodingArchPrivateDataRestoreConfirmationJournal",
    "CodingArchPrivateDataRestoreConfirmationV1",
]

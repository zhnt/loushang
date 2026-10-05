"""Product-private start and completion evidence for Arch backup restoration."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal

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
        restore_id = restore_id_for(
            installation_key, backup_id, deletion_receipt_id
        )
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
        if type(value) is not dict or set(value) != {
            "backupId",
            "deletionReceiptId",
            "installationKey",
            "phase",
            "recordDigest",
            "recordVersion",
            "restoreId",
            "revision",
        }:
            raise ValueError("Coding Arch restore event fields are invalid")
        return cls(
            revision=value["revision"],
            phase=value["phase"],
            installation_key=PluginInstallationKeyV1.from_dict(
                value["installationKey"]
            ),
            backup_id=value["backupId"],
            deletion_receipt_id=value["deletionReceiptId"],
            restore_id=value["restoreId"],
            record_digest=value["recordDigest"],
            record_version=value["recordVersion"],
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
    return "arch-restore:" + sha256(
        b"loushang.coding-arch-private-data-restore/v1\0"
        + canonical_json_bytes(
            {
                "backupId": backup_id,
                "deletionReceiptId": deletion_receipt_id,
                "installationKey": key.to_dict(),
            }
        )
    ).hexdigest()


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


class CodingArchPrivateDataRestoreJournal:
    """Serialize exact restore retries in the Product private state root."""

    def __init__(self, state_root: Path) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or ".." in state_root.parts
        ):
            raise ValueError("Coding Arch restore state root is invalid")
        self._path = state_root / _JOURNAL_NAME
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(
            partial_tail="raise", create_lock=False
        )

    @property
    def path(self) -> Path:
        return self._path

    def events(self) -> tuple[CodingArchPrivateDataRestoreEventV1, ...]:
        self._require_private_parent()
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            return self._load_unlocked()

    def begin(
        self,
        *,
        key: PluginInstallationKeyV1,
        backup_id: str,
        deletion_receipt_id: str,
    ) -> CodingArchPrivateDataRestoreEventV1:
        restore_id = restore_id_for(key, backup_id, deletion_receipt_id)
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked()
            if any(
                item.deletion_receipt_id == deletion_receipt_id
                and item.installation_key == key
                and item.restore_id != restore_id
                for item in events
            ):
                raise ValueError("Coding Arch deletion has another restore")
            if (
                events
                and events[-1].phase == "started"
                and events[-1].restore_id != restore_id
            ):
                raise ValueError("Another Coding Arch restore is unfinished")
            existing = next(
                (item for item in reversed(events) if item.restore_id == restore_id),
                None,
            )
            if existing is not None:
                return existing
            if len(events) >= _MAX_EVENTS:
                raise ValueError("Coding Arch restore journal is full")
            started = CodingArchPrivateDataRestoreEventV1.create(
                revision=len(events) + 1,
                phase="started",
                installation_key=key,
                backup_id=backup_id,
                deletion_receipt_id=deletion_receipt_id,
            )
            self._append(started)
            return started

    def complete(
        self, started: CodingArchPrivateDataRestoreEventV1
    ) -> CodingArchPrivateDataRestoreEventV1:
        if started.phase != "started":
            raise ValueError("Coding Arch restore start is required")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked()
            if (
                events
                and events[-1].phase == "completed"
                and events[-1].restore_id == started.restore_id
            ):
                return events[-1]
            if not events or events[-1] != started or len(events) >= _MAX_EVENTS:
                raise ValueError("Coding Arch restore start changed")
            completed = CodingArchPrivateDataRestoreEventV1.create(
                revision=len(events) + 1,
                phase="completed",
                installation_key=started.installation_key,
                backup_id=started.backup_id,
                deletion_receipt_id=started.deletion_receipt_id,
            )
            self._append(completed)
            return completed

    def _append(self, event: CodingArchPrivateDataRestoreEventV1) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
        )

    def _load_unlocked(self) -> tuple[CodingArchPrivateDataRestoreEventV1, ...]:
        if not self._require_safe_journal():
            return ()
        loaded: JsonlSnapshot[None, CodingArchPrivateDataRestoreEventV1] = load_jsonl(
            self._path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            load_policy=self._load_policy,
        )
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line, object_pairs_hook=_unique_object)
        events: tuple[CodingArchPrivateDataRestoreEventV1, ...] = loaded.records
        if len(events) > _MAX_EVENTS:
            raise ValueError("Coding Arch restore journal is full")
        pending: CodingArchPrivateDataRestoreEventV1 | None = None
        seen: set[str] = set()
        for revision, event in enumerate(events, 1):
            if event.revision != revision:
                raise ValueError("Coding Arch restore revisions changed")
            if event.phase == "started":
                if pending is not None or event.restore_id in seen:
                    raise ValueError("Coding Arch restore starts changed")
                pending = event
                seen.add(event.restore_id)
            elif (
                pending is None
                or event.restore_id != pending.restore_id
                or event.installation_key != pending.installation_key
                or event.backup_id != pending.backup_id
                or event.deletion_receipt_id != pending.deletion_receipt_id
            ):
                raise ValueError("Coding Arch restore completion changed")
            else:
                pending = None
        return events

    def _require_safe_journal(self) -> bool:
        try:
            metadata = self._path.lstat()
        except FileNotFoundError:
            return False
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or metadata.st_size > _MAX_JOURNAL_BYTES
        ):
            raise ValueError("Coding Arch restore journal is unsafe")
        return True

    def _require_private_parent(self) -> None:
        metadata = self._path.parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("Coding Arch restore Product state is not private")


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
            raise ValueError("Coding Arch restore event repeats a field")
        result[key] = value
    return result


__all__ = [
    "CodingArchPrivateDataRestoreEventV1",
    "CodingArchPrivateDataRestoreJournal",
    "restore_id_for",
]

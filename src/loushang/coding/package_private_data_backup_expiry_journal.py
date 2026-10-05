"""Private confirmation and crash-recovery history for one Arch backup expiry.

Only the archive owner may perform filesystem effects. This journal records
the exact reviewed plan, original archive tree, rename checkpoint, and receipt.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, replace
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

from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)

_JOURNAL_NAME = "private-data-backup-expiries.jsonl"
_MAX_RECORDS = 4096
_MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupExpiryEventV1:
    revision: int
    phase: Literal["confirmed", "started", "renamed", "completed"]
    plan: CodingArchPrivateDataBackupExpiryPlanV1
    confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1
    archive: CodingArchPrivateDataTargetSnapshotV1 | None = None
    receipt: CodingArchPrivateDataBackupExpiryReceiptV1 | None = None
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int
            or self.revision < 1
            or self.phase not in {"confirmed", "started", "renamed", "completed"}
            or not isinstance(self.plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or not isinstance(
                self.confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1
            )
            or self.confirmation.plan_fingerprint != self.plan.fingerprint
            or self.record_version != 1
        ):
            raise ValueError("Coding Arch backup expiry event is invalid")
        if self.phase == "confirmed":
            if self.archive is not None or self.receipt is not None:
                raise ValueError("Unstarted backup expiry has effects")
            return
        if (
            not isinstance(self.archive, CodingArchPrivateDataTargetSnapshotV1)
            or self.archive.root_identity != self.plan.archive_root_identity
            or self.archive.target_id != self.plan.archive_target_id
        ):
            raise ValueError("Coding Arch backup expiry archive changed")
        if self.phase == "completed":
            if not isinstance(
                self.receipt, CodingArchPrivateDataBackupExpiryReceiptV1
            ) or self.receipt != CodingArchPrivateDataBackupExpiryReceiptV1.create(
                self.plan, self.confirmation
            ):
                raise ValueError("Coding Arch backup expiry receipt changed")
        elif self.receipt is not None:
            raise ValueError("Unfinished backup expiry cannot claim a receipt")

    def to_dict(self) -> dict[str, object]:
        return {
            "archive": None if self.archive is None else self.archive.to_dict(),
            "confirmation": self.confirmation.to_dict(),
            "phase": self.phase,
            "plan": self.plan.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "recordVersion": self.record_version,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataBackupExpiryEventV1:
        if type(value) is not dict or set(value) != {
            "archive",
            "confirmation",
            "phase",
            "plan",
            "receipt",
            "recordVersion",
            "revision",
        }:
            raise ValueError("Coding Arch backup expiry event fields are invalid")
        archive = value["archive"]
        receipt = value["receipt"]
        return cls(
            revision=value["revision"],
            phase=value["phase"],
            plan=CodingArchPrivateDataBackupExpiryPlanV1.from_dict(value["plan"]),
            confirmation=CodingArchPrivateDataBackupExpiryConfirmationV1.from_dict(
                value["confirmation"]
            ),
            archive=(
                None
                if archive is None
                else CodingArchPrivateDataTargetSnapshotV1.from_dict(archive)
            ),
            receipt=(
                None
                if receipt is None
                else CodingArchPrivateDataBackupExpiryReceiptV1.from_dict(receipt)
            ),
            record_version=value["recordVersion"],
        )


def _decode(value: object) -> CodingArchPrivateDataBackupExpiryEventV1:
    try:
        return CodingArchPrivateDataBackupExpiryEventV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Arch backup expiry event is invalid",
            code="coding_arch_backup_expiry_record_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingArchPrivateDataBackupExpiryEventV1.to_dict,
    decoder=_decode,
)


class CodingArchPrivateDataBackupExpiryJournal:
    """One append-only exact attempt at a time in the Product state root."""

    def __init__(self, state_root: Path) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or ".." in state_root.parts
        ):
            raise ValueError("Coding Arch backup expiry state root is invalid")
        self._path = state_root / _JOURNAL_NAME
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._write_policy = JournalLoadPolicy(partial_tail="repair")
        self._read_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

    @property
    def path(self) -> Path:
        return self._path

    def events(self) -> tuple[CodingArchPrivateDataBackupExpiryEventV1, ...]:
        self._require_private_parent()
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            return self._load(self._read_policy)

    def confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        confirmation = CodingArchPrivateDataBackupExpiryConfirmationV1.create(
            plan, actor_id=actor_id, policy_revision=policy_revision
        )
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load(self._write_policy)
            if events and events[-1].phase != "completed":
                last = events[-1]
                if last.plan == plan and last.confirmation == confirmation:
                    return confirmation
                raise ValueError("Another Coding Arch backup expiry is unfinished")
            if events and events[-1].plan == plan:
                if events[-1].confirmation == confirmation:
                    return confirmation
                raise ValueError("Coding Arch backup expiry was already completed")
            if any(
                event.phase == "completed" and event.plan.backup_id == plan.backup_id
                for event in events
            ):
                raise ValueError("Coding Arch backup expiry was already completed")
            event = CodingArchPrivateDataBackupExpiryEventV1(
                revision=len(events) + 1,
                phase="confirmed",
                plan=plan,
                confirmation=confirmation,
            )
            self._append(event)
            return confirmation

    def begin(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
        archive: CodingArchPrivateDataTargetSnapshotV1,
    ) -> CodingArchPrivateDataBackupExpiryEventV1:
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load(self._write_policy)
            if not events or (
                events[-1].plan != plan or events[-1].confirmation != confirmation
            ):
                raise ValueError("Coding Arch backup expiry confirmation changed")
            last = events[-1]
            if last.phase != "confirmed":
                if last.archive == archive:
                    return last
                raise ValueError("Coding Arch backup expiry archive changed")
            event = CodingArchPrivateDataBackupExpiryEventV1(
                revision=len(events) + 1,
                phase="started",
                plan=plan,
                confirmation=confirmation,
                archive=archive,
            )
            self._append(event)
            return event

    def advance(
        self,
        prior: CodingArchPrivateDataBackupExpiryEventV1,
        phase: Literal["renamed", "completed"],
    ) -> CodingArchPrivateDataBackupExpiryEventV1:
        if phase not in {"renamed", "completed"}:
            raise ValueError("Coding Arch backup expiry transition is invalid")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load(self._write_policy)
            if not events or events[-1] != prior:
                raise ValueError("Coding Arch backup expiry checkpoint changed")
            if prior.phase == phase:
                return prior
            if (phase == "renamed" and prior.phase != "started") or (
                phase == "completed" and prior.phase != "renamed"
            ):
                raise ValueError("Coding Arch backup expiry checkpoint is out of order")
            event = CodingArchPrivateDataBackupExpiryEventV1(
                revision=len(events) + 1,
                phase=phase,
                plan=prior.plan,
                confirmation=prior.confirmation,
                archive=prior.archive,
                receipt=(
                    CodingArchPrivateDataBackupExpiryReceiptV1.create(
                        prior.plan, prior.confirmation
                    )
                    if phase == "completed"
                    else None
                ),
            )
            self._append(event)
            return event

    def _append(self, event: CodingArchPrivateDataBackupExpiryEventV1) -> None:
        if event.revision > _MAX_RECORDS:
            raise ValueError("Coding Arch backup expiry journal is full")
        append_jsonl_record(
            self._path,
            event,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
        )

    def _load(
        self, policy: JournalLoadPolicy
    ) -> tuple[CodingArchPrivateDataBackupExpiryEventV1, ...]:
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
            raise ValueError("Coding Arch backup expiry journal is unsafe")
        loaded: JsonlSnapshot[None, CodingArchPrivateDataBackupExpiryEventV1] = (
            load_jsonl(
                self._path,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
                load_policy=policy,
            )
        )
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line, object_pairs_hook=_unique_object)
        events = loaded.records
        if len(events) > _MAX_RECORDS:
            raise ValueError("Coding Arch backup expiry journal is full")
        previous: CodingArchPrivateDataBackupExpiryEventV1 | None = None
        completed_backups: set[str] = set()
        for revision, event in enumerate(events, 1):
            if event.revision != revision:
                raise ValueError("Coding Arch backup expiry revision changed")
            if event.phase == "confirmed":
                if previous is not None and previous.phase != "completed":
                    raise ValueError("Coding Arch backup expiry history overlaps")
                if event.plan.backup_id in completed_backups:
                    raise ValueError("Coding Arch backup expiry was repeated")
            elif (
                previous is None
                or previous.plan != event.plan
                or previous.confirmation != event.confirmation
                or (event.phase == "started" and previous.phase != "confirmed")
                or (event.phase == "renamed" and previous.phase != "started")
                or (event.phase == "completed" and previous.phase != "renamed")
                or (
                    event.phase in {"renamed", "completed"}
                    and previous.archive != event.archive
                )
            ):
                raise ValueError("Coding Arch backup expiry history changed")
            if event.phase == "completed":
                completed_backups.add(event.plan.backup_id)
            previous = event
        return events

    def _require_private_parent(self) -> None:
        metadata = self._path.parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("Coding Arch backup expiry state root is not private")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Coding Arch backup expiry repeats a field")
        result[key] = value
    return result


__all__ = [
    "CodingArchPrivateDataBackupExpiryConfirmationV1",
    "CodingArchPrivateDataBackupExpiryEventV1",
    "CodingArchPrivateDataBackupExpiryJournal",
    "CodingArchPrivateDataBackupExpiryReceiptV1",
]

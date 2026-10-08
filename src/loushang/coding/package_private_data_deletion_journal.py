"""Product-private start and receipt history for exact Arch data deletion.

The journal records authority and recovery state. It performs no filesystem
deletion; the Coding data-domain owner must hold Product quiescence around it.
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
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)

from .package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)

_JOURNAL_NAME = "private-data-deletions.jsonl"


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataDeletionEventV1:
    revision: int
    phase: Literal["started", "renamed", "completed"]
    plan: PluginPrivateDataDeletionPlanV1
    confirmation: PluginPrivateDataDeletionConfirmationV1
    target: CodingArchPrivateDataTargetSnapshotV1
    receipt: PluginPrivateDataDeletionReceiptV1 | None = None
    record_version: int = 1

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("Private-data deletion revision is invalid")
        if (
            self.phase not in {"started", "renamed", "completed"}
            or self.record_version != 1
        ):
            raise ValueError("Private-data deletion event phase is invalid")
        if (
            not isinstance(self.plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(
                self.confirmation, PluginPrivateDataDeletionConfirmationV1
            )
            or not isinstance(self.target, CodingArchPrivateDataTargetSnapshotV1)
            or self.plan.target_id != self.target.target_id
            or self.confirmation.plan_fingerprint != self.plan.fingerprint
        ):
            raise ValueError("Private-data deletion event target changed")
        if self.phase in {"started", "renamed"}:
            if self.receipt is not None:
                raise ValueError("Unfinished deletion cannot claim a receipt")
            if self.phase == "renamed" and self.target.root_identity is None:
                raise ValueError("Absent deletion target cannot be renamed")
        elif (
            not isinstance(self.receipt, PluginPrivateDataDeletionReceiptV1)
            or self.receipt.installation_key != self.plan.installation_key
            or self.receipt.owner_id != self.plan.owner_id
            or self.receipt.target_id != self.plan.target_id
            or self.receipt.plan_fingerprint != self.plan.fingerprint
            or self.receipt.confirmation_id != self.confirmation.confirmation_id
        ):
            raise ValueError("Private-data deletion receipt changed")

    def to_dict(self) -> dict[str, object]:
        return {
            "confirmation": self.confirmation.to_dict(),
            "phase": self.phase,
            "plan": self.plan.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "recordVersion": self.record_version,
            "revision": self.revision,
            "target": self.target.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataDeletionEventV1:
        if type(value) is not dict or set(value) != {
            "confirmation",
            "phase",
            "plan",
            "receipt",
            "recordVersion",
            "revision",
            "target",
        }:
            raise ValueError("Private-data deletion event fields are invalid")
        receipt = value["receipt"]
        return cls(
            revision=value["revision"],
            phase=value["phase"],
            plan=PluginPrivateDataDeletionPlanV1.from_dict(value["plan"]),
            confirmation=PluginPrivateDataDeletionConfirmationV1.from_dict(
                value["confirmation"]
            ),
            target=CodingArchPrivateDataTargetSnapshotV1.from_dict(value["target"]),
            receipt=(
                None
                if receipt is None
                else PluginPrivateDataDeletionReceiptV1.from_dict(receipt)
            ),
            record_version=value["recordVersion"],
        )


def _decode(value: object) -> CodingArchPrivateDataDeletionEventV1:
    try:
        return CodingArchPrivateDataDeletionEventV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Arch private-data deletion event is invalid",
            code="coding_arch_private_data_deletion_record_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingArchPrivateDataDeletionEventV1.to_dict,
    decoder=_decode,
)


class CodingArchPrivateDataDeletionJournal:
    """Append-only start/terminal pairs in one fenced Product state root."""

    def __init__(self, state_root: Path) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or ".." in state_root.parts
        ):
            raise ValueError("Coding Arch deletion Product state root is invalid")
        self._path = state_root / _JOURNAL_NAME
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._write_policy = JournalLoadPolicy(partial_tail="repair")
        self._read_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

    @property
    def path(self) -> Path:
        return self._path

    def events(self) -> tuple[CodingArchPrivateDataDeletionEventV1, ...]:
        self._require_private_parent()
        self._require_safe_journal()
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            return self._load_unlocked(self._read_policy)

    def started_for(
        self, plan: PluginPrivateDataDeletionPlanV1
    ) -> CodingArchPrivateDataDeletionEventV1 | None:
        events = self.events()
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.plan.installation_key == plan.installation_key:
                if event.phase == "completed":
                    return None
                return event if event.plan == plan else None
        return None

    def current_start(self) -> CodingArchPrivateDataDeletionEventV1 | None:
        return _open_start(self.events())

    def receipt_for(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1 | None:
        for event in reversed(self.events()):
            if (
                event.phase == "completed"
                and event.plan == plan
                and event.confirmation == confirmation
            ):
                return event.receipt
        return None

    def record_start(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
        target: CodingArchPrivateDataTargetSnapshotV1,
    ) -> CodingArchPrivateDataDeletionEventV1:
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked(self._write_policy)
            open_start = _open_start(events)
            if open_start is not None:
                if (
                    open_start.plan == plan
                    and open_start.confirmation == confirmation
                    and open_start.target == target
                ):
                    return open_start
                raise ValueError("Another private-data deletion is unfinished")
            if any(
                event.phase == "completed"
                and event.confirmation.confirmation_id == confirmation.confirmation_id
                for event in events
            ):
                raise ValueError("Private-data confirmation was already consumed")
            event = CodingArchPrivateDataDeletionEventV1(
                revision=len(events) + 1,
                phase="started",
                plan=plan,
                confirmation=confirmation,
                target=target,
            )
            self._append(event)
            return event

    def record_completion(
        self,
        started: CodingArchPrivateDataDeletionEventV1,
        receipt: PluginPrivateDataDeletionReceiptV1,
    ) -> CodingArchPrivateDataDeletionEventV1:
        if started.phase not in {"started", "renamed"}:
            raise ValueError("Private-data deletion start is required")
        if (started.target.root_identity is None) != (started.phase == "started"):
            raise ValueError("Private-data deletion rename evidence is required")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked(self._write_policy)
            if not events or _open_start(events) != started:
                replay = next(
                    (
                        event
                        for event in reversed(events)
                        if event.phase == "completed"
                        and event.plan == started.plan
                        and event.confirmation == started.confirmation
                    ),
                    None,
                )
                if replay is not None and replay.receipt == receipt:
                    return replay
                raise ValueError("Private-data deletion start changed")
            event = CodingArchPrivateDataDeletionEventV1(
                revision=len(events) + 1,
                phase="completed",
                plan=started.plan,
                confirmation=started.confirmation,
                target=started.target,
                receipt=receipt,
            )
            self._append(event)
            return event

    def record_renamed(
        self, started: CodingArchPrivateDataDeletionEventV1
    ) -> CodingArchPrivateDataDeletionEventV1:
        if (
            started.phase not in {"started", "renamed"}
            or started.target.root_identity is None
        ):
            raise ValueError("Present private-data deletion start is required")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked(self._write_policy)
            current = _open_start(events)
            if current is None or (
                current.plan != started.plan
                or current.confirmation != started.confirmation
                or current.target != started.target
            ):
                raise ValueError("Private-data deletion start changed")
            if current.phase == "renamed":
                return current
            event = CodingArchPrivateDataDeletionEventV1(
                revision=len(events) + 1,
                phase="renamed",
                plan=started.plan,
                confirmation=started.confirmation,
                target=started.target,
            )
            self._append(event)
            return event

    def _append(self, event: CodingArchPrivateDataDeletionEventV1) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
        )

    def _load_unlocked(
        self, policy: JournalLoadPolicy
    ) -> tuple[CodingArchPrivateDataDeletionEventV1, ...]:
        if not self._require_safe_journal():
            return ()
        loaded: JsonlSnapshot[None, CodingArchPrivateDataDeletionEventV1] = load_jsonl(
            self._path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            load_policy=policy,
        )
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line, object_pairs_hook=_unique_object)
        events = loaded.records
        pending: CodingArchPrivateDataDeletionEventV1 | None = None
        seen_confirmations: set[str] = set()
        for revision, event in enumerate(events, start=1):
            if event.revision != revision:
                raise ValueError("Private-data deletion revisions are inconsistent")
            if event.phase == "started":
                if (
                    pending is not None
                    or event.confirmation.confirmation_id in seen_confirmations
                ):
                    raise ValueError("Private-data deletion starts are inconsistent")
                pending = event
                seen_confirmations.add(event.confirmation.confirmation_id)
            elif event.phase == "renamed":
                if (
                    pending is None
                    or pending.phase != "started"
                    or pending.plan != event.plan
                    or pending.confirmation != event.confirmation
                    or pending.target != event.target
                ):
                    raise ValueError("Private-data deletion rename has no exact start")
                pending = event
            elif (
                pending is None
                or event.plan != pending.plan
                or event.confirmation != pending.confirmation
                or event.target != pending.target
                or (
                    (event.target.root_identity is None) != (pending.phase == "started")
                )
            ):
                raise ValueError("Private-data deletion completion has no exact start")
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
            or (os.name == "posix" and metadata.st_mode & 0o077)
            or (os.name == "posix" and metadata.st_uid != os.geteuid())
        ):
            raise ValueError("Coding Arch deletion journal is unsafe")
        return True

    def _require_private_parent(self) -> None:
        metadata = self._path.parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (os.name == "posix" and metadata.st_mode & 0o077)
            or (os.name == "posix" and metadata.st_uid != os.geteuid())
        ):
            raise ValueError("Coding Arch deletion Product state is not private")


def _open_start(
    events: tuple[CodingArchPrivateDataDeletionEventV1, ...],
) -> CodingArchPrivateDataDeletionEventV1 | None:
    if events and events[-1].phase in {"started", "renamed"}:
        return events[-1]
    return None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Private-data deletion record has a duplicate JSON key")
        result[key] = value
    return result


__all__ = [
    "CodingArchPrivateDataDeletionEventV1",
    "CodingArchPrivateDataDeletionJournal",
]

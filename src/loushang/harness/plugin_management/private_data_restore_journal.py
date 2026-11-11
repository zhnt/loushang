"""Exact restore and result-confirmation histories over the existing Journal.

Product supplies the persisted identity/record codec and limits. These owners
retain the original POSIX action contracts; Windows uses only the explicit
history validator and keeps its native publication/transaction admission.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Generic, Literal, Protocol, Self, TypeVar

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    JournalLoadPolicy,
    JournalRecordCodec,
    JsonlJournal,
    JsonlSnapshot,
    journal_file_lock,
    journal_file_read_lock,
)
from loushang.harness.journal._path_admission import (
    private_journal_exists,
    require_private_journal_parent,
)

from .records import PluginInstallationKeyV1


class PrivateDataRestoreEvent(Protocol):
    @property
    def revision(self) -> int: ...

    @property
    def phase(self) -> Literal["started", "completed"]: ...

    @property
    def installation_key(self) -> PluginInstallationKeyV1: ...

    @property
    def backup_id(self) -> str: ...

    @property
    def deletion_receipt_id(self) -> str: ...

    @property
    def restore_id(self) -> str: ...

    @classmethod
    def create(
        cls,
        *,
        revision: int,
        phase: Literal["started", "completed"],
        installation_key: PluginInstallationKeyV1,
        backup_id: str,
        deletion_receipt_id: str,
    ) -> Self: ...


class PrivateDataRestoreConfirmation(Protocol):
    @property
    def revision(self) -> int: ...

    @property
    def restore_id(self) -> str: ...

    def matches_restore_result(self, other: Self) -> bool: ...


_EventT = TypeVar("_EventT", bound=PrivateDataRestoreEvent)
_ConfirmationT = TypeVar("_ConfirmationT", bound=PrivateDataRestoreConfirmation)


def validate_restore_history(
    events: tuple[PrivateDataRestoreEvent, ...],
    *,
    bind_deletion_backup: bool,
    revision_error: str,
    starts_error: str,
    completion_error: str,
) -> None:
    """Check the original two-phase history, with explicit Windows binding."""
    pending: PrivateDataRestoreEvent | None = None
    seen: set[str] = set()
    consumed: dict[tuple[PluginInstallationKeyV1, str], str] = {}
    for revision, event in enumerate(events, 1):
        if event.revision != revision:
            raise ValueError(revision_error)
        if event.phase == "started":
            prior_backup = (
                consumed.get((event.installation_key, event.deletion_receipt_id))
                if bind_deletion_backup
                else None
            )
            if (
                pending is not None
                or event.restore_id in seen
                or (prior_backup is not None and prior_backup != event.backup_id)
            ):
                raise ValueError(starts_error)
            pending = event
            seen.add(event.restore_id)
            if bind_deletion_backup:
                consumed[(event.installation_key, event.deletion_receipt_id)] = (
                    event.backup_id
                )
        elif (
            pending is None
            or event.restore_id != pending.restore_id
            or event.installation_key != pending.installation_key
            or event.backup_id != pending.backup_id
            or event.deletion_receipt_id != pending.deletion_receipt_id
        ):
            raise ValueError(completion_error)
        else:
            pending = None


class PrivateDataRestoreJournal(Generic[_EventT]):
    """Keep exact begin/complete retries; native effects remain with Resources."""

    def __init__(
        self,
        path: Path,
        *,
        event_type: type[_EventT],
        codec: JournalRecordCodec[_EventT],
        identity_for: Callable[[PluginInstallationKeyV1, str, str], str],
        label: str,
        max_events: int,
        max_bytes: int,
    ) -> None:
        self._path = path
        self._event_type = event_type
        self._identity_for = identity_for
        self._label = label
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._journal: JsonlJournal[None, _EventT] = JsonlJournal(
            path,
            record_codec=codec,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=replace(DURABLE_LOCKED_JOURNAL, locking=False),
        )
        self._load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

    @property
    def path(self) -> Path:
        return self._path

    def events(self) -> tuple[_EventT, ...]:
        self._require_private_parent()
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            return self._load_unlocked()

    def completed_for(self, restore_id: str) -> _EventT:
        """Find the exact completion while retaining the global unfinished barrier."""
        events = self.events()
        completion = next(
            (
                item
                for item in reversed(events)
                if item.restore_id == restore_id and item.phase == "completed"
            ),
            None,
        )
        if completion is None or (events and events[-1].phase == "started"):
            raise ValueError(f"{self._label} restore is not completed")
        return completion

    def begin(
        self,
        *,
        key: PluginInstallationKeyV1,
        backup_id: str,
        deletion_receipt_id: str,
    ) -> _EventT:
        restore_id = self._identity_for(key, backup_id, deletion_receipt_id)
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked()
            if any(
                item.deletion_receipt_id == deletion_receipt_id
                and item.installation_key == key
                and item.restore_id != restore_id
                for item in events
            ):
                raise ValueError(f"{self._label} deletion has another restore")
            if (
                events
                and events[-1].phase == "started"
                and events[-1].restore_id != restore_id
            ):
                raise ValueError(f"Another {self._label} restore is unfinished")
            existing = next(
                (item for item in reversed(events) if item.restore_id == restore_id),
                None,
            )
            if existing is not None:
                return existing
            if len(events) >= self._max_events:
                raise ValueError(f"{self._label} restore journal is full")
            started = self._event_type.create(
                revision=len(events) + 1,
                phase="started",
                installation_key=key,
                backup_id=backup_id,
                deletion_receipt_id=deletion_receipt_id,
            )
            self._append(started)
            return started

    def complete(self, started: _EventT) -> _EventT:
        if started.phase != "started":
            raise ValueError(f"{self._label} restore start is required")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked()
            if (
                events
                and events[-1].phase == "completed"
                and events[-1].restore_id == started.restore_id
            ):
                return events[-1]
            if not events or events[-1] != started or len(events) >= self._max_events:
                raise ValueError(f"{self._label} restore start changed")
            completed = self._event_type.create(
                revision=len(events) + 1,
                phase="completed",
                installation_key=started.installation_key,
                backup_id=started.backup_id,
                deletion_receipt_id=started.deletion_receipt_id,
            )
            self._append(completed)
            return completed

    def _append(self, event: _EventT) -> None:
        self._journal.append(event)

    def _load_unlocked(self) -> tuple[_EventT, ...]:
        if not self._require_safe_journal():
            return ()
        loaded: JsonlSnapshot[None, _EventT] = self._journal.load(
            load_policy=replace(self._load_policy, collect_duplicate_keys=True)
        )
        loaded.require_unique_keys(f"{self._label} restore event repeats a field")
        events: tuple[_EventT, ...] = loaded.records
        if len(events) > self._max_events:
            raise ValueError(f"{self._label} restore journal is full")
        validate_restore_history(
            events,
            bind_deletion_backup=False,
            revision_error=f"{self._label} restore revisions changed",
            starts_error=f"{self._label} restore starts changed",
            completion_error=f"{self._label} restore completion changed",
        )
        return events

    def _require_safe_journal(self) -> bool:
        return private_journal_exists(
            self._path,
            message=f"{self._label} restore journal is unsafe",
            posix_only=False,
            max_bytes=self._max_bytes,
        )

    def _require_private_parent(self) -> None:
        require_private_journal_parent(
            self._path,
            message=f"{self._label} restore Product state is not private",
            posix_only=False,
        )


class PrivateDataRestoreConfirmationJournal(Generic[_ConfirmationT]):
    """Record one exact verified tree result per completed restore."""

    def __init__(
        self,
        path: Path,
        *,
        record_type: type[_ConfirmationT],
        codec: JournalRecordCodec[_ConfirmationT],
        label: str,
        max_records: int,
        max_bytes: int,
    ) -> None:
        self._path = path
        self._record_type = record_type
        self._label = label
        self._max_records = max_records
        self._max_bytes = max_bytes
        self._journal: JsonlJournal[None, _ConfirmationT] = JsonlJournal(
            path,
            record_codec=codec,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=replace(DURABLE_LOCKED_JOURNAL, locking=False),
        )
        self._load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

    @property
    def path(self) -> Path:
        return self._path

    def records(self) -> tuple[_ConfirmationT, ...]:
        self._require_private_parent()
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            return self._load_unlocked()

    def record(self, confirmation: _ConfirmationT) -> _ConfirmationT:
        if not isinstance(confirmation, self._record_type):
            raise TypeError(f"{self._label} restore confirmation is required")
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
                if not previous.matches_restore_result(confirmation):
                    raise ValueError(f"{self._label} restore confirmation changed")
                return previous
            if (
                len(records) >= self._max_records
                or confirmation.revision != len(records) + 1
            ):
                raise ValueError(f"{self._label} restore confirmation revision changed")
            self._journal.append(confirmation)
            return confirmation

    def _load_unlocked(self) -> tuple[_ConfirmationT, ...]:
        if not private_journal_exists(
            self._path,
            message=f"{self._label} restore confirmation journal is unsafe",
            posix_only=False,
            max_bytes=self._max_bytes,
        ):
            return ()
        loaded: JsonlSnapshot[None, _ConfirmationT] = self._journal.load(
            load_policy=replace(self._load_policy, collect_duplicate_keys=True)
        )
        loaded.require_unique_keys(
            f"{self._label} restore confirmation repeats a field"
        )
        records = loaded.records
        if len(records) > self._max_records:
            raise ValueError(f"{self._label} restore confirmation journal is full")
        seen: set[str] = set()
        for revision, record in enumerate(records, 1):
            if record.revision != revision or record.restore_id in seen:
                raise ValueError(f"{self._label} restore confirmations changed")
            seen.add(record.restore_id)
        return records

    def _require_private_parent(self) -> None:
        require_private_journal_parent(
            self._path,
            message=f"{self._label} restore confirmation root is not private",
            posix_only=False,
        )

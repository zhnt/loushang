from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from loushang.foundation.json import require_json_mapping
from loushang.harness.journal import (
    PROCESS_LOCAL_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalLoadPolicy,
    JsonlJournal,
    JsonlSnapshot,
)

_EVENT_LOG_ENTRY_FIELDS = frozenset(
    {
        "entry_id",
        "entry_type",
        "operation_id",
        "event_id",
        "run_id",
        "session_id",
        "sequence",
        "payload",
        "created_at",
    }
)


@dataclass(frozen=True, order=True)
class EventPosition:
    offset: int


@dataclass(frozen=True)
class EventLogEntry:
    entry_id: str
    entry_type: Literal["operation", "event"]
    operation_id: str
    event_id: str | None
    run_id: str
    session_id: str
    sequence: int
    payload: Mapping[str, object]
    created_at: datetime


class EventLogBackend(Protocol):
    def append(self, entry: EventLogEntry) -> EventPosition: ...

    def checkpoint(self) -> EventPosition: ...

    def query(
        self,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        after: EventPosition | None = None,
        limit: int | None = None,
    ) -> list[EventLogEntry]: ...

    def subscribe(
        self,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        after: EventPosition | None = None,
    ) -> AsyncIterator[EventLogEntry]: ...


@dataclass
class _Subscriber:
    operation_id: str | None
    run_id: str | None
    session_id: str | None
    queue: asyncio.Queue[EventLogEntry] = field(default_factory=asyncio.Queue)


class _EventLogState:
    def __init__(self) -> None:
        self._entries: list[tuple[EventPosition, EventLogEntry]] = []
        self._entries_by_operation: dict[
            str, list[tuple[EventPosition, EventLogEntry]]
        ] = {}
        self._entries_by_run: dict[str, list[tuple[EventPosition, EventLogEntry]]] = {}
        self._entries_by_session: dict[
            str, list[tuple[EventPosition, EventLogEntry]]
        ] = {}
        self._subscribers: list[_Subscriber] = []

    def _append_stored(self, entry: EventLogEntry) -> EventPosition:
        position = EventPosition(offset=len(self._entries) + 1)
        self._index(position, entry)
        for subscriber in list(self._subscribers):
            if _matches(
                entry,
                operation_id=subscriber.operation_id,
                run_id=subscriber.run_id,
                session_id=subscriber.session_id,
            ):
                subscriber.queue.put_nowait(entry)
        return position

    def _append_loaded(self, entry: EventLogEntry) -> EventPosition:
        position = EventPosition(offset=len(self._entries) + 1)
        self._index(position, entry)
        return position

    def _index(self, position: EventPosition, entry: EventLogEntry) -> None:
        positioned = (position, entry)
        self._entries.append(positioned)
        self._entries_by_operation.setdefault(entry.operation_id, []).append(positioned)
        self._entries_by_run.setdefault(entry.run_id, []).append(positioned)
        self._entries_by_session.setdefault(entry.session_id, []).append(positioned)

    def checkpoint(self) -> EventPosition:
        return EventPosition(offset=len(self._entries))

    def query(
        self,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        after: EventPosition | None = None,
        limit: int | None = None,
    ) -> list[EventLogEntry]:
        selected: list[EventLogEntry] = []
        positioned_entries = self._candidate_entries(
            operation_id=operation_id,
            run_id=run_id,
            session_id=session_id,
        )
        for position, entry in positioned_entries:
            if after is not None and position <= after:
                continue
            if not _matches(
                entry,
                operation_id=operation_id,
                run_id=run_id,
                session_id=session_id,
            ):
                continue
            selected.append(_snapshot_entry(entry))
            if limit is not None and len(selected) >= limit:
                break
        return selected

    def _candidate_entries(
        self,
        *,
        operation_id: str | None,
        run_id: str | None,
        session_id: str | None,
    ) -> list[tuple[EventPosition, EventLogEntry]]:
        candidates = [
            entries
            for value, entries in (
                (
                    operation_id,
                    self._entries_by_operation.get(operation_id, [])
                    if operation_id is not None
                    else self._entries,
                ),
                (
                    run_id,
                    self._entries_by_run.get(run_id, [])
                    if run_id is not None
                    else self._entries,
                ),
                (
                    session_id,
                    self._entries_by_session.get(session_id, [])
                    if session_id is not None
                    else self._entries,
                ),
            )
            if value is not None
        ]
        return min(candidates, key=len) if candidates else self._entries

    def subscribe(
        self,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        after: EventPosition | None = None,
    ) -> AsyncIterator[EventLogEntry]:
        async def stream() -> AsyncIterator[EventLogEntry]:
            subscriber = _Subscriber(
                operation_id=operation_id,
                run_id=run_id,
                session_id=session_id,
            )
            self._subscribers.append(subscriber)
            try:
                for entry in self.query(
                    operation_id=operation_id,
                    run_id=run_id,
                    session_id=session_id,
                    after=after,
                ):
                    yield entry
                while True:
                    yield _snapshot_entry(await subscriber.queue.get())
            finally:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)

        return stream()


class InMemoryEventLogBackend(_EventLogState):
    def append(self, entry: EventLogEntry) -> EventPosition:
        return self._append_stored(_normalize_entry(entry))


class JsonlEventLogBackend(_EventLogState):
    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._journal: JsonlJournal[object, EventLogEntry] = JsonlJournal(
            self._path,
            record_codec=_EVENT_LOG_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=PROCESS_LOCAL_JOURNAL,
            load_policy=JournalLoadPolicy(),
        )
        self._load()

    def append(self, entry: EventLogEntry) -> EventPosition:
        stored_entry = _normalize_entry(entry)
        self._journal.append(stored_entry)
        return self._append_stored(stored_entry)

    def _load(self) -> None:
        if not self._path.exists():
            return
        snapshot: JsonlSnapshot[object, EventLogEntry] = self._journal.load()
        for entry in snapshot.records:
            self._append_loaded(entry)


def _matches(
    entry: EventLogEntry,
    *,
    operation_id: str | None,
    run_id: str | None,
    session_id: str | None,
) -> bool:
    if operation_id is not None and entry.operation_id != operation_id:
        return False
    if run_id is not None and entry.run_id != run_id:
        return False
    if session_id is not None and entry.session_id != session_id:
        return False
    return True


def _normalize_entry(entry: EventLogEntry) -> EventLogEntry:
    return EventLogEntry(
        entry_id=_require_string(entry.entry_id, "entry_id"),
        entry_type=_require_entry_type(entry.entry_type),
        operation_id=_require_string(entry.operation_id, "operation_id"),
        event_id=_require_optional_string(entry.event_id, "event_id"),
        run_id=_require_string(entry.run_id, "run_id"),
        session_id=_require_string(entry.session_id, "session_id"),
        sequence=_require_integer(entry.sequence, "sequence"),
        payload=_normalize_payload(entry.payload),
        created_at=_require_datetime(entry.created_at, "created_at"),
    )


def _snapshot_entry(entry: EventLogEntry) -> EventLogEntry:
    return _normalize_entry(entry)


def _entry_to_json(entry: EventLogEntry) -> dict[str, object]:
    entry = _normalize_entry(entry)
    return {
        "entry_id": entry.entry_id,
        "entry_type": entry.entry_type,
        "operation_id": entry.operation_id,
        "event_id": entry.event_id,
        "run_id": entry.run_id,
        "session_id": entry.session_id,
        "sequence": entry.sequence,
        "payload": require_json_mapping(
            dict(entry.payload),
            name="event_log_entry.payload",
        ),
        "created_at": entry.created_at.isoformat(),
    }


def _entry_from_json(data: Mapping[str, object]) -> EventLogEntry:
    _require_exact_fields(data)
    return EventLogEntry(
        entry_id=_require_string(data["entry_id"], "entry_id"),
        entry_type=_require_entry_type(data["entry_type"]),
        operation_id=_require_string(data["operation_id"], "operation_id"),
        event_id=_require_optional_string(data["event_id"], "event_id"),
        run_id=_require_string(data["run_id"], "run_id"),
        session_id=_require_string(data["session_id"], "session_id"),
        sequence=_require_integer(data["sequence"], "sequence"),
        payload=cast(
            Mapping[str, object],
            require_json_mapping(
                data["payload"],
                name="event_log_entry.payload",
            ),
        ),
        created_at=_datetime_from_json(data["created_at"]),
    )


def _require_exact_fields(data: Mapping[str, object]) -> None:
    fields = frozenset(data)
    missing = sorted(_EVENT_LOG_ENTRY_FIELDS - fields)
    unexpected = sorted(fields - _EVENT_LOG_ENTRY_FIELDS)
    if missing:
        raise ValueError(f"event log entry is missing fields: {', '.join(missing)}")
    if unexpected:
        raise ValueError(
            f"event log entry has unexpected fields: {', '.join(unexpected)}"
        )


def _normalize_payload(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("payload must be a mapping")
    return cast(
        Mapping[str, object],
        require_json_mapping(dict(value), name="event_log_entry.payload"),
    )


def _require_string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    return cast(str, value)


def _require_optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _require_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    return cast(int, value)


def _require_entry_type(value: object) -> Literal["operation", "event"]:
    value = _require_string(value, "entry_type")
    if value not in ("operation", "event"):
        raise ValueError("entry_type must be 'operation' or 'event'")
    return cast(Literal["operation", "event"], value)


def _require_datetime(value: object, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    return cast(datetime, value)


def _datetime_from_json(value: object) -> datetime:
    text = _require_string(value, "created_at")
    if len(text) <= 10 or text[10] not in ("T", " "):
        raise ValueError("created_at must be an ISO 8601 datetime")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("created_at must be an ISO 8601 datetime") from exc


_EVENT_LOG_CODEC = FunctionalJournalRecordCodec(_entry_to_json, _entry_from_json)


__all__ = [
    "EventLogBackend",
    "EventLogEntry",
    "EventPosition",
    "InMemoryEventLogBackend",
    "JsonlEventLogBackend",
]

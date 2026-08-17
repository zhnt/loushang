from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

PayloadT = TypeVar("PayloadT")


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_optional_text(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name=name)


@dataclass(frozen=True)
class RuntimeEvent(Generic[PayloadT]):
    """One transient runtime fact ordered within a scoped event stream."""

    event_id: str
    kind: str
    stream_id: str
    sequence: int
    occurred_at: datetime
    payload: PayloadT
    session_id: str | None = None
    run_id: str | None = None
    source_event_ref: str | None = None
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_id, name="event id")
        _require_text(self.kind, name="event kind")
        _require_text(self.stream_id, name="event stream id")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("event sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("event sequence must be positive")
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("event occurrence time must be a datetime")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event occurrence time must be timezone-aware")
        _require_optional_text(self.session_id, name="session id")
        _require_optional_text(self.run_id, name="run id")
        _require_optional_text(self.source_event_ref, name="source event reference")
        _require_optional_text(self.source_record_id, name="source record id")


@dataclass(frozen=True)
class TranscriptRecordCommitted:
    """Durable transcript identity and revision observed after one append."""

    conversation_id: str
    record_id: str
    revision: int
    committed_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.conversation_id, name="conversation id")
        _require_text(self.record_id, name="transcript record id")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise TypeError("transcript revision must be an integer")
        if self.revision < 1:
            raise ValueError("transcript revision must be positive")
        if not isinstance(self.committed_at, datetime):
            raise TypeError("transcript commit time must be a datetime")
        if self.committed_at.tzinfo is None:
            raise ValueError("transcript commit time must be timezone-aware")


__all__ = ["RuntimeEvent", "TranscriptRecordCommitted"]

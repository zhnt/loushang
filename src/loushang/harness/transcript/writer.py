from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from loushang.foundation.json import JSONValue
from loushang.harness.conversation.types import (
    ConversationRecord,
)
from loushang.harness.transcript.codecs import STANDARD_PAYLOAD_VERSION
from loushang.harness.transcript.types import (
    AgentTranscriptPayload,
    AgentTranscriptRecord,
)

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class AgentTranscriptRecordFactory:
    """Build typed Agent transcript records without committing them."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._clock = clock or _utc_now
        self._id_factory = id_factory or _uuid

    def create(
        self,
        kind: str,
        payload: AgentTranscriptPayload,
        *,
        parent_id: str | None,
        payload_version: int = STANDARD_PAYLOAD_VERSION,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptRecord:
        record_id = self._id_factory()
        if not isinstance(record_id, str) or not record_id.strip():
            raise ValueError("transcript record id factory must return non-empty text")
        return cast(
            AgentTranscriptRecord,
            ConversationRecord(
                record_id=record_id,
                parent_id=parent_id,
                kind=kind,
                payload_version=payload_version,
                created_at=_encode_timestamp(self._clock()),
                payload=payload,
                metadata={} if metadata is None else metadata,
            ),
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())


def _encode_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("transcript clock must return datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("transcript clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "AgentTranscriptRecordFactory",
    "Clock",
    "IdFactory",
]

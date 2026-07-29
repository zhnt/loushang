from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, TypeAlias

from loushang.harness.events.projection import RuntimeEventView
from loushang.work.types import WorkEvent, WorkOperation

ChannelEnvelopeKind: TypeAlias = Literal["operation", "event"]
ChannelPayload: TypeAlias = WorkOperation | WorkEvent | RuntimeEventView


@dataclass(frozen=True)
class ChannelEndpoint:
    endpoint_id: str
    kind: str
    session_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelEnvelope:
    envelope_id: str
    kind: ChannelEnvelopeKind
    payload: ChannelPayload
    source: ChannelEndpoint | None = None
    target: ChannelEndpoint | None = None
    created_at: datetime | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in ("operation", "event"):
            raise ValueError("channel envelope kind must be 'operation' or 'event'")
        if self.kind == "operation" and not isinstance(self.payload, WorkOperation):
            actual = _payload_name(self.payload)
            raise TypeError(
                f"operation channel envelopes cannot carry {actual} payload"
            )
        if self.kind == "event" and not _is_event_payload(self.payload):
            actual = _payload_name(self.payload)
            raise TypeError(f"event channel envelopes cannot carry {actual} payload")


def _payload_name(payload: object) -> str:
    if isinstance(payload, WorkOperation):
        return "operation"
    if isinstance(payload, WorkEvent):
        return "event"
    if isinstance(payload, RuntimeEventView):
        return "runtime event view"
    return type(payload).__name__


def _is_event_payload(payload: object) -> bool:
    return isinstance(payload, WorkEvent | RuntimeEventView)


__all__ = [
    "ChannelEndpoint",
    "ChannelEnvelope",
    "ChannelEnvelopeKind",
    "ChannelPayload",
]

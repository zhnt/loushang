"""Neutral transport-ready views over transient runtime events.

Products decide how a typed runtime fact becomes a presentation payload.  This
module preserves the source envelope, validates that projected payload as
strict JSON, and provides generic event-type selection for transports.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias

from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.events.json import snake_case_json_keys
from loushang.harness.events.types import (
    RuntimeEvent,
    _require_optional_text,
    _require_text,
)

RuntimeEventDeliveryHint: TypeAlias = Literal["immediate", "coalesce", "final_only"]


@dataclass(frozen=True)
class RuntimeEventView:
    """One product-projected, transport-safe observation of a runtime event.

    ``event_id`` and ordering fields retain the identity of the source
    ``RuntimeEvent``.  ``event_type``, ``view``, and ``payload`` are supplied
    by the Product projection; no Product-specific fields are interpreted here.
    """

    event_id: str
    kind: str
    stream_id: str
    sequence: int
    occurred_at: datetime
    event_type: str
    view: str
    payload: Mapping[str, JSONValue]
    delivery_hint: RuntimeEventDeliveryHint = "immediate"
    session_id: str | None = None
    run_id: str | None = None
    source_event_ref: str | None = None
    source_record_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_id, name="runtime event id")
        _require_text(self.kind, name="runtime event kind")
        _require_text(self.stream_id, name="runtime event stream id")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("runtime event view sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("runtime event view sequence must be positive")
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("runtime event view occurrence time must be a datetime")
        if self.occurred_at.tzinfo is None:
            raise ValueError(
                "runtime event view occurrence time must be timezone-aware"
            )
        _require_text(self.event_type, name="runtime event view type")
        _require_text(self.view, name="runtime event view name")
        if self.delivery_hint not in ("immediate", "coalesce", "final_only"):
            raise ValueError(
                "runtime event view delivery hint must be 'immediate', "
                "'coalesce', or 'final_only'"
            )
        _require_optional_text(self.session_id, name="session id")
        _require_optional_text(self.run_id, name="run id")
        _require_optional_text(self.source_event_ref, name="source event reference")
        _require_optional_text(self.source_record_id, name="source record id")
        _require_optional_text(self.correlation_id, name="runtime event correlation id")
        object.__setattr__(
            self,
            "payload",
            require_json_mapping(dict(self.payload), name="runtime_event_view.payload"),
        )


def project_runtime_event(
    event: RuntimeEvent[object],
    *,
    event_type: str,
    view: str,
    payload: Mapping[str, object],
    delivery_hint: RuntimeEventDeliveryHint = "immediate",
    correlation_id: str | None = None,
) -> RuntimeEventView:
    """Bind a Product JSON projection to one common runtime envelope."""

    normalized_payload = snake_case_json_keys(dict(payload))
    if not isinstance(normalized_payload, Mapping):
        raise TypeError("runtime event projection must remain a mapping")
    return RuntimeEventView(
        event_id=event.event_id,
        kind=event.kind,
        stream_id=event.stream_id,
        sequence=event.sequence,
        occurred_at=event.occurred_at,
        event_type=event_type,
        view=view,
        payload=require_json_mapping(
            dict(normalized_payload),
            name="runtime_event_projection",
        ),
        delivery_hint=delivery_hint,
        session_id=event.session_id,
        run_id=event.run_id,
        source_event_ref=event.source_event_ref,
        source_record_id=event.source_record_id,
        correlation_id=correlation_id,
    )


def normalize_event_select(event_select: str | Sequence[str] | None) -> tuple[str, ...]:
    """Normalize exact or trailing-wildcard event type selectors."""

    if event_select is None:
        return ()
    if isinstance(event_select, str):
        event_select = (event_select,)
    if not isinstance(event_select, Sequence):
        raise TypeError("event_select must be a string or sequence of strings")
    normalized: list[str] = []
    for pattern in event_select:
        if not isinstance(pattern, str):
            raise TypeError("event_select patterns must be strings")
        if not pattern:
            raise ValueError("event_select patterns must be non-empty")
        normalized.append(pattern)
    return tuple(normalized)


def matches_event_select(event_type: str, event_select: Sequence[str]) -> bool:
    """Return whether a stable event type matches generic selector patterns."""

    _require_text(event_type, name="runtime event view type")
    for pattern in event_select:
        if pattern == "*":
            return True
        if pattern.endswith("*") and event_type.startswith(pattern[:-1]):
            return True
        if event_type == pattern:
            return True
    return not event_select


def select_runtime_event_views(
    views: Sequence[RuntimeEventView], event_select: Sequence[str]
) -> tuple[RuntimeEventView, ...]:
    """Select views without interpreting Product aliases or payload fields."""

    return tuple(
        view for view in views if matches_event_select(view.event_type, event_select)
    )


__all__ = [
    "RuntimeEventDeliveryHint",
    "RuntimeEventView",
    "matches_event_select",
    "normalize_event_select",
    "project_runtime_event",
    "select_runtime_event_views",
]

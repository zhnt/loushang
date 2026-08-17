from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkflowEvent:
    type: str
    text: str = ""
    data: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EventPattern:
    event: str
    contains: str | None = None
    data: Mapping[str, object] = field(default_factory=dict)


def event_matches(event: WorkflowEvent, pattern: EventPattern) -> bool:
    if event.type != pattern.event:
        return False
    if pattern.contains is not None and pattern.contains not in event.text:
        return False
    for key, expected in pattern.data.items():
        if event.data.get(key) != expected:
            return False
    return True


def find_event(
    events: tuple[WorkflowEvent, ...], pattern: EventPattern
) -> WorkflowEvent | None:
    for event in events:
        if event_matches(event, pattern):
            return event
    return None

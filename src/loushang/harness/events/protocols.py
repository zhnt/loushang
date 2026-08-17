from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol, TypeVar

from loushang.harness.events.types import RuntimeEvent

EventT_contra = TypeVar("EventT_contra", contravariant=True)
PayloadT = TypeVar("PayloadT")


class EventListener(Protocol[EventT_contra]):
    """Synchronous or asynchronous observer of one event value."""

    def __call__(self, event: EventT_contra, /) -> Awaitable[None] | None: ...


class EventPublisher(Protocol[PayloadT]):
    """Scoped publisher that owns runtime-event envelope allocation."""

    async def publish(
        self,
        kind: str,
        payload: PayloadT,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        source_event_ref: str | None = None,
        source_record_id: str | None = None,
    ) -> RuntimeEvent[PayloadT]: ...


__all__ = ["EventListener", "EventPublisher"]

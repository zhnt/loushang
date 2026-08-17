from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import uuid4

from loushang.harness.events.bus import OrderedEventBus
from loushang.harness.events.types import RuntimeEvent

PayloadT = TypeVar("PayloadT")
_Clock = Callable[[], datetime]
_EventIdFactory = Callable[[], str]


class RuntimeEventPublisher(Generic[PayloadT]):
    """Allocate and publish every envelope for one runtime event stream."""

    def __init__(
        self,
        stream_id: str,
        bus: OrderedEventBus[RuntimeEvent[PayloadT]],
        *,
        clock: _Clock | None = None,
        event_id_factory: _EventIdFactory | None = None,
    ) -> None:
        if not isinstance(stream_id, str) or not stream_id.strip():
            raise ValueError("event stream id must be a non-empty string")
        self._stream_id = stream_id
        self._bus = bus
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))
        self._sequence = 0

    @property
    def stream_id(self) -> str:
        return self._stream_id

    async def publish(
        self,
        kind: str,
        payload: PayloadT,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        source_event_ref: str | None = None,
        source_record_id: str | None = None,
    ) -> RuntimeEvent[PayloadT]:
        event = self._next_event(
            kind,
            payload,
            session_id=session_id,
            run_id=run_id,
            source_event_ref=source_event_ref,
            source_record_id=source_record_id,
        )
        await self._bus.dispatch(event)
        return event

    def schedule(
        self,
        kind: str,
        payload: PayloadT,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        source_event_ref: str | None = None,
        source_record_id: str | None = None,
    ) -> asyncio.Task[None]:
        """Schedule publication while preserving this stream's allocation order."""

        event = self._next_event(
            kind,
            payload,
            session_id=session_id,
            run_id=run_id,
            source_event_ref=source_event_ref,
            source_record_id=source_record_id,
        )
        return self._bus.schedule(event)

    def publish_without_loop(
        self,
        kind: str,
        payload: PayloadT,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        source_event_ref: str | None = None,
        source_record_id: str | None = None,
    ) -> RuntimeEvent[PayloadT]:
        """Publish to synchronous listeners when no event loop is available."""

        event = self._next_event(
            kind,
            payload,
            session_id=session_id,
            run_id=run_id,
            source_event_ref=source_event_ref,
            source_record_id=source_record_id,
        )
        self._bus.dispatch_without_loop(event)
        return event

    def _next_event(
        self,
        kind: str,
        payload: PayloadT,
        *,
        session_id: str | None,
        run_id: str | None,
        source_event_ref: str | None,
        source_record_id: str | None,
    ) -> RuntimeEvent[PayloadT]:
        sequence = self._sequence + 1
        event = RuntimeEvent(
            event_id=self._event_id_factory(),
            kind=kind,
            stream_id=self._stream_id,
            sequence=sequence,
            occurred_at=self._clock(),
            session_id=session_id,
            run_id=run_id,
            source_event_ref=source_event_ref,
            source_record_id=source_record_id,
            payload=payload,
        )
        self._sequence = sequence
        return event


__all__ = ["RuntimeEventPublisher"]

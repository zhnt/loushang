from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from loushang.harness.events import (
    OrderedEventBus,
    RuntimeEvent,
    RuntimeEventPublisher,
)


def _next(values: Iterator[str]) -> str:
    return next(values)


def test_runtime_event_publisher_owns_envelope_allocation_for_one_stream() -> None:
    bus: OrderedEventBus[RuntimeEvent[str]] = OrderedEventBus()
    seen: list[RuntimeEvent[str]] = []
    bus.subscribe(seen.append)
    event_ids = iter(("event-1", "event-2"))
    first_time = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    times = iter((first_time, first_time + timedelta(seconds=1)))
    publisher = RuntimeEventPublisher(
        "session:session-1",
        bus,
        event_id_factory=lambda: _next(event_ids),
        clock=lambda: next(times),
    )

    async def scenario() -> tuple[RuntimeEvent[str], RuntimeEvent[str]]:
        first = await publisher.publish(
            "runtime.started",
            "first",
            session_id="session-1",
            run_id="run-1",
            source_event_ref="agent-event-1",
        )
        second = await publisher.publish(
            "runtime.completed",
            "second",
            session_id="session-1",
            run_id="run-1",
            source_record_id="record-2",
        )
        return first, second

    first, second = asyncio.run(scenario())

    assert publisher.stream_id == "session:session-1"
    assert (first.event_id, second.event_id) == ("event-1", "event-2")
    assert (first.sequence, second.sequence) == (1, 2)
    assert (first.occurred_at, second.occurred_at) == (
        first_time,
        first_time + timedelta(seconds=1),
    )
    assert first.source_event_ref == "agent-event-1"
    assert second.source_record_id == "record-2"
    assert seen == [first, second]


def test_runtime_event_publishers_sequence_independent_streams() -> None:
    first_bus: OrderedEventBus[RuntimeEvent[None]] = OrderedEventBus()
    second_bus: OrderedEventBus[RuntimeEvent[None]] = OrderedEventBus()
    first = RuntimeEventPublisher("stream-1", first_bus)
    second = RuntimeEventPublisher("stream-2", second_bus)

    async def scenario() -> tuple[RuntimeEvent[None], RuntimeEvent[None]]:
        return (
            await first.publish("test.event", None),
            await second.publish("test.event", None),
        )

    first_event, second_event = asyncio.run(scenario())

    assert first_event.sequence == 1
    assert second_event.sequence == 1
    assert first_event.stream_id != second_event.stream_id


def test_runtime_event_publisher_schedules_in_stream_order() -> None:
    bus: OrderedEventBus[RuntimeEvent[str]] = OrderedEventBus()
    seen: list[RuntimeEvent[str]] = []
    bus.subscribe(seen.append)
    publisher = RuntimeEventPublisher("stream-1", bus)

    async def scenario() -> None:
        first = publisher.schedule("runtime.first", "first")
        second = publisher.schedule("runtime.second", "second")
        await asyncio.gather(first, second)

    asyncio.run(scenario())

    assert [event.payload for event in seen] == ["first", "second"]
    assert [event.sequence for event in seen] == [1, 2]


def test_runtime_event_publisher_propagates_listener_failure() -> None:
    bus: OrderedEventBus[RuntimeEvent[str]] = OrderedEventBus()

    async def fail(event: RuntimeEvent[str]) -> None:
        raise RuntimeError(f"cannot observe {event.kind}")

    bus.subscribe(fail)
    publisher = RuntimeEventPublisher("stream-1", bus)

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="cannot observe test.event"):
            await publisher.publish("test.event", "payload")

    asyncio.run(scenario())


def test_runtime_event_publisher_supports_synchronous_no_loop_delivery() -> None:
    bus: OrderedEventBus[RuntimeEvent[str]] = OrderedEventBus()
    seen: list[RuntimeEvent[str]] = []
    bus.subscribe(seen.append)
    publisher = RuntimeEventPublisher(
        "stream-1",
        bus,
        event_id_factory=lambda: "event-1",
    )

    event = publisher.publish_without_loop("runtime.started", "payload")

    assert event.sequence == 1
    assert seen == [event]

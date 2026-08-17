from __future__ import annotations

import asyncio

import pytest

from loushang.harness.events import OrderedEventBus


def test_ordered_event_bus_subscribes_and_unsubscribes() -> None:
    bus: OrderedEventBus[str] = OrderedEventBus()
    seen: list[str] = []
    assert bus.has_listeners is False
    unsubscribe = bus.subscribe(seen.append)
    assert bus.has_listeners is True

    asyncio.run(bus.dispatch("first"))
    unsubscribe()
    assert bus.has_listeners is False
    asyncio.run(bus.dispatch("ignored"))

    assert seen == ["first"]


def test_ordered_event_bus_serializes_scheduled_async_listeners() -> None:
    bus: OrderedEventBus[str] = OrderedEventBus()
    started = asyncio.Event()
    release = asyncio.Event()
    seen: list[str] = []

    async def listener(event: str) -> None:
        seen.append(f"start:{event}")
        if event == "first":
            started.set()
            await release.wait()
        seen.append(f"end:{event}")

    bus.subscribe(listener)

    async def scenario() -> None:
        first = bus.schedule("first")
        await started.wait()
        second = bus.schedule("second")
        await asyncio.sleep(0)
        assert seen == ["start:first"]
        release.set()
        await first
        await bus.drain()
        await second

    asyncio.run(scenario())

    assert seen == ["start:first", "end:first", "start:second", "end:second"]


def test_ordered_event_bus_propagates_failure_without_blocking_next_event() -> None:
    bus: OrderedEventBus[str] = OrderedEventBus()
    seen: list[str] = []

    async def listener(event: str) -> None:
        seen.append(event)
        if event == "first":
            raise RuntimeError("listener failed")

    bus.subscribe(listener)

    async def scenario() -> None:
        first = bus.schedule("first")
        second = bus.schedule("second")
        with pytest.raises(RuntimeError, match="listener failed"):
            await first
        await second
        await bus.drain()

    asyncio.run(scenario())

    assert seen == ["first", "second"]


def test_ordered_event_bus_no_loop_rejects_async_listener_with_configured_error() -> (
    None
):
    bus: OrderedEventBus[str] = OrderedEventBus(
        async_listener_error="Reference async listeners need a loop."
    )

    async def listener(event: str) -> None:
        del event

    bus.subscribe(listener)

    with pytest.raises(RuntimeError, match="Reference async listeners need a loop"):
        bus.dispatch_without_loop("event")

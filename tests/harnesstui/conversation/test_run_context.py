"""Tests for the shared conversation interaction run context."""

from __future__ import annotations

import asyncio
import inspect

import pytest


def test_interaction_run_context_closes_in_order_and_only_once() -> None:
    from loushang.harnesstui.conversation.run_context import InteractionRunContext

    calls: list[str] = []

    class ExitContext:
        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback
            calls.append("context.exit")

    async def emit(write_callable, *, label: str) -> None:
        del label
        write_callable()

    context = InteractionRunContext(
        emit=emit,
        _unsubscribe=lambda: calls.append("unsubscribe"),
        _exit_context=ExitContext(),
        _trace=lambda name, **_data: calls.append(name),
    )

    context.close()
    context.close()

    assert calls == ["tui.end", "unsubscribe", "context.exit"]


def test_interaction_run_context_exits_when_trace_or_unsubscribe_fails() -> None:
    from loushang.harnesstui.conversation.run_context import InteractionRunContext

    calls: list[str] = []

    class ExitContext:
        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback
            calls.append("context.exit")

    def trace(name: str, **_data: object) -> None:
        calls.append(name)
        raise RuntimeError("trace failed")

    context = InteractionRunContext(
        emit=_emit,
        _unsubscribe=lambda: calls.append("unsubscribe"),
        _exit_context=ExitContext(),
        _trace=trace,
    )

    with pytest.raises(RuntimeError, match="trace failed"):
        context.close()

    assert calls == ["tui.end", "unsubscribe", "context.exit"]


def test_stable_emit_factory_traces_success_and_write_error() -> None:
    from loushang.harnesstui.conversation.run_context import stable_emit_factory

    traces: list[tuple[str, dict[str, object]]] = []
    writes: list[str] = []
    emit = stable_emit_factory(
        trace=lambda name, **data: traces.append((name, data)),
        interactive=True,
    )

    asyncio.run(emit(lambda: writes.append("written"), label="event:delta"))

    def fail() -> None:
        raise RuntimeError("write failed")

    with pytest.raises(RuntimeError, match="write failed"):
        asyncio.run(emit(fail, label="event:error"))

    assert writes == ["written"]
    assert [name for name, _data in traces] == [
        "emit.start",
        "emit.end",
        "emit.start",
        "emit.error",
    ]
    assert traces[0][1] == {"label": "event:delta", "interactive": True}
    assert traces[-1][1]["error"] == "write failed"


def test_subscribe_events_uses_returned_hook_or_safe_noop() -> None:
    from loushang.harnesstui.conversation.run_context import subscribe_events

    calls: list[object] = []

    class Source:
        def subscribe(self, listener):
            calls.append(listener)
            return lambda: calls.append("unsubscribe")

    listener = object()
    unsubscribe = subscribe_events(Source(), listener)
    unsubscribe()

    assert calls == [listener, "unsubscribe"]
    assert subscribe_events(object(), listener)() is None


def test_rebindable_event_source_moves_existing_listener_and_cleans_up() -> None:
    from loushang.harnesstui.conversation.run_context import RebindableEventSource

    calls: list[str] = []

    class Source:
        def __init__(self, name: str) -> None:
            self.name = name

        def subscribe(self, _listener: object):
            calls.append(f"subscribe:{self.name}")
            return lambda: calls.append(f"unsubscribe:{self.name}")

    first = Source("first")
    second = Source("second")
    source = RebindableEventSource(first)
    unsubscribe = source.subscribe(object())

    source.rebind(second)
    unsubscribe()

    assert source.source is second
    assert calls == [
        "subscribe:first",
        "unsubscribe:first",
        "subscribe:second",
        "unsubscribe:second",
    ]


def test_rebindable_event_source_contains_rebind_subscription_failure() -> None:
    from loushang.harnesstui.conversation.run_context import RebindableEventSource

    class Source:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail

        def subscribe(self, _listener: object):
            if self.fail:
                raise RuntimeError("subscribe failed")
            return lambda: None

    source = RebindableEventSource(Source())
    unsubscribe = source.subscribe(object())
    failed = Source(fail=True)

    source.rebind(failed)
    unsubscribe()

    assert source.source is failed
    assert isinstance(source.last_rebind_error, RuntimeError)


def test_open_interaction_run_context_enters_wraps_and_closes_in_order() -> None:
    from loushang.harnesstui.conversation.run_context import (
        open_interaction_run_context,
    )

    calls: list[str] = []

    class Context:
        def __enter__(self):
            calls.append("context.enter")
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback
            calls.append("context.exit")

    class Source:
        def subscribe(self, listener):
            calls.append(f"subscribe:{inspect.iscoroutinefunction(listener)}")
            return lambda: calls.append("unsubscribe")

    async def direct_listener(_event) -> None:
        return None

    context = open_interaction_run_context(
        event_source=Source(),
        listener=direct_listener,
        interactive_listener_factory=lambda _emit: direct_listener,
        exit_context=Context(),
        interactive=True,
        trace=lambda name, **_data: calls.append(name),
        on_open=lambda: calls.append("open"),
    )

    assert calls == ["context.enter", "open", "subscribe:True"]
    context.close()
    assert calls == [
        "context.enter",
        "open",
        "subscribe:True",
        "tui.end",
        "unsubscribe",
        "context.exit",
    ]


def test_open_interaction_run_context_uses_direct_noninteractive_listener() -> None:
    from loushang.harnesstui.conversation.run_context import (
        open_interaction_run_context,
    )

    listeners: list[object] = []

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

    class Source:
        def subscribe(self, listener):
            listeners.append(listener)
            return lambda: None

    listener = object()
    context = open_interaction_run_context(
        event_source=Source(),
        listener=listener,
        interactive_listener_factory=lambda _emit: object(),
        exit_context=Context(),
        interactive=False,
        trace=lambda _name, **_data: None,
    )

    assert listeners == [listener]
    context.close()


def test_open_interaction_run_context_exits_when_subscribe_fails() -> None:
    from loushang.harnesstui.conversation.run_context import (
        open_interaction_run_context,
    )

    calls: list[str] = []

    class Context:
        def __enter__(self):
            calls.append("context.enter")
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback
            calls.append("context.exit")

    class Source:
        def subscribe(self, _listener):
            calls.append("subscribe")
            raise RuntimeError("subscribe failed")

    with pytest.raises(RuntimeError, match="subscribe failed"):
        open_interaction_run_context(
            event_source=Source(),
            listener=object(),
            interactive_listener_factory=lambda _emit: object(),
            exit_context=Context(),
            interactive=False,
            trace=lambda _name, **_data: None,
        )

    assert calls == ["context.enter", "subscribe", "context.exit"]


async def _emit(write_callable, *, label: str) -> None:
    del label
    write_callable()

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol


class TraceFn(Protocol):
    """Trace one interaction lifecycle fact."""

    def __call__(self, name: str, **data: Any) -> None: ...


class StableEmit(Protocol):
    """Emit one terminal write through the caller's stable-write boundary."""

    def __call__(
        self,
        write_callable: Callable[[], None],
        *,
        label: str,
    ) -> Awaitable[None]: ...


class ExitContext(Protocol):
    """Minimal context-manager exit hook owned by a product adapter."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class InteractionContext(ExitContext, Protocol):
    """Context entered for the lifetime of one terminal interaction."""

    def __enter__(self) -> object: ...


@dataclass
class _EventSubscription:
    listener: object
    cleanup: Callable[[], None]


class RebindableEventSource:
    """Keep existing listeners attached while the underlying source changes."""

    def __init__(self, source: object) -> None:
        self._source = source
        self._subscriptions: list[_EventSubscription] = []
        self._last_rebind_error: Exception | None = None

    @property
    def source(self) -> object:
        return self._source

    @property
    def last_rebind_error(self) -> Exception | None:
        return self._last_rebind_error

    def subscribe(self, listener: object) -> Callable[[], None]:
        subscription = _EventSubscription(
            listener=listener,
            cleanup=subscribe_events(self._source, listener),
        )
        self._subscriptions.append(subscription)
        active = True

        def unsubscribe() -> None:
            nonlocal active
            if not active:
                return
            active = False
            self._subscriptions.remove(subscription)
            subscription.cleanup()

        return unsubscribe

    def rebind(self, source: object) -> None:
        if source is self._source:
            return
        self._last_rebind_error = None
        for subscription in self._subscriptions:
            try:
                subscription.cleanup()
            except Exception as error:
                self._last_rebind_error = self._last_rebind_error or error
        self._source = source
        for subscription in self._subscriptions:
            try:
                subscription.cleanup = subscribe_events(
                    source,
                    subscription.listener,
                )
            except Exception as error:
                self._last_rebind_error = self._last_rebind_error or error
                subscription.cleanup = lambda: None


@dataclass
class InteractionRunContext:
    """Own close ordering for one product-neutral terminal interaction run.

    The injected exit context may represent observability or another
    product-owned resource. This object coordinates only terminal interaction
    cleanup; it does not create Sessions or persist conversation state.
    """

    emit: StableEmit
    _unsubscribe: Callable[[], None]
    _exit_context: ExitContext
    _trace: TraceFn
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            try:
                self._trace("tui.end")
            finally:
                self._unsubscribe()
        finally:
            self._exit_context.__exit__(None, None, None)


def open_interaction_run_context(
    *,
    event_source: object,
    listener: object,
    interactive_listener_factory: Callable[[StableEmit], object],
    exit_context: InteractionContext,
    interactive: bool,
    trace: TraceFn,
    on_open: Callable[[], None] = lambda: None,
) -> InteractionRunContext:
    """Enter, trace, and subscribe one interaction as an atomic operation."""

    exit_context.__enter__()
    try:
        on_open()
        emit = stable_emit_factory(trace=trace, interactive=interactive)
        subscribed_listener = (
            interactive_listener_factory(emit) if interactive else listener
        )
        unsubscribe = subscribe_events(event_source, subscribed_listener)
    except BaseException:
        exit_context.__exit__(None, None, None)
        raise
    return InteractionRunContext(
        emit=emit,
        _unsubscribe=unsubscribe,
        _exit_context=exit_context,
        _trace=trace,
    )


def subscribe_events(source: object, listener: object) -> Callable[[], None]:
    """Subscribe when supported and always return a safe unsubscribe hook."""

    subscribe = getattr(source, "subscribe", None)
    if callable(subscribe):
        unsubscribe = subscribe(listener)
        if callable(unsubscribe):
            return unsubscribe
    return lambda: None


def stable_emit_factory(*, trace: TraceFn, interactive: bool) -> StableEmit:
    """Create a traced stable terminal-write boundary."""

    async def emit(write_callable: Callable[[], None], *, label: str) -> None:
        started = time.monotonic()
        trace("emit.start", label=label, interactive=interactive)
        try:
            write_callable()
        except Exception as error:
            trace(
                "emit.error",
                label=label,
                elapsed_s=time.monotonic() - started,
                error=str(error) or error.__class__.__name__,
            )
            raise
        trace("emit.end", label=label, elapsed_s=time.monotonic() - started)

    return emit


__all__ = [
    "ExitContext",
    "InteractionContext",
    "InteractionRunContext",
    "RebindableEventSource",
    "StableEmit",
    "TraceFn",
    "open_interaction_run_context",
    "stable_emit_factory",
    "subscribe_events",
]

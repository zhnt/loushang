from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TextIO, TypeVar

from loushang.harnesstui.conversation.action_presentation import (
    ConversationTracebackPolicy,
)
from loushang.harnesstui.conversation.run_context import StableEmit, TraceFn


class DispatchResult(Protocol):
    """Product-neutral facts returned by a conversation dispatcher."""

    @property
    def exit_code(self) -> int | None: ...

    @property
    def error_message(self) -> str | None: ...

    @property
    def status_message(self) -> str | None: ...

    @property
    def traceback_text(self) -> str | None: ...


class DispatchLifecycle(Protocol):
    active: bool

    def begin_work(self) -> int: ...

    def end_work(self) -> None: ...


IntentT = TypeVar("IntentT")
IntentT_contra = TypeVar("IntentT_contra", contravariant=True)


class DispatchController(Protocol[IntentT_contra]):
    async def dispatch(self, intent: IntentT_contra) -> DispatchResult: ...


@dataclass(frozen=True)
class ConversationDispatchOutcome:
    """Record neutral result and interaction-run facts for one dispatch."""

    result: DispatchResult
    run_id: int | None
    work_intent: bool
    started_at: float


class ConversationDispatchHandler(Generic[IntentT]):
    """Bracket product-classified work with shared interaction control."""

    def __init__(
        self,
        *,
        lifecycle: DispatchLifecycle,
        controller: DispatchController[IntentT],
        is_work_intent: Callable[[IntentT], bool],
        session_running: Callable[[], object],
        now: Callable[[], float] = time.monotonic,
        trace: TraceFn,
    ) -> None:
        self._lifecycle = lifecycle
        self._controller = controller
        self._is_work_intent = is_work_intent
        self._session_running = session_running
        self._now = now
        self._trace = trace

    async def dispatch(self, intent: IntentT) -> ConversationDispatchOutcome:
        work_intent = self._is_work_intent(intent)
        started_at = self._now()
        run_id: int | None = None
        if work_intent:
            run_id = self._lifecycle.begin_work()
        self._trace(
            "prompt.dispatch.start",
            intent=type(intent).__name__,
            work_intent=work_intent,
            run_id=run_id,
        )
        try:
            result = await self._controller.dispatch(intent)
        finally:
            if work_intent:
                self._lifecycle.end_work()
            self._trace(
                "prompt.dispatch.end",
                run_id=run_id,
                active_run=self._lifecycle.active,
                session_running=bool(self._session_running()),
            )
        return ConversationDispatchOutcome(
            result=result,
            run_id=run_id,
            work_intent=work_intent,
            started_at=started_at,
        )


class ResultRenderer(Protocol):
    def render_status(self, text: str) -> None: ...

    def render_error(self, text: str) -> None: ...

    def render_worked(self, elapsed_seconds: float) -> None: ...


class ConversationResultPresenter:
    """Present neutral dispatch facts through a supplied stable emitter."""

    def __init__(
        self,
        *,
        renderer: ResultRenderer,
        emit: StableEmit,
        stderr: TextIO,
        traceback_policy: ConversationTracebackPolicy,
        last_error_message: Callable[[], str | None],
        now: Callable[[], float],
        trace: TraceFn,
    ) -> None:
        self._renderer = renderer
        self._emit = emit
        self._stderr = stderr
        self._traceback_policy = traceback_policy
        self._last_error_message = last_error_message
        self._now = now
        self._trace = trace

    async def handle(
        self,
        outcome: ConversationDispatchOutcome,
        *,
        prompt_started: float,
        error_message: str | None,
    ) -> int | None:
        result = outcome.result
        if error_message:
            if self._last_error_message() != error_message:
                await self._emit(
                    lambda: self._renderer.render_error(error_message),
                    label="prompt:error",
                )
            self._traceback_policy.write(
                result.traceback_text,
                sink=self._stderr,
            )
        elif result.status_message:
            await self._emit(
                lambda: self._renderer.render_status(result.status_message or ""),
                label="prompt:status",
            )
        elif outcome.work_intent and result.exit_code is None:
            await self._emit(
                lambda: self._renderer.render_worked(self._now() - outcome.started_at),
                label="prompt:worked",
            )

        self._trace(
            "prompt.end",
            run_id=outcome.run_id,
            exit_code=result.exit_code,
            error_message=error_message,
            elapsed_s=self._now() - prompt_started,
        )
        return result.exit_code


EventT = TypeVar("EventT")
EventT_contra = TypeVar("EventT_contra", contravariant=True)


class EventRenderer(Protocol[EventT_contra]):
    def handle(self, event: EventT_contra) -> None: ...


class StableEventStreamHandler(Generic[EventT]):
    """Route caller-selected events through a stable emit boundary."""

    def __init__(
        self,
        *,
        renderer: EventRenderer[EventT],
        emit: StableEmit,
        writes_stably: Callable[[EventT], bool],
        event_type: Callable[[EventT], str],
        trace: TraceFn,
    ) -> None:
        self._renderer = renderer
        self._emit = emit
        self._writes_stably = writes_stably
        self._event_type = event_type
        self._trace = trace

    async def handle(self, event: EventT) -> None:
        event_type = self._event_type(event)
        self._trace("event.start", event_type=event_type)
        try:
            if not self._writes_stably(event):
                self._renderer.handle(event)
                return
            await self._emit(
                lambda: self._renderer.handle(event),
                label=f"event:{event_type}",
            )
        finally:
            self._trace("event.end", event_type=event_type)


__all__ = [
    "ConversationDispatchHandler",
    "ConversationDispatchOutcome",
    "ConversationResultPresenter",
    "DispatchController",
    "DispatchLifecycle",
    "DispatchResult",
    "EventRenderer",
    "ResultRenderer",
    "StableEmit",
    "StableEventStreamHandler",
    "TraceFn",
]

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from loushang.harness.events.session import (
    QueuedMessageSnapshot,
    QueueKind,
    QueueSnapshot,
)
from loushang.harness.runtime.input_queue import HostInputQueue
from loushang.harness.runtime.types import QueueMode

A = TypeVar("A")
M = TypeVar("M")
P = TypeVar("P")

StreamingBehavior = Literal["steer", "follow_up"]


@dataclass(frozen=True)
class TurnInput(Generic[A]):
    text: str
    attachments: A | None = None
    source: str | None = None


TurnInterceptor = Callable[[TurnInput[A]], Awaitable[TurnInput[A] | None]]
TurnPreflight = Callable[[TurnInput[A]], Awaitable[TurnInput[A] | None]]
QueueTurn = Callable[[StreamingBehavior, TurnInput[A]], None]
MessageBuilder = Callable[[TurnInput[A]], M]
BeforeStart = Callable[[TurnInput[A]], Awaitable[Iterable[M] | None]]
RunTurn = Callable[[list[M]], Awaitable[None]]
AsyncHook = Callable[[], Awaitable[object | None]]
AcceptanceReporter = Callable[[bool], None]


class TurnOrchestrator(Generic[A, M]):
    """Run a product-neutral prompt turn while products own payload semantics."""

    def __init__(
        self,
        *,
        interceptors: Iterable[TurnInterceptor[A]] = (),
        preflight: TurnPreflight[A],
        is_running: Callable[[], bool],
        queue_turn: QueueTurn[A],
        build_message: MessageBuilder[A, M],
        drain_pending: Callable[[], list[M]],
        run_turn: RunTurn[M],
        before_run: AsyncHook | None = None,
        before_start: BeforeStart[A, M] | None = None,
        busy_error: str | None = None,
    ) -> None:
        self._interceptors = tuple(interceptors)
        self._preflight = preflight
        self._is_running = is_running
        self._queue_turn = queue_turn
        self._build_message = build_message
        self._drain_pending = drain_pending
        self._run_turn = run_turn
        self._before_run = before_run
        self._before_start = before_start
        self._busy_error = busy_error or (
            "Host is already processing. Specify streaming_behavior "
            "('steer' or 'followUp') to queue the message."
        )

    async def run(
        self,
        turn_input: TurnInput[A],
        *,
        streaming_behavior: str | None = None,
        report_accepted: AcceptanceReporter | None = None,
    ) -> None:
        try:
            current = turn_input
            for interceptor in self._interceptors:
                intercepted = await interceptor(current)
                if intercepted is None:
                    _report(report_accepted, True)
                    return
                current = intercepted

            prepared = await self._preflight(current)
            if prepared is None:
                _report(report_accepted, True)
                return

            if self._is_running():
                behavior = normalize_streaming_behavior(streaming_behavior)
                if behavior is None:
                    raise RuntimeError(self._busy_error)
                self._queue_turn(behavior, prepared)
                _report(report_accepted, True)
                return

            if self._before_run is not None:
                await self._before_run()
            messages = [self._build_message(prepared), *self._drain_pending()]
            if self._before_start is not None:
                extra_messages = await self._before_start(prepared)
                if extra_messages is not None:
                    messages.extend(extra_messages)
        except Exception:
            _report(report_accepted, False)
            raise

        _report(report_accepted, True)
        await self._run_turn(messages)


def normalize_streaming_behavior(value: str | None) -> StreamingBehavior | None:
    if value == "steer":
        return "steer"
    if value in {"followUp", "follow_up"}:
        return "follow_up"
    return None


QueueSubmitter = Callable[[QueueKind, P], P]
QueueNotifier = Callable[[], None]
QueueObserver = Callable[[str, QueuedMessageSnapshot], None]


class TurnInputQueue(HostInputQueue[P], Generic[P]):
    """Coordinate visible turn queues with a product-owned delivery queue."""

    def __init__(
        self,
        *,
        submit: QueueSubmitter[P],
        clear_delivery_queue: Callable[[], None],
        has_delivery_messages: Callable[[], bool],
        notify: QueueNotifier,
        observe: QueueObserver | None = None,
    ) -> None:
        super().__init__()
        self._submit = submit
        self._clear_delivery_queue = clear_delivery_queue
        self._has_delivery_messages = has_delivery_messages
        self._notify = notify
        self._observe = observe

    def has_pending(self) -> bool:
        return super().has_pending() or self._has_delivery_messages()

    def enqueue(
        self,
        kind: QueueKind,
        *,
        text: str,
        payload: P,
    ) -> QueuedMessageSnapshot:
        delivered = self._submit(kind, payload)
        item = super().enqueue(kind, text=text, payload=delivered)
        self._observe_event("queued", item)
        self._notify()
        return item

    def clear(self) -> QueueSnapshot:
        previous = super().clear()
        self._clear_delivery_queue()
        self._notify()
        return previous

    def consume_visible(
        self, payload: object, *, fallback_text: str | None = None
    ) -> bool:
        consumed = super().consume(payload, fallback_text=fallback_text)
        if consumed is None:
            return False
        self._observe_event("consumed", consumed)
        self._notify()
        return True

    def prepare_continue(
        self,
        *,
        previous_turn_completed: bool,
        steering_mode: QueueMode,
        follow_up_mode: QueueMode,
    ) -> bool:
        if not previous_turn_completed:
            return False
        if self.texts("steering"):
            self.drain("steering", steering_mode)
            return True
        if self.texts("follow_up"):
            self.drain("follow_up", follow_up_mode)
            return True
        return False

    def _observe_event(self, event: str, item: QueuedMessageSnapshot) -> None:
        if self._observe is not None:
            self._observe(event, item)


def _report(reporter: AcceptanceReporter | None, accepted: bool) -> None:
    if reporter is not None:
        reporter(accepted)


__all__ = [
    "StreamingBehavior",
    "TurnInput",
    "TurnInputQueue",
    "TurnOrchestrator",
    "normalize_streaming_behavior",
]

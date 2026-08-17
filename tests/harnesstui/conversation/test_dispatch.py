from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import StringIO

import pytest

from loushang.harnesstui.conversation.action_presentation import (
    ConversationTracebackPolicy,
)
from loushang.harnesstui.conversation.dispatch import (
    ConversationDispatchHandler,
    ConversationDispatchOutcome,
    ConversationResultPresenter,
    StableEventStreamHandler,
)


@dataclass
class _Result:
    exit_code: int | None = None
    error_message: str | None = None
    status_message: str | None = None
    traceback_text: str | None = None


class _Lifecycle:
    def __init__(self) -> None:
        self.active = False
        self.begin_calls = 0
        self.end_calls = 0

    def begin_work(self) -> int:
        self.begin_calls += 1
        self.active = True
        return self.begin_calls

    def end_work(self) -> None:
        self.end_calls += 1
        self.active = False


class _Controller:
    def __init__(
        self,
        result: _Result | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or _Result()
        self.error = error

    async def dispatch(self, _intent: str) -> _Result:
        if self.error is not None:
            raise self.error
        return self.result


def test_dispatch_brackets_only_caller_classified_work() -> None:
    lifecycle = _Lifecycle()
    traces: list[tuple[str, dict[str, object]]] = []
    handler = ConversationDispatchHandler(
        lifecycle=lifecycle,
        controller=_Controller(_Result(exit_code=3)),
        is_work_intent=lambda intent: intent.startswith("work:"),
        session_running=lambda: False,
        now=lambda: 10.0,
        trace=lambda name, **data: traces.append((name, data)),
    )

    outcome = asyncio.run(handler.dispatch("work:review"))

    assert outcome.run_id == 1
    assert outcome.work_intent is True
    assert outcome.started_at == 10.0
    assert lifecycle.end_calls == 1
    assert traces == [
        (
            "prompt.dispatch.start",
            {"intent": "str", "work_intent": True, "run_id": 1},
        ),
        (
            "prompt.dispatch.end",
            {"run_id": 1, "active_run": False, "session_running": False},
        ),
    ]


def test_dispatch_does_not_start_lifecycle_for_non_work_intent() -> None:
    lifecycle = _Lifecycle()
    handler = ConversationDispatchHandler(
        lifecycle=lifecycle,
        controller=_Controller(_Result(exit_code=0)),
        is_work_intent=lambda _intent: False,
        session_running=lambda: True,
        trace=lambda _name, **_data: None,
    )

    outcome = asyncio.run(handler.dispatch("quit"))

    assert outcome.run_id is None
    assert outcome.work_intent is False
    assert outcome.result.exit_code == 0
    assert lifecycle.begin_calls == 0
    assert lifecycle.end_calls == 0


def test_dispatch_ends_work_when_controller_raises() -> None:
    lifecycle = _Lifecycle()
    handler = ConversationDispatchHandler(
        lifecycle=lifecycle,
        controller=_Controller(error=RuntimeError("dispatch exploded")),
        is_work_intent=lambda _intent: True,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    with pytest.raises(RuntimeError, match="dispatch exploded"):
        asyncio.run(handler.dispatch("work"))

    assert lifecycle.end_calls == 1
    assert lifecycle.active is False


class _Renderer:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.statuses: list[str] = []
        self.worked: list[float] = []

    def render_error(self, text: str) -> None:
        self.errors.append(text)

    def render_status(self, text: str) -> None:
        self.statuses.append(text)

    def render_worked(self, elapsed_seconds: float) -> None:
        self.worked.append(elapsed_seconds)


def _outcome(
    result: _Result,
    *,
    work_intent: bool = True,
) -> ConversationDispatchOutcome:
    return ConversationDispatchOutcome(
        result=result,
        run_id=2,
        work_intent=work_intent,
        started_at=10.0,
    )


def test_result_presenter_uses_caller_resolved_error_and_traceback() -> None:
    renderer = _Renderer()
    stderr = StringIO()

    async def emit(write, *, label: str) -> None:
        assert label == "prompt:error"
        write()

    presenter = ConversationResultPresenter(
        renderer=renderer,
        emit=emit,
        stderr=stderr,
        traceback_policy=ConversationTracebackPolicy(enabled=True),
        last_error_message=lambda: None,
        now=lambda: 12.0,
        trace=lambda _name, **_data: None,
    )

    exit_code = asyncio.run(
        presenter.handle(
            _outcome(_Result(exit_code=2, traceback_text="traceback text")),
            prompt_started=9.0,
            error_message="caller resolved error",
        )
    )

    assert exit_code == 2
    assert renderer.errors == ["caller resolved error"]
    assert stderr.getvalue() == "traceback text"


def test_result_presenter_does_not_duplicate_existing_event_error() -> None:
    renderer = _Renderer()
    labels: list[str] = []

    async def emit(write, *, label: str) -> None:
        labels.append(label)
        write()

    presenter = ConversationResultPresenter(
        renderer=renderer,
        emit=emit,
        stderr=StringIO(),
        traceback_policy=ConversationTracebackPolicy(enabled=False),
        last_error_message=lambda: "same error",
        now=lambda: 12.0,
        trace=lambda _name, **_data: None,
    )

    exit_code = asyncio.run(
        presenter.handle(
            _outcome(_Result(error_message="same error")),
            prompt_started=9.0,
            error_message="same error",
        )
    )

    assert exit_code is None
    assert labels == []
    assert renderer.errors == []


def test_result_presenter_emits_status_or_worked() -> None:
    renderer = _Renderer()
    labels: list[str] = []

    async def emit(write, *, label: str) -> None:
        labels.append(label)
        write()

    presenter = ConversationResultPresenter(
        renderer=renderer,
        emit=emit,
        stderr=StringIO(),
        traceback_policy=ConversationTracebackPolicy(enabled=False),
        last_error_message=lambda: None,
        now=lambda: 12.5,
        trace=lambda _name, **_data: None,
    )

    asyncio.run(
        presenter.handle(
            _outcome(_Result(status_message="caller status")),
            prompt_started=8.0,
            error_message=None,
        )
    )
    asyncio.run(
        presenter.handle(
            _outcome(_Result()),
            prompt_started=8.0,
            error_message=None,
        )
    )

    assert labels == ["prompt:status", "prompt:worked"]
    assert renderer.statuses == ["caller status"]
    assert renderer.worked == [2.5]


@dataclass(frozen=True)
class _Event:
    kind: str
    stable: bool


class _EventRenderer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.events: list[_Event] = []
        self.error = error

    def handle(self, event: _Event) -> None:
        if self.error is not None:
            raise self.error
        self.events.append(event)


def test_event_stream_uses_injected_stable_write_and_event_policy() -> None:
    renderer = _EventRenderer()
    labels: list[str] = []

    async def emit(write, *, label: str) -> None:
        labels.append(label)
        write()

    handler = StableEventStreamHandler(
        renderer=renderer,
        emit=emit,
        writes_stably=lambda event: event.stable,
        event_type=lambda event: event.kind,
        trace=lambda _name, **_data: None,
    )
    stable = _Event("committed", True)
    transient = _Event("streaming", False)

    asyncio.run(handler.handle(stable))
    asyncio.run(handler.handle(transient))

    assert renderer.events == [stable, transient]
    assert labels == ["event:committed"]


def test_event_stream_traces_end_when_renderer_raises() -> None:
    traces: list[str] = []
    handler = StableEventStreamHandler(
        renderer=_EventRenderer(error=RuntimeError("render failed")),
        emit=_unused_emit,
        writes_stably=lambda _event: False,
        event_type=lambda event: event.kind,
        trace=lambda name, **_data: traces.append(name),
    )

    with pytest.raises(RuntimeError, match="render failed"):
        asyncio.run(handler.handle(_Event("broken", False)))

    assert traces == ["event.start", "event.end"]


async def _unused_emit(write, *, label: str) -> None:
    del write
    raise AssertionError(f"unexpected stable emit: {label}")

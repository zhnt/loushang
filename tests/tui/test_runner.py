from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import StringIO
from typing import Any, Literal

from loushang.tui import (
    FakeTerminalPort,
    FocusableMixin,
    InputEvent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    TerminalSize,
    Tui,
    TuiInputResult,
    TuiRunner,
)
from loushang.tui.input import BRACKETED_PASTE_END, BRACKETED_PASTE_START


def test_runner_renders_first_frame_and_calls_input_handler() -> None:
    tui = Tui()
    tui.add_child(_MutableRenderable(("ready",)))
    seen: list[InputEvent] = []

    async def run() -> int:
        async def handle(event: InputEvent, _context: object) -> TuiInputResult:
            seen.append(event)
            return TuiInputResult(exit_code=7)

        return await TuiRunner(
            tui,
            stdin=StringIO("x"),
            stdout=StringIO(),
            terminal_session_factory=_recording_terminal_session_factory(),
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run(on_input=handle)

    assert asyncio.run(run()) == 7
    assert seen == [InputEvent(kind="text", text="x")]


def test_runner_defaults_to_tui_input_routing_when_no_handler_is_provided() -> None:
    tui = Tui()
    target = _FocusableRenderable(("input",))
    tui.add_child(target)
    tui.set_focus(target)

    async def run() -> int:
        return await TuiRunner(
            tui,
            stdin=StringIO("a"),
            stdout=StringIO(),
            terminal_session_factory=_recording_terminal_session_factory(),
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run()

    assert asyncio.run(run()) == 0
    assert target.events == [InputEvent(kind="text", text="a")]


def test_runner_restores_tui_terminal_runtime_and_context_after_exit() -> None:
    tui = Tui()
    old_terminal = FakeTerminalPort(size=TerminalSize(columns=10, rows=3))
    old_context = object()
    tui.attach_terminal(old_terminal)
    old_runtime = tui._ensure_runtime()
    tui.terminal_context = old_context

    async def run() -> int:
        return await TuiRunner(
            tui,
            stdin=StringIO(""),
            stdout=StringIO(),
            terminal_session_factory=_recording_terminal_session_factory(),
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run()

    assert asyncio.run(run()) == 0
    assert tui.terminal is old_terminal
    assert tui._runtime is old_runtime
    assert tui.terminal_context is old_context


def test_runner_consumes_terminal_control_events_without_dispatching_them() -> None:
    session = _RecordingTerminalSession()
    tui = Tui()
    seen: list[InputEvent] = []

    async def run() -> int:
        async def handle(event: InputEvent, _context: object) -> TuiInputResult:
            seen.append(event)
            return TuiInputResult()

        return await TuiRunner(
            tui,
            stdin=StringIO("\x1b[6;18;9t"),
            stdout=StringIO(),
            terminal_session_factory=lambda _stdin, _stdout: session,
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run(on_input=handle)

    assert asyncio.run(run()) == 0
    assert seen == []
    assert session.control_events == [
        (
            InputEvent(
                kind="signal", signal="cell_size", text="18;9", raw="\x1b[6;18;9t"
            ),
        )
    ]


def test_runner_keeps_split_bracketed_paste_atomic() -> None:
    tui = Tui()
    seen: list[InputEvent] = []

    async def run() -> int:
        async def handle(event: InputEvent, _context: object) -> TuiInputResult:
            seen.append(event)
            return TuiInputResult()

        return await TuiRunner(
            tui,
            stdin=StringIO(f"{BRACKETED_PASTE_START}hello\nworld{BRACKETED_PASTE_END}"),
            stdout=StringIO(),
            terminal_session_factory=_recording_terminal_session_factory(),
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run(on_input=handle)

    assert asyncio.run(run()) == 0
    assert seen == [InputEvent(kind="paste", text="hello\nworld")]


def test_runner_context_request_render_wakes_input_wait() -> None:
    root = _MutableRenderable(("first",))
    tui = Tui()
    tui.add_child(root)
    stdout = StringIO()

    async def run() -> int:
        async def handle(event: InputEvent, context: Any) -> TuiInputResult:
            assert event == InputEvent(kind="text", text="x")

            async def request_later() -> None:
                await asyncio.sleep(0.001)
                root.lines = ("updated",)
                context.request_render("input")

            asyncio.create_task(request_later())
            return TuiInputResult(render_requested=False)

        return await TuiRunner(
            tui,
            stdin=StringIO(""),
            stdout=stdout,
            terminal_session_factory=_recording_terminal_session_factory(),
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
            input_chunk_reader=_AsyncAfterFirstInput(first="x", block_seconds=0.03),
        ).run(on_input=handle)

    assert asyncio.run(run()) == 0
    assert "first" in stdout.getvalue()
    assert "updated" in stdout.getvalue()


def test_runner_restores_tui_state_when_input_handler_raises() -> None:
    tui = Tui()
    old_terminal = FakeTerminalPort(size=TerminalSize(columns=10, rows=3))
    old_context = object()
    tui.attach_terminal(old_terminal)
    old_runtime = tui._ensure_runtime()
    tui.terminal_context = old_context

    async def run() -> None:
        async def handle(_event: InputEvent, _context: object) -> TuiInputResult:
            raise RuntimeError("boom")

        await TuiRunner(
            tui,
            stdin=StringIO("x"),
            stdout=StringIO(),
            terminal_session_factory=_recording_terminal_session_factory(),
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run(on_input=handle)

    try:
        asyncio.run(run())
    except RuntimeError as error:
        assert str(error) == "boom"
    else:
        raise AssertionError("expected handler error")

    assert tui.terminal is old_terminal
    assert tui._runtime is old_runtime
    assert tui.terminal_context is old_context


def test_runner_rejects_reentrant_run_calls() -> None:
    tui = Tui()
    runner = TuiRunner(
        tui,
        stdin=StringIO(""),
        stdout=StringIO(),
        terminal_session_factory=_recording_terminal_session_factory(),
        terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        input_chunk_reader=_AsyncAfterFirstInput(first="x", block_seconds=0.03),
    )
    errors: list[str] = []

    async def run() -> int:
        async def handle(_event: InputEvent, _context: object) -> TuiInputResult:
            try:
                await runner.run()
            except RuntimeError as error:
                errors.append(str(error))
            return TuiInputResult(exit_code=0)

        return await runner.run(on_input=handle)

    assert asyncio.run(run()) == 0
    assert errors == [
        "TuiRunner.run() cannot be called while the runner is already running"
    ]


def test_runner_context_stop_returns_exit_code() -> None:
    tui = Tui()

    async def run() -> int:
        async def handle(_event: InputEvent, context: Any) -> TuiInputResult:
            return context.stop(12)

        return await TuiRunner(
            tui,
            stdin=StringIO("x"),
            stdout=StringIO(),
            terminal_session_factory=_recording_terminal_session_factory(),
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run(on_input=handle)

    assert asyncio.run(run()) == 12


def test_runner_passes_streams_to_terminal_session_factory() -> None:
    stdin = StringIO("")
    stdout = StringIO()
    seen: list[tuple[object, object]] = []

    def factory(
        input_stream: object, output_stream: object
    ) -> _RecordingTerminalSession:
        seen.append((input_stream, output_stream))
        return _RecordingTerminalSession()

    async def run() -> int:
        return await TuiRunner(
            Tui(),
            stdin=stdin,
            stdout=stdout,
            terminal_session_factory=factory,
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run()

    assert asyncio.run(run()) == 0
    assert seen == [(stdin, stdout)]


def test_runner_invokes_start_hook_after_runtime_is_available() -> None:
    root = _MutableRenderable(("before",))
    tui = Tui()
    tui.add_child(root)
    stdout = StringIO()
    contexts: list[object] = []

    async def run() -> int:
        def start(context: object) -> None:
            contexts.append(context)
            root.lines = ("started",)

        return await TuiRunner(
            tui,
            stdin=StringIO(""),
            stdout=stdout,
            terminal_session_factory=_recording_terminal_session_factory(),
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
        ).run(on_start=start)

    assert asyncio.run(run()) == 0
    assert len(contexts) == 1
    assert "started" in stdout.getvalue()


def test_runner_polls_terminal_runtime_fallback_on_idle_wakeup() -> None:
    session = _PollingTerminalSession()

    async def run() -> int:
        async def handle(_event: InputEvent, _context: object) -> TuiInputResult:
            return TuiInputResult(render_requested=False)

        return await TuiRunner(
            Tui(),
            stdin=StringIO(""),
            stdout=StringIO(),
            terminal_session_factory=lambda _stdin, _stdout: session,
            terminal_size_provider=lambda: TerminalSize(columns=20, rows=5),
            input_chunk_reader=_AsyncAfterFirstInput(first="x", block_seconds=0.03),
        ).run(on_input=handle)

    assert asyncio.run(run()) == 0
    assert session.fallback_polls >= 1


@dataclass
class _MutableRenderable:
    lines: tuple[str, ...]

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            [RenderLine(line) for line in self.lines], constraints=constraints
        )


class _FocusableRenderable(FocusableMixin):
    def __init__(self, lines: tuple[str, ...]) -> None:
        super().__init__()
        self.lines = lines
        self.events: list[InputEvent] = []

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            [RenderLine(line) for line in self.lines], constraints=constraints
        )

    def handle_input(self, event: Any) -> object:
        self.events.append(event)
        return None


class _RecordingTerminalSession:
    def __init__(self) -> None:
        self.control_events: list[tuple[InputEvent, ...]] = []
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> _RecordingTerminalSession:
        self.entered += 1
        return self

    def __exit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> Literal[False]:
        self.exited += 1
        return False

    def consume_control_events(self, events: tuple[InputEvent, ...]) -> None:
        self.control_events.append(events)

    def next_wakeup_delay_ms(self) -> int | None:
        return None

    def flush_keyboard_protocol_fallback_if_due(self) -> bool:
        return False


class _PollingTerminalSession(_RecordingTerminalSession):
    def __init__(self) -> None:
        super().__init__()
        self.fallback_polls = 0

    def next_wakeup_delay_ms(self) -> int | None:
        return None if self.fallback_polls else 1

    def flush_keyboard_protocol_fallback_if_due(self) -> bool:
        self.fallback_polls += 1
        return True


def _recording_terminal_session_factory() -> Any:
    return lambda _stdin, _stdout: _RecordingTerminalSession()


class _AsyncAfterFirstInput:
    def __init__(self, *, first: str, block_seconds: float) -> None:
        self._first = first
        self._block_seconds = block_seconds
        self._calls = 0

    async def __call__(self, _stdin: Any) -> str:
        self._calls += 1
        if self._calls == 1:
            return self._first
        await asyncio.sleep(self._block_seconds)
        return ""

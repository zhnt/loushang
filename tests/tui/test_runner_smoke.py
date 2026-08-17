from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import StringIO
from typing import Any, Literal

from loushang.tui import (
    InputEvent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    TerminalSize,
    Tui,
    TuiInputResult,
    TuiRunner,
    strip_control_sequences,
)


def test_runner_smoke_drives_input_async_render_control_event_and_exit_cleanup() -> (
    None
):
    view = _SmokeView()
    tui = Tui()
    tui.add_child(view)
    stdout = StringIO()
    session = _RecordingTerminalSession()
    input_chunk_reader = _ScriptedInput(
        (
            "a",
            "\x1b[6;18;9t",
            "r",
            _SleepThen("q", seconds=0.03),
            "",
        )
    )
    seen_events: list[InputEvent] = []

    async def run() -> int:
        async def handle(event: InputEvent, context: Any) -> TuiInputResult:
            seen_events.append(event)
            if event.kind == "text" and "q" in event.text:
                return context.stop(0)
            if event.kind == "text" and "a" in event.text:
                view.count += 1
                view.status = "typed"
                return TuiInputResult()
            if event.kind == "text" and "r" in event.text:

                async def refresh_later() -> None:
                    await asyncio.sleep(0.001)
                    view.status = "async refreshed"
                    context.request_render("stream")

                asyncio.create_task(refresh_later())
                return TuiInputResult(render_requested=False)
            return TuiInputResult(render_requested=False)

        return await TuiRunner(
            tui,
            stdin=StringIO(""),
            stdout=stdout,
            terminal_session_factory=lambda _stdin, _stdout: session,
            terminal_size_provider=lambda: TerminalSize(columns=32, rows=8),
            input_chunk_reader=input_chunk_reader,
        ).run(on_input=handle)

    assert asyncio.run(run()) == 0
    output = stdout.getvalue()
    plain_output = strip_control_sequences(output)

    assert "Count: 0" in plain_output
    assert "Count: 1" in plain_output
    assert "Status: typed" in plain_output
    assert "Status: async refreshed" in plain_output
    assert "\x1b[?2026h" in output
    assert "\x1b[?2026l" in output
    assert "\x1b[?25l" in output
    assert "\x1b[?25h" in output
    assert tuple(seen_events) == (
        InputEvent(kind="text", text="a"),
        InputEvent(kind="text", text="r"),
        InputEvent(kind="text", text="q"),
    )
    assert session.control_events == [
        (
            InputEvent(
                kind="signal", signal="cell_size", text="18;9", raw="\x1b[6;18;9t"
            ),
        )
    ]
    assert session.entered == 1
    assert session.exited == 1


@dataclass(slots=True)
class _SmokeView:
    count: int = 0
    status: str = "initial"

    def render(self, constraints: RenderConstraints) -> RenderResult:
        rows = (
            "Runner Smoke",
            f"Count: {self.count}",
            f"Status: {self.status}",
        )
        return RenderResult.from_lines(
            [RenderLine(row[: constraints.width]) for row in rows],
            constraints=constraints,
        )


@dataclass(frozen=True, slots=True)
class _SleepThen:
    value: str
    seconds: float


class _ScriptedInput:
    def __init__(self, chunks: tuple[str | _SleepThen, ...]) -> None:
        self._chunks = list(chunks)

    async def __call__(self, _stdin: Any) -> str:
        if not self._chunks:
            return ""
        chunk = self._chunks.pop(0)
        if isinstance(chunk, _SleepThen):
            await asyncio.sleep(chunk.seconds)
            return chunk.value
        return chunk


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

from __future__ import annotations

import argparse
import asyncio
import random
import shutil
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Literal, Protocol, TextIO

from loushang.tui import (
    AssistantMessageRecord,
    BottomFrame,
    Composer,
    ErrorRecord,
    InputEvent,
    InputReader,
    InputRouter,
    MarkdownRenderer,
    PendingQueueView,
    PendingSection,
    RenderConstraints,
    RenderLine,
    RenderLoop,
    RenderResult,
    ScreenLayout,
    StatusBar,
    StatusField,
    TerminalSize,
    ThemeResolver,
    ThinkingRecord,
    ThinkingVisibility,
    ToolExecutionRecord,
    TuiRuntime,
    UserPromptRecord,
    WorkedDivider,
    WorkedDividerRecord,
    WorkingLine,
    apply_theme_style,
    truncate_to_width,
    visible_width,
    wrap_cells,
)
from loushang.tui.terminal import ProcessTerminalPort
from loushang.tui.terminal_input import (
    TerminalInputMode,
    read_input_chunk_or_render_tick,
)

THEME = {
    "user": {"color": "bright_cyan", "bold": True},
    "assistant": {"color": 252},
    "muted": {"color": 245},
    "thinking": {"color": "yellow"},
    "tool": {"color": "green"},
    "error": {"color": "bright_red"},
    "hint": {"color": 250},
}


MARKDOWN_THEME = ThemeResolver(
    defaults={
        "markdown.heading.level1": {"color": "bright_cyan", "bold": True},
        "markdown.heading.level2": {"color": "bright_cyan", "bold": True},
        "markdown.heading.level3": {"color": "bright_cyan", "bold": True},
        "markdown.inline_code": {"color": "yellow"},
        "markdown.strong": {"bold": True},
        "markdown.emphasis": {"italic": True},
        "markdown.strikethrough": {"strikethrough": True},
        "markdown.link": {"color": "bright_blue", "underline": True},
        "markdown.list.marker": {"color": "bright_cyan"},
        "markdown.quote.marker": {"color": "green"},
        "markdown.code.fence": {"color": "bright_black"},
        "markdown.code.text": {"color": 252},
        "markdown.table.header": {"bold": True},
        "markdown.hr": {"dim": True},
    }
)


SAMPLE_ASSISTANT_MARKDOWN = """## Bottom frame contract
- The transcript stays above the live input frame.
- The composer supports soft wrap, explicit newlines, history, kill ring, and large paste markers.
- The status line stays on the last row and truncates low-priority fields first.
  - Low-priority status fields truncate before the prompt moves.
  - Queued follow-ups and steer messages stay in the bottom frame.

| Area | Responsibility |
| --- | --- |
| transcript | committed records and streaming drafts |
| working | transient run progress |
| composer | editable prompt buffer |

> Visual check: links, lists, tables, quotes, and code should share the same width model.

```python
frame = BottomFrame(
    composer=composer,
    working_line=working,
    pending_queue=pending,
    status_bar=status,
)
```

This example is fake model output, but it exercises the same render path used by the coding UI adapter."""


FAKE_RESPONSE_TEMPLATE = """## Fake assistant response

You submitted:

> {prompt}

The demo now streams a markdown-shaped answer through the same logical screen buffer as the composer:

- `WorkingLine` is transient while the request is active.
- `PendingQueueView` appears below the working line when you submit follow-up or steer text during a run.
- `WorkedDivider` is committed after the fake turn finishes.
  - The divider becomes stable transcript content.
  - The next composer render should not duplicate the previous prompt.

Task list sample:

- [x] Keep composer input visible while output streams.
- [ ] Preserve queued follow-up text below the working line.
- [ ] Reflow tables and lists after resize.

| Feature | Markdown shape | Expected behavior |
| --- | --- | --- |
| links | [docs](https://example.com) and <https://example.com> | OSC 8 when available, visible URL fallback otherwise |
| table | long cells wrap inside the box | borders stay aligned by cell width |
| list | nested bullets with `inline code` | continuation rows align under item text |

> Follow-up text typed during streaming should be visible in the pending queue.
> - `/steer text` becomes a steering message.
> - Plain submitted text becomes the next queued prompt.

```text
Enter      submit
Ctrl-J     insert explicit newline
Alt-Up     edit last queued follow-up
/steer x   steer current fake run after the next model chunk
Esc/Ctrl-C abort active fake run
```

Try typing another prompt while this answer is still streaming."""


STREAM_CHUNK_SIZE = 42
DEFAULT_MIN_RUN_SECONDS = 5.0
DEFAULT_MAX_RUN_SECONDS = 15.0
ACTIVE_RENDER_INTERVAL_MS = 80
EXIT_COMMANDS = {"/q", "/quit", "/exit"}


DisplayState = Literal["idle", "running", "cancelled"]


class ExampleRenderable(Protocol):
    def render(self, constraints: RenderConstraints) -> RenderResult: ...


@dataclass(slots=True)
class ComposerBottomFrameDemo:
    composer: Composer = field(default_factory=lambda: Composer(prompt="› ", continuation_prompt="  "))
    records: list[object] = field(default_factory=list)
    pending_followups: list[str] = field(default_factory=list)
    pending_steers: list[str] = field(default_factory=list)
    interruption_message: str | None = None
    assistant_draft: AssistantMessageRecord | None = None
    state: DisplayState = "idle"
    started_at: float | None = None
    planned_duration_seconds: float = 0.0
    _active_tool_index: int | None = None
    _record_line_cache: dict[tuple[object, int], tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def seeded(cls) -> ComposerBottomFrameDemo:
        app = cls()
        app.records.extend(
            [
                UserPromptRecord("展示一下新的 TUI 底部布局。"),
                ThinkingRecord("Sketching the frame hierarchy before rendering.", ThinkingVisibility.COLLAPSED),
                ToolExecutionRecord("inspect_tui_parts", "completed", 0.31, "Composer, BottomFrame, StatusBar"),
                AssistantMessageRecord(SAMPLE_ASSISTANT_MARKDOWN, stable=True),
                WorkedDividerRecord(1.24),
            ]
        )
        return app

    @property
    def running(self) -> bool:
        return self.state == "running"

    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self.started_at)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        width = constraints.width
        visible_height = constraints.visible_height or constraints.max_height
        frame_height_limit = 16 if self.interruption_message or self.pending_followups or self.pending_steers else 12
        editor_height = max(1, min(frame_height_limit, visible_height))
        layout = ScreenLayout(
            transcript=_TranscriptRegion(
                records=self.records,
                draft=self.assistant_draft,
                cache=self._record_line_cache,
            ),
            editor=_CappedRenderable(self._bottom_frame(), max_height=editor_height),
            editor_min_height=editor_height,
        )
        return layout.render(RenderConstraints(width=width, max_height=constraints.max_height, visible_height=visible_height))

    def next_frame_due_ms(self, *, after_ms: int) -> int | None:
        if not self.running:
            return None
        return after_ms + ACTIVE_RENDER_INTERVAL_MS

    def _bottom_frame(self) -> BottomFrame:
        return BottomFrame(
            composer=self.composer,
            pending_queue=self._pending_queue(),
            working_line=self._working_line(),
            status_bar=self._status_bar(),
        )

    def _pending_queue(self) -> PendingQueueView | None:
        sections: list[PendingSection] = []
        if self.interruption_message:
            sections.append(
                PendingSection(
                    label=self.interruption_message,
                    marker="■",
                    show_when_empty=True,
                )
            )
        if self.pending_steers:
            sections.append(
                PendingSection(
                    label="Messages to be submitted after next tool call",
                    items=tuple(self.pending_steers),
                    hint="press esc to interrupt and send immediately",
                    hint_placement="header",
                )
            )
        if self.pending_followups:
            sections.append(
                PendingSection(
                    label="Queued follow-up inputs",
                    items=tuple(self.pending_followups),
                    hint="alt + ↑ edit last queued message",
                )
            )
        if not sections:
            return None
        return PendingQueueView(sections=tuple(sections))

    def _working_line(self) -> WorkingLine | None:
        if not self.running:
            return None
        return WorkingLine(label="Working", elapsed_seconds=self.elapsed_seconds())

    def _status_bar(self) -> StatusBar:
        status = "running" if self.running else self.state
        return StatusBar(
            [
                StatusField("fake-model", priority=100),
                StatusField("5D composer-frame", priority=90),
                StatusField(status, priority=80),
                StatusField(f"queued={len(self.pending_followups)} steer={len(self.pending_steers)}", priority=70),
                StatusField(f"target={self.planned_duration_seconds:.1f}s", priority=60),
                StatusField("ctrl-c quit idle", priority=10),
            ]
        )

    def start_prompt(self, text: str, *, duration_seconds: float) -> asyncio.Task[int | None]:
        self.records.append(UserPromptRecord(text))
        self.state = "running"
        self.started_at = time.monotonic()
        self.planned_duration_seconds = duration_seconds
        self.assistant_draft = None
        self.interruption_message = None
        self._active_tool_index = len(self.records)
        self.records.append(ToolExecutionRecord("fake_model_stream", "running", 0.0, "markdown chunks"))
        return asyncio.create_task(self._stream_response(text, duration_seconds=duration_seconds))

    def queue_followup(self, text: str) -> None:
        self.pending_followups.append(text)

    def start_next_followup(self, *, duration_seconds: float) -> asyncio.Task[int | None] | None:
        if self.running or self.state != "idle" or not self.pending_followups:
            return None
        return self.start_prompt(self.pending_followups.pop(0), duration_seconds=duration_seconds)

    def queue_steer(self, text: str) -> None:
        self.pending_steers.append(text)

    def pop_last_queued(self) -> str | None:
        if not self.pending_followups:
            return None
        return self.pending_followups.pop()

    def abort(self, task: asyncio.Task[int | None] | None) -> None:
        if task is not None and not task.done():
            task.cancel()
        elapsed = self.elapsed_seconds()
        if self.assistant_draft is not None:
            self.records.append(AssistantMessageRecord(self.assistant_draft.text, stable=True))
            self.assistant_draft = None
        self.records.append(WorkedDividerRecord(elapsed))
        self.interruption_message = (
            "Conversation interrupted - tell the model what to do differently. "
            "Something went wrong? Hit `/feedback` to report the issue."
        )
        self.state = "cancelled"
        self.started_at = None
        self.planned_duration_seconds = 0.0
        self._active_tool_index = None

    async def _stream_response(self, prompt: str, *, duration_seconds: float) -> int | None:
        try:
            chunks = _chunks(FAKE_RESPONSE_TEMPLATE.format(prompt=prompt), STREAM_CHUNK_SIZE)
            per_chunk_delay = _chunk_delay(duration_seconds, len(chunks))
            await asyncio.sleep(per_chunk_delay)
            self._complete_tool()
            for chunk in chunks:
                self._consume_steers()
                self._append_assistant_chunk(chunk)
                await asyncio.sleep(per_chunk_delay)
            self._consume_steers()
            self._commit_assistant()
            self.records.append(WorkedDividerRecord(self.elapsed_seconds()))
            self.state = "idle"
            self.started_at = None
            self.planned_duration_seconds = 0.0
            self._active_tool_index = None
            return None
        except asyncio.CancelledError:
            return None

    def _complete_tool(self) -> None:
        if self._active_tool_index is None:
            return
        self.records[self._active_tool_index] = ToolExecutionRecord(
            "fake_model_stream",
            "completed",
            self.elapsed_seconds(),
            "markdown chunks",
        )

    def _append_assistant_chunk(self, chunk: str) -> None:
        if self.assistant_draft is None:
            self.assistant_draft = AssistantMessageRecord(chunk, stable=False)
            return
        self.assistant_draft = AssistantMessageRecord(self.assistant_draft.text + chunk, stable=False)

    def _commit_assistant(self) -> None:
        if self.assistant_draft is None:
            return
        self.records.append(AssistantMessageRecord(self.assistant_draft.text, stable=True))
        self.assistant_draft = None

    def _consume_steers(self) -> None:
        if not self.pending_steers:
            return
        steers = tuple(self.pending_steers)
        self.pending_steers.clear()
        for steer in steers:
            self.records.append(ThinkingRecord(f"Steer applied: {steer}", ThinkingVisibility.VISIBLE))


@dataclass(slots=True)
class _TranscriptRegion:
    records: list[object]
    draft: AssistantMessageRecord | None
    cache: dict[tuple[object, int], tuple[str, ...]]

    def render(self, constraints: RenderConstraints) -> RenderResult:
        lines = _render_transcript(
            records=self.records,
            draft=self.draft,
            width=constraints.width,
            max_height=1_000_000,
            cache=self.cache,
        )
        lines = lines[-constraints.max_height :]
        return RenderResult.from_lines([RenderLine(_fit(line, constraints.width)) for line in lines], constraints=constraints)


@dataclass(slots=True)
class _CappedRenderable:
    renderable: ExampleRenderable
    max_height: int

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return self.renderable.render(
            RenderConstraints(
                width=constraints.width,
                max_height=max(1, min(self.max_height, constraints.max_height)),
                visible_height=constraints.visible_height,
            )
        )


def _render_transcript(
    *,
    records: list[object],
    draft: AssistantMessageRecord | None,
    width: int,
    max_height: int,
    cache: dict[tuple[object, int], tuple[str, ...]] | None = None,
) -> list[str]:
    rows: list[str] = []
    for record in [*records, *([draft] if draft is not None else [])]:
        rows.extend(_cached_render_record(record, width=width, cache=cache))
        rows.append("")
    if rows and rows[-1] == "":
        rows.pop()
    return rows[-max_height:]


def _cached_render_record(
    record: object,
    *,
    width: int,
    cache: dict[tuple[object, int], tuple[str, ...]] | None,
) -> tuple[str, ...]:
    if cache is None or _record_is_streaming_draft(record):
        return tuple(_render_record(record, width=width))

    key = (record, width)
    cached = cache.get(key)
    if cached is not None:
        return cached
    rendered = tuple(_render_record(record, width=width))
    cache[key] = rendered
    return rendered


def _record_is_streaming_draft(record: object) -> bool:
    return isinstance(record, AssistantMessageRecord) and not record.stable


def _render_record(record: object, *, width: int) -> list[str]:
    if isinstance(record, UserPromptRecord):
        return _prefixed_text("› ", record.text, width=width, style=THEME["user"])
    if isinstance(record, AssistantMessageRecord):
        style = THEME["assistant"] if record.stable else THEME["hint"]
        return _prefixed_markdown("• ", record.text, width=width, style=style)
    if isinstance(record, ThinkingRecord):
        if record.visibility is ThinkingVisibility.HIDDEN:
            return []
        label = "• Thinking"
        text = "collapsed" if record.visibility is ThinkingVisibility.COLLAPSED else record.text
        return _prefixed_text(label + " ", text, width=width, style=THEME["thinking"])
    if isinstance(record, ToolExecutionRecord):
        if record.state == "running":
            text = f"Ran {record.name} {record.elapsed_seconds:.2f}s"
        else:
            text = f"Ran {record.name} took {record.elapsed_seconds:.2f}s"
        if record.output:
            text = f"{text}\n{record.output}"
        return _prefixed_text("• ", text, width=width, style=THEME["tool"])
    if isinstance(record, ErrorRecord):
        text = record.summary if not record.diagnostics else f"{record.summary}\n{record.diagnostics}"
        return _prefixed_text("■ Error: ", text, width=width, style=THEME["error"])
    if isinstance(record, WorkedDividerRecord):
        return [WorkedDivider(record.elapsed_seconds).render(_rc(max(1, width - 1), 1)).lines[0].text]
    return []


def _prefixed_markdown(prefix: str, markdown: str, *, width: int, style: dict[str, object]) -> list[str]:
    prefix_width = visible_width(prefix)
    continuation = "  "
    inner_width = max(1, width - max(prefix_width, visible_width(continuation)))
    result = MarkdownRenderer(markdown, theme=MARKDOWN_THEME).render(_rc(inner_width, 1_000))
    lines = [line.text for line in result.lines]
    return _prefix_lines(prefix, continuation, lines, width=width, style=style)


def _prefixed_text(prefix: str, text: str, *, width: int, style: dict[str, object]) -> list[str]:
    prefix_width = visible_width(prefix)
    continuation = "  "
    inner_width = max(1, width - max(prefix_width, visible_width(continuation)))
    lines: list[str] = []
    for logical_line in text.split("\n"):
        lines.extend(wrap_cells(logical_line, width=inner_width))
    return _prefix_lines(prefix, continuation, lines or [""], width=width, style=style)


def _prefix_lines(
    prefix: str,
    continuation: str,
    lines: list[str],
    *,
    width: int,
    style: dict[str, object],
) -> list[str]:
    rows: list[str] = []
    for index, line in enumerate(lines):
        row_prefix = prefix if index == 0 else continuation
        styled_prefix = apply_theme_style(row_prefix, style)
        rows.append(_fit(styled_prefix + line, width))
    return rows


def _fit(text: str, width: int) -> str:
    return truncate_to_width(text, max_width=max(1, width - 1), ellipsis="...")


def _rc(width: int, height: int) -> RenderConstraints:
    return RenderConstraints(width=max(1, width), max_height=max(1, height), visible_height=max(1, height))


def _chunks(text: str, size: int) -> tuple[str, ...]:
    return tuple(text[index : index + size] for index in range(0, len(text), size))


def _chunk_delay(duration_seconds: float, chunk_count: int) -> float:
    if duration_seconds <= 0 or chunk_count <= 0:
        return 0.0
    return duration_seconds / (chunk_count + 1)


def _terminal_size() -> TerminalSize:
    size = shutil.get_terminal_size((100, 28))
    return TerminalSize(columns=size.columns, rows=size.lines)


async def run_interactive(*, stdin: TextIO, stdout: TextIO, min_run_seconds: float, max_run_seconds: float) -> int:
    app = ComposerBottomFrameDemo.seeded()
    reader = InputReader()
    runtime = TuiRuntime(
        render_loop=RenderLoop(app),
        terminal=ProcessTerminalPort(output=stdout, size_provider=_terminal_size, track_screen=False),
    )
    stdout.write("\n")
    stdout.flush()
    active_task: asyncio.Task[int | None] | None = None
    with TerminalInputMode(stdin=stdin, stdout=stdout):
        runtime.render_now()
        while True:
            active_task, drained = await _drain_finished_task(
                active_task,
                app=app,
                min_run_seconds=min_run_seconds,
                max_run_seconds=max_run_seconds,
            )
            if drained:
                runtime.render_now()
            data = await read_input_chunk_or_render_tick(stdin, runtime=runtime, active_task=active_task)
            if data is None:
                continue
            if data == "":
                stdout.write("\n")
                stdout.flush()
                return 0
            exit_requested = False
            for event in reader.feed(data):
                if _idle_exit_requested(event, app):
                    exit_requested = True
                    break
                router = InputRouter(
                    composer=app.composer,
                    running=app.running,
                    width=runtime.terminal.size().columns,
                )
                for intent in router.route(event):
                    if intent.kind == "submit":
                        if _is_exit_command(intent.text):
                            exit_requested = True
                            break
                        runtime.render_now()
                        active_task = app.start_prompt(
                            intent.text,
                            duration_seconds=random.uniform(min_run_seconds, max_run_seconds),
                        )
                    elif intent.kind == "follow_up":
                        if _is_exit_command(intent.text):
                            if active_task is not None and not active_task.done():
                                active_task.cancel()
                            exit_requested = True
                            break
                        stripped = intent.text.strip()
                        if stripped.startswith("/steer "):
                            app.queue_steer(stripped[len("/steer ") :])
                        else:
                            app.queue_followup(intent.text)
                    elif intent.kind == "abort":
                        app.abort(active_task)
                        active_task = None
                    elif intent.kind == "command" and intent.note == "edit_last_queued_prompt":
                        restored = app.pop_last_queued()
                        if restored is not None:
                            app.composer.set_text(restored)
                if exit_requested:
                    break
            runtime.render_now()
            if exit_requested:
                stdout.write("\n")
                stdout.flush()
                return 0


async def _drain_finished_task(
    active_task: asyncio.Task[int | None] | None,
    *,
    app: ComposerBottomFrameDemo,
    min_run_seconds: float,
    max_run_seconds: float,
) -> tuple[asyncio.Task[int | None] | None, bool]:
    if active_task is None or not active_task.done():
        return active_task, False
    with suppress(asyncio.CancelledError):
        await active_task
    next_task = app.start_next_followup(duration_seconds=random.uniform(min_run_seconds, max_run_seconds))
    return next_task, True


def _idle_exit_requested(event: InputEvent, app: ComposerBottomFrameDemo) -> bool:
    return event.kind == "key" and event.key == "ctrl_c" and not app.running


def _is_exit_command(text: str) -> bool:
    return text.strip() in EXIT_COMMANDS


async def print_scripted(*, stdout: TextIO, width: int, height: int) -> None:
    app = ComposerBottomFrameDemo.seeded()
    task = app.start_prompt("请用 Markdown 展示底部 frame 的交互状态。", duration_seconds=0)
    app.queue_followup("顺便解释一下 pending queue。")
    app.queue_steer("请把回答重点转向 steer 队列。")
    while task is not None:
        await task
        task = app.start_next_followup(duration_seconds=0)
    result = app.render(_rc(width, height))
    for line in result.lines:
        stdout.write(line.text + "\n")


def print_snapshot(*, stdout: TextIO, width: int, height: int) -> None:
    app = ComposerBottomFrameDemo.seeded()
    app.state = "running"
    app.started_at = time.monotonic() - 273.0
    app.planned_duration_seconds = 300.0
    app.interruption_message = (
        "Conversation interrupted - tell the model what to do differently. "
        "Something went wrong? Hit `/feedback` to report the issue."
    )
    app.queue_steer("继续")
    app.queue_followup("继续")
    app.composer.set_text("Summarize recent commits")
    result = app.render(_rc(width, height))
    for line in result.lines:
        stdout.write(line.text + "\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive composer and bottom-frame showcase for loushang.tui.")
    parser.add_argument("--snapshot", action="store_true", help="print one static render instead of entering raw mode")
    parser.add_argument("--scripted", action="store_true", help="print a completed fake streaming turn")
    parser.add_argument("--min-run-seconds", type=float, default=DEFAULT_MIN_RUN_SECONDS, help="minimum fake run duration")
    parser.add_argument("--max-run-seconds", type=float, default=DEFAULT_MAX_RUN_SECONDS, help="maximum fake run duration")
    parser.add_argument("--width", type=int, default=100, help="snapshot width")
    parser.add_argument("--height", type=int, default=28, help="snapshot height")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.snapshot:
        print_snapshot(stdout=sys.stdout, width=args.width, height=args.height)
        return 0
    if args.scripted:
        asyncio.run(print_scripted(stdout=sys.stdout, width=args.width, height=args.height))
        return 0
    min_seconds = max(0.0, min(args.min_run_seconds, args.max_run_seconds))
    max_seconds = max(0.0, max(args.min_run_seconds, args.max_run_seconds))
    return asyncio.run(
        run_interactive(
            stdin=sys.stdin,
            stdout=sys.stdout,
            min_run_seconds=min_seconds,
            max_run_seconds=max_seconds,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

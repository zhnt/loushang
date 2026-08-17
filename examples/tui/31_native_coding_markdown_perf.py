from __future__ import annotations

import argparse
import asyncio
import gc
import sys
import tracemalloc
from collections import Counter
from dataclasses import dataclass, field
from io import StringIO
from time import perf_counter
from typing import Any, TextIO, cast

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import (
    CODING_CANCELLATION_MESSAGE,
    CODING_INTERRUPTION_MESSAGE,
    build_screen_input_router,
)
from loushang.harnesstui.conversation.screen_runner import (
    ConversationInputRouterFactoryPort,
    run_conversation_screen,
)
from loushang.tui import (
    PlaybackStep,
    ProcessTerminalPort,
    RenderConstraints,
    RenderLoop,
    RenderResult,
    TerminalSize,
    ToolExecutionRecord,
    TuiRuntime,
    strip_control_sequences,
)

DEFAULT_STREAM_SECONDS = 1.2
MARKDOWN_LINES_PER_BLOCK = 20


@dataclass(slots=True)
class RenderStats:
    calls: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_line_count: int = 0
    max_line_count: int = 0
    previous_render_result_lines: int = 0
    last_active_records: int = 0
    max_active_records: int = 0

    def reset(self) -> None:
        self.calls = 0
        self.total_ms = 0.0
        self.max_ms = 0.0
        self.last_line_count = 0
        self.max_line_count = 0
        self.previous_render_result_lines = 0
        self.last_active_records = 0
        self.max_active_records = 0

    def record(
        self,
        *,
        elapsed_ms: float,
        line_count: int,
        previous_line_count: int,
        active_records: int,
    ) -> None:
        self.calls += 1
        self.total_ms += elapsed_ms
        self.max_ms = max(self.max_ms, elapsed_ms)
        self.last_line_count = line_count
        self.max_line_count = max(self.max_line_count, line_count)
        self.previous_render_result_lines = previous_line_count
        self.last_active_records = active_records
        self.max_active_records = max(self.max_active_records, active_records)

    @property
    def average_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0


@dataclass(frozen=True, slots=True)
class PerfReport:
    requested_lines: int
    stream_elapsed_seconds: float
    render_calls: int
    render_total_ms: float
    render_avg_ms: float
    render_max_ms: float
    last_line_count: int
    max_line_count: int
    previous_render_result_lines: int
    state_records_before_stats: int
    active_records: int
    max_active_records: int
    state_record_chars: int
    assistant_draft_chars: int
    active_text_chars: int
    stable_cache_entries: int
    stable_cache_lines: int
    stable_cache_chars: int
    transient_cache_lines: int
    transient_cache_chars: int
    markdown_cache_entries: int
    markdown_cache_lines: int
    markdown_cache_chars: int
    evicted_prefix_records: int
    transcript_window_generation: int
    rss_max_kib: int
    tracemalloc_current_kib: int | None
    tracemalloc_peak_kib: int | None
    gc_objects: int
    gc_count_0: int
    gc_count_1: int
    gc_count_2: int


@dataclass(slots=True)
class ScriptRoundSummary:
    """Aggregate diagnostics without retaining every playback frame."""

    frame_count: int = 0
    operation_count: int = 0
    serialized_bytes: int = 0
    clear_scrollback_frames: int = 0
    operation_classes: Counter[str] = field(default_factory=Counter)
    last_step: PlaybackStep | None = None

    def record(self, step: PlaybackStep) -> None:
        self.frame_count += 1
        self.operation_count += len(step.diagnostics.operations)
        operation_class = str(step.diagnostics.operation_class or "unknown")
        self.operation_classes[operation_class] += 1
        if step.frame is not None:
            self.serialized_bytes += len(step.frame.serialized_output)
            if step.frame.clear_scrollback_emitted:
                self.clear_scrollback_frames += 1
        self.last_step = step


class PerfScreenCodingTuiApp(ScreenCodingTuiApp):
    __slots__ = ("_last_render_line_count", "perf_reports", "render_stats")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.perf_reports: list[PerfReport] = []
        self.render_stats = RenderStats()
        self._last_render_line_count = 0

    def render(self, constraints: RenderConstraints) -> RenderResult:
        started = perf_counter()
        result = super().render(constraints)
        # Stop the timer before collecting even the O(1) harness counters below.
        elapsed_ms = (perf_counter() - started) * 1000
        line_count = len(result.lines)
        self.render_stats.record(
            elapsed_ms=elapsed_ms,
            line_count=line_count,
            previous_line_count=self._last_render_line_count,
            active_records=len(self.state.records)
            + (1 if self.state.assistant_draft_buffer is not None else 0),
        )
        self._last_render_line_count = line_count
        return result


async def _fake_markdown_handler(
    app: PerfScreenCodingTuiApp, text: str, *, stream_seconds: float
) -> int | None:
    count = _parse_count(text)
    app.render_stats.reset()
    started = perf_counter()
    app.begin_assistant()
    if count is None:
        app.append_assistant_chunk(
            "Enter a positive integer, for example `1`, `10`, or `100`.\n"
        )
        app.end_assistant()
        _append_perf_stats(
            app, requested_lines=0, stream_elapsed_seconds=perf_counter() - started
        )
        return None

    delay = stream_seconds / max(1, count)
    for index in range(1, count + 1):
        app.append_assistant_chunk(_markdown_line(index))
        await asyncio.sleep(delay)
    app.end_assistant()
    _append_perf_stats(
        app, requested_lines=count, stream_elapsed_seconds=perf_counter() - started
    )
    return None


def _parse_count(text: str) -> int | None:
    try:
        value = int(text.strip())
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _markdown_line(index: int) -> str:
    block_prefix = ""
    if (index - 1) % MARKDOWN_LINES_PER_BLOCK == 0:
        block_number = (index - 1) // MARKDOWN_LINES_PER_BLOCK + 1
        block_prefix = (
            "" if index == 1 else "\n"
        ) + f"### Markdown block {block_number}\n\n"
    return (
        block_prefix + f"- **Line {index}**: markdown `code-{index}` with 中文宽字符 "
        f"and [link {index}](https://example.com/{index}).\n"
    )


def _append_perf_stats(
    app: PerfScreenCodingTuiApp, *, requested_lines: int, stream_elapsed_seconds: float
) -> None:
    stats = app.render_stats
    active_stats = _active_state_stats(app)
    cache_stats = _transcript_cache_stats(app)
    memory_stats = _memory_stats()
    gc_counts = gc.get_count()
    report = PerfReport(
        requested_lines=requested_lines,
        stream_elapsed_seconds=stream_elapsed_seconds,
        render_calls=stats.calls,
        render_total_ms=stats.total_ms,
        render_avg_ms=stats.average_ms,
        render_max_ms=stats.max_ms,
        last_line_count=stats.last_line_count,
        max_line_count=stats.max_line_count,
        previous_render_result_lines=stats.previous_render_result_lines,
        state_records_before_stats=len(app.state.records),
        active_records=stats.last_active_records,
        max_active_records=stats.max_active_records,
        state_record_chars=active_stats["state_record_chars"],
        assistant_draft_chars=active_stats["assistant_draft_chars"],
        active_text_chars=active_stats["active_text_chars"],
        stable_cache_entries=cache_stats["stable_cache_entries"],
        stable_cache_lines=cache_stats["stable_cache_lines"],
        stable_cache_chars=cache_stats["stable_cache_chars"],
        transient_cache_lines=cache_stats["transient_cache_lines"],
        transient_cache_chars=cache_stats["transient_cache_chars"],
        markdown_cache_entries=cache_stats["markdown_cache_entries"],
        markdown_cache_lines=cache_stats["markdown_cache_lines"],
        markdown_cache_chars=cache_stats["markdown_cache_chars"],
        evicted_prefix_records=app.state.evicted_prefix_record_count,
        transcript_window_generation=app.state.transcript_window_generation,
        rss_max_kib=int(memory_stats["rss_max_kib"] or 0),
        tracemalloc_current_kib=memory_stats["tracemalloc_current_kib"],
        tracemalloc_peak_kib=memory_stats["tracemalloc_peak_kib"],
        gc_objects=len(gc.get_objects()),
        gc_count_0=gc_counts[0],
        gc_count_1=gc_counts[1],
        gc_count_2=gc_counts[2],
    )
    app.perf_reports.append(report)
    app.state.records.append(
        ToolExecutionRecord(
            name="render_stats",
            state="completed",
            elapsed_seconds=stream_elapsed_seconds,
            output=(
                f"requested_lines={report.requested_lines}\n"
                f"stream_elapsed={report.stream_elapsed_seconds:.3f}s\n"
                f"render_calls={report.render_calls}\n"
                f"render_total_ms={report.render_total_ms:.2f}\n"
                f"render_avg_ms={report.render_avg_ms:.2f}\n"
                f"render_max_ms={report.render_max_ms:.2f}\n"
                f"last_line_count={report.last_line_count}\n"
                f"max_line_count={report.max_line_count}\n"
                f"previous_render_result_lines={report.previous_render_result_lines}\n"
                f"state_records_before_stats={report.state_records_before_stats}\n"
                f"active_records={report.active_records}\n"
                f"max_active_records={report.max_active_records}\n"
                f"state_record_chars={report.state_record_chars}\n"
                f"assistant_draft_chars={report.assistant_draft_chars}\n"
                f"active_text_chars={report.active_text_chars}\n"
                f"stable_cache_entries={report.stable_cache_entries}\n"
                f"stable_cache_lines={report.stable_cache_lines}\n"
                f"stable_cache_chars={report.stable_cache_chars}\n"
                f"transient_cache_lines={report.transient_cache_lines}\n"
                f"transient_cache_chars={report.transient_cache_chars}\n"
                f"markdown_cache_entries={report.markdown_cache_entries}\n"
                f"markdown_cache_lines={report.markdown_cache_lines}\n"
                f"markdown_cache_chars={report.markdown_cache_chars}\n"
                f"evicted_prefix_records={report.evicted_prefix_records}\n"
                f"transcript_window_generation={report.transcript_window_generation}\n"
                f"rss_max_kib={report.rss_max_kib}\n"
                f"tracemalloc_current_kib={_format_optional_int(report.tracemalloc_current_kib)}\n"
                f"tracemalloc_peak_kib={_format_optional_int(report.tracemalloc_peak_kib)}\n"
                f"gc_objects={report.gc_objects}\n"
                f"gc_count={report.gc_count_0},{report.gc_count_1},{report.gc_count_2}"
            ),
        )
    )


async def run_interactive(
    *, stdin: TextIO, stdout: TextIO, stream_seconds: float
) -> int:
    app = PerfScreenCodingTuiApp(
        model_label="fake-model",
        cwd="/repo",
        branch="markdown-perf",
        session_label="manual",
    )
    app.set_status("type 1, 10, 100... /quit exits")
    return await run_conversation_screen(
        app=app,
        stdin=stdin,
        stdout=stdout,
        handle_prompt=lambda prompt: _fake_markdown_handler(
            app, prompt, stream_seconds=stream_seconds
        ),
        on_abort=lambda: None,
        should_exit=lambda text: text.strip() in {"/quit", "/exit", "q"},
        input_router_factory=cast(
            ConversationInputRouterFactoryPort,
            build_screen_input_router,
        ),
        interruption_message=CODING_INTERRUPTION_MESSAGE,
        cancellation_message=CODING_CANCELLATION_MESSAGE,
    )


async def run_script(
    *,
    stdout: TextIO,
    count: int,
    rounds: int,
    width: int,
    height: int,
    stream_seconds: float,
    render_interval_ms: int,
    trace_memory: bool,
    show_final: bool,
    render_every_n_chunks: int = 0,
) -> int:
    if trace_memory and not tracemalloc.is_tracing():
        tracemalloc.start()
    app = PerfScreenCodingTuiApp(
        model_label="fake-model",
        cwd="/repo",
        branch="markdown-perf",
        session_label="script",
    )
    app.set_status("scripted fake render")
    terminal = ProcessTerminalPort(
        output=StringIO(),
        size_provider=lambda: TerminalSize(columns=width, rows=height),
        frame_history_limit=1,
        track_screen=False,
    )
    runtime = TuiRuntime(render_loop=RenderLoop(app), terminal=terminal)
    stdout.write("Native coding markdown perf script\n")
    stdout.write(f"requested_markdown_lines={count}\n")
    stdout.write(f"rounds={rounds}\n")
    stdout.write(f"stream_seconds={stream_seconds:.3f}\n")
    stdout.write(f"markdown_lines_per_block={MARKDOWN_LINES_PER_BLOCK}\n")
    stdout.write(f"render_every_n_chunks={max(0, render_every_n_chunks)}\n\n")

    for round_index in range(1, rounds + 1):
        summary = await _drive_script_round(
            app=app,
            runtime=runtime,
            count=count,
            stream_seconds=stream_seconds,
            render_interval_ms=render_interval_ms,
            render_every_n_chunks=render_every_n_chunks,
        )
        stdout.write(_script_round_line(round_index, app=app, summary=summary))

    if show_final:
        final = app.render(
            RenderConstraints(width=width, max_height=height, visible_height=height)
        )
        rendered = "\n".join(strip_control_sequences(line.text) for line in final.lines)
        stdout.write("\n")
        stdout.write(f"rendered_line_count={len(final.lines)}\n")
        stdout.write(f"contains_first_line={'Line 1' in rendered}\n")
        stdout.write(f"contains_last_line={f'Line {count}' in rendered}\n\n")
        for line in final.lines:
            stdout.write(strip_control_sequences(line.text) + "\n")
    return 0


async def _drive_script_round(
    *,
    app: PerfScreenCodingTuiApp,
    runtime: TuiRuntime,
    count: int,
    stream_seconds: float,
    render_interval_ms: int,
    render_every_n_chunks: int = 0,
) -> ScriptRoundSummary:
    summary = ScriptRoundSummary()
    app.start_prompt(str(count), started_at=app.now())
    summary.record(runtime.render_now())
    # Setup/finalize frames belong to the terminal summary, not streaming timings.
    app.render_stats.reset()

    started = perf_counter()
    app.begin_assistant()
    delay = stream_seconds / max(1, count)
    render_interval = max(0, render_interval_ms) / 1000
    render_every_n_chunks = max(0, render_every_n_chunks)
    next_render_at = perf_counter()
    for index in range(1, count + 1):
        app.append_assistant_chunk(_markdown_line(index))
        now = perf_counter()
        if render_every_n_chunks:
            should_render = index % render_every_n_chunks == 0 or index == count
        else:
            should_render = (
                render_interval <= 0 or now >= next_render_at or index == count
            )
        if should_render:
            summary.record(runtime.render_now())
            next_render_at = perf_counter() + render_interval
        if delay > 0:
            await asyncio.sleep(delay)

    stream_elapsed = perf_counter() - started
    app.end_assistant()
    _append_perf_stats(
        app, requested_lines=count, stream_elapsed_seconds=stream_elapsed
    )
    app.complete_run(elapsed_seconds=stream_elapsed)
    summary.record(runtime.render_now())
    return summary


def _script_round_line(
    round_index: int,
    *,
    app: PerfScreenCodingTuiApp,
    summary: ScriptRoundSummary,
) -> str:
    report = app.perf_reports[-1] if app.perf_reports else None
    active_stats = _active_state_stats(app)
    cache_stats = _transcript_cache_stats(app)
    memory_stats = _memory_stats()
    stream_elapsed = report.stream_elapsed_seconds if report is not None else 0.0
    operation_classes = _format_operation_classes(summary.operation_classes)
    last_step = summary.last_step
    previous_lines = (
        last_step.diagnostics.previous_rendered_lines if last_step is not None else ()
    )
    new_lines = (
        last_step.diagnostics.current_logical_lines if last_step is not None else ()
    )
    # These full-frame diagnostics run once, after the streaming report is frozen.
    previous_line_chars = sum(len(line) for line in previous_lines)
    new_line_chars = sum(len(line) for line in new_lines)
    previous_render_loop_lines = len(previous_lines)
    new_lines_count = len(new_lines)
    viewport_top = last_step.diagnostics.viewport_top if last_step is not None else 0
    changed_range = _format_range(
        last_step.diagnostics.changed_line_range if last_step is not None else None
    )
    append_start = last_step.diagnostics.append_start if last_step is not None else None
    render_end = last_step.diagnostics.render_end if last_step is not None else None
    return (
        f"round={round_index} "
        f"requested_lines={report.requested_lines if report is not None else 0} "
        f"stream_elapsed={stream_elapsed:.3f}s "
        f"render_calls={report.render_calls if report is not None else 0} "
        f"render_total_ms={report.render_total_ms if report is not None else 0.0:.2f} "
        f"render_avg_ms={report.render_avg_ms if report is not None else 0.0:.2f} "
        f"render_max_ms={report.render_max_ms if report is not None else 0.0:.2f} "
        f"frames={summary.frame_count} "
        f"operations={summary.operation_count} "
        f"serialized_bytes={summary.serialized_bytes} "
        f"clear_scrollback_frames={summary.clear_scrollback_frames} "
        f"operation_classes={operation_classes} "
        f"max_line_count={report.max_line_count if report is not None else 0} "
        f"previous_render_loop_lines={previous_render_loop_lines} "
        f"previous_render_loop_chars={previous_line_chars} "
        f"new_lines={new_lines_count} "
        f"new_line_chars={new_line_chars} "
        f"changed_range={changed_range} "
        f"append_start={_format_optional_int(append_start)} "
        f"appended_lines={last_step.diagnostics.appended_lines if last_step is not None else 0} "
        f"render_end={_format_optional_int(render_end)} "
        f"viewport_top={viewport_top} "
        f"active_records={len(app.state.records) + (1 if app.state.assistant_draft is not None else 0)} "
        f"state_record_chars={active_stats['state_record_chars']} "
        f"assistant_draft_chars={active_stats['assistant_draft_chars']} "
        f"active_text_chars={active_stats['active_text_chars']} "
        f"stable_cache_entries={cache_stats['stable_cache_entries']} "
        f"stable_cache_lines={cache_stats['stable_cache_lines']} "
        f"stable_cache_chars={cache_stats['stable_cache_chars']} "
        f"transient_cache_lines={cache_stats['transient_cache_lines']} "
        f"transient_cache_chars={cache_stats['transient_cache_chars']} "
        f"markdown_cache_entries={cache_stats['markdown_cache_entries']} "
        f"markdown_cache_lines={cache_stats['markdown_cache_lines']} "
        f"markdown_cache_chars={cache_stats['markdown_cache_chars']} "
        f"evicted_prefix_records={app.state.evicted_prefix_record_count} "
        f"transcript_window_generation={app.state.transcript_window_generation} "
        f"rss_max_kib={memory_stats['rss_max_kib']} "
        f"tracemalloc_current_kib={_format_optional_int(memory_stats['tracemalloc_current_kib'])} "
        f"tracemalloc_peak_kib={_format_optional_int(memory_stats['tracemalloc_peak_kib'])} "
        f"gc_objects={len(gc.get_objects())} "
        f"gc_count={','.join(str(value) for value in gc.get_count())}\n"
    )


def _format_operation_classes(counter: Counter[str]) -> str:
    return (
        ",".join(f"{name}:{count}" for name, count in sorted(counter.items())) or "none"
    )


def _active_state_stats(app: PerfScreenCodingTuiApp) -> dict[str, int]:
    state_record_chars = sum(_record_text_chars(record) for record in app.state.records)
    assistant_draft_chars = (
        len(app.state.assistant_draft.text)
        if app.state.assistant_draft is not None
        else 0
    )
    return {
        "state_record_chars": state_record_chars,
        "assistant_draft_chars": assistant_draft_chars,
        "active_text_chars": state_record_chars + assistant_draft_chars,
    }


def _record_text_chars(record: object) -> int:
    total = 0
    for attribute in ("text", "output", "summary", "diagnostics", "command", "stderr"):
        value = getattr(record, attribute, None)
        if isinstance(value, str):
            total += len(value)
    return total


def _transcript_cache_stats(app: PerfScreenCodingTuiApp) -> dict[str, int]:
    stable_cache = getattr(app._transcript_region, "_stable_line_cache", {})
    stable_lines = 0
    stable_chars = 0
    for lines in stable_cache.values():
        stable_lines += len(lines)
        stable_chars += sum(len(line) for line in lines)

    transient_lines_value = getattr(
        app._transcript_region, "_transient_line_cache_lines", None
    )
    transient_lines = (
        len(transient_lines_value) if transient_lines_value is not None else 0
    )
    transient_chars = (
        sum(len(line) for line in transient_lines_value)
        if transient_lines_value is not None
        else 0
    )
    markdown_cache = getattr(app._transcript_region, "_markdown_render_cache", None)
    return {
        "stable_cache_entries": len(stable_cache),
        "stable_cache_lines": stable_lines,
        "stable_cache_chars": stable_chars,
        "transient_cache_lines": transient_lines,
        "transient_cache_chars": transient_chars,
        "markdown_cache_entries": getattr(markdown_cache, "stable_entry_count", 0),
        "markdown_cache_lines": getattr(markdown_cache, "stable_line_count", 0),
        "markdown_cache_chars": getattr(markdown_cache, "stable_char_count", 0),
    }


def _memory_stats() -> dict[str, int | None]:
    current_kib: int | None = None
    peak_kib: int | None = None
    if tracemalloc.is_tracing():
        current, peak = tracemalloc.get_traced_memory()
        current_kib = current // 1024
        peak_kib = peak // 1024
    return {
        "rss_max_kib": _rss_max_kib(),
        "tracemalloc_current_kib": current_kib,
        "tracemalloc_peak_kib": peak_kib,
    }


def _rss_max_kib() -> int:
    try:
        import resource
    except ImportError:
        return 0
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return value // 1024
    return value


def _format_optional_int(value: int | None) -> str:
    return "disabled" if value is None else str(value)


def _format_range(value: tuple[int, int] | None) -> str:
    if value is None:
        return "none"
    return f"{value[0]}:{value[1]}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual fake-model Markdown streaming performance harness."
    )
    parser.add_argument(
        "--script-count",
        type=int,
        help="run one non-interactive fake prompt with this line count",
    )
    parser.add_argument(
        "--script-rounds",
        type=int,
        default=1,
        help="number of scripted fake prompts to run",
    )
    parser.add_argument(
        "--show-final",
        action="store_true",
        help="print the final rendered snapshot after script stats",
    )
    parser.add_argument(
        "--stream-seconds",
        type=float,
        default=DEFAULT_STREAM_SECONDS,
        help="target fake stream duration",
    )
    parser.add_argument(
        "--script-render-interval-ms",
        type=int,
        default=80,
        help="script render coalescing interval; use 0 to render every chunk",
    )
    parser.add_argument(
        "--script-render-every-n-chunks",
        type=int,
        default=0,
        help="use a fixed chunk cadence instead of wall-clock render coalescing",
    )
    parser.add_argument(
        "--trace-memory",
        action="store_true",
        help="enable tracemalloc current/peak memory stats",
    )
    parser.add_argument("--width", type=int, default=100, help="script snapshot width")
    parser.add_argument("--height", type=int, default=32, help="script snapshot height")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    stream_seconds = max(0.0, args.stream_seconds)
    if args.script_count is not None:
        return asyncio.run(
            run_script(
                stdout=sys.stdout,
                count=max(1, args.script_count),
                rounds=max(1, args.script_rounds),
                width=args.width,
                height=args.height,
                stream_seconds=stream_seconds,
                render_interval_ms=args.script_render_interval_ms,
                trace_memory=args.trace_memory,
                show_final=args.show_final,
                render_every_n_chunks=args.script_render_every_n_chunks,
            )
        )
    return asyncio.run(
        run_interactive(
            stdin=sys.stdin, stdout=sys.stdout, stream_seconds=stream_seconds
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

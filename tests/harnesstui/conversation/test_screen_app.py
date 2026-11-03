from __future__ import annotations

import asyncio
import threading
import time
from contextlib import nullcontext
from io import StringIO

import pytest

from loushang.harnesstui.conversation.loading_input import LOADING_MESSAGE
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_frame import (
    ScreenFrameCopy,
    ScreenFramePresentation,
)
from loushang.tui import RenderBaselineReset, RenderConstraints, strip_control_sequences
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)
from loushang.tui.ui_parts.transcript import TranscriptRegion


class _TestScreenConversationApp(ScreenConversationApp):
    def _create_frame_presentation(self) -> ScreenFramePresentation:
        return ScreenFramePresentation(
            ScreenFrameCopy(
                working_label="Running",
                steer_label="Steers",
                steer_hint="interrupt",
                followup_label="Follow-ups",
                followup_hint="edit",
            )
        )


def _app() -> _TestScreenConversationApp:
    return _TestScreenConversationApp(
        model_label="model",
        cwd="/workspace",
        branch="main",
        session_label="session",
        now=lambda: 2.0,
    )


def test_loading_status_animates_on_timer_and_stops_after_loading() -> None:
    clock = [1.0]
    app = _TestScreenConversationApp(
        model_label="model",
        cwd="/workspace",
        branch="main",
        session_label="session",
        now=lambda: clock[0],
    )
    app.state.startup_pending = True
    app.state.status_message = LOADING_MESSAGE

    def status(width: int = 80) -> str:
        status_bar = app._bottom_frame().status_bar
        assert status_bar is not None
        result = status_bar.render(RenderConstraints(width=width, max_height=1))
        return strip_control_sequences(result.lines[0].text)

    first = status()
    assert first[2:] == LOADING_MESSAGE
    assert first[0] in "|/-\\"
    assert app.next_frame_due_ms(after_ms=1000) == 1200

    clock[0] = 1.2
    second = status()
    assert second[2:] == LOADING_MESSAGE
    assert second[0] != first[0]
    assert status(width=12).startswith(second[:2])
    assert len(status(width=12)) <= 11

    app.startup_phase_provider = lambda: "starting runtime"
    assert status()[2:] == "Starting runtime · type now; Enter disabled"
    assert app.next_frame_due_ms(after_ms=1200) == 1400

    app.state.status_message = "Closing — waiting for preparation cleanup"
    assert status() == app.state.status_message
    assert app.next_frame_due_ms(after_ms=1200) is None

    app.state.startup_pending = False
    assert app.next_frame_due_ms(after_ms=1200) is None


def test_input_frame_does_not_flatten_long_screen_history(monkeypatch) -> None:
    from loushang.tui.core import RenderLine

    app = _app()
    app.state.records = [UserPromptRecord(f"history {i}") for i in range(2000)]
    app.state.mark_records_changed()
    constraints = RenderConstraints(width=80, max_height=1_000_000, visible_height=24)
    app.render(constraints)
    reads = 0
    original_getattribute = RenderLine.__getattribute__

    def count_text_reads(line, name):
        nonlocal reads
        if name == "text":
            reads += 1
        return original_getattribute(line, name)

    monkeypatch.setattr(RenderLine, "__getattribute__", count_text_reads)
    app.composer.set_text("draft")
    app.render(constraints)
    assert reads <= 40
    # Selection and detail hit testing still have access to every logical row.
    assert "history 0" in strip_control_sequences(app._screen_rows[0])
    assert any("draft" in row for row in app._screen_rows[-24:])
    assert len(app._screen_rows) > 4000


@pytest.mark.parametrize("interrupt", [False, True])
def test_long_history_keeps_running_and_stopping_input_live(
    monkeypatch, interrupt: bool
) -> None:
    from loushang.harnesstui.conversation.screen_runner import run_conversation_screen
    from loushang.tui import TerminalSize
    from loushang.tui.runtime import TuiRuntime

    async def scenario() -> None:
        clock = [10.0]
        app = _TestScreenConversationApp(
            model_label="offline",
            cwd="/workspace",
            branch=None,
            session_label="long-history",
            now=lambda: clock[0],
        )
        history = [UserPromptRecord(f"history {i}") for i in range(2000)]
        app.state.records = list(history)
        app.state.mark_records_changed()
        started, advance, updated, finish, cancelled, cleanup = (
            asyncio.Event() for _ in range(6)
        )
        first_frame, second_frame, stopping, edited, third_frame, settled = (
            asyncio.Event() for _ in range(6)
        )
        worker = None
        materialized: list[int] = []
        render_now = TuiRuntime.render_now

        def measure_render(runtime):
            step = render_now(runtime)
            if step.diagnostics.previous_rendered_lines:
                materialized.append(step.diagnostics.materialized_logical_line_count)
            return step

        monkeypatch.setattr(TuiRuntime, "render_now", measure_render)

        class Output(StringIO):
            def write(self, text):
                return len(text)

            def flush(self):
                visible = strip_control_sequences("\n".join(app._screen_rows[-24:]))
                if "draft" in visible and "Running 1.00s" in visible:
                    first_frame.set()
                if "Running 2.00s" in visible:
                    second_frame.set()
                if "Stopping…" in visible:
                    stopping.set()
                if "draft after Esc" in visible:
                    edited.set()
                if "Stopping… 3.00s" in visible:
                    third_frame.set()
                if "Worked for" in visible:
                    settled.set()

        def tool(state, output):
            app.state.upsert_tool_record(
                "live",
                ToolExecutionRecord(
                    name="bash",
                    state=state,
                    elapsed_seconds=app.elapsed_seconds(),
                    output=output,
                    expanded_output=output,
                ),
            )
            app.request_render("product")

        async def prompt(_text):
            nonlocal worker
            worker = asyncio.current_task()
            try:
                tool("running", "first")
                started.set()
                await advance.wait()
                tool("running", "update")
                updated.set()
                await finish.wait()
                tool("completed", "done")
            except asyncio.CancelledError:
                cancelled.set()
                await cleanup.wait()
                tool("error", "cancelled")
                raise

        async def abort():
            assert worker is not None
            worker.cancel()

        queue = asyncio.Queue()

        async def read(_stdin):
            return await queue.get()

        async def drive():
            queue.put_nowait("run\r")
            await started.wait()
            clock[0] = 11.0
            queue.put_nowait("draft")
            await first_frame.wait()
            advance.set()
            await updated.wait()
            clock[0] = 12.0
            app.request_render("product")
            await second_frame.wait()
            if interrupt:
                queue.put_nowait("\x1b")
                await stopping.wait()
                await cancelled.wait()
                queue.put_nowait(" after Esc")
                await edited.wait()
                assert not cleanup.is_set()
                clock[0] = 13.0
                app.request_render("product")
                await third_frame.wait()
                cleanup.set()
            else:
                finish.set()
            await settled.wait()
            assert app.composer.value == ("draft after Esc" if interrupt else "draft")
            queue.put_nowait("\x15/quit\r")

        driver = asyncio.create_task(drive())
        try:
            async with asyncio.timeout(10):
                assert (
                    await run_conversation_screen(
                        app=app,
                        stdin=StringIO(),
                        stdout=Output(),
                        handle_prompt=prompt,
                        on_abort=abort,
                        should_exit=lambda text: text == "/quit",
                        terminal_mode_factory=lambda *_: nullcontext(),
                        terminal_size_provider=lambda: TerminalSize(
                            columns=80, rows=24
                        ),
                        input_chunk_reader=read,
                        interruption_message="Interrupted",
                        cancellation_message="Cancelled",
                    )
                    == 0
                )
                await driver
            assert materialized and max(materialized) <= 40
            assert all(
                current is original
                for current, original in zip(
                    app.state.records[: len(history)], history, strict=True
                )
            )
            assert (
                sum(isinstance(r, WorkedDividerRecord) for r in app.state.records) == 1
            )
            assert not app.state.running
            assert not [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()
            ]
        finally:
            cleanup.set()
            finish.set()
            driver.cancel()
            await asyncio.gather(driver, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.tui_render_contract
@pytest.mark.parametrize("statusline_visible", [False, True])
@pytest.mark.parametrize("width", [30, 80])
def test_stopping_acknowledgement_survives_crowded_or_hidden_statusline(
    statusline_visible: bool, width: int
) -> None:
    app = _app()
    app.state.model_label = "long-model-name-" * 20
    app.state.cwd = "/workspace/" + "long-project-name-" * 20
    app.state.statusline_visible = statusline_visible
    constraints = RenderConstraints(width=width, max_height=24, visible_height=24)

    def visible() -> str:
        return strip_control_sequences(
            "\n".join(line.text for line in app.render(constraints).lines)
        )

    app.start_prompt("run", started_at=1.0)
    app.begin_stopping()
    assert "Stopping…" in visible()
    assert "1.00s" in visible()
    app.complete_run()
    assert "Stopping…" not in visible()
    app.start_prompt("next", started_at=1.0)
    assert "Running" in visible() and "Stopping…" not in visible()

    app.begin_stopping()
    app.state.abort(message="Interrupted", elapsed_seconds=1.0)
    app.begin_run(started_at=1.0)
    assert "Running" in visible() and "Stopping…" not in visible()


@pytest.mark.tui_render_contract
def test_screen_conversation_app_coordinates_neutral_streaming_state() -> None:
    app = _app()
    app.start_prompt("hello", started_at=1.0)
    app.begin_assistant()
    app.append_assistant_chunk("world")

    result = app.render(RenderConstraints(width=60, max_height=24, visible_height=24))

    assert type(app._transcript_region) is TranscriptRegion
    assert app._transcript_region.records is app.state.records
    assert tuple(line.text for line in result.lines)[:3] == (
        "> hello",
        "",
        "* world",
    )


@pytest.mark.tui_render_contract
def test_screen_conversation_app_keeps_presentation_and_region_instances() -> None:
    app = _app()
    presentation = app._transcript_presentation
    region = app._transcript_region
    app.add_status("ready")

    app.render(RenderConstraints(width=60, max_height=24, visible_height=24))
    app.render(RenderConstraints(width=60, max_height=24, visible_height=24))

    assert app._transcript_presentation is presentation
    assert app._transcript_region is region


@pytest.mark.tui_render_contract
@pytest.mark.parametrize("start_method", ("prompt", "begin_run"))
def test_active_frames_defer_context_usage_rebuild_until_run_completes(
    start_method: str,
) -> None:
    app = _app()
    calls: list[int] = []

    def context_usage() -> int:
        calls.append(app.state.records_revision)
        return len(calls)

    app.context_usage_provider = context_usage
    constraints = RenderConstraints(width=60, max_height=24, visible_height=24)
    app.render(constraints)
    assert calls == [0]

    if start_method == "prompt":
        app.start_prompt("run", started_at=1.0)
    else:
        app.begin_run(started_at=1.0)
    app.render(constraints)
    app.state.upsert_tool_record(
        "tool-1", ToolExecutionRecord(name="bash", state="running", elapsed_seconds=0.0)
    )
    app.render(constraints)

    assert calls == [0]
    assert app.state.context_usage == 1

    app.complete_run(elapsed_seconds=1.0)
    app.render(constraints)

    assert calls == [0, app.state.records_revision]
    assert app.state.context_usage == 2


def test_context_usage_refreshes_after_run_without_display_changes() -> None:
    app = _app()
    app.state.records.append(WorkedDividerRecord(1.0))
    app.state.mark_records_changed()
    calls = 0

    def context_usage() -> int:
        nonlocal calls
        calls += 1
        return calls

    app.context_usage_provider = context_usage
    app.statusline_preview_snapshot()
    revision = app.state.records_revision

    app.begin_run(started_at=1.0)
    app.statusline_preview_snapshot()
    app.complete_run(elapsed_seconds=1.0)
    app.statusline_preview_snapshot()

    assert app.state.records_revision == revision
    assert calls == 2


def test_worked_frame_does_not_wait_for_context_usage_rebuild() -> None:
    async def scenario() -> None:
        app = _app()
        started = threading.Event()
        release = threading.Event()

        def slow_context_usage() -> int:
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("context usage worker did not finish")
            return 42

        app.context_usage_provider = slow_context_usage
        constraints = RenderConstraints(width=60, max_height=24, visible_height=24)
        app.begin_run(started_at=1.0)
        app.complete_run(elapsed_seconds=1.0)
        try:
            frame = app.render(constraints)
            assert any("Worked for" in line.text for line in frame.lines)
            assert app.state.context_usage is None
            assert await asyncio.to_thread(started.wait, 1)
        finally:
            release.set()
        task = app._context_usage_refresh_task
        assert task is not None
        await asyncio.wait_for(task, timeout=2)
        assert app.state.context_usage == 42

    asyncio.run(scenario())


def test_context_usage_from_previous_run_cannot_replace_newer_snapshot() -> None:
    async def scenario() -> None:
        app = _app()
        started = threading.Event()
        release = threading.Event()
        calls = 0

        def context_usage() -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("context usage worker did not finish")
            return calls

        app.context_usage_provider = context_usage
        constraints = RenderConstraints(width=60, max_height=24, visible_height=24)
        app.render(constraints)
        try:
            assert await asyncio.to_thread(started.wait, 1)
            app.start_prompt("new run", started_at=1.0)
            app.complete_run(elapsed_seconds=1.0)
        finally:
            release.set()
        first_task = app._context_usage_refresh_task
        assert first_task is not None
        await asyncio.wait_for(first_task, timeout=2)
        assert app.state.context_usage is None
        app.render(constraints)
        second_task = app._context_usage_refresh_task
        assert second_task is not None
        await asyncio.wait_for(second_task, timeout=2)
        assert app.state.context_usage == 2

    asyncio.run(scenario())


def test_cancel_context_refresh_keeps_exited_screen_unmodified() -> None:
    async def scenario() -> None:
        app = _app()
        started = threading.Event()
        release = threading.Event()

        def context_usage() -> int:
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("context usage worker did not finish")
            return 42

        app.context_usage_provider = context_usage
        app.render(RenderConstraints(width=60, max_height=24, visible_height=24))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task = app._context_usage_refresh_task
            assert task is not None
            app.cancel_context_usage_refresh()
            assert app._context_usage_refresh_task is None
        finally:
            release.set()
        await asyncio.gather(task, return_exceptions=True)
        assert app.state.context_usage is None

    asyncio.run(scenario())


def test_cancelled_context_refresh_does_not_delay_event_loop_shutdown() -> None:
    started = threading.Event()
    release = threading.Event()

    def slow_context_usage() -> int:
        started.set()
        release.wait(timeout=5)
        return 42

    async def scenario() -> None:
        app = _app()
        app.context_usage_provider = slow_context_usage
        app.render(RenderConstraints(width=60, max_height=24, visible_height=24))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        app.cancel_context_usage_refresh()

    start = time.perf_counter()
    try:
        asyncio.run(scenario())
        assert time.perf_counter() - start < 1.0
    finally:
        release.set()


def test_screen_conversation_app_reports_window_replacement_reason_once() -> None:
    app = _app()

    app.replace_transcript_window((), reason="test")

    assert app.consume_render_baseline_reset_reason() == (
        "transcript_window_replaced:test"
    )
    assert app.consume_render_baseline_reset_reason() is None


def test_screen_conversation_app_atomically_installs_bounded_resumed_history() -> None:
    app = _app()
    app.active_transcript_line_budget = 2

    app.install_resumed_history(
        (
            UserPromptRecord("old"),
            AssistantMessageRecord("new"),
        )
    )

    assert app.state.records == [AssistantMessageRecord("new")]
    assert app.state.evicted_prefix_record_count == 1
    assert app.consume_render_baseline_reset_reason() == RenderBaselineReset(
        reason="transcript_window_replaced:resume",
        replay_hidden_prefix=True,
    )
    assert app.consume_render_baseline_reset_reason() is None


def test_screen_conversation_app_owns_compaction_window_mechanics() -> None:
    app = _app()
    app.state.records.extend(
        [
            UserPromptRecord("old"),
            AssistantMessageRecord("middle"),
            UserPromptRecord("new"),
        ]
    )

    app.compact_transcript_window(summary=" condensed ", max_records=2)

    assert app.state.records == [
        AssistantMessageRecord("condensed"),
        UserPromptRecord("new"),
    ]
    assert app.state.evicted_prefix_record_count == 2
    assert app.consume_render_baseline_reset_reason() == (
        "transcript_window_replaced:compaction"
    )


def test_screen_conversation_app_appends_compaction_fact_without_trimming_records() -> (
    None
):
    app = _app()
    app.state.records.extend(UserPromptRecord(str(index)) for index in range(3))

    app.append_context_compaction_record(
        summary="condensed",
        tokens_before=42,
    )

    assert app.state.records == [
        UserPromptRecord("0"),
        UserPromptRecord("1"),
        UserPromptRecord("2"),
        ContextCompactionRecord(summary="condensed", tokens_before=42),
    ]
    assert app.state.evicted_prefix_record_count == 0
    assert app.consume_render_baseline_reset_reason() is None


def test_screen_conversation_app_applies_active_logical_line_budget() -> None:
    app = _app()
    app.active_transcript_line_budget = 2
    app.state.records.extend(
        [
            UserPromptRecord("old"),
            AssistantMessageRecord("new"),
        ]
    )

    app.trim_active_transcript_window()

    assert app.state.records == [AssistantMessageRecord("new")]
    assert app.state.evicted_prefix_record_count == 1
    assert app.consume_render_baseline_reset_reason() == (
        "transcript_window_trimmed:active_line_budget"
    )

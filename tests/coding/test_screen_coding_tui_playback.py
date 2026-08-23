from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loushang.ai.model import ModelSelection
from loushang.coding.ui.completion import coding_inline_completion_provider
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import build_screen_input_router
from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
from loushang.harnesstui.conversation.input import (
    ConversationAbortResult,
    ConversationLocalResult,
    ConversationSurfaceResult,
)
from loushang.harnesstui.status.provider import StatusProvider
from loushang.tui import (
    FakeTerminalPort,
    ImageBlock,
    InputReader,
    PlaybackEvent,
    PlaybackHarness,
    PlaybackStep,
    Renderable,
    RenderConstraints,
    RenderDiagnostics,
    RenderLoop,
    SearchableList,
    SearchableListItem,
    TerminalRuntimeCapabilities,
    TerminalSize,
    TuiRuntime,
    drain_input,
    format_terminal_diagnostics,
    strip_control_sequences,
)
from loushang.tui._runner_utils import (
    flush_pending_input,
    input_events_for_chunk,
    poll_terminal_runtime,
    terminal_runtime_wakeup_ms,
)
from tests.coding.tui_support.playback import ScreenTuiInputPlayback


def test_screen_tui_playback_applies_model_argument_completion() -> None:
    session = _Session()
    app = _app()
    app.composer.set_completion_provider(
        asyncio.run(coding_inline_completion_provider(session, base_path=None))
    )
    playback = ScreenTuiInputPlayback(app)

    steps = playback.play([PlaybackEvent.input("/model gpt\t")])

    assert all(step.flush_succeeded for step in steps)
    assert app.composer.value == "/model openai:test-endpoint:gpt-5.4"
    lines = _plain_lines(steps[-1].diagnostics)
    assert "› /model openai:test-endpoint:gpt-5.4" in lines
    assert (
        "moonshot:test-endpoint:kimi-for-coding | repo | main | abcd | idle"
        in lines[-1]
    )


def test_screen_tui_playback_applies_recursive_at_file_completion(
    tmp_path: Path,
) -> None:
    (tmp_path / "src" / "tests").mkdir(parents=True)
    (tmp_path / "src" / "tests" / "test_completion.py").write_text("", encoding="utf-8")
    session = _Session(cwd=tmp_path)
    app = _app(cwd=str(tmp_path))
    app.composer.set_completion_provider(
        asyncio.run(coding_inline_completion_provider(session, base_path=tmp_path))
    )
    playback = ScreenTuiInputPlayback(app)

    steps = playback.play([PlaybackEvent.input("@test\t")])

    assert all(step.flush_succeeded for step in steps)
    assert app.composer.value == "@src/tests/test_completion.py "
    assert "› @src/tests/test_completion.py " in _plain_lines(steps[-1].diagnostics)


def test_screen_tui_playback_browses_history_from_non_empty_single_line_draft() -> None:
    app = _app()
    app.composer.add_history("first prompt")
    app.composer.add_history("second prompt")
    playback = ScreenTuiInputPlayback(app)

    result = playback.play(
        [
            PlaybackEvent.input("draft"),
            PlaybackEvent.input("\x1b[A"),
            PlaybackEvent.input("\x1b[A"),
            PlaybackEvent.input("\x1b[B"),
            PlaybackEvent.input("\x1b[B"),
        ]
    )

    assert all(step.flush_succeeded for step in result)
    assert [state["composer_text"] for state in playback.step_state_snapshots] == [
        "draft",
        "second prompt",
        "first prompt",
        "second prompt",
        "draft",
    ]
    assert app.composer.value == "draft"
    assert "› draft" in _plain_lines(result[-1].diagnostics)
    for step in result:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_uses_visual_up_before_history_for_multiline_draft() -> (
    None
):
    app = _app()
    app.composer.add_history("previous prompt")
    playback = ScreenTuiInputPlayback(app, columns=80, rows=12)

    result = playback.play(
        [
            PlaybackEvent.input("alpha\nbeta"),
            PlaybackEvent.input("\x1b[A"),
            PlaybackEvent.input("\x1b[A"),
        ]
    )

    assert all(step.flush_succeeded for step in result)
    assert [state["composer_text"] for state in playback.step_state_snapshots] == [
        "alpha\nbeta",
        "alpha\nbeta",
        "previous prompt",
    ]
    assert app.composer.value == "previous prompt"
    for step in result:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_routes_composer_page_keys() -> None:
    app = _app()
    app.composer.set_text("one\ntwo\nthree\nfour\nfive")
    playback = ScreenTuiInputPlayback(app, columns=20, rows=3)

    page_up_steps = playback.play([PlaybackEvent.input("\x1b[5~")])
    page_up = app.composer.render(RenderConstraints(width=20, max_height=5))

    assert all(step.flush_succeeded for step in page_up_steps)
    assert page_up.cursor is not None
    assert (page_up.cursor.row, page_up.cursor.column) == (2, 6)

    page_down_steps = playback.play([PlaybackEvent.input("\x1b[6~")])
    page_down = app.composer.render(RenderConstraints(width=20, max_height=5))

    assert all(step.flush_succeeded for step in page_down_steps)
    assert page_down.cursor is not None
    assert (page_down.cursor.row, page_down.cursor.column) == (4, 6)
    for step in (*page_up_steps, *page_down_steps):
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_completion_navigation_wins_over_history_navigation() -> (
    None
):
    app = _app()
    app.composer.add_history("history prompt")
    app.composer.set_completion_provider(
        asyncio.run(coding_inline_completion_provider(_Session(), base_path=None))
    )
    playback = ScreenTuiInputPlayback(app)

    result = playback.play(
        [
            PlaybackEvent.input("/"),
            PlaybackEvent.input("\x1b[B"),
            PlaybackEvent.input("\t"),
        ]
    )

    assert all(step.flush_succeeded for step in result)
    assert app.composer.value == "/models "
    assert [state["composer_text"] for state in playback.step_state_snapshots] == [
        "/",
        "/",
        "/models ",
    ]
    for step in result:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_shift_selection_replaces_selected_text() -> None:
    app = _app()
    playback = ScreenTuiInputPlayback(app)

    result = playback.play(
        [
            PlaybackEvent.input("abc"),
            PlaybackEvent.input("\x1b[1;2D"),
            PlaybackEvent.input("x"),
        ]
    )

    assert all(step.flush_succeeded for step in result)
    selected_output = result[1].frame.serialized_output if result[1].frame else ""
    assert "\x1b[7mc\x1b[27m" in selected_output
    assert app.composer.value == "abx"
    assert "› abx" in _plain_lines(result[-1].diagnostics)
    for step in result:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_escape_clears_idle_draft_without_abort() -> None:
    app = _app()
    playback = ScreenTuiInputPlayback(app)

    result = playback.play(
        [
            PlaybackEvent.input("draft"),
            PlaybackEvent.input("\x1b"),
        ]
    )

    assert all(step.flush_succeeded for step in result)
    assert app.composer.value == ""
    assert not any(
        isinstance(input_result, ConversationAbortResult)
        for input_result in playback.input_results
    )
    assert "› draft" not in _plain_lines(result[-1].diagnostics)
    for step in result:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_edits_settings_search_with_text_input_cursor() -> None:
    app = _app()
    app.active_surface = SearchableList(
        [
            SearchableListItem("memory", "Memory", "on"),
            SearchableListItem("model", "Model", "kimi"),
        ],
        focused=True,
        placeholder="Search settings...",
        detail_column=24,
    )
    playback = ScreenTuiInputPlayback(app)

    steps = playback.play([PlaybackEvent.input("mo\x1b[Dx")])

    assert all(step.flush_succeeded for step in steps)
    lines = _plain_lines(steps[-1].diagnostics)
    assert "mxo" in lines
    assert "No matching items" in lines


def test_tui_playback_renders_auto_terminal_image_and_text_fallback(
    monkeypatch: Any,
) -> None:
    _clear_image_protocol_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-kitty")
    kitty_playback = _RenderPlayback(
        ImageBlock(alt_text="screenshot", source="shot.png", data=b"abc")
    )

    kitty_step = kitty_playback.play([PlaybackEvent("render")])[0]

    assert kitty_step.flush_succeeded
    assert "\x1b_Ga=T,f=100,t=d;YWJj\x1b\\" in (
        kitty_step.frame.serialized_output if kitty_step.frame else ""
    )

    _clear_image_protocol_env(monkeypatch)
    fallback_playback = _RenderPlayback(
        ImageBlock(alt_text="screenshot", source="shot.png", data=b"abc")
    )

    fallback_step = fallback_playback.play([PlaybackEvent("render")])[0]

    assert fallback_step.flush_succeeded
    output = fallback_step.frame.serialized_output if fallback_step.frame else ""
    assert "[image: screenshot] shot.png" in output
    assert "\x1b_G" not in output


def test_screen_tui_playback_resizes_cleanly_after_drain() -> None:
    app = _app()
    playback = ScreenTuiInputPlayback(app, columns=80, rows=12)

    drained = drain_input(StringIO("stale buffered input"))
    steps = playback.play(
        [
            PlaybackEvent.input("hello"),
            PlaybackEvent.resize(columns=42, rows=8),
        ]
    )

    assert drained == "stale buffered input"
    assert all(step.flush_succeeded for step in steps)
    assert steps[-1].size == TerminalSize(columns=42, rows=8)
    assert steps[-1].diagnostics.operation_class == "resize_repaint"
    assert steps[-1].diagnostics.clear_scrollback_emitted is False
    assert "› hello" in _plain_lines(steps[-1].diagnostics)
    assert playback.harness.port.screen.size == TerminalSize(columns=42, rows=8)


def test_screen_tui_playback_smokes_surfaces_editor_and_image_fallback(
    monkeypatch: Any,
) -> None:
    _clear_image_protocol_env(monkeypatch)
    session = _Session()
    app = _app()
    app.terminal_diagnostics_provider = lambda: (
        "keyboard_protocol_state: kitty\nruntime_image_protocol: none\ncell_size: 9x18"
    )
    app.composer.set_completion_provider(
        asyncio.run(coding_inline_completion_provider(session, base_path=None))
    )
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=18,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/ter\t"),
            PlaybackEvent.input("\r"),
            PlaybackEvent.input("\x1b"),
            PlaybackEvent.input("/model\r"),
            PlaybackEvent.input("\x1b"),
            PlaybackEvent.input("abc\x1b<\x1b>!"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert "› /terminal " in _plain_lines(steps[0].diagnostics)
    terminal_lines = _plain_lines(steps[1].diagnostics)
    assert any(line.strip() == "Terminal" for line in terminal_lines)
    assert any("keyboard_protocol_state: kitty" in line for line in terminal_lines)
    assert any("cell_size: 9x18" in line for line in terminal_lines)
    assert not any(
        line.strip() == "Terminal" for line in _plain_lines(steps[2].diagnostics)
    )
    assert any(
        line.strip() == "Select Model" for line in _plain_lines(steps[3].diagnostics)
    )
    final_lines = _plain_lines(steps[-1].diagnostics)
    assert not any(line.strip() == "Select Model" for line in final_lines)
    assert not any(line.strip() == "Terminal" for line in final_lines)
    assert "› abc!" in final_lines
    assert (
        "moonshot:test-endpoint:kimi-for-coding | repo | main | abcd | idle | perm=standard"
        in final_lines
    )

    fallback_step = _RenderPlayback(
        ImageBlock(alt_text="screenshot", source="shot.png", data=b"abc")
    ).play([PlaybackEvent("render")])[0]

    assert fallback_step.flush_succeeded
    output = fallback_step.frame.serialized_output if fallback_step.frame else ""
    assert "[image: screenshot] shot.png" in output
    assert "\x1b_G" not in output


def test_screen_tui_playback_command_surface_filters_and_selects_command() -> None:
    session = _Session()
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=18,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/command\r"),
            PlaybackEvent.input("rep\r"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert app.composer.value == "/report "
    assert app.active_surface is None
    assert app.surface_host is not None
    assert app.surface_host.entries == []
    lines = _plain_lines(steps[-1].diagnostics)
    assert "Commands" not in lines
    assert "› /report " in lines
    assert "Command selected: /report" in lines[-1]
    for step in steps:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_settings_page_toggles_statusline_and_exits() -> None:
    session = _Session()
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=18,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("\x1b[A"),
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[B"),
            PlaybackEvent.input("\r"),
            PlaybackEvent.input("\x1b"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert app.active_surface is None
    assert app.state.statusline_visible is False
    assert app.state.status_message is None
    before_close_lines = _plain_lines(steps[-2].diagnostics)
    assert any("Status line: off" in line for line in before_close_lines)
    lines = _plain_lines(steps[-1].diagnostics)
    assert "Settings" not in lines
    assert not any("Status line: off" in line for line in lines)
    assert not any(
        "moonshot:test-endpoint:kimi-for-coding | repo | main | abcd | idle" in line
        for line in lines
    )
    for step in steps:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_settings_page_toggles_statusline_style() -> None:
    session = _Session()
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=110,
        rows=24,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("\x1b[A"),
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[B"),
            PlaybackEvent.input("style"),
            PlaybackEvent.input("\r"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert app.active_surface is not None
    assert app.state.statusline_settings.style == "muted"
    assert app.state.status_message is None
    lines = _plain_lines(steps[-1].diagnostics)
    assert any("Style" in line and "muted" in line for line in lines)
    assert any("Status line style: muted" in line for line in lines)
    for step in steps:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_settings_page_toggles_statusline_field() -> None:
    session = _Session()
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=110,
        rows=24,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("\x1b[A"),
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[B"),
            PlaybackEvent.input("queue"),
            PlaybackEvent.input("\r"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert app.active_surface is not None
    assert app.state.statusline_settings.queue == "true"
    assert app.state.status_message is None
    lines = _plain_lines(steps[-1].diagnostics)
    assert any("Queue" in line and "true" in line for line in lines)
    assert any("queued=0 steer=0" in line for line in lines)
    assert any("Status line queue: true" in line for line in lines)
    for step in steps:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_settings_page_searches_when_opened_by_command() -> None:
    session = _Session()
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=18,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("zz"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    lines = _plain_lines(steps[-1].diagnostics)
    assert "Settings" in lines
    assert any("zz" in line for line in lines)
    assert "No matching settings" in lines
    assert app.state.statusline_visible is True
    for step in steps:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_settings_page_q_is_search_text() -> None:
    session = _Session()
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=18,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("q"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert app.active_surface is not None
    lines = _plain_lines(steps[-1].diagnostics)
    assert any("q" in line for line in lines)
    assert "No matching settings" in lines
    for step in steps:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_settings_escape_restores_single_prompt_with_status_gap() -> (
    None
):
    session = _Session()
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=18,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("\x1b"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert app.active_surface is None
    lines = _plain_lines(steps[-1].diagnostics)
    prompt_rows = [index for index, line in enumerate(lines) if line.startswith("›")]
    status_rows = [
        index
        for index, line in enumerate(lines)
        if "moonshot:test-endpoint:kimi-for-coding | repo | main | abcd | idle" in line
    ]
    assert prompt_rows == [status_rows[0] - 2]
    assert lines[prompt_rows[0] + 1] == ""


def test_screen_tui_playback_settings_page_model_tab_is_available() -> None:
    session = _Session()
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=18,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("\x1b[A"),
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[B"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    lines = _plain_lines(steps[-1].diagnostics)
    assert any("Search models..." in line for line in lines)
    assert any("moonshot:test-endpoint:kimi-for-coding" in line for line in lines)
    for step in steps:
        step.assert_no_clear_scrollback()


def test_screen_tui_playback_smokes_terminal_context_model_selector_and_resize() -> (
    None
):
    context = _PlaybackTerminalContext()
    session = _Session()
    app = _app()
    app.terminal_diagnostics_provider = lambda: format_terminal_diagnostics(context)
    app.composer.set_completion_provider(
        asyncio.run(coding_inline_completion_provider(session, base_path=None))
    )
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=30,
        terminal_context=context,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("\x1b[?7u\x1b[6;18;9t"),
            PlaybackEvent.input("/terminal\r"),
            PlaybackEvent.input("\x1b"),
            PlaybackEvent.input("/model\r"),
            PlaybackEvent.input("\x1b[B\r"),
            PlaybackEvent.resize(columns=72, rows=10),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert [event.signal for event in context.events] == ["kitty_protocol", "cell_size"]
    terminal_lines = _plain_lines(steps[1].diagnostics)
    assert any("keyboard_protocol_state: kitty" in line for line in terminal_lines)
    assert any("cell_size: 9x18" in line for line in terminal_lines)
    assert session.current_model == ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    assert app.state.model_label == "openai:test-endpoint:gpt-5.4"
    assert steps[-1].size == TerminalSize(columns=72, rows=10)
    assert steps[-1].diagnostics.operation_class == "resize_repaint"


def test_screen_tui_model_selector_ignores_key_release_events() -> None:
    session = _Session(
        models=(
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            ),
            ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
            ),
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="anthropic",
                model_id="claude-sonnet",
            ),
        )
    )
    app = _app()
    playback = _ScreenInteractivePlayback(
        app,
        _manager(app, session),
        columns=100,
        rows=18,
    )

    steps = playback.play(
        [
            PlaybackEvent.input("/model\r"),
            # Down press followed by a release event from an enhanced keyboard protocol.
            PlaybackEvent.input("\x1b[1;1B\x1b[1;1:3B"),
            PlaybackEvent.input("\r"),
        ]
    )

    assert all(step.flush_succeeded for step in steps)
    assert session.current_model == ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    assert app.state.model_label == "openai:test-endpoint:gpt-5.4"
    lines = _plain_lines(steps[-1].diagnostics)
    assert "Model set: openai:test-endpoint:gpt-5.4" in lines[-1]
    assert not any("claude-sonnet" in line for line in lines)


def test_screen_loop_filters_terminal_control_responses_before_routing() -> None:
    events = input_events_for_chunk(InputReader(), "\x1b[?7uhello")

    assert len(events) == 1
    assert events[0].kind == "text"
    assert events[0].text == "hello"


def test_screen_loop_filters_split_terminal_control_responses_before_routing() -> None:
    reader = InputReader()
    context = _ControlContext()

    first = input_events_for_chunk(reader, "\x1b[?", terminal_context=context)
    second = input_events_for_chunk(reader, "7uhello", terminal_context=context)

    assert first == ()
    assert len(second) == 1
    assert second[0].kind == "text"
    assert second[0].text == "hello"
    assert len(context.events) == 1
    assert context.events[0].signal == "kitty_protocol"
    assert context.events[0].text == "7"


def test_screen_loop_keeps_split_escape_sequence_pending_until_complete() -> None:
    reader = InputReader()

    first = input_events_for_chunk(reader, "\x1b")
    second = input_events_for_chunk(reader, "[A")

    assert first == ()
    assert len(second) == 1
    assert second[0].kind == "key"
    assert second[0].key == "up"


def test_screen_loop_flushes_pending_escape_explicitly() -> None:
    reader = InputReader()

    first = input_events_for_chunk(reader, "\x1b")
    flushed = flush_pending_input(reader)

    assert first == ()
    assert len(flushed) == 1
    assert flushed[0].kind == "key"
    assert flushed[0].key == "escape"


def test_screen_loop_passes_terminal_control_events_to_context() -> None:
    context = _ControlContext()

    events = input_events_for_chunk(
        InputReader(), "\x1b[6;18;9t", terminal_context=context
    )

    assert events == ()
    assert len(context.events) == 1
    assert context.events[0].signal == "cell_size"


def test_screen_loop_reads_terminal_runtime_wakeup_delay() -> None:
    context = _RuntimeWakeupContext(delay_ms=42)

    assert terminal_runtime_wakeup_ms(context) == 42
    assert context.wakeup_calls == 1


def test_screen_loop_polls_terminal_runtime_fallback() -> None:
    context = _RuntimeWakeupContext(delay_ms=0)

    assert poll_terminal_runtime(context) is True
    assert context.poll_calls == 1


class _ScreenInteractivePlayback:
    def __init__(
        self,
        app: ScreenCodingTuiApp,
        surface_manager: ScreenSurfaceManager,
        *,
        columns: int = 80,
        rows: int = 12,
        terminal_context: object | None = None,
    ) -> None:
        self.app = app
        self.surface_manager = surface_manager
        self.terminal_context = terminal_context
        self.reader = InputReader()
        self.terminal = FakeTerminalPort(size=TerminalSize(columns=columns, rows=rows))
        self.runtime = TuiRuntime(
            render_loop=RenderLoop(app, clear_scrollback_policy="disabled"),
            terminal=self.terminal,
        )
        self.app.surface_host = self.runtime.overlay_host()
        self.router = build_screen_input_router(
            app,
            should_exit=lambda _text: False,
            is_local_command=surface_manager.is_local_command,
            width=columns,
            height=rows,
        )

    def play(self, events: list[PlaybackEvent]) -> tuple[PlaybackStep, ...]:
        steps: list[PlaybackStep] = []
        for event in events:
            if event.kind == "resize":
                if not isinstance(event.payload, TerminalSize):
                    raise TypeError("resize event payload must be TerminalSize")
                self.terminal.resize(event.payload)
                self.router.width = event.payload.columns
                self.router.height = event.payload.rows
            elif event.kind == "input":
                if not isinstance(event.payload, str):
                    raise TypeError("input playback event payload must be str")
                self._route_input(event.payload)
            steps.append(self.runtime.render_now())
        return tuple(steps)

    def _route_input(self, data: str) -> None:
        events = list(
            input_events_for_chunk(
                self.reader, data, terminal_context=self.terminal_context
            )
        )
        if self.reader.has_pending:
            events.extend(
                flush_pending_input(self.reader, terminal_context=self.terminal_context)
            )
        for event in events:
            result = self.router.handle(event)
            if isinstance(result, ConversationLocalResult):
                asyncio.run(self.surface_manager.handle_text(result.text))
            if isinstance(result, ConversationSurfaceResult):
                asyncio.run(
                    self.surface_manager.handle_surface_intent(result.intent)
                )


class _RenderPlayback:
    def __init__(self, root: Renderable, *, columns: int = 80, rows: int = 12) -> None:
        self.render_loop = RenderLoop(root, clear_scrollback_policy="disabled")
        self.harness = PlaybackHarness(
            render=self._render,
            port=FakeTerminalPort(size=TerminalSize(columns=columns, rows=rows)),
        )

    def play(self, events: list[PlaybackEvent]) -> tuple[PlaybackStep, ...]:
        return self.harness.play(events)

    def _render(
        self,
        _event: PlaybackEvent,
        size: TerminalSize,
        _previous: RenderDiagnostics | None,
    ) -> RenderDiagnostics:
        diagnostics = self.render_loop.plan(size)
        self.render_loop.commit(diagnostics, size=size)
        return diagnostics


class _ControlContext:
    def __init__(self) -> None:
        self.events: tuple[Any, ...] = ()

    def consume_control_events(self, events: tuple[Any, ...]) -> None:
        self.events += events


class _RuntimeWakeupContext:
    def __init__(self, *, delay_ms: int | None) -> None:
        self.delay_ms = delay_ms
        self.wakeup_calls = 0
        self.poll_calls = 0

    def next_wakeup_delay_ms(self) -> int | None:
        self.wakeup_calls += 1
        return self.delay_ms

    def flush_keyboard_protocol_fallback_if_due(self) -> bool:
        self.poll_calls += 1
        return True


class _PlaybackTerminalContext:
    def __init__(self) -> None:
        self.capabilities = TerminalRuntimeCapabilities(
            image_protocol="none", truecolor=True
        )
        self.events: tuple[Any, ...] = ()
        self.keyboard_protocol_state = "querying"
        self.cell_size = None

    def consume_control_events(self, events: tuple[Any, ...]) -> None:
        self.events += events
        for event in events:
            if event.signal == "kitty_protocol":
                self.keyboard_protocol_state = "kitty"
            elif event.signal == "cell_size":
                height, width = (int(part) for part in event.text.split(";", 1))
                self.cell_size = SimpleNamespace(width_px=width, height_px=height)

    def diagnostics(self) -> object:
        return SimpleNamespace(
            keyboard_protocol_state=self.keyboard_protocol_state,
            mouse_mode_active=False,
            cell_size=self.cell_size,
            image_protocol="none",
            alternate_screen=False,
            tmux_passthrough=False,
            windows_vt_input=False,
            termux_session=False,
            is_multiplexer=False,
            inside_ssh=False,
        )


class _Session:
    def __init__(
        self,
        *,
        cwd: Path | None = None,
        models: tuple[ModelSelection, ...] | None = None,
    ) -> None:
        self.session_manager = (
            SimpleNamespace(get_cwd=lambda: str(cwd)) if cwd is not None else None
        )
        self.current_model = ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        )
        self.models = models or (
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            ),
            ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
            ),
        )

    def list_commands(self) -> list[object]:
        return [
            SimpleNamespace(name="model", description="Select model", source="builtin"),
            SimpleNamespace(name="models", description="List models", source="builtin"),
            SimpleNamespace(name="report", description="Show report", source="builtin"),
            SimpleNamespace(
                name="terminal",
                description="Show terminal diagnostics",
                source="builtin",
            ),
        ]

    def get_model_selection(self) -> ModelSelection:
        return self.current_model

    def get_available_models(self) -> list[object]:
        return list(self.models)

    async def set_model(self, selection: object) -> None:
        self.current_model = selection


def _app(*, cwd: str = "/repo") -> ScreenCodingTuiApp:
    return ScreenCodingTuiApp(
        model_label="moonshot:test-endpoint:kimi-for-coding",
        cwd=cwd,
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )


def _manager(app: ScreenCodingTuiApp, session: _Session) -> ScreenSurfaceManager:
    return ScreenSurfaceManager(
        app=app,
        session=session,
        status_provider=StatusProvider(
            model_label=app.state.model_label,
            cwd=app.state.cwd,
            branch=app.state.branch,
            session_label=lambda: app.state.session_label,
            thinking_level=lambda: None,
            running=lambda: app.state.running,
        ),
    )


def _plain_lines(diagnostics: RenderDiagnostics) -> tuple[str, ...]:
    return tuple(
        strip_control_sequences(line) for line in diagnostics.current_logical_lines
    )


def _clear_image_protocol_env(monkeypatch: Any) -> None:
    for name in (
        "TERM",
        "TERM_PROGRAM",
        "ITERM_SESSION_ID",
        "KITTY_WINDOW_ID",
        "TMUX",
        "STY",
        "WEZTERM_PANE",
        "WEZTERM_EXECUTABLE",
        "GHOSTTY_RESOURCES_DIR",
        "LOUSHANG_TUI_TMUX_PASSTHROUGH",
    ):
        monkeypatch.delenv(name, raising=False)

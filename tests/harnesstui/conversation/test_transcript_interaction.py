from __future__ import annotations

import asyncio
from contextlib import nullcontext
from io import StringIO

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import build_screen_input_router
from loushang.harnesstui.conversation.input import ConversationCopyTextResult
from loushang.harnesstui.conversation.screen_runner import run_conversation_screen
from loushang.tui import RenderConstraints, strip_control_sequences
from loushang.tui.input import InputEvent
from loushang.tui.keybindings import KeybindingManager
from loushang.tui.terminal import TerminalSize
from loushang.tui.transcript import AssistantMessageRecord, ToolExecutionRecord


def _app() -> ScreenCodingTuiApp:
    app = ScreenCodingTuiApp(
        model_label="test", cwd="/repo", branch="main", session_label="test"
    )
    app.state.records.extend(
        (
            AssistantMessageRecord("answer"),
            ToolExecutionRecord(
                name="shell",
                state="completed",
                elapsed_seconds=1,
                command="short",
                expanded_command="long command with detail",
                output="preview",
                expanded_output="full output detail",
            ),
        )
    )
    app.state.mark_records_changed()
    return app


def _render(app: ScreenCodingTuiApp) -> tuple[str, ...]:
    return tuple(
        strip_control_sequences(line.text)
        for line in app.render(RenderConstraints(width=80, max_height=24)).lines
    )


def test_detail_control_click_and_keyboard_focus() -> None:
    app = _app()
    router = build_screen_input_router(app, should_exit=lambda _text: False)
    lines = _render(app)
    row = next(index for index, line in enumerate(lines) if "Show Detail" in line)

    column = lines[row].index("Show Detail")
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="press",
            mouse_button=0,
            mouse_row=row,
            mouse_column=column,
        )
    )
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="release",
            mouse_button=0,
            mouse_row=row,
            mouse_column=column,
        )
    )
    expanded = _render(app)
    assert any("Show Less" in line for line in expanded)
    assert any("long command with detail" in line for line in expanded)
    assert any("full output detail" in line for line in expanded)

    router.handle(InputEvent(kind="key", key="f4"))
    assert app._focused_tool_index == 1
    router.handle(InputEvent(kind="key", key="enter"))
    assert any("Show Detail" in line for line in _render(app))
    router.handle(InputEvent(kind="key", key="esc"))
    assert app._focused_tool_index is None


def test_mouse_rows_follow_the_rendered_terminal_viewport() -> None:
    app = _app()
    app.state.records.insert(
        0, AssistantMessageRecord("\n".join(f"older line {i}" for i in range(36)))
    )
    app.state.mark_records_changed()
    router = build_screen_input_router(app, should_exit=lambda _text: False)
    frame = app.render(RenderConstraints(width=80, max_height=1_000_000, visible_height=24))
    lines = tuple(strip_control_sequences(line.text) for line in frame.lines)
    viewport_top = len(lines) - 24
    assert viewport_top > 0
    control_row = next(index for index, line in enumerate(lines) if "Show Detail" in line)
    physical_row = control_row - viewport_top
    assert 0 <= physical_row < 24
    column = lines[control_row].index("Show Detail")

    router.set_transcript_viewport_top(viewport_top)
    for action in ("press", "release"):
        router.handle(
            InputEvent(
                kind="mouse",
                mouse_action=action,
                mouse_button=0,
                mouse_row=physical_row,
                mouse_column=column,
            )
        )
    expanded = app.render(RenderConstraints(width=80, max_height=1_000_000, visible_height=24))
    expanded_lines = tuple(strip_control_sequences(line.text) for line in expanded.lines)
    expanded_control_row = next(
        index for index, line in enumerate(expanded_lines) if "Show Less" in line
    )
    expanded_physical_row = expanded_control_row - (len(expanded_lines) - 24)
    assert 0 <= expanded_physical_row < 24
    expanded_column = expanded_lines[expanded_control_row].index("Show Less")
    router.set_transcript_viewport_top(len(expanded_lines) - 24)
    for action in ("press", "release"):
        router.handle(
            InputEvent(
                kind="mouse",
                mouse_action=action,
                mouse_button=0,
                mouse_row=expanded_physical_row,
                mouse_column=expanded_column,
            )
        )
    collapsed = app.render(RenderConstraints(width=80, max_height=1_000_000, visible_height=24))
    assert any("Show Detail" in line.text for line in collapsed.lines)


def test_mouse_selection_uses_rendered_terminal_viewport() -> None:
    app = _app()
    app.state.records.insert(
        0, AssistantMessageRecord("\n".join(f"older line {i}" for i in range(36)))
    )
    app.state.mark_records_changed()
    router = build_screen_input_router(app, should_exit=lambda _text: False)
    frame = app.render(RenderConstraints(width=80, max_height=1_000_000, visible_height=24))
    lines = tuple(strip_control_sequences(line.text) for line in frame.lines)
    viewport_top = len(lines) - 24
    logical_row = next(index for index, line in enumerate(lines) if "answer" in line)
    physical_row = logical_row - viewport_top
    assert 0 <= physical_row < 24
    column = lines[logical_row].index("answer")

    router.set_transcript_viewport_top(viewport_top)
    for action, end in (("press", 0), ("drag", 5)):
        router.handle(
            InputEvent(
                kind="mouse",
                mouse_action=action,
                mouse_button=0,
                mouse_row=physical_row,
                mouse_column=column + end,
            )
        )
    copied = router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="release",
            mouse_button=0,
            mouse_row=physical_row,
            mouse_column=column + 6,
        )
    )
    assert copied == ConversationCopyTextResult("answer")


def test_screen_runner_maps_sgr_click_from_terminal_viewport() -> None:
    app = _app()
    app.state.records.insert(
        0, AssistantMessageRecord("\n".join(f"older line {i}" for i in range(36)))
    )
    app.state.mark_records_changed()
    frame = app.render(RenderConstraints(width=80, max_height=1_000_000, visible_height=24))
    lines = tuple(strip_control_sequences(line.text) for line in frame.lines)
    logical_row = next(index for index, line in enumerate(lines) if "Show Detail" in line)
    physical_row = logical_row - (len(lines) - 24)
    column = lines[logical_row].index("Show Detail")
    assert 0 <= physical_row < 24
    chunks = iter(
        (
            f"\x1b[<0;{column + 1};{physical_row + 1}M",
            f"\x1b[<0;{column + 1};{physical_row + 1}m",
            "",
        )
    )

    async def read(_stdin: object) -> str:
        return next(chunks)

    assert asyncio.run(
        run_conversation_screen(
            app=app,
            stdin=StringIO(),
            stdout=StringIO(),
            handle_prompt=lambda _text: None,
            on_abort=lambda: None,
            should_exit=lambda _text: False,
            input_router_factory=build_screen_input_router,
            input_chunk_reader=read,
            terminal_mode_factory=lambda _stdin, _stdout: nullcontext(object()),
            terminal_size_provider=lambda: TerminalSize(columns=80, rows=24),
            interruption_message="Interrupted",
            cancellation_message="Cancelled",
        )
    ) == 0
    assert any("Show Less" in line for line in _render(app))


def test_drag_selection_copies_displayed_text_and_ctrl_c_precedes_interrupt() -> None:
    app = _app()
    router = build_screen_input_router(app, should_exit=lambda _text: False)
    lines = _render(app)
    row = next(index for index, line in enumerate(lines) if "answer" in line)
    line = lines[row]
    start = line.index("answer")
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="press",
            mouse_button=0,
            mouse_row=row,
            mouse_column=start,
        )
    )
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="drag",
            mouse_button=0,
            mouse_row=row,
            mouse_column=start + 5,
        )
    )
    copied = router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="release",
            mouse_button=0,
            mouse_row=row,
            mouse_column=start + 6,
        )
    )
    assert copied == ConversationCopyTextResult("answer")
    assert router.handle(
        InputEvent(kind="key", key="ctrl+c")
    ) == ConversationCopyTextResult("answer")
    router.handle(InputEvent(kind="key", key="esc"))
    assert app.selected_transcript_text() == ""


def test_ctrl_o_copies_latest_completed_answer_without_opening_reader() -> None:
    app = _app()
    router = build_screen_input_router(app, should_exit=lambda _text: False)
    assert router.handle(
        InputEvent(kind="key", key="ctrl+o")
    ) == ConversationCopyTextResult("answer")


def test_focused_space_toggles_without_editing_draft() -> None:
    app = _app()
    router = build_screen_input_router(app, should_exit=lambda _text: False)
    _render(app)
    router.handle(InputEvent(kind="key", key="f4"))
    before = app.composer.value
    router.handle(InputEvent(kind="text", text=" "))
    assert app.composer.value == before
    assert any("Show Less" in line for line in _render(app))
    router.handle(InputEvent(kind="text", text="x"))
    assert app.composer.value == "x"
    assert app._focused_tool_index is None


def test_drag_from_control_suppresses_click_and_excludes_control_from_copy() -> None:
    app = _app()
    router = build_screen_input_router(app, should_exit=lambda _text: False)
    lines = _render(app)
    row = next(index for index, line in enumerate(lines) if "Show Detail" in line)
    column = lines[row].index("Show Detail")
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="press",
            mouse_button=0,
            mouse_row=row,
            mouse_column=column,
        )
    )
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="drag",
            mouse_button=0,
            mouse_row=row - 1,
            mouse_column=0,
        )
    )
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="release",
            mouse_button=0,
            mouse_row=row,
            mouse_column=column,
        )
    )
    assert any("Show Detail" in line for line in _render(app))
    assert "Show Detail" not in app.selected_transcript_text()


def test_expansion_anchor_never_exceeds_screen_budget() -> None:
    app = _app()
    app.state.records.append(
        AssistantMessageRecord("\n".join(f"later {i}" for i in range(40)))
    )
    app.state.mark_records_changed()
    app._toggle_tool_detail(1)
    rows = _render(app)
    assert len(rows) <= 24
    assert any("Show Less" in row for row in rows)
    assert app._transcript_region.visible_height < 24


def test_explicit_ctrl_o_transcript_override_takes_priority_over_copy_default() -> None:
    from loushang.tui import SurfaceHost

    app = _app()
    app.surface_host = SurfaceHost()
    router = build_screen_input_router(
        app,
        should_exit=lambda _text: False,
        keybindings=KeybindingManager({"tui.transcript.open": "ctrl+o"}),
    )
    router.handle(InputEvent(kind="key", key="ctrl+o"))
    assert app.surface_host.entries
    reader = app._reader_surface
    assert reader is not None
    assert (
        reader.handle_input(InputEvent(kind="key", key="ctrl+o")).kind
        == "surface_close"
    )


def test_multiline_selection_omits_synthetic_control_rows() -> None:
    app = _app()
    router = build_screen_input_router(app, should_exit=lambda _text: False)
    lines = _render(app)
    first = next(index for index, line in enumerate(lines) if "answer" in line)
    last = next(index for index, line in enumerate(lines) if "Show Detail" in line)
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="press",
            mouse_button=0,
            mouse_row=first,
            mouse_column=0,
        )
    )
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="drag",
            mouse_button=0,
            mouse_row=last,
            mouse_column=len(lines[last]),
        )
    )
    router.handle(
        InputEvent(
            kind="mouse",
            mouse_action="release",
            mouse_button=0,
            mouse_row=last,
            mouse_column=len(lines[last]),
        )
    )
    selected = app.selected_transcript_text()
    assert "answer" in selected
    assert "Show Detail" not in selected

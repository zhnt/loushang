from __future__ import annotations

from collections.abc import Callable

from loushang.coding.types import ModelSelection
from loushang.coding.ui.native_surfaces import NativeSurfaceManager, NativeSurfaceView
from loushang.coding.ui.playback import (
    NativeTuiInputPlaybackResult,
    NativeTuiInputScenario,
    NativeTuiLoopPlayback,
)
from loushang.coding.ui.playback_fakes import (
    ModelPlaybackSession,
    SessionCommandPlaybackSession,
)
from loushang.coding.ui.playback_scenarios.budgets import INTERACTION_FRAME_BUDGET
from loushang.coding.ui.playback_suite import NativePlaybackScenarioSpec
from loushang.coding.ui.status_provider import CodingTuiStatusProvider
from loushang.tui import DialogSurface, SelectionSurface, SelectItem


def _run_active_surface() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_active_surface(SelectionSurface([SelectItem("Choose me", value="chosen")]))
        .with_composer_text("draft")
        .render()
        .enter()
        .run()
    )
    result.assert_surface_intents(("select", "chosen"))
    result.assert_composer_text("draft")
    result.assert_visible_contains("Choose me")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_status_surface() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    manager = _surface_manager(playback.app)

    result = playback.run(
        (0.00, "/status\r"),
        (0.01, "\r"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Status")
    result.assert_text_contains("moonshot/kimi-for-coding")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_commands_info_surface() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    manager = _surface_manager(playback.app)

    result = playback.run(
        (0.00, "/commands status\r"),
        (0.01, "\r"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Commands")
    result.assert_text_contains("/status - Show current status (local)")
    result.assert_text_not_contains("/settings - Open settings (local)")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_commands_info_session_command() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    session = SessionCommandPlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/commands name\r"),
        (0.01, "\r"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Commands")
    result.assert_text_contains("/name <name> - Set session display name (builtin)")
    result.assert_text_not_contains("/status - Show current status (local)")
    result.assert_no_clear_screen()
    assert session.commands == []
    assert session.prompts == []
    assert result.app.active_surface is None
    return result


def _run_statusline_command() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    manager = _surface_manager(playback.app)

    off_result = playback.run(
        (0.00, "/statusline off\r"),
        (0.02, ""),
        handle_local=manager.handle_text,
        is_local_command=manager.is_local_command,
    )

    off_result.assert_exit_code(0)
    assert playback.app.state.statusline_visible is False
    assert playback.app.state.status_message == "Status line: off"
    off_result.assert_no_clear_screen()

    on_result = playback.run(
        (0.00, "/statusline on\r"),
        (0.02, ""),
        handle_local=manager.handle_text,
        is_local_command=manager.is_local_command,
    )

    on_result.assert_exit_code(0)
    assert playback.app.state.statusline_visible is True
    assert playback.app.state.status_message == "Status line: on"
    on_result.assert_text_contains("Status line: on")
    on_result.assert_text_contains("moonshot/kimi-for-coding | repo | main | abcd | idle")
    on_result.assert_no_clear_screen()
    return on_result


def _run_command_palette_select() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    manager = _surface_manager(playback.app)

    result = playback.run(
        (0.00, "/command\r"),
        (0.01, "sta"),
        (0.03, "\r"),
        (0.05, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_composer_text("/status ")
    result.assert_text_contains("Command selected: /status")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_command_palette_session_command() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    session = SessionCommandPlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/command\r"),
        (0.01, "nam"),
        (0.03, "\r"),
        (0.05, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_composer_text("/name ")
    result.assert_text_contains("Command selected: /name")
    result.assert_no_clear_screen()
    assert session.commands == []
    assert session.prompts == []
    assert result.app.active_surface is None
    return result


def _run_settings_search() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    manager = _surface_manager(playback.app)

    result = playback.run(
        (0.00, "/settings\r"),
        (0.01, "zz"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Settings")
    result.assert_text_contains("Search: zz")
    result.assert_text_contains("No matching settings")
    result.assert_text_not_contains("Status line: off")
    result.assert_no_clear_screen()
    return result


def _run_model_select() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    session = ModelPlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/model\r"),
        (0.01, "2"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    assert session.current_model == ModelSelection(provider="openai", model_id="gpt-5.4")
    assert playback.app.state.model_label == "openai/gpt-5.4"
    result.assert_text_contains("Select Model")
    result.assert_text_contains("Model set: openai/gpt-5.4")
    result.assert_text_contains("openai/gpt-5.4 | repo | main | abcd | idle")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_model_select_search() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    session = ModelPlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/model\r"),
        (0.01, "gpt"),
        (0.03, "\r"),
        (0.05, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    assert session.current_model == ModelSelection(provider="openai", model_id="gpt-5.4")
    assert playback.app.state.model_label == "openai/gpt-5.4"
    result.assert_text_contains("Search: gpt")
    result.assert_text_contains("Model set: openai/gpt-5.4")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_approval_surface() -> object:
    return _run_approval_surface_response(input_text="y", approved=True, expected_status="Action confirmed: write file")


def _run_approval_reject_surface() -> object:
    return _run_approval_surface_response(input_text="n", approved=False, expected_status="Action rejected")


def _run_approval_surface_response(*, input_text: str, approved: bool, expected_status: str) -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    approvals: list[dict[str, object]] = []

    async def on_approval(payload: dict[str, object]) -> None:
        approvals.append(payload)

    manager = _surface_manager(playback.app, on_approval=on_approval)
    manager.open_approval(action="write file", risk="Will modify /repo/app.py", action_id="write:app.py")

    result = playback.run(
        (0.00, input_text),
        (0.02, ""),
        handle_surface_intent=manager.handle_surface_intent,
    )

    result.assert_exit_code(0)
    assert approvals == [
        {
            "action_id": "write:app.py",
            "action": "write file",
            "approved": approved,
            "raw_note": "write:app.py",
        }
    ]
    result.assert_text_contains("Approval")
    result.assert_text_contains("write file")
    result.assert_text_contains(expected_status)
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_dialog_surface() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    manager = _surface_manager(playback.app)
    playback.app.active_surface = NativeSurfaceView(
        title="Confirm",
        purpose="dialog",
        content=DialogSurface(title="Confirm", message="Proceed?"),
        footer="",
        presentation="bottom-exclusive",
    )

    result = playback.run(
        (0.00, "\r"),
        (0.02, ""),
        handle_surface_intent=manager.handle_surface_intent,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Confirm")
    result.assert_text_contains("Proceed?")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_mouse_select_active_surface() -> NativeTuiInputPlaybackResult:
    surface = SelectionSurface(
        [
            SelectItem("First option", value="first"),
            SelectItem("Second option", value="second"),
            SelectItem("Third option", value="third"),
        ],
        max_visible=3,
    )
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_active_surface(surface)
        .render()
        .key("\x1b[<0;1;2M")
        .enter()
        .run()
    )
    result.assert_surface_intents(("select", "second"))
    result.assert_composer_text("")
    result.assert_visible_contains("Second option")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _surface_manager(
    app: object,
    *,
    session: object | None = None,
    on_approval: Callable[[dict[str, object]], object] | None = None,
) -> NativeSurfaceManager:
    return NativeSurfaceManager(
        app=app,
        session=object() if session is None else session,
        status_provider=_status_provider(app),
        on_approval=on_approval,
    )


def _status_provider(app: object) -> CodingTuiStatusProvider:
    state = getattr(app, "state")
    return CodingTuiStatusProvider(
        model_label=state.model_label,
        cwd=state.cwd,
        branch=state.branch,
        session_label=lambda: state.session_label,
        thinking_level=lambda: None,
        running=lambda: state.running,
    )


SURFACE_SCENARIOS = (
    NativePlaybackScenarioSpec(
        name="active-surface",
        description="Route enter to an active surface before the composer.",
        run=_run_active_surface,
    ),
    NativePlaybackScenarioSpec(
        name="status-surface",
        description="Open and close the native status info surface through the local command path.",
        run=_run_status_surface,
        tags=("command", "surface"),
    ),
    NativePlaybackScenarioSpec(
        name="statusline-command",
        description="Toggle the native status line through the local command path.",
        run=_run_statusline_command,
        tags=("command", "local"),
    ),
    NativePlaybackScenarioSpec(
        name="command-palette-select",
        description="Search the native command palette and insert the selected command.",
        run=_run_command_palette_select,
        tags=("command", "surface"),
    ),
    NativePlaybackScenarioSpec(
        name="command-palette-session-command",
        description="Select a session command from the native command palette without executing it.",
        run=_run_command_palette_session_command,
        tags=("command", "surface", "session"),
    ),
    NativePlaybackScenarioSpec(
        name="commands-info-surface",
        description="Open and close the native commands info surface through the local command path.",
        run=_run_commands_info_surface,
        tags=("command", "surface"),
    ),
    NativePlaybackScenarioSpec(
        name="commands-info-session-command",
        description="Show session commands in the native commands info surface without executing them.",
        run=_run_commands_info_session_command,
        tags=("command", "surface", "session"),
    ),
    NativePlaybackScenarioSpec(
        name="settings-search",
        description="Search the settings surface opened through the native command path.",
        run=_run_settings_search,
    ),
    NativePlaybackScenarioSpec(
        name="model-select",
        description="Open the native model selector and switch models without clearing the screen.",
        run=_run_model_select,
    ),
    NativePlaybackScenarioSpec(
        name="model-select-search",
        description="Search the native model selector and select the filtered model.",
        run=_run_model_select_search,
    ),
    NativePlaybackScenarioSpec(
        name="approval-surface",
        description="Approve an active native approval surface and verify its callback payload.",
        run=_run_approval_surface,
    ),
    NativePlaybackScenarioSpec(
        name="approval-reject-surface",
        description="Reject an active native approval surface and verify its callback payload.",
        run=_run_approval_reject_surface,
    ),
    NativePlaybackScenarioSpec(
        name="dialog-surface",
        description="Confirm an active native dialog surface without repainting the screen.",
        run=_run_dialog_surface,
    ),
    NativePlaybackScenarioSpec(
        name="mouse-select-active-surface",
        description="Route raw SGR mouse press events to an active selection surface.",
        run=_run_mouse_select_active_surface,
    ),
)


__all__ = ["SURFACE_SCENARIOS"]

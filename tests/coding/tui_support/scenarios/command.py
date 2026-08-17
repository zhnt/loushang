from __future__ import annotations

from io import StringIO

from loushang.coding.ui.product_binding import build_coding_ui_controller
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
from loushang.harnesstui.status.provider import StatusProvider
from loushang.tui.playback_suite import (
    PlaybackScenarioSpec as ScreenPlaybackScenarioSpec,
)
from tests.coding.tui_support.action_host import (
    coding_screen_prompt_handler,
)
from tests.coding.tui_support.fakes import SessionCommandPlaybackSession
from tests.coding.tui_support.playback import (
    ScreenTuiInputPlaybackResult,
    ScreenTuiInputScenario,
    ScreenTuiLoopPlayback,
)
from tests.coding.tui_support.scenarios.budgets import INTERACTION_FRAME_BUDGET


def _run_local_command() -> ScreenTuiInputPlaybackResult:
    result = (
        ScreenTuiInputScenario(width=80, height=12)
        .with_local_commands("/local")
        .render()
        .type_text("/local")
        .enter()
        .run()
    )
    result.assert_local_texts("/local")
    result.assert_prompt_texts()
    result.assert_composer_text("")
    result.assert_visible_not_contains("› /local")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_session_rename_command() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot/kimi-for-coding"
    )
    session = SessionCommandPlaybackSession()
    controller = build_coding_ui_controller(session=session)
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/rename Project Alpha\r"),
        (0.03, ""),
        handle_prompt=coding_screen_prompt_handler(
            presenter=playback.app,
            controller=controller,
            stderr=StringIO(),
            verbose=False,
        ),
        handle_local=manager.handle_text,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_idle()
    assert session.commands == [("rename", "Project Alpha")]
    assert session.prompts == []
    result.assert_text_contains("› /rename Project Alpha")
    result.assert_text_contains("Session name set: Project Alpha")
    result.assert_no_clear_screen()
    return result


def _run_session_command_error() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot/kimi-for-coding"
    )
    session = SessionCommandPlaybackSession()
    controller = build_coding_ui_controller(session=session)
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/export /root/out.jsonl\r"),
        (0.03, ""),
        handle_prompt=coding_screen_prompt_handler(
            presenter=playback.app,
            controller=controller,
            stderr=StringIO(),
            verbose=False,
        ),
        handle_local=manager.handle_text,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_idle()
    assert session.commands == [("export", "/root/out.jsonl")]
    assert session.prompts == []
    result.assert_text_contains("› /export /root/out.jsonl")
    result.assert_text_contains("Export failed: /root/out.jsonl")
    result.assert_no_clear_screen()
    return result


def _run_unknown_slash_prompt() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot/kimi-for-coding"
    )
    session = SessionCommandPlaybackSession()
    controller = build_coding_ui_controller(session=session)
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/unknown keep me\r"),
        (0.03, ""),
        handle_prompt=coding_screen_prompt_handler(
            presenter=playback.app,
            controller=controller,
            stderr=StringIO(),
            verbose=False,
        ),
        handle_local=manager.handle_text,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_idle()
    assert session.commands == []
    assert session.prompts == ["/unknown keep me"]
    result.assert_text_contains("› /unknown keep me")
    result.assert_no_clear_screen()
    return result


def _run_non_executable_session_command() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot/kimi-for-coding"
    )
    session = SessionCommandPlaybackSession()
    controller = build_coding_ui_controller(session=session)
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/review check dispatch\r"),
        (0.04, "/debugging trace queue\r"),
        (0.08, ""),
        handle_prompt=coding_screen_prompt_handler(
            presenter=playback.app,
            controller=controller,
            stderr=StringIO(),
            verbose=False,
        ),
        handle_local=manager.handle_text,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_idle()
    assert session.commands == []
    assert session.prompts == ["/review check dispatch", "/debugging trace queue"]
    result.assert_text_contains("› /review check dispatch")
    result.assert_text_contains("› /debugging trace queue")
    result.assert_no_clear_screen()
    return result


def _surface_manager(
    app: ScreenCodingTuiApp,
    *,
    session: object | None = None,
) -> ScreenSurfaceManager:
    return ScreenSurfaceManager(
        app=app,
        session=object() if session is None else session,
        status_provider=_status_provider(app),
    )


def _status_provider(app: ScreenCodingTuiApp) -> StatusProvider:
    state = app.state
    return StatusProvider(
        model_label=state.model_label,
        cwd=state.cwd,
        branch=state.branch,
        session_label=lambda: state.session_label,
        thinking_level=lambda: None,
        running=lambda: state.running,
    )


COMMAND_ROUTING_SCENARIOS = (
    ScreenPlaybackScenarioSpec(
        name="local-command",
        description="Route a local command without echoing it as a prompt.",
        run=_run_local_command,
        tags=("command", "local"),
    ),
    ScreenPlaybackScenarioSpec(
        name="session-rename-command",
        description="Dispatch /rename through the screen session command path without prompting the agent.",
        run=_run_session_rename_command,
        tags=("command", "session"),
    ),
    ScreenPlaybackScenarioSpec(
        name="session-command-error",
        description="Render session command errors through the screen command path without prompting the agent.",
        run=_run_session_command_error,
        tags=("command", "session"),
    ),
    ScreenPlaybackScenarioSpec(
        name="unknown-slash-prompt",
        description="Leave unknown slash-prefixed prompts on the agent prompt path.",
        run=_run_unknown_slash_prompt,
        tags=("command", "prompt"),
    ),
    ScreenPlaybackScenarioSpec(
        name="non-executable-session-command",
        description="Leave prompt and skill slash commands on the agent prompt path in screen TUI.",
        run=_run_non_executable_session_command,
        tags=("command", "session", "prompt"),
    ),
)


__all__ = ["COMMAND_ROUTING_SCENARIOS"]

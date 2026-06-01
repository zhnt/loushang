from __future__ import annotations

from collections.abc import Callable
from io import StringIO

from loushang.coding.ui.controller import CodingUiController
from loushang.coding.ui.mode import _native_prompt_handler
from loushang.coding.ui.native_surfaces import NativeSurfaceManager
from loushang.coding.ui.playback import (
    NativeTuiInputPlaybackResult,
    NativeTuiInputScenario,
    NativeTuiLoopPlayback,
)
from loushang.coding.ui.playback_fakes import SessionCommandPlaybackSession
from loushang.coding.ui.playback_scenarios.budgets import INTERACTION_FRAME_BUDGET
from loushang.coding.ui.playback_suite import NativePlaybackScenarioSpec
from loushang.coding.ui.status_provider import CodingTuiStatusProvider


def _run_local_command() -> NativeTuiInputPlaybackResult:
    result = (
        NativeTuiInputScenario(width=80, height=12)
        .with_local_commands("/status")
        .render()
        .type_text("/status")
        .enter()
        .run()
    )
    result.assert_local_texts("/status")
    result.assert_prompt_texts()
    result.assert_composer_text("")
    result.assert_visible_not_contains("› /status")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


def _run_session_name_command() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    session = SessionCommandPlaybackSession()
    controller = CodingUiController(session=session)
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/name Project Alpha\r"),
        (0.03, ""),
        handle_prompt=_native_prompt_handler(
            app=playback.app,
            controller=controller,
            stderr=StringIO(),
            verbose=False,
        ),
        handle_local=manager.handle_text,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_idle()
    assert session.commands == [("name", "Project Alpha")]
    assert session.prompts == []
    result.assert_text_contains("› /name Project Alpha")
    result.assert_text_contains("Session name set: Project Alpha")
    result.assert_no_clear_screen()
    return result


def _run_session_command_error() -> object:
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    session = SessionCommandPlaybackSession()
    controller = CodingUiController(session=session)
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/export /root/out.jsonl\r"),
        (0.03, ""),
        handle_prompt=_native_prompt_handler(
            app=playback.app,
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
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    session = SessionCommandPlaybackSession()
    controller = CodingUiController(session=session)
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/unknown keep me\r"),
        (0.03, ""),
        handle_prompt=_native_prompt_handler(
            app=playback.app,
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
    playback = NativeTuiLoopPlayback(width=100, height=18, model_label="moonshot/kimi-for-coding")
    session = SessionCommandPlaybackSession()
    controller = CodingUiController(session=session)
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/review check dispatch\r"),
        (0.04, "/debugging trace queue\r"),
        (0.08, ""),
        handle_prompt=_native_prompt_handler(
            app=playback.app,
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


COMMAND_ROUTING_SCENARIOS = (
    NativePlaybackScenarioSpec(
        name="local-command",
        description="Route a local command without echoing it as a prompt.",
        run=_run_local_command,
        tags=("command", "local"),
    ),
    NativePlaybackScenarioSpec(
        name="session-name-command",
        description="Dispatch /name through the native session command path without prompting the agent.",
        run=_run_session_name_command,
        tags=("command", "session"),
    ),
    NativePlaybackScenarioSpec(
        name="session-command-error",
        description="Render session command errors through the native command path without prompting the agent.",
        run=_run_session_command_error,
        tags=("command", "session"),
    ),
    NativePlaybackScenarioSpec(
        name="unknown-slash-prompt",
        description="Leave unknown slash-prefixed prompts on the agent prompt path.",
        run=_run_unknown_slash_prompt,
        tags=("command", "prompt"),
    ),
    NativePlaybackScenarioSpec(
        name="non-executable-session-command",
        description="Leave prompt and skill slash commands on the agent prompt path in native TUI.",
        run=_run_non_executable_session_command,
        tags=("command", "session", "prompt"),
    ),
)


__all__ = ["COMMAND_ROUTING_SCENARIOS"]

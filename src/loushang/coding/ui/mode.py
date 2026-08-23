from __future__ import annotations

import time
from functools import partial
from pathlib import Path
from typing import Any, TextIO

from loushang.coding.presentation.tui.plain import (
    PlainCodingUiRenderer,
)
from loushang.coding.ui.completion import coding_inline_completion_provider
from loushang.coding.ui.plain_app import build_plain_coding_tui_app
from loushang.coding.ui.product_binding import (
    build_coding_ui_controller,
    build_screen_coding_action_host,
)
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import CODING_SCREEN_RUN_PROFILE
from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
from loushang.coding.ui.startup import load_coding_tui_startup_view
from loushang.foundation.observability import get_log, log_context
from loushang.harness.diagnostics import observability_runtime
from loushang.harnesstui.conversation.agent_application import (
    AgentPlainConversationApplicationBinding,
    AgentScreenConversationApplicationBinding,
    current_agent_runtime_session,
    handle_agent_screen_approval,
)
from loushang.harnesstui.conversation.application_host import (
    run_prepared_plain_conversation,
    run_prepared_screen_conversation,
)
from loushang.harnesstui.conversation.host import (
    ConversationScreenRunProfile,
    run_action_host_conversation_screen,
)
from loushang.harnesstui.conversation.run_context import (
    RebindableEventSource,
    StableEmit,
)
from loushang.tui import CompletionProvider
from loushang.tui.launch import TuiLaunchProfile, run_tui_launch_shell
from loushang.tui.prompt import run_non_interactive_prompt_loop

log = get_log(__name__).bind(component="CodingUiMode")


async def run_coding_tui(
    *,
    runtime: Any,
    session: Any,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool = False,
    screen_run_profile: ConversationScreenRunProfile = CODING_SCREEN_RUN_PROFILE,
) -> int:
    return await run_tui_launch_shell(
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        profile=TuiLaunchProfile(
            run_screen=partial(
                _run_screen_interactive_tui,
                runtime=runtime,
                session=session,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                verbose=verbose,
                screen_run_profile=screen_run_profile,
            ),
            run_plain=partial(
                _run_plain_tui,
                runtime=runtime,
                session=session,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                verbose=verbose,
            ),
            error_prefix="■ Error: ",
        ),
        verbose=verbose,
    )


async def _run_screen_interactive_tui(
    *,
    runtime: Any,
    session: Any,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool,
    screen_run_profile: ConversationScreenRunProfile,
) -> int:
    snapshot = await load_coding_tui_startup_view(runtime=runtime, session=session)
    app = ScreenCodingTuiApp(
        model_label=snapshot.model_label,
        cwd=snapshot.cwd,
        branch=snapshot.branch,
        session_label=snapshot.session_label,
        now=time.monotonic,
    )
    completion_provider = await _load_completion_provider(
        session, base_path=Path(snapshot.cwd)
    )
    controller = build_coding_ui_controller(
        runtime=runtime,
        session=session,
        verbose=verbose,
    )
    action_host = build_screen_coding_action_host(
        presenter=app,
        controller=controller,
        stderr=stderr,
        verbose=verbose,
    )
    event_source = RebindableEventSource(session)

    def current_approval_interaction():
        return getattr(
            current_agent_runtime_session(runtime, session),
            "approval_interaction",
            None,
        )

    def build_surface(status_provider):
        return ScreenSurfaceManager(
            app=app,
            session=session,
            runtime=runtime,
            status_provider=status_provider,
            on_approval=lambda event: handle_agent_screen_approval(
                current_approval_interaction(),
                event,
            ),
            approval_interaction_provider=current_approval_interaction,
        )

    def report_rebind_problem(code: str, error: Exception) -> None:
        log.problem(
            f"coding_ui_{code}",
            source="tui",
            message=str(error) or error.__class__.__name__,
            recoverable=True,
            exc=error,
        )

    prepared = AgentScreenConversationApplicationBinding(
        session=session,
        app=app,
        action_host=action_host,
        build_surface=build_surface,
        startup=snapshot,
        interaction_context=log_context(
            session_id=snapshot.session_observability_id,
            cwd=snapshot.cwd,
            mode="tui",
        ),
        profile=screen_run_profile,
        trace=_trace,
        stdout=stdout,
        now=time.monotonic,
        completion_provider=completion_provider,
        resume_command_prefix=("loushang", "--resume"),
        session_provider=lambda: current_agent_runtime_session(runtime, session),
        get_operations=controller.get_operations,
        approval_interaction_provider=current_approval_interaction,
        event_source=event_source,
        runtime=runtime,
        completion_provider_loader=lambda next_session, cwd: (
            _load_completion_provider(next_session, base_path=Path(cwd))
        ),
        report_rebind_problem=report_rebind_problem,
    ).prepare()
    return await run_prepared_screen_conversation(
        prepared,
        stdin=stdin,
        stdout=stdout,
        screen_runner=run_action_host_conversation_screen,
    )


async def _run_plain_tui(
    *,
    runtime: Any,
    session: Any,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool,
) -> int:
    renderer = PlainCodingUiRenderer(stdout=stdout, stderr=stderr, verbose=verbose)
    snapshot = await load_coding_tui_startup_view(runtime=runtime, session=session)

    def build_app(event_renderer: Any, emit: StableEmit):
        return build_plain_coding_tui_app(
            runtime=runtime,
            session=session,
            renderer=renderer,
            event_renderer=event_renderer,
            stderr=stderr,
            verbose=verbose,
            cwd=snapshot.cwd,
            emit=emit,
            trace=_trace,
            now=time.monotonic,
            enable_debug=observability_runtime.enable_session_debug,
            disable_debug=observability_runtime.disable_session_debug,
        )

    prepared = AgentPlainConversationApplicationBinding(
        session=session,
        renderer=renderer,
        startup=snapshot,
        interaction_context=log_context(
            session_id=snapshot.session_observability_id,
            cwd=snapshot.cwd,
            mode="tui",
        ),
        build_app=build_app,
        trace=_trace,
    ).prepare()
    return await run_prepared_plain_conversation(
        prepared,
        stdin=stdin,
        stdout=stdout,
        prompt_runner=run_non_interactive_prompt_loop,
    )


def _trace(name: str, **data: Any) -> None:
    log.debug_event("tui", name, **data)


async def _load_completion_provider(session: Any, *, base_path: Path | None) -> Any:
    try:
        return await coding_inline_completion_provider(session, base_path=base_path)
    except Exception as error:
        log.problem(
            "coding_ui_completion_provider_failed",
            source="tui",
            message=str(error) or error.__class__.__name__,
            recoverable=True,
            exc=error,
        )
        return CompletionProvider(())

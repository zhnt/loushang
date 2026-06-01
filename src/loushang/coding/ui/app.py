from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

from loushang.coding.ui.abort import AbortHandler
from loushang.coding.ui.command_list import (
    CommandPaletteChooser,
    format_coding_commands,
    select_coding_command,
)
from loushang.coding.ui.controller import CodingUiController
from loushang.coding.ui.debug_command import DebugCommandHandler
from loushang.coding.ui.follow_up_queue import FollowUpQueueHandler
from loushang.coding.ui.handlers import (
    CodingTuiHandlers,
    InfoPanelPresenter,
    SettingsListPresenter,
)
from loushang.coding.ui.hotkeys import format_hotkeys
from loushang.coding.ui.lifecycle import RunLifecycle
from loushang.coding.ui.model_list import (
    ModelPaletteChooser,
    format_available_models,
    select_available_model,
)
from loushang.coding.ui.prompt_dispatch import PromptDispatchHandler
from loushang.coding.ui.prompt_result import PromptResultHandler
from loushang.coding.ui.renderer import CodingUiRenderer
from loushang.coding.ui.session_view import (
    is_running,
    session_error_message,
    session_label,
    thinking_level,
)
from loushang.coding.ui.status_provider import CodingTuiStatusProvider
from loushang.coding.ui.steer import SteerHandler
from loushang.tui import CompletionProvider


class TraceFn(Protocol):
    def __call__(self, name: str, **data: Any) -> None: ...


class StableEmit(Protocol):
    def __call__(self, write_callable: Callable[[], None], *, label: str) -> Awaitable[None]: ...


EnableDebug = Callable[..., Path]
DisableDebug = Callable[[], None]


@dataclass(frozen=True)
class CodingTuiApp:
    lifecycle: RunLifecycle
    handlers: CodingTuiHandlers
    status: Callable[[], str]
    status_visible: Callable[[], bool]
    completion_provider: CompletionProvider | None = None


def build_coding_tui_app(
    *,
    runtime: Any,
    session: Any,
    renderer: CodingUiRenderer,
    event_renderer: Any,
    stderr: TextIO,
    verbose: bool,
    model_label: str | None,
    cwd: str,
    branch: str | None,
    emit: StableEmit,
    trace: TraceFn,
    now: Callable[[], float],
    enable_debug: EnableDebug,
    disable_debug: DisableDebug,
    completion_provider: CompletionProvider | None = None,
    model_palette_chooser: ModelPaletteChooser | None = None,
    command_palette_chooser: CommandPaletteChooser | None = None,
    info_panel_presenter: InfoPanelPresenter | None = None,
    settings_list_presenter: SettingsListPresenter | None = None,
) -> CodingTuiApp:
    lifecycle = RunLifecycle()
    controller = CodingUiController(runtime=runtime, session=session, verbose=verbose)
    follow_up_queue = FollowUpQueueHandler(
        lifecycle=lifecycle,
        controller=controller,
        renderer=renderer,
        emit=emit,
        trace=trace,
    )
    steer_handler = SteerHandler(
        lifecycle=lifecycle,
        controller=controller,
        renderer=renderer,
        emit=emit,
        trace=trace,
    )
    abort_handler = AbortHandler(
        lifecycle=lifecycle,
        controller=controller,
        renderer=renderer,
        emit=emit,
        session_running=lambda: is_running(session),
        trace=trace,
    )
    debug_command = DebugCommandHandler(
        session=session,
        cwd=cwd,
        renderer=renderer,
        emit=emit,
        trace=trace,
        enable=enable_debug,
        disable=disable_debug,
    )
    prompt_dispatch = PromptDispatchHandler(
        lifecycle=lifecycle,
        controller=controller,
        session_running=lambda: is_running(session),
        now=now,
        trace=trace,
    )
    prompt_result = PromptResultHandler(
        lifecycle=lifecycle,
        renderer=renderer,
        emit=emit,
        stderr=stderr,
        verbose=verbose,
        last_error_message=lambda: event_renderer.last_error_message,
        session_error_message=lambda: session_error_message(session),
        now=now,
        trace=trace,
    )
    status_provider = CodingTuiStatusProvider(
        model_label=model_label,
        cwd=cwd,
        branch=branch,
        session_label=lambda: session_label(session),
        thinking_level=lambda: thinking_level(session),
        running=lambda: lifecycle.visible_running(session_running=is_running(session)),
    )
    handlers = CodingTuiHandlers(
        lifecycle=lifecycle,
        follow_up=follow_up_queue.queue,
        steer=steer_handler.steer,
        debug=debug_command.handle,
        dispatch=prompt_dispatch.dispatch,
        result=prompt_result.handle,
        abort=abort_handler.abort,
        session=session,
        emit=emit,
        render_status=renderer.render_status,
        render_info_panel=getattr(renderer, "render_info_panel", None),
        present_info_panel=info_panel_presenter,
        status=status_provider.render,
        model_select=lambda query: select_available_model(session, query=query, choose=model_palette_chooser),
        models=lambda query: format_available_models(session, query=query),
        command_select=lambda query: select_coding_command(session, query=query, choose=command_palette_chooser),
        commands=lambda query: format_coding_commands(session, query=query),
        hotkeys=format_hotkeys,
        settings=status_provider.settings_text,
        settings_list=status_provider.settings_list,
        apply_settings=status_provider.apply_settings,
        present_settings_list=settings_list_presenter,
        statusline=status_provider.set_visible,
        now=now,
        session_running=lambda: is_running(session),
        trace=trace,
    )
    return CodingTuiApp(
        lifecycle=lifecycle,
        handlers=handlers,
        status=status_provider.render,
        status_visible=status_provider.is_visible,
        completion_provider=completion_provider,
    )


__all__ = ["CodingTuiApp", "build_coding_tui_app"]

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from loushang.coding.diagnostics.debug_status import debug_status_text
from loushang.coding.model_selection_tui import select_available_model
from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
from loushang.coding.ui.hotkeys import format_hotkeys
from loushang.coding.ui.product_binding import (
    build_coding_ui_controller,
)
from loushang.harness.events.recording_policy import is_cancelled_error_message
from loushang.harnesstui.commands.interaction import CommandPaletteChooser
from loushang.harnesstui.conversation.agent_plain_app import (
    build_agent_plain_conversation_app,
    build_agent_plain_conversation_ports,
)
from loushang.harnesstui.conversation.info import InfoPanelPresenter
from loushang.harnesstui.conversation.plain_app import PlainConversationApp
from loushang.harnesstui.conversation.run_context import StableEmit, TraceFn
from loushang.harnesstui.selection.interaction import ModelInteractionChooser
from loushang.tui import CompletionProvider


def build_plain_coding_tui_app(
    *,
    runtime: Any,
    session: Any,
    renderer: PlainCodingUiRenderer,
    event_renderer: Any,
    stderr: TextIO,
    verbose: bool,
    cwd: str,
    emit: StableEmit,
    trace: TraceFn,
    now: Callable[[], float],
    enable_debug: Callable[..., Path],
    disable_debug: Callable[[], None],
    completion_provider: CompletionProvider | None = None,
    model_palette_chooser: ModelInteractionChooser | None = None,
    command_palette_chooser: CommandPaletteChooser | None = None,
    info_panel_presenter: InfoPanelPresenter | None = None,
) -> PlainConversationApp:
    """Bind Coding content to the standard Agent plain conversation app."""

    controller = build_coding_ui_controller(
        runtime=runtime,
        session=session,
        verbose=verbose,
    )

    def current_hotkeys() -> str:
        settings_manager = getattr(session, "settings_manager", None)
        get_keybindings = getattr(settings_manager, "get_keybindings", None)
        return format_hotkeys(get_keybindings() if callable(get_keybindings) else None)

    return build_agent_plain_conversation_app(
        ports=build_agent_plain_conversation_ports(
            session=session,
            renderer=renderer,
            event_renderer=event_renderer,
            stderr=stderr,
            verbose=verbose,
            emit=emit,
            trace=trace,
            now=now,
            controller=controller,
            get_operations=controller.get_operations,
            select_model=lambda query, chooser: select_available_model(
                session,
                query=query,
                choose=chooser,
            ),
            hotkeys=current_hotkeys,
            debug_status=lambda debug_path, scopes: debug_status_text(
                debug_path,
                scopes=scopes,
                cwd=cwd,
            ),
            enable_debug=enable_debug,
            disable_debug=disable_debug,
            suppress_cancelled_error=is_cancelled_error_message,
            completion_provider=completion_provider,
            model_palette_chooser=model_palette_chooser,
            command_palette_chooser=command_palette_chooser,
            info_panel_presenter=info_panel_presenter,
        )
    )

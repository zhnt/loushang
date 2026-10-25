"""Native Coding selector for model-specific reasoning levels."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from loushang.coding.model_reasoning import (
    effective_reasoning_label,
    reasoning_choice_label,
    reasoning_choices,
    reasoning_description,
    select_reasoning_level,
)
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.surface.factory import command_surface_view
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import SelectItem


def build_reasoning_selector(session: object) -> ScreenSurfaceView | None:
    levels = reasoning_choices(session)
    if len(levels) <= 1:
        return None
    view = command_surface_view(
        title="Select Reasoning",
        purpose="reasoning",
        items=(
            SelectItem(
                label=reasoning_choice_label(level),
                value=level,
                description=reasoning_description(session, level),
            )
            for level in levels
        ),
        subtitle="Choose a reasoning level for this session",
        footer="Enter to select · Esc to keep current",
        presentation="bottom-exclusive",
    )
    current = getattr(session, "thinking_level", None)
    if current in levels:
        view.content.selected_index = levels.index(current)
    return view


def bind_reasoning_selection(
    app: ScreenConversationApp,
    current_session: Callable[[], object],
) -> tuple[
    Callable[[], ScreenSurfaceView | None],
    Callable[[str], Awaitable[str]],
]:
    app.reasoning_label_provider = lambda: effective_reasoning_label(current_session())
    return (
        lambda: build_reasoning_selector(current_session()),
        lambda level: select_reasoning_level(current_session(), level),
    )


__all__ = ["bind_reasoning_selection", "build_reasoning_selector"]

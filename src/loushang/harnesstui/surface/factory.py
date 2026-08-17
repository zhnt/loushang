from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from loushang.harnesstui.commands.presentation import (
    command_palette,
    command_palette_select_items,
)
from loushang.harnesstui.selection.model import (
    MODEL_SELECTOR_THEME,
    ModelSelectorSurface,
)
from loushang.harnesstui.surface.view import (
    ScreenSurfacePresentation,
    ScreenSurfaceView,
)
from loushang.tui import (
    CommandPalette,
    CommandSurface,
    InfoPanel,
    SelectItem,
    ThemeResolver,
)


def info_surface_view(
    *,
    title: str,
    text: str,
    subtitle: str = "",
    footer: str = "Enter/Esc to close",
    presentation: ScreenSurfacePresentation = "bottom",
    preferred_height: int | None = None,
    panel_title: str | None = None,
    panel_footer: str = "",
) -> ScreenSurfaceView:
    """Build a reusable information surface from presentation-ready text."""

    content = InfoPanel.from_text(
        title=title if panel_title is None else panel_title,
        text=text,
        footer=panel_footer,
    )
    return ScreenSurfaceView(
        title=title,
        purpose="info",
        content=content,
        footer=footer,
        subtitle=subtitle,
        presentation=presentation,
        preferred_height=preferred_height,
    )


def command_surface_view(
    *,
    title: str,
    purpose: Literal["model", "command"],
    items: Iterable[SelectItem],
    subtitle: str = "",
    footer: str = "Enter to select - Esc to close",
    presentation: ScreenSurfacePresentation = "bottom",
    preferred_height: int | None = None,
    query: str = "",
    max_visible: int = 8,
) -> ScreenSurfaceView:
    """Build a searchable command-style surface over neutral selection items."""

    content = CommandSurface(
        list(items),
        query=query,
        max_visible=max_visible,
    )
    return ScreenSurfaceView(
        title=title,
        purpose=purpose,
        content=content,
        footer=footer,
        subtitle=subtitle,
        presentation=presentation,
        preferred_height=preferred_height,
    )


def command_palette_surface_view(
    palette: CommandPalette,
    *,
    purpose: Literal["model", "command"] = "command",
    title: str | None = None,
    subtitle: str = "",
    footer: str = "Enter to select - Esc to close",
    presentation: ScreenSurfacePresentation = "bottom",
    preferred_height: int | None = None,
    query: str = "",
    max_visible: int = 8,
) -> ScreenSurfaceView:
    """Present a prepared command palette as a framed selection surface."""

    return command_surface_view(
        title=palette.title if title is None else title,
        purpose=purpose,
        items=command_palette_select_items(palette),
        subtitle=subtitle,
        footer=footer,
        presentation=presentation,
        preferred_height=preferred_height,
        query=query,
        max_visible=max_visible,
    )


def command_catalog_surface_view(
    catalog: object,
    *,
    title: str = "Commands",
    purpose: Literal["model", "command"] = "command",
    subtitle: str = "",
    footer: str = "Enter to select - Esc to close",
    presentation: ScreenSurfacePresentation = "bottom",
    max_visible: int = 8,
) -> ScreenSurfaceView:
    """Build a command selection surface from a structural catalog."""

    commands = getattr(catalog, "commands", None)
    items = commands() if callable(commands) else ()
    return command_palette_surface_view(
        command_palette(items, title=title),
        title=title,
        purpose=purpose,
        subtitle=subtitle,
        footer=footer,
        presentation=presentation,
        max_visible=max_visible,
    )


def model_selector_surface_view(
    *,
    all_items: Iterable[SelectItem],
    scoped_items: Iterable[SelectItem] = (),
    selected_value: str | None = None,
    title: str = "Select Model",
    subtitle: str = "",
    footer: str = "Enter to select - Esc to close",
    presentation: ScreenSurfacePresentation = "bottom",
    preferred_height: int | None = None,
    max_visible: int = 10,
    theme: ThemeResolver | None = None,
) -> ScreenSurfaceView:
    """Present prepared, product-neutral model items in the shared selector."""

    resolved_theme = theme if theme is not None else MODEL_SELECTOR_THEME
    content = ModelSelectorSurface(
        all_items=tuple(all_items),
        scoped_items=tuple(scoped_items),
        selected_value=selected_value,
        max_visible=max_visible,
        theme=resolved_theme,
    )
    return ScreenSurfaceView(
        title=title,
        purpose="model",
        content=content,
        footer=footer,
        subtitle=subtitle,
        presentation=presentation,
        preferred_height=preferred_height,
        theme=resolved_theme,
        feedback_theme_token="model_selector.error",
        feedback_hint_theme_token="model_selector.recovery",
    )


__all__ = [
    "command_catalog_surface_view",
    "command_palette_surface_view",
    "command_surface_view",
    "info_surface_view",
    "model_selector_surface_view",
]

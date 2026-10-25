"""Coding persistence binding for the shared model-selection interaction."""

from __future__ import annotations

import inspect
from collections.abc import Callable

from loushang.coding.model_reasoning import (
    reasoning_choices,
    reasoning_description,
    select_reasoning_level,
)
from loushang.coding.model_selection import (
    apply_model_selection,
    persistence_warning_message,
)
from loushang.harnesstui.selection.binding import select_session_model
from loushang.harnesstui.selection.interaction import (
    ModelInteractionChooser as ModelPaletteChooser,
)
from loushang.tui import CommandPalette, CommandPaletteItem

_REASONING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh"}


async def select_available_model(
    session: object,
    *,
    query: str = "",
    choose: ModelPaletteChooser | None = None,
    settings_manager: object | None = None,
    on_model_changed: Callable[[], None] | None = None,
) -> str:
    model_query, separator, possible_level = query.strip().rpartition(" ")
    requested_level = (
        possible_level
        if separator and possible_level in _REASONING_LEVELS
        else None
    )
    if requested_level is not None:
        query = model_query

    async def apply(selection: object) -> object:
        return await apply_model_selection(
            session,
            selection,
            settings_manager=settings_manager,
        )

    label = await select_session_model(
        session,
        apply_selection=apply,
        query=query,
        choose=choose,
        persistence_warning=persistence_warning_message,
    )
    if on_model_changed is not None:
        on_model_changed()
    if not label.startswith("Model set:"):
        return label
    levels = reasoning_choices(session)
    if requested_level is not None:
        return f"{label} · {await select_reasoning_level(session, requested_level)}"
    if choose is None or len(levels) <= 1:
        return label
    palette = CommandPalette(
        title="Select Reasoning",
        items=tuple(
            CommandPaletteItem(
                value=level,
                label=level,
                description=reasoning_description(session, level),
            )
            for level in levels
        ),
    )
    selected = choose(palette)
    if inspect.isawaitable(selected):
        selected = await selected
    if selected is None:
        return f"{label} · Reasoning unchanged"
    if selected not in levels:
        raise ValueError(f"Unsupported reasoning level: {selected}")
    return f"{label} · {await select_reasoning_level(session, selected)}"


__all__ = ["ModelPaletteChooser", "select_available_model"]

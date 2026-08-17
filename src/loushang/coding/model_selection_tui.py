"""Coding persistence binding for the shared model-selection interaction."""

from __future__ import annotations

from loushang.coding.model_selection import (
    apply_model_selection,
    persistence_warning_message,
)
from loushang.harnesstui.selection.binding import select_session_model
from loushang.harnesstui.selection.interaction import (
    ModelInteractionChooser as ModelPaletteChooser,
)


async def select_available_model(
    session: object,
    *,
    query: str = "",
    choose: ModelPaletteChooser | None = None,
    settings_manager: object | None = None,
) -> str:
    async def apply(selection: object) -> object:
        return await apply_model_selection(
            session,
            selection,
            settings_manager=settings_manager,
        )

    return await select_session_model(
        session,
        apply_selection=apply,
        query=query,
        choose=choose,
        persistence_warning=persistence_warning_message,
    )


__all__ = ["ModelPaletteChooser", "select_available_model"]

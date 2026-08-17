from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from loushang.harnesstui.selection.catalog import (
    ModelChoice,
    current_model_choice_first,
    matching_model_choices,
    model_palette,
)
from loushang.tui import CommandPalette

ModelInteractionChooser = Callable[[CommandPalette], Awaitable[str | None] | str | None]
ModelInteractionKind = Literal["list", "selected", "empty", "ambiguous", "cancelled"]


@dataclass(frozen=True, slots=True)
class ModelInteractionPresentationCopy:
    """Product wording and list projection for a model resolution."""

    list_items: Callable[[tuple[ModelChoice, ...], str | None], str]
    item_text: Callable[[ModelChoice], str]
    cancelled: str
    empty: str
    no_match: Callable[[str], str]
    ambiguous_title: str
    ambiguous_hint: Callable[[tuple[ModelChoice, ...]], str]


@dataclass(frozen=True, slots=True)
class ModelInteractionSnapshot:
    """Product-neutral model choices captured for one interaction."""

    choices: tuple[ModelChoice, ...]
    current_value: str | None = None
    title: str = "Models"


@dataclass(frozen=True, slots=True)
class ModelInteractionResult:
    """A model-selection resolution without applying the selected model."""

    kind: ModelInteractionKind
    query: str = ""
    choice: ModelChoice | None = None
    matches: tuple[ModelChoice, ...] = ()
    palette: CommandPalette | None = None


def resolve_model_interaction(
    snapshot: ModelInteractionSnapshot,
    *,
    query: str = "",
) -> ModelInteractionResult:
    """Resolve a query against a stable model-choice snapshot."""

    stripped_query = query.strip()
    choices = tuple(
        current_model_choice_first(
            snapshot.choices,
            current_value=snapshot.current_value,
        )
    )
    palette = model_palette(
        choices,
        current_value=snapshot.current_value,
        title=snapshot.title,
    )
    if not choices:
        return ModelInteractionResult(
            kind="empty",
            query=stripped_query,
            palette=palette,
        )
    if not stripped_query:
        return ModelInteractionResult(
            kind="list",
            matches=choices,
            palette=palette,
        )

    matches = tuple(matching_model_choices(choices, stripped_query))
    if not matches:
        return ModelInteractionResult(
            kind="empty",
            query=stripped_query,
            palette=palette,
        )
    if len(matches) > 1:
        return ModelInteractionResult(
            kind="ambiguous",
            query=stripped_query,
            matches=matches,
            palette=palette,
        )
    return ModelInteractionResult(
        kind="selected",
        query=stripped_query,
        choice=matches[0],
        matches=matches,
        palette=palette,
    )


async def run_model_interaction(
    snapshot: ModelInteractionSnapshot,
    *,
    query: str = "",
    choose: ModelInteractionChooser | None = None,
) -> ModelInteractionResult:
    """Optionally choose from a palette, then resolve without side effects."""

    resolution = resolve_model_interaction(snapshot, query=query)
    if query.strip() or choose is None:
        return resolution

    assert resolution.palette is not None
    selected = choose(resolution.palette)
    if inspect.isawaitable(selected):
        selected = await selected
    if selected is None:
        return ModelInteractionResult(
            kind="cancelled",
            matches=resolution.matches,
            palette=resolution.palette,
        )
    return resolve_model_interaction(snapshot, query=selected)


def present_model_interaction(
    result: ModelInteractionResult,
    *,
    current_value: str | None,
    copy: ModelInteractionPresentationCopy,
) -> str | None:
    """Present non-selected outcomes while leaving model application to Product."""

    if result.kind == "selected":
        return None
    if result.kind == "list":
        return copy.list_items(result.matches, current_value)
    if result.kind == "cancelled":
        return copy.cancelled
    if result.kind == "empty":
        return copy.no_match(result.query) if result.query else copy.empty
    return "\n".join(
        (
            copy.ambiguous_title,
            *(f"  {copy.item_text(choice)}" for choice in result.matches),
            copy.ambiguous_hint(result.matches),
        )
    )


__all__ = [
    "ModelInteractionChooser",
    "ModelInteractionKind",
    "ModelInteractionPresentationCopy",
    "ModelInteractionResult",
    "ModelInteractionSnapshot",
    "present_model_interaction",
    "resolve_model_interaction",
    "run_model_interaction",
]

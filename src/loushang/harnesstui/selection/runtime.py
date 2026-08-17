"""Product-neutral model-selection interaction runtime.

The runtime owns the interaction flow only.  Products provide a typed view
port that supplies normalized choices and applies the selected value.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

from loushang.harnesstui.selection.catalog import (
    ModelChoice,
    filter_model_choices,
    format_model_choices,
    model_choice_display_label,
    model_completion_provider,
)
from loushang.harnesstui.selection.interaction import (
    ModelInteractionChooser,
    ModelInteractionPresentationCopy,
    ModelInteractionSnapshot,
    present_model_interaction,
    run_model_interaction,
)
from loushang.tui import CompletionProvider

ModelValue = object
ModelApplyResult = object
ModelChoices = Sequence[ModelChoice] | Awaitable[Sequence[ModelChoice]]
ModelCurrentValue = str | None | Awaitable[str | None]
PersistenceWarning = Callable[[ModelApplyResult], str | None]
T = TypeVar("T")


class ModelSelectionViewPort(Protocol):
    """Explicit product binding for model-selection UI."""

    def available_choices(self) -> ModelChoices: ...

    def current_value(self, choices: Sequence[ModelChoice]) -> ModelCurrentValue: ...

    def apply_selection(self, selection: ModelValue) -> ModelApplyResult | Awaitable[ModelApplyResult]: ...


def _ambiguous_model_hint(matches: tuple[ModelChoice, ...]) -> str:
    if any(choice.endpoint_id for choice in matches):
        return "Use /model <provider:endpoint:model> or choose one from the model list."
    return "Use /model <full model> to select one."


STANDARD_MODEL_INTERACTION_COPY = ModelInteractionPresentationCopy(
    list_items=lambda choices, current: format_model_choices(
        choices,
        current_value=current,
    ),
    item_text=model_choice_display_label,
    cancelled="Model selection cancelled.",
    empty="No models available.",
    no_match=lambda query: f"No models match: {query}",
    ambiguous_title="Multiple models match:",
    ambiguous_hint=_ambiguous_model_hint,
)


async def format_available_models(
    port: ModelSelectionViewPort,
    *,
    query: str = "",
) -> str:
    choices = tuple(await _maybe_await(port.available_choices()))
    stripped_query = query.strip()
    if stripped_query:
        choices = tuple(filter_model_choices(choices, stripped_query))
    current_value = await _maybe_await(port.current_value(choices))
    return format_model_choices(choices, query=query, current_value=current_value)


async def available_model_completion_provider(
    port: ModelSelectionViewPort,
) -> CompletionProvider:
    choices = tuple(await _maybe_await(port.available_choices()))
    current_value = await _maybe_await(port.current_value(choices))
    return model_completion_provider(choices, current_value=current_value)


async def select_available_model(
    port: ModelSelectionViewPort,
    *,
    query: str = "",
    choose: ModelInteractionChooser | None = None,
    persistence_warning: PersistenceWarning | None = None,
    copy: ModelInteractionPresentationCopy = STANDARD_MODEL_INTERACTION_COPY,
) -> str:
    choices = tuple(await _maybe_await(port.available_choices()))
    current_value = await _maybe_await(port.current_value(choices))
    resolution = await run_model_interaction(
        ModelInteractionSnapshot(choices=choices, current_value=current_value),
        query=query,
        choose=choose,
    )
    presentation = present_model_interaction(
        resolution,
        current_value=current_value,
        copy=copy,
    )
    if presentation is not None:
        return presentation

    assert resolution.choice is not None
    try:
        result = await _maybe_await(port.apply_selection(resolution.choice.selection))
    except RuntimeError as error:
        if str(error) == "Model selection is not available.":
            return "Model selection is not available."
        raise
    message = f"Model set: {model_choice_display_label(resolution.choice)}"
    if persistence_warning is not None:
        warning = persistence_warning(result)
        if warning:
            return f"{message}, but {warning}"
    return message


async def _maybe_await(value: T | Awaitable[T]) -> T:
    return await value if inspect.isawaitable(value) else value


__all__ = [
    "ModelSelectionViewPort",
    "STANDARD_MODEL_INTERACTION_COPY",
    "available_model_completion_provider",
    "format_available_models",
    "select_available_model",
]

"""Harness model-data binding for terminal selection models."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass

from loushang.harness.session.model_selection import (
    ModelChoiceData,
    get_session_model_identity,
    iter_available_model_details,
    iter_available_model_selections,
    iter_scoped_model_selections,
    model_choice_data_from_details,
    model_choice_data_from_selections,
    model_identity_data,
)
from loushang.harnesstui.selection.catalog import (
    ModelChoice,
    ModelChoiceIdentity,
    merge_model_choice_sources,
    model_choice_descriptions_by_label,
    model_choice_select_items,
    model_label_select_items,
    resolve_current_model_choice_value,
)
from loushang.harnesstui.selection.interaction import ModelInteractionChooser
from loushang.harnesstui.selection.runtime import (
    PersistenceWarning,
    available_model_completion_provider,
    format_available_models,
    select_available_model,
)
from loushang.harnesstui.surface.factory import model_selector_surface_view
from loushang.harnesstui.surface.view import (
    ScreenSurfacePresentation,
    ScreenSurfaceView,
)
from loushang.tui import CompletionProvider

ApplyModelSelection = Callable[
    [object],
    object | Awaitable[object],
]


@dataclass(frozen=True, slots=True)
class SessionModelSelectorSurfaceProfile:
    """Product copy and sizing for the shared session model selector."""

    title: str = "Select Model"
    subtitle: str = ""
    footer: str = "Enter to select - Esc to close"
    presentation: ScreenSurfacePresentation = "bottom"
    max_visible: int = 10


def model_identity_from_value(selection: object | None) -> ModelChoiceIdentity:
    data = model_identity_data(selection)
    return ModelChoiceIdentity(label=data.label, value=data.value)


def model_choices_from_details(details: Iterable[object]) -> list[ModelChoice]:
    return _model_choices_from_data(model_choice_data_from_details(details))


async def available_session_model_choices(session: object) -> list[ModelChoice]:
    identity = await get_session_model_identity(session)
    detail_choices = model_choices_from_details(
        await iter_available_model_details(session)
    )
    selection_choices = _model_choices_from_data(
        model_choice_data_from_selections(
            await iter_available_model_selections(session)
        )
    )
    return merge_model_choice_sources(
        detail_choices,
        selection_choices,
        current_identity=ModelChoiceIdentity(
            label=identity.label,
            value=identity.value,
        ),
    )


async def current_session_model_choice_value(
    session: object,
    *,
    choices: Sequence[ModelChoice] | None = None,
) -> str | None:
    model_choices = (
        choices
        if choices is not None
        else await available_session_model_choices(session)
    )
    identity = await get_session_model_identity(session)
    return resolve_current_model_choice_value(
        model_choices,
        ModelChoiceIdentity(label=identity.label, value=identity.value),
    )


async def build_session_model_selector_surface(
    session: object,
    *,
    profile: SessionModelSelectorSurfaceProfile = (
        SessionModelSelectorSurfaceProfile()
    ),
) -> ScreenSurfaceView:
    """Build the standard model selector for any compatible Product session."""

    identity = await get_session_model_identity(session)
    choices = await available_session_model_choices(session)
    current_value = await current_session_model_choice_value(session, choices=choices)
    scoped_labels = [
        label
        for selection in await iter_scoped_model_selections(session)
        if (label := model_identity_from_value(selection).label)
    ]
    descriptions = model_choice_descriptions_by_label(choices)
    return model_selector_surface_view(
        all_items=model_choice_select_items(
            choices,
            current_value=current_value,
        ),
        scoped_items=model_label_select_items(
            scoped_labels,
            current_label=identity.label,
            descriptions=descriptions,
        ),
        selected_value=current_value or identity.label,
        title=profile.title,
        subtitle=profile.subtitle,
        footer=profile.footer,
        presentation=profile.presentation,
        max_visible=profile.max_visible,
    )


class SessionModelSelectionViewPort:
    """Bind a standard Product session to the shared selection runtime."""

    def __init__(
        self,
        session: object,
        *,
        apply_selection: ApplyModelSelection | None = None,
    ) -> None:
        self._session = session
        self._apply_selection = apply_selection

    async def available_choices(self) -> list[ModelChoice]:
        return await available_session_model_choices(self._session)

    async def current_value(self, choices: Sequence[ModelChoice]) -> str | None:
        return await current_session_model_choice_value(
            self._session,
            choices=choices,
        )

    async def apply_selection(self, selection: object) -> object:
        if self._apply_selection is None:
            raise RuntimeError("Model selection is not available.")
        result = self._apply_selection(selection)
        return await result if inspect.isawaitable(result) else result


async def format_available_session_models(
    session: object,
    *,
    query: str = "",
) -> str:
    return await format_available_models(
        SessionModelSelectionViewPort(session),
        query=query,
    )


async def available_session_model_completion_provider(
    session: object,
) -> CompletionProvider:
    return await available_model_completion_provider(
        SessionModelSelectionViewPort(session)
    )


async def select_session_model(
    session: object,
    *,
    apply_selection: ApplyModelSelection,
    query: str = "",
    choose: ModelInteractionChooser | None = None,
    persistence_warning: PersistenceWarning | None = None,
) -> str:
    return await select_available_model(
        SessionModelSelectionViewPort(
            session,
            apply_selection=apply_selection,
        ),
        query=query,
        choose=choose,
        persistence_warning=persistence_warning,
    )


def _model_choices_from_data(
    values: Iterable[ModelChoiceData],
) -> list[ModelChoice]:
    return [
        ModelChoice(
            label=data.label,
            value=data.value,
            selection=data.selection,
            endpoint_id=data.endpoint_id,
            region=data.region,
            lane=data.lane,
            api=data.api,
            preferred_endpoint=data.preferred_endpoint,
            description=data.description,
        )
        for data in values
    ]


__all__ = [
    "ApplyModelSelection",
    "SessionModelSelectionViewPort",
    "SessionModelSelectorSurfaceProfile",
    "available_session_model_completion_provider",
    "available_session_model_choices",
    "build_session_model_selector_surface",
    "current_session_model_choice_value",
    "format_available_session_models",
    "model_choices_from_details",
    "model_identity_from_value",
    "select_session_model",
]

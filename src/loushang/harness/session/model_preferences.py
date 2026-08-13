"""Product-neutral preferred-model candidate selection helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from loushang.ai.model import ModelSelection, normalize_model_selection
from loushang.harness.session.model_selection import (
    iter_available_model_details,
    iter_available_model_selections,
)


@dataclass(frozen=True)
class PreferredModel:
    """A stable model identity a Product may use for candidate ordering."""

    provider: str
    endpoint_id: str | None
    model_id: str


async def preferred_model_candidates(
    session: object,
    preferred_models: Sequence[PreferredModel],
) -> list[object]:
    """Return preferred available details, then preferred/model selections."""

    details = await available_model_details(session)
    preferred_details = preferred_model_details(details, preferred_models)
    if preferred_details:
        return preferred_details
    selections = await iter_available_model_selections(session)
    preferred_selection = preferred_model_selection(selections, preferred_models)
    if preferred_selection is not None:
        return [preferred_selection]
    candidates: list[object] = list(selections)
    return candidates


async def available_model_details(session: object) -> list[object]:
    """Compatibility name for the canonical session detail iterator."""

    return await iter_available_model_details(session)


def preferred_model_details(
    details: Iterable[object],
    preferred_models: Sequence[PreferredModel],
) -> list[object]:
    values = list(details)
    matches: list[object] = []
    for preferred in preferred_models:
        candidates = [
            detail
            for detail in values
            if _matches_preferred_model_detail(detail, preferred)
        ]
        if len(candidates) == 1:
            matches.append(candidates[0])
    return matches


def preferred_model_selection(
    selections: Iterable[ModelSelection],
    preferred_models: Sequence[PreferredModel],
) -> ModelSelection | None:
    values = list(selections)
    for preferred in preferred_models:
        if preferred.endpoint_id is not None:
            for selection in values:
                normalized = normalize_model_selection(selection)
                if normalized == _preferred_selection(preferred):
                    return selection
            continue
        candidates = [
            selection
            for selection in values
            if (normalized := normalize_model_selection(selection)) is not None
            and (normalized.provider, normalized.model_id)
            == (preferred.provider, preferred.model_id)
        ]
        if len(candidates) == 1:
            return candidates[0]
    return None


def persistence_warning_message(result: object) -> str | None:
    """Format a non-fatal default-model persistence failure."""

    error = getattr(result, "persistence_error", None)
    if error is None:
        return None
    message = str(error).strip() or error.__class__.__name__
    return f"saving the default failed: {message}"


def _matches_preferred_model_detail(
    detail: object,
    preferred: PreferredModel,
) -> bool:
    normalized = normalize_model_selection(detail)
    if normalized is None:
        return False
    if preferred.endpoint_id is not None:
        return normalized == _preferred_selection(preferred)
    return (normalized.provider, normalized.model_id) == (
        preferred.provider,
        preferred.model_id,
    )


def _preferred_selection(preferred: PreferredModel) -> ModelSelection:
    if preferred.endpoint_id is None:
        raise ValueError("preferred model selection requires endpoint_id")
    return ModelSelection(
        provider=preferred.provider,
        endpoint_id=preferred.endpoint_id,
        model_id=preferred.model_id,
    )


__all__ = [
    "PreferredModel",
    "available_model_details",
    "preferred_model_candidates",
    "preferred_model_details",
    "preferred_model_selection",
    "persistence_warning_message",
]

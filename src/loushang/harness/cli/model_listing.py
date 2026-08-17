"""Shared CLI model catalog selection and output projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from loushang.harness.session.model_selection import (
    model_listing_getter,
    model_listing_matches_query,
    normalize_model_listing,
    unique_sorted_model_entries,
)


class ModelListingError(RuntimeError):
    """Raised when a bound session cannot provide model candidates."""


@dataclass(frozen=True, slots=True)
class ModelListingRequest:
    query: str = ""


@dataclass(frozen=True, slots=True)
class ModelListingResult:
    entries: tuple[Mapping[str, object], ...]
    includes_metadata: bool


def list_model_entries(
    session: object,
    request: ModelListingRequest = ModelListingRequest(),
) -> ModelListingResult:
    """Read, deduplicate and filter model entries through an injected session."""

    getter, include_metadata = model_listing_getter(session)
    if getter is None:
        raise ModelListingError("model registry is not available.")
    try:
        models = getter()
    except Exception as error:
        raise ModelListingError(str(error)) from error
    if not isinstance(models, list):
        raise ModelListingError("model listing returned an invalid response.")
    entries = normalize_model_listing(
        unique_sorted_model_entries(models),
        include_metadata=include_metadata,
    )
    if request.query:
        entries = [
            entry
            for entry in entries
            if model_listing_matches_query(entry, request.query)
        ]
    return ModelListingResult(tuple(entries), include_metadata)


__all__ = [
    "ModelListingError",
    "ModelListingRequest",
    "ModelListingResult",
    "list_model_entries",
]

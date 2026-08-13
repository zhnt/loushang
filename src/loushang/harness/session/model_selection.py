"""Optional AI-backed model selection operations for product sessions."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from loushang.ai.model import (
    ModelSelection,
    is_usable_model_selection,
    model_selection_ref,
    normalize_model_selection,
)

ModelCandidates = Callable[[object], Iterable[object] | Awaitable[Iterable[object]]]
PersistModelSelection = Callable[[ModelSelection], object]


@dataclass(frozen=True)
class ModelSelectionApplyResult:
    selection: ModelSelection
    persisted: bool = False
    persistence_error: Exception | None = None


@dataclass(frozen=True)
class ModelIdentityData:
    """Neutral model identity for a presentation or settings adapter."""

    label: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class ModelChoiceData:
    """Neutral model detail projected without a TUI dependency."""

    label: str
    value: str
    selection: object
    endpoint_id: str
    region: str = ""
    lane: str = ""
    api: str = ""
    preferred_endpoint: bool = False
    description: str = ""


def model_identity_data(selection: object | None) -> ModelIdentityData:
    normalized = normalize_model_selection(selection)
    if normalized is None:
        return ModelIdentityData()
    label = _model_label(normalized)
    value = model_selection_ref(normalized)
    return ModelIdentityData(label=label, value=value)


def model_choice_data_from_details(
    details: Iterable[object],
) -> list[ModelChoiceData]:
    choices: list[ModelChoiceData] = []
    seen: set[str] = set()
    for detail in details:
        normalized = normalize_model_selection(detail)
        if normalized is None:
            continue
        label = _model_label(normalized)
        value = model_selection_ref(normalized)
        if value in seen:
            continue
        seen.add(value)
        choices.append(
            ModelChoiceData(
                label=label,
                value=value,
                selection=detail,
                endpoint_id=normalized.endpoint_id,
                region=_detail_string(detail, "region"),
                lane=_detail_string(detail, "lane"),
                api=_detail_string(detail, "api"),
                preferred_endpoint=_detail_bool(
                    detail, "preferred_endpoint", "preferredEndpoint", "preferred"
                ),
                description=_detail_string(detail, "name", "family", "alias"),
            )
        )
    return choices


def model_choice_data_from_selections(
    selections: Iterable[object],
) -> list[ModelChoiceData]:
    """Project normalized fallback selections without endpoint presentation data."""

    choices: list[ModelChoiceData] = []
    seen: set[str] = set()
    for selection in selections:
        normalized = normalize_model_selection(selection)
        if normalized is None:
            continue
        label = _model_label(normalized)
        if label in seen:
            continue
        seen.add(label)
        choices.append(
            ModelChoiceData(
                label=label,
                value=model_selection_ref(normalized),
                selection=selection,
                endpoint_id=normalized.endpoint_id,
            )
        )
    return choices


def _detail_string(value: object, *names: str) -> str:
    for name in names:
        field = _detail_field(value, name)
        if isinstance(field, str) and field.strip():
            return field.strip()
    return ""


def _detail_bool(value: object, *names: str) -> bool:
    return any(_detail_field(value, name) is True for name in names)


def _detail_field(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name)
    try:
        return getattr(value, name, None)
    except Exception:
        return None


async def apply_session_model_selection(
    session: object,
    selection: object,
    *,
    persist: PersistModelSelection | None = None,
) -> ModelSelectionApplyResult:
    """Apply a model on a bound session and optionally persist its selection."""

    normalized = normalize_model_selection(selection)
    if normalized is None:
        raise ValueError("Model selection requires provider, endpoint, and model ids.")
    setter = getattr(session, "set_model", None)
    if not callable(setter):
        raise RuntimeError("Model selection is not available.")
    await _maybe_await(setter(normalized))
    if persist is None:
        return ModelSelectionApplyResult(selection=normalized)
    try:
        await _maybe_await(persist(normalized))
    except Exception as error:
        return ModelSelectionApplyResult(selection=normalized, persistence_error=error)
    return ModelSelectionApplyResult(selection=normalized, persisted=True)


async def get_session_model_selection(session: object) -> ModelSelection | None:
    getter = getattr(session, "get_model_selection", None)
    if not callable(getter):
        return None
    return normalize_model_selection(await _maybe_await(getter()))


async def get_session_model_identity(session: object) -> ModelIdentityData:
    """Resolve the live Agent model first, then the persisted session selection."""

    agent = getattr(session, "agent", None)
    identity = model_identity_data(getattr(agent, "model", None))
    if identity.value is not None:
        return identity
    return model_identity_data(await get_session_model_selection(session))


async def iter_available_model_details(session: object) -> list[object]:
    getter = getattr(session, "get_available_model_details", None)
    if not callable(getter):
        return []
    details = await _maybe_await(getter())
    if not isinstance(details, Iterable) or isinstance(details, str | bytes | Mapping):
        return []
    return list(details)


async def iter_available_model_selections(session: object) -> list[ModelSelection]:
    getter = getattr(session, "get_available_models", None)
    if not callable(getter):
        return []
    return _dedupe_model_selections(await _maybe_await(getter()))


async def iter_scoped_model_selections(session: object) -> list[ModelSelection]:
    raw_models = getattr(session, "scopedModels", None)
    if raw_models is None:
        getter = getattr(session, "get_scoped_models", None)
        raw_models = await _maybe_await(getter()) if callable(getter) else None
    if not isinstance(raw_models, Iterable):
        return []
    return _dedupe_model_selections(
        value.get("model", value) if isinstance(value, Mapping) else value
        for value in raw_models
    )


async def ensure_usable_session_model(
    session: object,
    *,
    candidates: ModelCandidates | None = None,
) -> ModelSelection | None:
    """Ensure a usable model using a product-provided candidate policy."""

    current = await get_session_model_selection(session)
    if is_usable_model_selection(current):
        return current
    raw_candidates = (
        await _maybe_await(candidates(session))
        if candidates is not None
        else await iter_available_model_selections(session)
    )
    setter = getattr(session, "set_model", None)
    for candidate in raw_candidates:
        normalized = normalize_model_selection(candidate)
        if normalized is None or not is_usable_model_selection(normalized):
            continue
        if not callable(setter):
            return normalized
        try:
            await _maybe_await(setter(candidate))
        except (RuntimeError, ValueError):
            continue
        return await get_session_model_selection(session) or normalized
    return None


def _dedupe_model_selections(values: object) -> list[ModelSelection]:
    if not isinstance(values, Iterable):
        return []
    selections: list[ModelSelection] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_value in values:
        selection = normalize_model_selection(raw_value)
        if selection is None or not is_usable_model_selection(selection):
            continue
        key = (selection.provider, selection.endpoint_id, selection.model_id)
        if key not in seen:
            seen.add(key)
            selections.append(selection)
    return selections


def model_listing_getter(
    session: object,
) -> tuple[Callable[[], object] | None, bool]:
    """Resolve the preferred model-detail getter for a Product host."""

    details_getter = getattr(session, "get_available_model_details", None)
    if callable(details_getter):
        return details_getter, True
    getter = getattr(session, "get_available_models", None)
    if callable(getter):
        return getter, False
    return None, False


def unique_sorted_model_entries(models: Iterable[object]) -> list[object]:
    """Dedupe model values by complete identity in stable display order."""

    by_key: dict[tuple[str, str, str], object] = {}
    for selection in models:
        normalized = _safe_normalize_model_selection(selection)
        if normalized is not None:
            by_key.setdefault(
                (
                    normalized.provider,
                    normalized.endpoint_id,
                    normalized.model_id,
                ),
                selection,
            )
    return [by_key[key] for key in sorted(by_key)]


def normalize_model_listing(
    models: Iterable[object], *, include_metadata: bool = False
) -> list[dict[str, object]]:
    """Project model selections into the shared host listing shape."""

    entries: list[dict[str, object]] = []
    for selection in models:
        normalized = _safe_normalize_model_selection(selection)
        if normalized is None:
            continue
        entry: dict[str, object] = {
            "provider": normalized.provider,
            "endpoint_id": normalized.endpoint_id,
            "model_id": normalized.model_id,
            "id": model_selection_ref(normalized),
        }
        if include_metadata:
            entry.update(
                {
                    "context_window": _optional_int_attr(selection, "context_window"),
                    "max_tokens": _optional_int_attr(selection, "max_tokens"),
                    "supports_thinking": _bool_model_attr(
                        selection, "supports_thinking", "reasoning"
                    ),
                    "supports_images": _bool_model_attr(
                        selection, "supports_image_input"
                    ),
                }
            )
        entries.append(entry)
    return entries


def model_listing_matches_query(entry: Mapping[str, object], query: str) -> bool:
    """Match a normalized model entry by substring or subsequence."""

    provider = str(entry.get("provider") or "").lower()
    endpoint_id = str(entry.get("endpoint_id") or "").lower()
    model_id = str(entry.get("model_id") or "").lower()
    if not provider and not model_id:
        return False
    if query in provider or query in model_id:
        return True
    haystack = f"{provider}:{endpoint_id}:{model_id}"
    return query in haystack or _is_subsequence(query, haystack)


def format_model_metadata_table(models: Sequence[Mapping[str, object]]) -> str:
    """Format the canonical human-readable model metadata table."""

    rows = [
        (
            str(model["provider"]),
            str(model["endpoint_id"]),
            str(model["model_id"]),
            _format_context_window(model.get("context_window")),
            _format_optional_int(model.get("max_tokens")),
            _format_bool(model.get("supports_thinking")),
            _format_bool(model.get("supports_images")),
        )
        for model in models
    ]
    headers = (
        "provider",
        "endpoint",
        "model",
        "context",
        "max-out",
        "thinking",
        "images",
    )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        if rows
        else len(headers[index])
        for index in range(len(headers))
    ]
    lines = [_format_model_table_row(headers, widths)]
    lines.extend(_format_model_table_row(row, widths) for row in rows)
    return "\n".join(lines) + "\n"


def _safe_normalize_model_selection(selection: object) -> ModelSelection | None:
    try:
        return normalize_model_selection(selection)
    except Exception:
        return None


def _model_label(selection: ModelSelection) -> str:
    return model_selection_ref(selection)


def _optional_int_attr(selection: object, attr: str) -> int | None:
    value = _detail_field(selection, attr)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool_model_attr(selection: object, *attrs: str) -> bool:
    for attr in attrs:
        value = _detail_field(selection, attr)
        if isinstance(value, bool):
            return value
    return False


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    haystack_iter = iter(haystack)
    return all(char in haystack_iter for char in needle)


def _format_model_table_row(row: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(
        value.ljust(widths[index]) for index, value in enumerate(row)
    ).rstrip()


def _format_context_window(value: object) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        return "-"
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000}M"
    if value >= 1000 and value % 1000 == 0:
        return f"{value // 1000}K"
    return str(value)


def _format_optional_int(value: object) -> str:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else "-"


def _format_bool(value: object) -> str:
    return "yes" if value is True else "no"


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


__all__ = [
    "ModelCandidates",
    "ModelChoiceData",
    "ModelIdentityData",
    "ModelSelectionApplyResult",
    "PersistModelSelection",
    "apply_session_model_selection",
    "ensure_usable_session_model",
    "format_model_metadata_table",
    "get_session_model_identity",
    "get_session_model_selection",
    "iter_available_model_details",
    "iter_available_model_selections",
    "iter_scoped_model_selections",
    "model_choice_data_from_details",
    "model_choice_data_from_selections",
    "model_identity_data",
    "model_listing_getter",
    "model_listing_matches_query",
    "normalize_model_listing",
    "unique_sorted_model_entries",
]

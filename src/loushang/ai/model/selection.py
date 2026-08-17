from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from loushang.ai.model.registry import ModelRegistry

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ModelSelection:
    """Complete lightweight reference to a configured endpoint model."""

    provider: str
    endpoint_id: str
    model_id: str

    def __post_init__(self) -> None:
        for field_name in ("provider", "endpoint_id", "model_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ModelSelection.{field_name} must be non-empty")
            object.__setattr__(self, field_name, value.strip())


def normalize_model_selection(selection: object | None) -> ModelSelection | None:
    """Normalize a public model reference without resolving provider policy."""

    if selection is None:
        return None
    provider = _string_attr(selection, "provider", "provider_id", "providerId")
    model_id = _string_attr(selection, "model_id", "modelId", "id")
    endpoint_id = _string_attr(selection, "endpoint_id", "endpoint", "endpointId")
    if provider is None or endpoint_id is None or model_id is None:
        return None
    return ModelSelection(provider=provider, model_id=model_id, endpoint_id=endpoint_id)


def is_usable_model_selection(selection: object | None) -> bool:
    normalized = normalize_model_selection(selection)
    return (
        normalized is not None
        and _is_usable_value(normalized.provider)
        and _is_usable_value(normalized.endpoint_id)
        and _is_usable_value(normalized.model_id)
    )


def model_label_from_selection(selection: object | None) -> str | None:
    normalized = normalize_model_selection(selection)
    if normalized is None or not is_usable_model_selection(normalized):
        return None
    return model_selection_ref(normalized)


def model_selection_ref(selection: ModelSelection) -> str:
    return f"{selection.provider}:{selection.endpoint_id}:{selection.model_id}"


def parse_model_selection_reference(
    model: str | None,
    *,
    provider: str | None = None,
    registry: ModelRegistry | None = None,
) -> ModelSelection | None:
    """Parse a model reference and immediately complete shorthand references."""

    if provider is None and model is None:
        return None
    if provider is None and model is not None and model.count(":") >= 2:
        provider_id, rest = model.split(":", 1)
        endpoint_id, model_id = rest.rsplit(":", 1)
        if provider_id and endpoint_id and model_id:
            return ModelSelection(
                provider=provider_id,
                endpoint_id=endpoint_id,
                model_id=model_id,
            )
    if provider is not None and model is not None:
        return _complete_model_selection(provider, model, registry=registry)
    if provider is None and model is not None and model.count(":") == 1:
        provider_id, model_id = model.split(":", 1)
        if provider_id and model_id:
            return _complete_model_selection(
                provider_id,
                model_id,
                registry=registry,
                ref=model,
            )
    if provider is None and model is not None and "/" in model:
        provider_id, model_id = model.split("/", 1)
        if provider_id and model_id:
            return _complete_model_selection(provider_id, model_id, registry=registry)
    raise ValueError(
        "Model selection requires --provider and --model, "
        "--model provider:model_id, --model provider/model_id, "
        "or --model provider:endpoint:model_id."
    )


def _complete_model_selection(
    provider: str,
    model_id: str,
    *,
    registry: ModelRegistry | None,
    ref: str | None = None,
) -> ModelSelection:
    if registry is None:
        from loushang.ai.model.registry import get_default_model_registry

        registry = get_default_model_registry()
    candidates = registry.list_models(provider=provider, model_id=model_id)
    if not candidates:
        raise KeyError((provider, model_id))
    if len(candidates) > 1:
        from loushang.ai.model.registry import AmbiguousModelReference

        raise AmbiguousModelReference(ref or f"{provider}/{model_id}", candidates)
    resolved = candidates[0]
    return ModelSelection(
        provider=resolved.provider_id,
        endpoint_id=resolved.endpoint_id,
        model_id=resolved.id,
    )


def current_model_first(
    items: Iterable[T],
    *,
    current_label: str | None,
    label_of: Callable[[T], str | None],
) -> list[T]:
    ordered = list(items)
    if current_label is None:
        return ordered
    current = [item for item in ordered if label_of(item) == current_label]
    return (
        ordered
        if not current
        else [
            *current,
            *(item for item in ordered if label_of(item) != current_label),
        ]
    )


def _string_attr(value: object, *names: str) -> str | None:
    for name in names:
        raw_value = (
            value.get(name)
            if isinstance(value, Mapping)
            else getattr(value, name, None)
        )
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return None


def _is_usable_value(value: str) -> bool:
    return value.strip().lower() not in {"", "unknown"}


__all__ = [
    "ModelSelection",
    "current_model_first",
    "is_usable_model_selection",
    "model_label_from_selection",
    "model_selection_ref",
    "parse_model_selection_reference",
    "normalize_model_selection",
]

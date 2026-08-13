"""Product-neutral model resolution helpers for session bootstrap."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from loushang.ai.model import Model, ModelSelection
from loushang.harness.diagnostics.service import DiagnosticsService

ModelBuilder = Callable[[ModelSelection], Model]
ModelLookup = Callable[[str], ModelSelection | None]
EndpointLookup = Callable[[str, str], object | None]
UnavailableModelHandler = Callable[[ModelSelection, Exception, str], None]


@dataclass(frozen=True)
class DefaultModelResolution:
    """The result of resolving an optional configured default model."""

    model: Model | None
    reason: str | None = None
    error: Exception | None = None


def resolve_default_model(
    selection: ModelSelection | None,
    *,
    build_model: ModelBuilder,
    endpoint_lookup: EndpointLookup | None = None,
    on_unavailable: UnavailableModelHandler | None = None,
) -> DefaultModelResolution:
    """Build a configured model and return a fallback-safe resolution result.

    Products decide how an unavailable model is reported. The session layer
    owns only the common resolution and reason classification.
    """

    if selection is None:
        return DefaultModelResolution(model=None)
    try:
        return DefaultModelResolution(model=build_model(selection))
    except (KeyError, ValueError) as error:
        reason = classify_model_resolution_failure(
            selection,
            error=error,
            endpoint_lookup=endpoint_lookup,
        )
        if on_unavailable is not None:
            on_unavailable(selection, error, reason)
        return DefaultModelResolution(model=None, reason=reason, error=error)


def resolve_session_model(
    model: Model | ModelSelection | None,
    *,
    default_selection: ModelSelection | None,
    build_model: ModelBuilder,
    endpoint_lookup: EndpointLookup | None = None,
    on_default_unavailable: UnavailableModelHandler | None = None,
) -> Model | None:
    """Resolve an explicit model or a fallback-safe configured default."""

    if isinstance(model, Model):
        return model
    if isinstance(model, ModelSelection):
        return build_model(model)
    return resolve_default_model(
        default_selection,
        build_model=build_model,
        endpoint_lookup=endpoint_lookup,
        on_unavailable=on_default_unavailable,
    ).model


def record_default_model_unavailable(
    selection: ModelSelection,
    error: Exception,
    reason: str,
    *,
    diagnostics_service: DiagnosticsService,
    session_id: str,
) -> None:
    """Record the standard startup diagnostic for an unavailable model."""

    selection_ref = f"{selection.provider}:{selection.endpoint_id}:{selection.model_id}"
    message = f"Default model unavailable: {selection_ref}; using startup fallback."
    diagnostics_service.record(
        diagnostics_service.normalize_error(
            code="default_model_unavailable",
            error=message,
            phase="startup",
            source="model",
            level="warning",
            session_id=session_id,
            details={
                "provider": selection.provider,
                "model_id": selection.model_id,
                "endpoint_id": selection.endpoint_id,
                "reason": reason,
                "error": str(error),
            },
        )
    )


def classify_model_resolution_failure(
    selection: ModelSelection,
    *,
    error: Exception,
    endpoint_lookup: EndpointLookup | None = None,
) -> str:
    """Return the stable reason used by session diagnostics and hosts."""

    if endpoint_lookup is None:
        return "missing"
    endpoint = endpoint_lookup(selection.provider, selection.endpoint_id)
    return "missing" if endpoint is not None else "endpoint_unavailable"


def split_model_thinking_pattern(pattern: str) -> tuple[str, str | None]:
    """Split a supported thinking suffix from a model reference."""

    name, separator, suffix = pattern.rpartition(":")
    if (
        separator
        and suffix in {"off", "minimal", "low", "medium", "high", "xhigh"}
        and name
    ):
        return name, suffix
    return pattern, None


def scoped_models_from_patterns(
    patterns: Sequence[str] | None,
    *,
    resolve_model: ModelLookup,
    thinking_key: str = "thinkingLevel",
) -> list[dict[str, object]]:
    """Resolve configured model/thinking patterns into session scope payloads."""

    if not patterns:
        return []
    scoped_models: list[dict[str, object]] = []
    for pattern in patterns:
        model_name, thinking_level = split_model_thinking_pattern(pattern)
        selection = resolve_model(model_name)
        if selection is None:
            continue
        model_payload: dict[str, object] = {
            "provider": selection.provider,
            "endpoint_id": selection.endpoint_id,
            "model_id": selection.model_id,
        }
        scoped: dict[str, object] = {"model": model_payload}
        if thinking_level is not None:
            scoped[thinking_key] = thinking_level
        scoped_models.append(scoped)
    return scoped_models


__all__ = [
    "DefaultModelResolution",
    "classify_model_resolution_failure",
    "record_default_model_unavailable",
    "resolve_default_model",
    "resolve_session_model",
    "scoped_models_from_patterns",
    "split_model_thinking_pattern",
]

from __future__ import annotations

from dataclasses import asdict

import pytest

from loushang.ai import ModelSelection
from loushang.ai.model import (
    AmbiguousModelReference,
    Endpoint,
    Model,
    ModelRegistry,
    Provider,
    model_label_from_selection,
    model_selection_ref,
    normalize_model_selection,
    parse_model_selection_reference,
)


def _registry(*, duplicate: bool = False, preferred: bool = False) -> ModelRegistry:
    first = Endpoint(
        id="responses",
        provider="provider",
        api="openai-responses",
        preferred=preferred,
        models={"model": Model(id="model", provider="provider", endpoint="responses")},
    )
    endpoints = {first.id: first}
    if duplicate:
        second = Endpoint(
            id="completions",
            provider="provider",
            api="openai-completions",
            models={
                "model": Model(
                    id="model",
                    provider="provider",
                    endpoint="completions",
                )
            },
        )
        endpoints[second.id] = second
    return ModelRegistry.from_providers(
        {"provider": Provider(id="provider", endpoints=endpoints)}
    )


def test_model_selection_requires_complete_non_empty_identity() -> None:
    selection = ModelSelection(
        provider="example",
        endpoint_id="responses",
        model_id="example-1",
    )

    assert model_selection_ref(selection) == "example:responses:example-1"
    with pytest.raises(TypeError):
        ModelSelection(provider="example", model_id="example-1")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="endpoint_id"):
        ModelSelection(provider="example", endpoint_id="", model_id="example-1")


def test_model_selection_normalization_preserves_endpoint_identity() -> None:
    selection = normalize_model_selection(
        {
            "providerId": "provider",
            "endpointId": "responses",
            "modelId": "model",
        }
    )

    assert selection == ModelSelection(
        provider="provider",
        endpoint_id="responses",
        model_id="model",
    )
    assert model_label_from_selection(selection) == "provider:responses:model"
    persisted = asdict(selection)
    assert persisted == {
        "provider": "provider",
        "endpoint_id": "responses",
        "model_id": "model",
    }
    assert normalize_model_selection(persisted) == selection
    assert (
        normalize_model_selection({"provider": "provider", "model_id": "model"}) is None
    )
    resolved = _registry().resolve_model_selection(selection)
    assert (resolved.provider_id, resolved.endpoint_id, resolved.id) == (
        "provider",
        "responses",
        "model",
    )
    assert resolved.api == "openai-responses"


def test_model_selection_reference_parser_accepts_complete_reference() -> None:
    assert parse_model_selection_reference(
        "provider:responses:model"
    ) == ModelSelection(
        provider="provider",
        endpoint_id="responses",
        model_id="model",
    )


@pytest.mark.parametrize(
    ("model", "provider"),
    [("provider:model", None), ("provider/model", None), ("model", "provider")],
)
def test_model_selection_reference_parser_completes_unique_shorthand(
    model: str,
    provider: str | None,
) -> None:
    assert parse_model_selection_reference(
        model,
        provider=provider,
        registry=_registry(),
    ) == ModelSelection(
        provider="provider",
        endpoint_id="responses",
        model_id="model",
    )


def test_model_selection_reference_parser_reports_missing_model() -> None:
    with pytest.raises(KeyError):
        parse_model_selection_reference(
            "provider/missing",
            registry=_registry(),
        )


def test_model_selection_reference_parser_rejects_ambiguous_shorthand() -> None:
    with pytest.raises(AmbiguousModelReference) as exc_info:
        parse_model_selection_reference(
            "provider/model",
            registry=_registry(duplicate=True, preferred=True),
        )

    assert exc_info.value.candidates == (
        "provider:completions:model",
        "provider:responses:model",
    )

    with pytest.raises(AmbiguousModelReference) as colon_exc_info:
        parse_model_selection_reference(
            "provider:model",
            registry=_registry(duplicate=True, preferred=True),
        )

    assert colon_exc_info.value.ref == "provider:model"
    assert colon_exc_info.value.candidates == exc_info.value.candidates


def test_model_selection_reference_parser_rejects_partial_reference() -> None:
    with pytest.raises(ValueError, match="Model selection requires"):
        parse_model_selection_reference("model")

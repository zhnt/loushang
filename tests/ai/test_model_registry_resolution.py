from __future__ import annotations

import pytest

from loushang.ai.model import Capabilities, Endpoint, Model, Provider
from loushang.ai.model.registry import (
    AmbiguousModelReference,
    ModelRegistry,
    resolve_model_ref,
)


def _model(
    model_id: str, *, provider: str = "provider", endpoint: str = "primary"
) -> Model:
    return Model(
        id=model_id,
        provider=provider,
        endpoint=endpoint,
        capabilities=Capabilities(input=("text",), output=("text",)),
    )


def _registry(
    *, primary_preferred: bool = False, secondary_preferred: bool = False
) -> ModelRegistry:
    primary = Endpoint(
        id="primary",
        provider="provider",
        api="openai-responses",
        preferred=primary_preferred,
        models={"chat": _model("chat", endpoint="primary")},
    )
    secondary = Endpoint(
        id="secondary",
        provider="provider",
        api="openai-completions",
        preferred=secondary_preferred,
        models={"chat": _model("chat", endpoint="secondary")},
    )
    return ModelRegistry.from_providers(
        {
            "provider": Provider(
                id="provider",
                endpoints={primary.id: primary, secondary.id: secondary},
            )
        }
    )


def test_resolve_model_ref_uses_explicit_endpoint_identity() -> None:
    registry = _registry()

    model = resolve_model_ref(registry, "provider:secondary:chat")

    assert model.provider_id == "provider"
    assert model.endpoint_id == "secondary"


def test_resolve_model_ref_completes_unique_colon_shorthand() -> None:
    endpoint = Endpoint(
        id="primary",
        provider="provider",
        api="openai-responses",
        models={"chat": _model("chat", endpoint="primary")},
    )
    registry = ModelRegistry.from_providers(
        {"provider": Provider(id="provider", endpoints={endpoint.id: endpoint})}
    )

    model = resolve_model_ref(registry, "provider:chat")

    assert model.endpoint_id == "primary"
    assert model.id == "chat"


def test_resolve_model_ref_accepts_endpoint_identity_with_colons() -> None:
    endpoint = Endpoint(
        id="openai-completions:cn:coding",
        provider="provider",
        api="openai-completions",
        models={
            "chat": _model("chat", endpoint="openai-completions:cn:coding"),
        },
    )
    registry = ModelRegistry.from_providers(
        {"provider": Provider(id="provider", endpoints={endpoint.id: endpoint})}
    )

    model = resolve_model_ref(registry, "provider:openai-completions:cn:coding:chat")

    assert model.endpoint_id == "openai-completions:cn:coding"
    assert model.id == "chat"


def test_resolve_provider_model_ref_uses_single_matching_endpoint() -> None:
    endpoint = Endpoint(
        id="primary",
        provider="provider",
        api="openai-responses",
        models={"chat": _model("chat", endpoint="primary")},
    )
    registry = ModelRegistry.from_providers(
        {"provider": Provider(id="provider", endpoints={endpoint.id: endpoint})}
    )

    model = resolve_model_ref(registry, "provider/chat")

    assert model.endpoint_id == "primary"


def test_resolve_provider_model_ref_rejects_duplicates_even_when_one_is_preferred() -> (
    None
):
    registry = _registry(primary_preferred=True)

    with pytest.raises(AmbiguousModelReference):
        resolve_model_ref(registry, "provider/chat")


def test_resolve_provider_model_ref_lists_explicit_candidates_when_ambiguous() -> None:
    registry = _registry()

    with pytest.raises(AmbiguousModelReference) as exc_info:
        resolve_model_ref(registry, "provider/chat")

    assert exc_info.value.candidates == (
        "provider:primary:chat",
        "provider:secondary:chat",
    )
    assert "provider:primary:chat" in str(exc_info.value)
    assert "provider:secondary:chat" in str(exc_info.value)

    with pytest.raises(AmbiguousModelReference) as colon_exc_info:
        resolve_model_ref(registry, "provider:chat")

    assert colon_exc_info.value.ref == "provider:chat"
    assert colon_exc_info.value.candidates == exc_info.value.candidates


def test_resolve_provider_model_ref_rejects_multiple_preferred_endpoints() -> None:
    registry = _registry(primary_preferred=True, secondary_preferred=True)

    with pytest.raises(AmbiguousModelReference) as exc_info:
        resolve_model_ref(registry, "provider/chat")

    assert exc_info.value.candidates == (
        "provider:primary:chat",
        "provider:secondary:chat",
    )

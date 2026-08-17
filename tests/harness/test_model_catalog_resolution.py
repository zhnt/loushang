from __future__ import annotations

from loushang.ai.model import Capabilities, Endpoint, Model, ModelSelection, Provider
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.harness.model_catalog import ModelCatalog as ModelRegistry


def _model(model_id: str, *, endpoint: str) -> Model:
    return Model(
        id=model_id,
        provider="provider",
        endpoint=endpoint,
        capabilities=Capabilities(input=("text",), output=("text",)),
    )


def _registry() -> ModelRegistry:
    primary = Endpoint(
        id="primary",
        provider="provider",
        api="openai-responses",
        models={"chat": _model("chat", endpoint="primary")},
    )
    secondary = Endpoint(
        id="secondary",
        provider="provider",
        api="openai-completions",
        models={"chat": _model("chat", endpoint="secondary")},
    )
    ai_registry = AiModelRegistry.from_providers(
        {
            "provider": Provider(
                id="provider",
                endpoints={primary.id: primary, secondary.id: secondary},
            )
        }
    )
    return ModelRegistry(ai_registry)


def test_model_catalog_resolves_complete_primary_endpoint_selection() -> None:
    model = _registry().build_model(
        ModelSelection(provider="provider", endpoint_id="primary", model_id="chat")
    )

    assert model.endpoint_id == "primary"


def test_model_catalog_resolves_explicit_endpoint_selection() -> None:
    model = _registry().build_model(
        ModelSelection(provider="provider", endpoint_id="secondary", model_id="chat")
    )

    assert model.endpoint_id == "secondary"


def test_model_catalog_lists_each_endpoint_as_a_distinct_selection() -> None:
    assert _registry().list_models() == [
        ModelSelection(provider="provider", endpoint_id="primary", model_id="chat"),
        ModelSelection(provider="provider", endpoint_id="secondary", model_id="chat"),
    ]

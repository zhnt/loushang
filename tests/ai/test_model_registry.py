from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from loushang.ai.model import (
    AmbiguousModelReference,
    Auth,
    Defaults,
    Endpoint,
    Model,
    ModelRegistry,
    OpenAICompletionsConfig,
    Provider,
    format_model_ref,
    resolve_model_api,
    resolve_model_endpoint,
    resolve_model_ref,
)


def _endpoint(
    endpoint_id: str,
    *,
    provider: str = "custom",
    preferred: bool = False,
    model_ids: tuple[str, ...] = ("shared",),
) -> Endpoint:
    return Endpoint(
        id=endpoint_id,
        provider=provider,
        api="openai-completions",
        preferred=preferred,
        adapter=OpenAICompletionsConfig(developer_role=False),
        models={
            model_id: Model(
                id=model_id,
                provider=provider,
                endpoint=endpoint_id,
                adapter=OpenAICompletionsConfig(reasoning_format="moonshot"),
            )
            for model_id in model_ids
        },
    )


def _registry() -> ModelRegistry:
    preferred = _endpoint("preferred", preferred=True, model_ids=("shared", "solo"))
    fallback = _endpoint("fallback")
    other = _endpoint("other", provider="other")
    return ModelRegistry.from_providers(
        {
            "custom": Provider(
                id="custom",
                endpoints={preferred.id: preferred, fallback.id: fallback},
            ),
            "other": Provider(id="other", endpoints={other.id: other}),
        }
    )


def test_registry_resolves_only_unambiguous_shorthand_refs() -> None:
    registry = _registry()

    assert (
        format_model_ref(resolve_model_ref(registry, "custom:preferred:shared"))
        == "custom:preferred:shared"
    )
    with pytest.raises(AmbiguousModelReference):
        resolve_model_ref(registry, "custom/shared")
    with pytest.raises(AmbiguousModelReference):
        resolve_model_ref(registry, "shared", provider="custom")
    assert (
        resolve_model_ref(
            registry,
            "shared",
            provider="custom",
            endpoint="fallback",
        ).endpoint_id
        == "fallback"
    )
    assert resolve_model_ref(registry, "solo", api="openai-completions").id == "solo"


def test_registry_reports_ambiguous_refs() -> None:
    registry = ModelRegistry.from_providers(
        {
            "custom": Provider(
                id="custom",
                endpoints={
                    "a": _endpoint("a", preferred=False),
                    "b": _endpoint("b", preferred=False),
                },
            )
        }
    )

    with pytest.raises(AmbiguousModelReference):
        resolve_model_ref(registry, "shared", provider="custom")
    with pytest.raises(AmbiguousModelReference):
        resolve_model_ref(registry, "shared", api="openai-completions")
    with pytest.raises(ValueError, match="Ambiguous model_id"):
        registry.get_model("shared")
    assert registry.find_model("shared") is None


def test_registry_does_not_use_preferred_metadata_to_break_ambiguity() -> None:
    registry = ModelRegistry.from_providers(
        {
            "custom": Provider(
                id="custom",
                endpoints={
                    "a": _endpoint("a", preferred=True),
                    "b": _endpoint("b", preferred=True),
                },
            )
        }
    )

    with pytest.raises(AmbiguousModelReference) as exc_info:
        resolve_model_ref(registry, "shared", provider="custom")

    assert exc_info.value.candidates == (
        "custom:a:shared",
        "custom:b:shared",
    )


def test_registry_is_constructed_once_and_exposes_queries_only() -> None:
    model = Model(
        id="new-model",
        provider="new-provider",
        endpoint="new-endpoint",
        auth=Auth(api_key_env="NEW_PROVIDER_KEY"),
        adapter=OpenAICompletionsConfig(reasoning_format="moonshot"),
        defaults=Defaults.from_raw({"metadata": {"tags": ["stable"]}}),
    )
    endpoint = Endpoint(
        id="new-endpoint",
        provider="new-provider",
        api="openai-completions",
        headers={"x-static": "yes"},
        models={model.id: model},
    )
    registry = ModelRegistry.from_providers(
        {
            "new-provider": Provider(
                id="new-provider",
                endpoints={endpoint.id: endpoint},
            )
        }
    )

    assert registry.get_providers() == ["new-provider"]
    assert registry.get_endpoint("new-provider", "new-endpoint") is not None
    assert (
        registry.get_model("new-provider", "new-endpoint", "new-model").api
        == "openai-completions"
    )
    assert registry.list_endpoints(provider="missing") == []
    assert registry.find_model("new-provider", "missing", "new-model") is None
    exposed_providers = registry.providers
    exposed_providers.clear()
    assert registry.get_providers() == ["new-provider"]
    provider = registry.get_provider("new-provider")
    assert provider is not None
    with pytest.raises(TypeError):
        provider.endpoints["other"] = endpoint  # type: ignore[index]
    resolved_endpoint = registry.get_endpoint("new-provider", "new-endpoint")
    assert resolved_endpoint is not None
    with pytest.raises(TypeError):
        resolved_endpoint.models["other"] = model  # type: ignore[index]
    resolved_model = registry.get_model("new-provider", "new-endpoint", "new-model")
    with pytest.raises(TypeError):
        resolved_model.defaults.items_by_key["temperature"] = 0.2  # type: ignore[index]
    default_metadata = resolved_model.defaults["metadata"]
    assert isinstance(default_metadata, Mapping)
    default_tags = default_metadata["tags"]
    assert isinstance(default_tags, tuple)
    assert default_tags == ["stable"]
    assert not default_tags != ["stable"]
    with pytest.raises(TypeError):
        default_tags[0] = "changed"  # type: ignore[index]
    assert resolved_model.auth is not None
    with pytest.raises(TypeError):
        resolved_model.headers["x-static"] = "changed"  # type: ignore[index]
    assert isinstance(resolved_model.adapter, OpenAICompletionsConfig)
    json.dumps(resolved_model.to_raw())
    for method_name in (
        "replace_providers",
        "register_provider",
        "unregister_provider",
        "register_endpoint",
        "register_model",
    ):
        assert not hasattr(registry, method_name)


def test_registry_get_and_find_model_error_branches() -> None:
    registry = _registry()

    with pytest.raises(KeyError):
        registry.get_model("missing")
    with pytest.raises(TypeError):
        registry.get_model("custom", "preferred")
    with pytest.raises(TypeError):
        registry.find_model("custom", "preferred")
    with pytest.raises(KeyError):
        registry.get_model("custom", "preferred", "missing")

    assert registry.find_model("missing") is None
    assert registry.list_models(provider="custom", endpoint="fallback") == [
        registry.get_model("custom", "fallback", "shared")
    ]


def test_bound_endpoint_snapshot_preserves_adapter_and_defaults() -> None:
    model = Model(
        id="snapshot",
        provider="custom",
        endpoint="openai-completions",
        api="openai-completions",
        base_url="https://example.test/v1",
        adapter=OpenAICompletionsConfig(reasoning_format="moonshot"),
        defaults={"maxOutputTokens": 12},
    )

    endpoint = resolve_model_endpoint(model)

    assert endpoint is not None
    assert endpoint.base_url == "https://example.test/v1"
    assert endpoint.defaults.get("maxOutputTokens") == 12
    assert isinstance(endpoint.adapter, OpenAICompletionsConfig)
    assert endpoint.adapter.reasoning_format == "moonshot"
    assert resolve_model_api(model) == "openai-completions"


def test_resolve_model_api_requires_endpoint_context() -> None:
    model = Model(id="missing", provider="custom", endpoint="missing")

    with pytest.raises(ValueError, match="Endpoint not found"):
        resolve_model_api(model, registry=ModelRegistry.from_providers({}))

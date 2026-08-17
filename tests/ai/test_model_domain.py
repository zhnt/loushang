from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from loushang.ai.model import (
    AnthropicMessagesConfig,
    Auth,
    Capabilities,
    Defaults,
    Endpoint,
    Model,
    ModelRegistry,
    OAuthConfig,
    OpenAICompletionsConfig,
    OpenAIResponsesConfig,
    Pricing,
    Provider,
)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stream": "false"},
        {"tool_use": 1},
        {"reasoning": None},
        {"max_tokens": True},
        {"context_window": 0},
        {"context_window": 1.5},
        {"input": ()},
        {"input": ("text", "text")},
        {"output": ("audio",)},
    ],
)
def test_capabilities_reject_invalid_programmatic_values(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="capability field"):
        Capabilities(**kwargs)  # type: ignore[arg-type]


def test_capabilities_from_raw_rejects_lossy_coercion() -> None:
    with pytest.raises(ValueError, match="must be a boolean"):
        Capabilities.from_raw({"stream": "false"})
    with pytest.raises(ValueError, match="invalid modalities"):
        Capabilities.from_raw({"input": ["text", "audio"]})


@pytest.mark.parametrize(
    "raw",
    [
        {"contextWindow": True},
        {"contextWindow": None},
        {"maxTokens": 0},
        {"maxOutputTokens": 1.5},
        {"temperature": float("inf")},
        {"temperature": None},
        {"reasoningEffort": " "},
        {"reasoningEffort": None},
    ],
)
def test_defaults_reject_invalid_programmatic_values(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="model default"):
        Defaults.from_raw(raw)


def test_openai_completions_adapter_round_trip() -> None:
    adapter = OpenAICompletionsConfig.from_raw(
        {
            "store": False,
            "developerRole": False,
            "streamingUsage": True,
            "maxOutputTokensField": "max_tokens",
            "reasoningEffort": True,
            "reasoningEffortMap": {"off": None, "minimal": "low"},
            "strictSchema": True,
            "assistantReasoningContent": True,
            "reasoningFormat": "moonshot",
        }
    )
    endpoint = Endpoint(
        id="openai-completions",
        provider="custom",
        api="openai-completions",
        adapter=adapter,
    )

    raw = endpoint.to_raw()["adapter"]

    assert raw == {
        "store": False,
        "developerRole": False,
        "streamingUsage": True,
        "maxOutputTokensField": "max_tokens",
        "reasoningEffort": True,
        "reasoningEffortMap": {"off": None, "minimal": "low"},
        "strictSchema": True,
        "assistantReasoningContent": True,
        "reasoningFormat": "moonshot",
    }
    assert OpenAICompletionsConfig.from_raw(raw) == adapter


def test_openai_completions_adapter_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="adapter config field must be a boolean"):
        OpenAICompletionsConfig(strict_schema="yes")
    with pytest.raises(
        ValueError, match="adapter config field must be a non-empty string"
    ):
        OpenAICompletionsConfig(max_output_tokens_field="")
    with pytest.raises(ValueError, match="adapter config has unknown keys"):
        OpenAICompletionsConfig.from_raw({"futureFlag": True})


def test_openai_completions_adapter_rejects_removed_escape_hatches() -> None:
    with pytest.raises(ValueError, match="unknown keys"):
        OpenAICompletionsConfig.from_raw({"extra" + "Body": {"model": "other"}})


def test_openai_responses_adapter_round_trip() -> None:
    adapter = OpenAIResponsesConfig.from_raw(
        {
            "developerRole": False,
            "maxOutputTokens": False,
            "promptCacheKey": False,
            "longCacheRetention": False,
        }
    )
    endpoint = Endpoint(
        id="openai-responses",
        provider="custom",
        api="openai-responses",
        adapter=adapter,
    )

    raw = endpoint.to_raw()["adapter"]

    assert raw == {
        "developerRole": False,
        "maxOutputTokens": False,
        "promptCacheKey": False,
        "longCacheRetention": False,
    }
    assert OpenAIResponsesConfig.from_raw(raw) == adapter


def test_openai_responses_adapter_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="adapter config field must be a boolean"):
        OpenAIResponsesConfig(prompt_cache_key="yes")
    with pytest.raises(ValueError, match="adapter config has unknown keys"):
        OpenAIResponsesConfig.from_raw({"reasoningFormat": "openai"})


def test_anthropic_messages_adapter_round_trip() -> None:
    adapter = AnthropicMessagesConfig.from_raw(
        {
            "fineGrainedTools": True,
            "interleavedThinking": False,
            "longCacheRetention": False,
            "reasoningEffortMap": {
                "high": "high",
                "xhigh": "max",
            },
            "thinkingMode": "adaptive",
        }
    )
    endpoint = Endpoint(
        id="anthropic-messages",
        provider="custom",
        api="anthropic-messages",
        adapter=adapter,
    )

    raw = endpoint.to_raw()["adapter"]

    assert raw == {
        "longCacheRetention": False,
        "fineGrainedTools": True,
        "interleavedThinking": False,
        "reasoningEffortMap": {
            "high": "high",
            "xhigh": "max",
        },
        "thinkingMode": "adaptive",
    }
    assert AnthropicMessagesConfig.from_raw(raw) == adapter


def test_anthropic_messages_adapter_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="adapter config field must be a boolean"):
        AnthropicMessagesConfig(long_cache_retention="yes")
    with pytest.raises(ValueError, match="unsupported Anthropic thinkingMode"):
        AnthropicMessagesConfig(thinking_mode="automatic")
    with pytest.raises(ValueError, match="unsupported keys"):
        AnthropicMessagesConfig(reasoning_effort_map={"future": "high"})
    with pytest.raises(ValueError, match="unsupported .*values"):
        AnthropicMessagesConfig(reasoning_effort_map={"high": "extreme"})
    with pytest.raises(ValueError, match="adapter config has unknown keys"):
        AnthropicMessagesConfig.from_raw({"developerRole": False})


def test_model_adapter_override_merges_endpoint_adapter() -> None:
    endpoint = Endpoint(
        id="openai-completions",
        provider="custom",
        api="openai-completions",
        adapter=OpenAICompletionsConfig(
            developer_role=False,
            max_output_tokens_field="max_tokens",
        ),
    )
    model = Model(
        id="public-model",
        provider="custom",
        endpoint="openai-completions",
        adapter=OpenAICompletionsConfig(reasoning_format="moonshot"),
    )

    bound = ModelRegistry.from_providers(
        {
            "custom": Provider(
                id="custom",
                endpoints={endpoint.id: replace(endpoint, models={model.id: model})},
            )
        }
    ).get_model("custom", "openai-completions", model.id)

    assert isinstance(bound.adapter, OpenAICompletionsConfig)
    assert bound.adapter.developer_role is False
    assert bound.adapter.reasoning_format == "moonshot"


def test_model_adapter_raw_override_can_restore_default_value() -> None:
    endpoint = Endpoint(
        id="openai-completions",
        provider="custom",
        api="openai-completions",
        adapter=OpenAICompletionsConfig(developer_role=False),
    )
    model = Model(
        id="public-model",
        provider="custom",
        endpoint="openai-completions",
        adapter=OpenAICompletionsConfig.from_raw({"developerRole": True}),
    )

    bound = ModelRegistry.from_providers(
        {
            "custom": Provider(
                id="custom",
                endpoints={endpoint.id: replace(endpoint, models={model.id: model})},
            )
        }
    ).get_model("custom", "openai-completions", model.id)

    assert isinstance(bound.adapter, OpenAICompletionsConfig)
    assert bound.adapter.developer_role is True


def test_model_omits_unknown_pricing_from_raw() -> None:
    model = Model(id="public-model", provider="custom", endpoint="openai-completions")

    raw = model.to_raw()

    assert model.pricing is None
    assert "pricing" not in raw


def test_provider_endpoint_and_model_to_raw_include_optional_fields() -> None:
    model = Model(
        id="public-model",
        provider="custom",
        endpoint="openai-completions",
        name="Public Model",
        family="test",
        alias="public",
        knowledge="2026-01",
        release_date="2026-01-01",
        last_updated="2026-02-01",
        auth=Auth(api_key_env="MODEL_KEY"),
        adapter=OpenAICompletionsConfig(reasoning_format="moonshot"),
        pricing=Pricing(input=1, output=2),
    )
    endpoint = Endpoint(
        id="openai-completions",
        provider="custom",
        api="openai-completions",
        name="OpenAI-compatible",
        base_url="https://example.test/v1",
        base_url_env="CUSTOM_BASE_URL",
        region="global",
        lane="coding",
        preferred=True,
        docs="https://example.test/docs",
        auth=Auth(api_key_env="ENDPOINT_KEY"),
        adapter=OpenAICompletionsConfig(developer_role=False),
        models={"public-model": model},
    )
    provider = Provider(
        id="custom",
        name="Custom",
        website="https://example.test",
        auth=Auth(api_key_env="PROVIDER_KEY"),
        endpoints={endpoint.id: endpoint},
    )

    raw = provider.to_raw()

    assert provider.get_endpoint("openai-completions") == endpoint
    assert provider.get_model("openai-completions", "public-model") == model
    assert provider.get_model("missing", "public-model") is None
    assert provider.list_models() == [model]
    assert raw["displayName"] == "Custom"
    assert raw["website"] == "https://example.test"
    endpoint_raw = raw["endpoints"]["openai-completions"]
    assert endpoint_raw["displayName"] == "OpenAI-compatible"
    assert endpoint_raw["baseUrl"] == "https://example.test/v1"
    assert endpoint_raw["baseUrlEnv"] == "CUSTOM_BASE_URL"
    assert endpoint_raw["region"] == "global"
    assert endpoint_raw["lane"] == "coding"
    assert endpoint_raw["preferred"] is True
    assert endpoint_raw["docs"] == "https://example.test/docs"
    model_raw = endpoint_raw["models"]["public-model"]
    assert model_raw["adapter"]["reasoningFormat"] == "moonshot"
    assert model_raw["pricing"] == {"input": 1, "output": 2}
    assert model_raw["auth"]["apiKeyEnv"] == "MODEL_KEY"


def test_auth_to_raw_omits_empty_optional_fields() -> None:
    assert Auth(kind="oauth").to_raw() == {"kind": "oauth"}
    assert Auth(kind="oauth", provider="example-oauth").to_raw() == {
        "kind": "oauth",
        "provider": "example-oauth",
    }
    assert Auth(
        kind="apiKey",
        api_key_env="PRIMARY_KEY",
        api_key_envs=("SECONDARY_KEY",),
        header="X-Key",
        prefix="",
    ).to_raw() == {
        "kind": "apiKey",
        "apiKeyEnv": "PRIMARY_KEY",
        "apiKeyEnvs": ["SECONDARY_KEY"],
        "header": "X-Key",
        "prefix": "",
    }


def test_oauth_config_round_trips_through_auth() -> None:
    oauth = OAuthConfig(
        client_id="client",
        authorization_endpoint="https://oauth.test/authorize",
        token_endpoint="https://oauth.test/token",
        scopes=("model.invoke", "model.read"),
        redirect_uri="http://127.0.0.1:9876/callback",
    )

    raw = Auth(kind="oauth", provider="example-oauth", oauth=oauth).to_raw()

    assert raw == {
        "kind": "oauth",
        "provider": "example-oauth",
        "oauth": {
            "client_id": "client",
            "authorization_endpoint": "https://oauth.test/authorize",
            "token_endpoint": "https://oauth.test/token",
            "scopes": ["model.invoke", "model.read"],
            "redirect_uri": "http://127.0.0.1:9876/callback",
        },
    }
    assert Auth.from_raw(raw) == Auth(
        kind="oauth",
        provider="example-oauth",
        oauth=oauth,
    )


def test_pricing_round_trip_preserves_unknown_and_zero_components() -> None:
    pricing = Pricing.from_raw({"input": 0, "output": 2.0})

    assert pricing == Pricing(input=0, output=2.0)
    assert pricing.cache_read is None
    assert pricing.cache_write is None
    assert pricing.to_raw() == {"input": 0, "output": 2.0}


def test_model_upstream_id_round_trip() -> None:
    model = Model(
        id="public-model",
        provider="custom",
        endpoint="openai-completions",
        upstream_id="vendor/public-model:latest",
    )

    raw = model.to_raw()

    assert raw["upstreamId"] == "vendor/public-model:latest"
    assert "upstreamModelId" not in raw


def test_model_constructor_keeps_existing_fields_before_upstream_id() -> None:
    parameters = list(inspect.signature(Model).parameters)

    assert parameters.index("knowledge") < parameters.index("upstream_id")


def test_model_rejects_invalid_upstream_id() -> None:
    with pytest.raises(ValueError, match="upstream_id must be a non-empty string"):
        Model(
            id="public-model",
            provider="custom",
            endpoint="openai-completions",
            upstream_id="",
        )
    with pytest.raises(ValueError, match="upstream_id must be a non-empty string"):
        Model(
            id="public-model",
            provider="custom",
            endpoint="openai-completions",
            upstream_id=" ",
        )

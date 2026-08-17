from __future__ import annotations

from dataclasses import dataclass

import pytest

from loushang.ai import CallOptions, ReasoningOptions
from loushang.ai.auth import ApiKeyAuth, AuthCredential
from loushang.ai.context import NormalizedContext
from loushang.ai.model import (
    AnthropicMessagesConfig,
    Auth,
    Capabilities,
    Defaults,
    Endpoint,
    Model,
    ModelRegistry,
    OpenAICompletionsConfig,
    Provider,
    load_builtin_model_registry,
)
from loushang.ai.provider import (
    ProviderRequest,
    ensure_request_api,
    normalize_provider_request_for_api,
    resolve_endpoint_for_model,
    resolve_request_for_model,
)


@dataclass
class _Options:
    auth: AuthCredential | None = ApiKeyAuth("secret")
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    temperature: float | None = None


def _model(
    *,
    api: str = "openai-responses",
    endpoint: str | None = None,
    adapter: object | None = None,
    region: str | None = None,
    base_url: str | None = "https://example.test/v1",
    base_url_env: str | None = None,
    capabilities: Capabilities | None = None,
    defaults: Defaults | None = None,
    upstream_id: str | None = None,
    auth: Auth | None = None,
) -> Model:
    return Model(
        id="model-a",
        provider="custom",
        endpoint=endpoint or api,
        api=api,
        base_url=base_url,
        base_url_env=base_url_env,
        region=region,
        auth=auth,
        capabilities=capabilities or Capabilities(stream=True),
        adapter=adapter,  # type: ignore[arg-type]
        defaults=defaults or Defaults(),
        upstream_id=upstream_id,
    )


def _request(model: Model, **overrides: object) -> ProviderRequest:
    values: dict[str, object] = {
        "model": model,
        "context": NormalizedContext(system_prompt=None),
        "options": None,
        "base_url": model.base_url,
    }
    values.update(overrides)
    return ProviderRequest(**values)  # type: ignore[arg-type]


def test_provider_request_defensively_copies_and_hides_headers() -> None:
    model = _model(auth=Auth(kind="none"))
    headers = {"Authorization": "Bearer original"}

    request = _request(model, headers=headers)
    headers["Authorization"] = "Bearer mutated"

    assert request.headers == {"Authorization": "Bearer original"}
    assert "original" not in repr(request)


def test_builtin_openai_style_model_resolves_its_bound_facts() -> None:
    model = load_builtin_model_registry().get_model(
        "moonshot", "openai-completions", "kimi-k2.7-code"
    )

    resolved = resolve_request_for_model(
        model,
        options=_Options(auth=ApiKeyAuth("moonshot-key")),
    )

    assert resolved.model is model
    assert resolved.model.provider_id == "moonshot"
    assert resolved.model.endpoint_id == "openai-completions"
    assert resolved.base_url == "https://api.moonshot.cn/v1"
    assert isinstance(resolved.model.adapter, OpenAICompletionsConfig)
    assert resolved.model.adapter.reasoning_format == "moonshot"
    assert (resolved.model.upstream_id or resolved.model.id) == "kimi-k2.7-code"


def test_resolver_rejects_concrete_model_without_base_url() -> None:
    model = Model(
        id="faux-model",
        provider="faux-provider",
        endpoint="faux-api",
        api="faux-api",
    )

    with pytest.raises(ValueError, match="no configured provider base URL"):
        resolve_request_for_model(
            model,
            options=_Options(auth=ApiKeyAuth("token")),
            env={"LOUSHANG_REGION": "ignored"},
        )


@pytest.mark.parametrize(
    "model",
    [
        Model(id="missing-all"),
        Model(id="missing-api", provider="custom", endpoint="responses"),
        Model(id="missing-provider", api="openai-responses"),
    ],
)
def test_resolver_rejects_unbound_model(model: Model) -> None:
    with pytest.raises(ValueError, match="not bound to a concrete provider endpoint"):
        resolve_request_for_model(model, options=_Options(auth=ApiKeyAuth("token")))


def test_resolver_rejects_non_model_input() -> None:
    with pytest.raises(TypeError, match="model must be Model"):
        resolve_request_for_model(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reasoning", "default_effort", "expected_enabled", "expected_effort"),
    [
        (None, "medium", True, "medium"),
        (ReasoningOptions(enabled=False), "medium", False, None),
        (ReasoningOptions(enabled=True), "medium", True, "medium"),
        (ReasoningOptions(effort="high"), "medium", True, "high"),
        (ReasoningOptions(budget_tokens=2048), "medium", True, "medium"),
        (ReasoningOptions(expose_summary=True), None, True, None),
        (ReasoningOptions(), "medium", True, "medium"),
        (ReasoningOptions(), None, None, None),
    ],
)
def test_resolver_produces_authoritative_reasoning_state(
    reasoning: ReasoningOptions | None,
    default_effort: str | None,
    expected_enabled: bool | None,
    expected_effort: str | None,
) -> None:
    defaults = (
        Defaults.from_raw({"reasoningEffort": default_effort})
        if default_effort is not None
        else Defaults()
    )

    resolved = resolve_request_for_model(
        _model(defaults=defaults),
        options=CallOptions(auth=ApiKeyAuth("token"), reasoning=reasoning),
        env={},
    )

    assert resolved.reasoning_enabled is expected_enabled
    assert resolved.reasoning_effort == expected_effort


def test_resolver_applies_default_and_explicit_temperature() -> None:
    model = _model(defaults=Defaults.from_raw({"temperature": 0.4}))

    default_request = resolve_request_for_model(
        model,
        options=CallOptions(auth=ApiKeyAuth("token")),
        env={},
    )
    override_request = resolve_request_for_model(
        model,
        options=CallOptions(auth=ApiKeyAuth("token"), temperature=0.7),
        env={},
    )

    assert default_request.temperature == 0.4
    assert override_request.temperature == 0.7


def test_resolver_uses_bound_model_without_registry_reselection() -> None:
    us_capabilities = Capabilities(stream=True)
    eu_capabilities = Capabilities(reasoning=True)
    us_defaults = Defaults.from_raw({"temperature": 0.1})
    eu_defaults = Defaults.from_raw({"temperature": 0.7})
    us_adapter = OpenAICompletionsConfig(reasoning_format="moonshot")
    eu_adapter = OpenAICompletionsConfig(reasoning_format="openai")
    endpoint_us = Endpoint(
        id="regional-us",
        provider="custom",
        api="openai-completions",
        base_url="https://us.example.test/v1",
        region="us",
        auth=Auth(
            header="x-region-key",
            prefix="",
        ),
        headers={"x-selected-region": "us"},
        adapter=us_adapter,
        defaults=us_defaults,
        models={
            "m": Model(
                id="m",
                provider="custom",
                endpoint="regional-us",
                capabilities=us_capabilities,
                upstream_id="upstream-us",
            )
        },
    )
    endpoint_eu = Endpoint(
        id="regional-eu",
        provider="custom",
        api="openai-completions",
        base_url="https://eu.example.test/v1",
        region="eu",
        auth=Auth(
            header="x-region-key",
            prefix="",
        ),
        headers={"x-selected-region": "eu"},
        adapter=eu_adapter,
        defaults=eu_defaults,
        models={
            "m": Model(
                id="m",
                provider="custom",
                endpoint="regional-eu",
                capabilities=eu_capabilities,
                upstream_id="upstream-eu",
            )
        },
    )
    registry = ModelRegistry.from_providers(
        {
            "custom": Provider(
                id="custom",
                endpoints={endpoint_us.id: endpoint_us, endpoint_eu.id: endpoint_eu},
            )
        }
    )
    selected_us = registry.get_model("custom", "regional-us", "m")

    resolved_us = resolve_request_for_model(
        selected_us,
        options=_Options(auth=ApiKeyAuth("token")),
        env={"LOUSHANG_REGION": "eu"},
    )

    assert resolved_us.model is selected_us
    assert resolved_us.model.provider_id == "custom"
    assert resolved_us.model.endpoint_id == "regional-us"
    assert resolved_us.model.api == "openai-completions"
    assert resolved_us.base_url == "https://us.example.test/v1"
    assert resolved_us.model.region == "us"
    assert resolved_us.model.capabilities == us_capabilities
    assert resolved_us.model.defaults == us_defaults
    assert resolved_us.model.adapter == us_adapter
    assert resolved_us.model.upstream_id == "upstream-us"
    assert resolved_us.headers == {
        "x-region-key": "token",
        "x-selected-region": "us",
    }

    selected_eu = registry.get_model("custom", "regional-eu", "m")
    resolved_eu = resolve_request_for_model(
        selected_eu,
        options=_Options(auth=ApiKeyAuth("token")),
        env={"LOUSHANG_REGION": "us"},
    )

    assert resolved_eu.model is selected_eu
    assert resolved_eu.model.endpoint_id == "regional-eu"
    assert resolved_eu.base_url == "https://eu.example.test/v1"
    assert resolved_eu.model.region == "eu"
    assert resolved_eu.model.capabilities == eu_capabilities
    assert resolved_eu.model.defaults == eu_defaults
    assert resolved_eu.model.adapter == eu_adapter
    assert resolved_eu.model.upstream_id == "upstream-eu"
    assert resolved_eu.headers == {
        "x-region-key": "token",
        "x-selected-region": "eu",
    }


def test_bound_model_endpoint_snapshot_preserves_model_facts() -> None:
    model = _model(
        api="openai-completions",
        adapter=OpenAICompletionsConfig(reasoning_format="moonshot"),
    )

    endpoint = resolve_endpoint_for_model(model)

    assert endpoint is not None
    assert endpoint.base_url == model.base_url
    assert endpoint.adapter == model.adapter
    assert endpoint.get_model(model.id) is model


def test_base_url_env_template_is_expanded_from_bound_model() -> None:
    model = _model(base_url="https://{HOST}/v1")

    resolved = resolve_request_for_model(
        model,
        options=_Options(auth=ApiKeyAuth("token")),
        env={"HOST": "example.test"},
    )

    assert resolved.base_url == "https://example.test/v1"


def test_missing_base_url_env_template_fails() -> None:
    model = _model(base_url="https://{HOST}/v1")

    with pytest.raises(ValueError, match="Environment variable HOST"):
        resolve_request_for_model(
            model, options=_Options(auth=ApiKeyAuth("token")), env={}
        )


def test_missing_base_url_env_fails_without_sdk_fallback() -> None:
    model = _model(base_url=None, base_url_env="CUSTOM_BASE_URL")

    with pytest.raises(ValueError, match="CUSTOM_BASE_URL is required"):
        resolve_request_for_model(
            model, options=_Options(auth=ApiKeyAuth("token")), env={}
        )


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_base_url_env_value_fails(value: str) -> None:
    model = _model(base_url=None, base_url_env="CUSTOM_BASE_URL")

    with pytest.raises(ValueError, match="must contain a non-empty base URL"):
        resolve_request_for_model(
            model,
            options=_Options(auth=ApiKeyAuth("token")),
            env={"CUSTOM_BASE_URL": value},
        )


def test_unresolved_base_url_template_fails() -> None:
    model = _model(base_url="https://{host}/v1")

    with pytest.raises(ValueError, match="unresolved template"):
        resolve_request_for_model(
            model, options=_Options(auth=ApiKeyAuth("token")), env={}
        )


def test_provider_request_accepts_resolved_runtime_base_url() -> None:
    model = _model(base_url="https://catalog.example/v1")

    request = _request(
        model,
        base_url="https://runtime.example/v1",
        headers={"Authorization": "Bearer token"},
    )

    assert request.base_url == "https://runtime.example/v1"


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("", "resolved non-empty string"),
        ("   ", "resolved non-empty string"),
        ("https://{HOST}/v1", "unresolved template"),
    ],
)
def test_provider_request_requires_resolved_base_url(
    base_url: str,
    message: str,
) -> None:
    model = _model(base_url=base_url)

    with pytest.raises(ValueError, match=message):
        _request(model, base_url=base_url)


def test_provider_request_contains_only_runtime_facts() -> None:
    assert set(ProviderRequest.__dataclass_fields__) == {
        "model",
        "context",
        "options",
        "base_url",
        "headers",
        "mode",
        "max_output_tokens",
        "reasoning_effort",
        "reasoning_enabled",
        "temperature",
        "invocation_id",
        "attempt",
    }


def test_provider_request_requires_typed_model() -> None:
    assert "candidate_base_urls" not in ProviderRequest.__dataclass_fields__
    with pytest.raises(TypeError, match="model must be Model"):
        ProviderRequest(
            model=object(),  # type: ignore[arg-type]
            context=NormalizedContext(system_prompt=None),
            options=None,
            base_url="https://example.test/v1",
        )


def test_provider_request_repr_redacts_headers() -> None:
    request = _request(
        _model(),
        headers={
            "Authorization": "Bearer access-secret",
            "chatgpt-account-id": "account-secret",
        },
    )

    rendered = repr(request)

    assert "access-secret" not in rendered
    assert "account-secret" not in rendered


def test_normalize_provider_request_accepts_model_default_core_adapter_config() -> None:
    model = _model(adapter=None)
    assert model.base_url is not None
    request = ProviderRequest(
        model=model,
        context=NormalizedContext(system_prompt=None),
        options=None,
        base_url=model.base_url,
    )

    assert normalize_provider_request_for_api("openai-responses", request) == request


@pytest.mark.parametrize(
    ("api", "adapter_config", "expected_type"),
    [
        ("openai-completions", AnthropicMessagesConfig(), "OpenAICompletionsConfig"),
        ("openai-responses", OpenAICompletionsConfig(), "OpenAIResponsesConfig"),
        ("anthropic-messages", OpenAICompletionsConfig(), "AnthropicMessagesConfig"),
    ],
)
def test_normalize_provider_request_rejects_wrong_core_adapter_config_type(
    api: str,
    adapter_config: object,
    expected_type: str,
) -> None:
    model = _model(api=api, adapter=adapter_config)
    request = _request(model)

    with pytest.raises(TypeError, match=expected_type):
        normalize_provider_request_for_api(api, request)


def test_ensure_request_api_rejects_mismatch() -> None:
    request = _request(_model(api="openai-completions"))

    with pytest.raises(ValueError, match="Mismatched api"):
        ensure_request_api("openai-responses", request)


def test_normalize_provider_request_leaves_non_core_config_to_provider() -> None:
    config = {"raw": True}
    model = _model(api="custom-api", adapter=config)
    request = _request(model)

    assert normalize_provider_request_for_api("custom-api", request) is request

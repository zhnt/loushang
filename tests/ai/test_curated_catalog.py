from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loushang.ai.model import (
    AnthropicMessagesConfig,
    ModelRegistry,
    OpenAICompletionsConfig,
    OpenAIResponsesConfig,
    load_builtin_model_registry,
    load_model_registry_from_file,
)
from loushang.ai.model.loader import validate_model_registry_raw

REPO_ROOT = Path(__file__).resolve().parents[2]
CURATED_CATALOG_PATH = REPO_ROOT / "src/loushang/ai/model/models.json"


def _load_curated_raw() -> dict[str, Any]:
    return json.loads(CURATED_CATALOG_PATH.read_text(encoding="utf-8"))


def _load_curated_registry() -> ModelRegistry:
    return load_model_registry_from_file(CURATED_CATALOG_PATH)


def test_curated_catalog_loads_runtime_models_json() -> None:
    raw = _load_curated_raw()

    assert "schemaVersion" not in raw
    validate_model_registry_raw(raw)
    assert [provider.id for provider in _load_curated_registry().list_providers()] == [
        "anthropic",
        "baidu-qianfan",
        "dashscope",
        "deepseek",
        "kimi-code",
        "minimax",
        "moonshot",
        "openai",
        "stepfun",
        "tencent-hunyuan",
        "volcano-ark",
        "zai",
    ]


def test_default_builtin_catalog_matches_curated_catalog() -> None:
    registry = load_builtin_model_registry()
    curated = _load_curated_registry()

    assert [provider.id for provider in registry.list_providers()] == [
        provider.id for provider in curated.list_providers()
    ]
    assert [
        (endpoint.provider_id, endpoint.id) for endpoint in registry.list_endpoints()
    ] == [(endpoint.provider_id, endpoint.id) for endpoint in curated.list_endpoints()]
    assert [
        (model.provider_id, model.endpoint_id, model.id)
        for model in registry.list_models()
    ] == [
        (model.provider_id, model.endpoint_id, model.id)
        for model in curated.list_models()
    ]


def test_curated_catalog_tracks_current_primary_model_roster() -> None:
    raw = _load_curated_raw()
    actual = {
        (provider_id, endpoint_id): set(endpoint["models"])
        for provider_id, provider in raw["providers"].items()
        for endpoint_id, endpoint in provider["endpoints"].items()
    }

    assert actual == {
        ("anthropic", "anthropic-messages"): {
            "claude-fable-5",
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-haiku-4-5",
        },
        ("baidu-qianfan", "openai-completions-cn"): {"ernie-5.1"},
        ("dashscope", "openai-responses"): {"qwen3.7-max", "qwen3.7-plus"},
        ("deepseek", "openai-completions"): {
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        },
        ("minimax", "anthropic-messages"): {"MiniMax-M3", "MiniMax-M2.7"},
        ("moonshot", "openai-completions"): {
            "kimi-k2.6",
            "kimi-k2.7-code",
            "kimi-k3",
        },
        ("kimi-code", "kimi-code-openai"): {"k3", "kimi-for-coding"},
        ("kimi-code", "kimi-code-anthropic"): {"k3", "kimi-for-coding"},
        ("openai", "openai-responses"): {
            "gpt-5.5",
            "gpt-5.6-sol",
            "gpt-5.4-mini",
        },
        ("openai", "coding-responses"): {"gpt-5.5", "gpt-5.6-sol"},
        ("stepfun", "openai-completions"): {"step-3.7-flash"},
        ("tencent-hunyuan", "openai-responses"): {"hy3"},
        ("volcano-ark", "openai-completions-cn-beijing"): {
            "doubao-seed-evolving",
            "doubao-seed-2-1-pro-260628",
            "doubao-seed-2-1-turbo-260628",
        },
        ("zai", "openai-completions"): {"glm-5.2", "glm-4.7"},
    }


def test_curated_catalog_has_no_removed_model_contract_fields() -> None:
    raw = _load_curated_raw()
    removed_fields = {"compat", "protocol", "dialect"}

    for provider in raw["providers"].values():
        for endpoint in provider["endpoints"].values():
            assert removed_fields.isdisjoint(endpoint)
            for model in endpoint["models"].values():
                assert removed_fields.isdisjoint(model)


def test_curated_catalog_uses_core_adapter_configs() -> None:
    registry = _load_curated_registry()

    adapters = {
        (endpoint.provider_id, endpoint.id): type(endpoint.adapter)
        for endpoint in registry.list_endpoints()
    }

    assert adapters[("anthropic", "anthropic-messages")] is AnthropicMessagesConfig
    assert adapters[("openai", "openai-responses")] is OpenAIResponsesConfig
    assert adapters[("openai", "coding-responses")] is OpenAIResponsesConfig
    assert adapters[("deepseek", "openai-completions")] is OpenAICompletionsConfig
    assert adapters[("moonshot", "openai-completions")] is OpenAICompletionsConfig


def test_minimax_anthropic_catalog_uses_sdk_base_url_and_short_cache() -> None:
    registry = _load_curated_registry()
    endpoint = registry.get_endpoint("minimax", "anthropic-messages")

    assert endpoint is not None
    assert endpoint.base_url == "https://api.minimax.io/anthropic"
    assert isinstance(endpoint.adapter, AnthropicMessagesConfig)
    assert endpoint.adapter.long_cache_retention is False


def test_kimi_code_catalog_uses_its_own_api_key_not_moonshot_platform_key() -> None:
    registry = _load_curated_registry()
    provider = registry.get_provider("kimi-code")
    anthropic_endpoint = registry.get_endpoint("kimi-code", "kimi-code-anthropic")
    anthropic_model = registry.get_model(
        "kimi-code", "kimi-code-anthropic", "kimi-for-coding"
    )
    openai_endpoint = registry.get_endpoint("kimi-code", "kimi-code-openai")
    openai_model = registry.get_model(
        "kimi-code", "kimi-code-openai", "kimi-for-coding"
    )
    anthropic_k3 = registry.get_model("kimi-code", "kimi-code-anthropic", "k3")
    openai_k3 = registry.get_model("kimi-code", "kimi-code-openai", "k3")

    assert provider is not None
    assert anthropic_endpoint is not None
    assert openai_endpoint is not None
    for model in (anthropic_model, openai_model):
        assert model.auth is not None
        assert model.auth.kind == "apiKey"
        assert model.auth.api_key_env == "KIMI_CODE_API_KEY"
        assert model.auth.header == "Authorization"
        assert model.auth.prefix == "Bearer "
        assert model.pricing is None
        assert model.supports_temperature is False
        assert model.capabilities.input == ("text", "image")
    assert anthropic_endpoint.base_url == "https://api.kimi.com/coding"
    assert openai_endpoint.base_url == "https://api.kimi.com/coding/v1"
    for model in (anthropic_k3, openai_k3):
        assert model.name == "Kimi Code K3"
        assert model.upstream_id is None
        assert model.defaults["reasoningEffort"] == "high"


def test_curated_openai_style_custom_base_urls_declare_adapter() -> None:
    raw = _load_curated_raw()

    for provider_id, provider in raw["providers"].items():
        for endpoint_id, endpoint in provider["endpoints"].items():
            if provider_id == "openai" or endpoint["api"] != "openai-completions":
                continue
            if not (endpoint.get("baseUrl") or endpoint.get("baseUrlEnv")):
                continue
            assert endpoint.get("adapter"), (provider_id, endpoint_id)


def test_curated_catalog_keeps_key_model_defaults() -> None:
    registry = _load_curated_registry()
    kimi = registry.get_model("moonshot", "openai-completions", "kimi-k2.6")
    kimi_code = registry.get_model("moonshot", "openai-completions", "kimi-k2.7-code")
    minimax = registry.get_model("minimax", "anthropic-messages", "MiniMax-M3")
    gpt = registry.get_model("openai", "openai-responses", "gpt-5.5")
    sol = registry.get_model("openai", "openai-responses", "gpt-5.6-sol")
    coding = registry.get_model("openai", "coding-responses", "gpt-5.5")
    coding_sol = registry.get_model("openai", "coding-responses", "gpt-5.6-sol")
    claude = registry.get_model("anthropic", "anthropic-messages", "claude-sonnet-5")

    assert kimi.supports_temperature is False
    assert kimi_code.defaults["maxOutputTokens"] == 32000
    assert kimi_code.defaults["reasoningEffort"] == "medium"
    assert minimax.pricing is None
    assert gpt.capabilities.context_window == 1050000
    assert sol.capabilities.context_window == 1050000
    assert coding.capabilities.context_window == 400000
    assert coding.defaults["reasoningEffort"] == "medium"
    assert coding.pricing is None
    assert coding_sol.pricing is None
    assert claude.pricing is not None
    assert claude.pricing.output == 15


def test_curated_catalog_keeps_corrected_base_pricing() -> None:
    registry = _load_curated_registry()
    expected = {
        ("baidu-qianfan", "openai-completions-cn", "ernie-5.1"): (
            "CNY",
            4,
            18,
            None,
        ),
        ("moonshot", "openai-completions", "kimi-k2.6"): ("CNY", 6.5, 27, 1.1),
        ("moonshot", "openai-completions", "kimi-k2.7-code"): (
            "CNY",
            6.5,
            27,
            1.3,
        ),
        ("moonshot", "openai-completions", "kimi-k3"): ("CNY", 20, 100, 2),
        ("tencent-hunyuan", "openai-responses", "hy3"): ("CNY", 1, 4, 0.25),
        (
            "volcano-ark",
            "openai-completions-cn-beijing",
            "doubao-seed-evolving",
        ): ("CNY", 6, 30, 1.2),
        (
            "volcano-ark",
            "openai-completions-cn-beijing",
            "doubao-seed-2-1-pro-260628",
        ): ("CNY", 6, 30, 1.2),
        (
            "volcano-ark",
            "openai-completions-cn-beijing",
            "doubao-seed-2-1-turbo-260628",
        ): ("CNY", 3, 15, 0.6),
        ("zai", "openai-completions", "glm-4.7"): ("USD", 0.6, 2.2, 0.11),
    }

    for model_ref, pricing_values in expected.items():
        model = registry.get_model(*model_ref)
        assert model.pricing is not None
        assert (
            model.pricing.currency,
            model.pricing.input,
            model.pricing.output,
            model.pricing.cache_read,
        ) == pricing_values


def test_coding_route_is_oauth_openai_responses_without_product_adapter() -> None:
    registry = _load_curated_registry()
    provider = registry.get_provider("openai")
    endpoint = registry.get_endpoint("openai", "coding-responses")
    model = registry.get_model("openai", "coding-responses", "gpt-5.5")

    assert provider is not None
    assert provider.auth is None
    assert endpoint is not None
    assert endpoint.api == "openai-responses"
    assert endpoint.base_url == "https://chatgpt.com/backend-api/codex"
    assert endpoint.preferred is False
    assert endpoint.auth is not None
    assert endpoint.auth.kind == "oauth"
    assert endpoint.auth.provider is None
    assert endpoint.auth.api_key_env is None
    assert endpoint.auth.api_key_envs == ()
    assert dict(endpoint.headers) == {
        "originator": "loushang",
        "OpenAI-Beta": "responses=experimental",
    }
    assert model.provider_id == "openai"
    assert model.upstream_id is None
    assert "codex" not in model.api


def test_openai_api_key_auth_is_scoped_to_the_public_api_endpoint() -> None:
    registry = _load_curated_registry()
    endpoint = registry.get_endpoint("openai", "openai-responses")
    model = registry.get_model("openai", "openai-responses", "gpt-5.5")

    assert endpoint is not None
    assert endpoint.auth is not None
    assert endpoint.auth.kind == "apiKey"
    assert endpoint.auth.api_key_env == "OPENAI_API_KEY"
    assert model.auth is not None
    assert model.auth.api_key_env == "OPENAI_API_KEY"

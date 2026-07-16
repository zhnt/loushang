from __future__ import annotations

from loushang.ai.model import load_builtin_model_registry

CURATED_PROVIDER_IDS = [
    "anthropic",
    "atlascloud",
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


def test_builtin_catalog_uses_curated_provider_set() -> None:
    registry = load_builtin_model_registry()

    assert [
        provider.id for provider in registry.list_providers()
    ] == CURATED_PROVIDER_IDS


def test_builtin_catalog_excludes_archived_legacy_providers() -> None:
    registry = load_builtin_model_registry()

    for provider_id in [
        "openrouter",
        "cloudflare-ai-gateway",
        "cloudflare-workers-ai",
        "mistral",
        "google",
        "google-vertex",
        "zai-coding-cn",
    ]:
        assert registry.get_provider(provider_id) is None


def test_builtin_catalog_includes_verified_curated_routes() -> None:
    registry = load_builtin_model_registry()

    moonshot = registry.get_model("moonshot", "openai-completions", "kimi-k2.6")
    openai = registry.get_model("openai", "openai-responses", "gpt-5.5")
    anthropic = registry.get_model(
        "anthropic", "anthropic-messages", "claude-sonnet-4-6"
    )
    qianfan = registry.get_model("baidu-qianfan", "openai-completions-cn", "ernie-5.1")
    stepfun = registry.get_model("stepfun", "openai-completions", "step-3.7-flash")
    atlascloud = registry.get_model(
        "atlascloud",
        "openai-completions",
        "qwen/qwen3.5-flash",
    )

    assert moonshot.api == "openai-completions"
    assert moonshot.supports_stream is True
    assert moonshot.supports_tool_use is True
    assert openai.api == "openai-responses"
    assert anthropic.api == "anthropic-messages"
    assert qianfan.auth is not None
    assert "QIANFAN_API_KEY" in qianfan.auth.api_key_envs
    assert stepfun.reasoning is True
    assert stepfun.auth is not None
    assert "STEPFUN_API_KEY" in stepfun.auth.api_key_envs
    assert atlascloud.api == "openai-completions"
    assert atlascloud.base_url == "https://api.atlascloud.ai/v1"
    assert atlascloud.auth is not None
    assert atlascloud.auth.api_key_env == "ATLASCLOUD_API_KEY"
    assert atlascloud.adapter is not None
    assert atlascloud.adapter.max_output_tokens_field == "max_tokens"
    assert registry.get_model(
        "atlascloud",
        "openai-completions",
        "deepseek-ai/deepseek-v4-pro",
    ).reasoning is True


def test_builtin_catalog_marks_single_preferred_endpoint_per_provider() -> None:
    registry = load_builtin_model_registry()

    for provider in registry.list_providers():
        preferred = [
            endpoint for endpoint in provider.list_endpoints() if endpoint.preferred
        ]
        assert [endpoint.id for endpoint in preferred] == [
            endpoint.id for endpoint in provider.list_endpoints()
        ]


def test_builtin_catalog_models_expose_endpoint_context() -> None:
    registry = load_builtin_model_registry()

    model = registry.get_model("moonshot", "openai-completions", "kimi-k2.7-code")

    assert model.api == "openai-completions"
    assert model.region is None
    assert model.lane is None
    assert model.preferred_endpoint is True


def test_builtin_catalog_only_declares_implemented_modalities() -> None:
    registry = load_builtin_model_registry()

    modalities = {
        modality
        for model in registry.list_models()
        for modality in (*model.capabilities.input, *model.capabilities.output)
    }

    assert modalities <= {"text", "image"}
    assert "image" in modalities

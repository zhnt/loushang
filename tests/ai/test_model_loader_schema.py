from __future__ import annotations

import json
from pathlib import Path

import pytest

import loushang.ai.model as model_api
from loushang.ai.model import (
    AnthropicMessagesConfig,
    OpenAICompletionsConfig,
    OpenAIResponsesConfig,
    load_builtin_model_registry,
    load_model_registry_from_directory,
    load_model_registry_from_file,
    validate_model_registry_raw,
)
from loushang.ai.model.loader import _load_layered_model_registry


def _capabilities() -> dict[str, object]:
    return {
        "contextWindow": 128000,
        "maxTokens": 8192,
        "input": ["text"],
        "output": ["text"],
        "reasoning": True,
        "stream": True,
        "toolUse": True,
        "structuredOutput": True,
        "attachment": False,
        "temperature": True,
    }


def test_model_loader_public_surface_uses_explicit_sources() -> None:
    assert not hasattr(model_api, "load_model_registry")
    assert not hasattr(model_api, "load_layered_model_registry")
    assert callable(model_api.load_model_registry_from_file)
    assert callable(model_api.load_model_registry_from_directory)


def _model_raw(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "displayName": "Test Model",
        "capabilities": _capabilities(),
    }
    raw.update(overrides)
    return raw


def _registry_raw(
    *,
    provider_id: str = "custom",
    api: str = "openai-completions",
    endpoint_adapter: dict[str, object] | None = None,
    model_adapter: dict[str, object] | None = None,
    endpoint_extra: dict[str, object] | None = None,
    model_extra: dict[str, object] | None = None,
) -> dict[str, object]:
    endpoint: dict[str, object] = {
        "api": api,
        "baseUrl": "https://example.test/v1",
        "models": {
            "test-model": _model_raw(
                **({"adapter": model_adapter} if model_adapter is not None else {}),
                **(model_extra or {}),
            )
        },
    }
    if endpoint_adapter is not None:
        endpoint["adapter"] = endpoint_adapter
    endpoint.update(endpoint_extra or {})
    return {
        "providers": {
            provider_id: {
                "displayName": "Custom",
                "auth": {"kind": "apiKey", "apiKeyEnv": "TEST_API_KEY"},
                "endpoints": {"test-endpoint": endpoint},
            }
        }
    }


def _write_registry(tmp_path: Path, raw: dict[str, object]) -> Path:
    path = tmp_path / "models.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_load_model_registry_from_file_rejects_invalid_json_with_file_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_model_registry_from_file(path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "invalid JSON" in message


def test_load_model_registry_from_file_rejects_missing_providers_with_field_path(
    tmp_path: Path,
) -> None:
    path = _write_registry(tmp_path, {})

    with pytest.raises(ValueError) as exc_info:
        load_model_registry_from_file(path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "providers" in message
    assert "must be an object" in message


def test_endpoint_requires_base_url_or_base_url_env() -> None:
    raw = _registry_raw()
    endpoint = raw["providers"]["custom"]["endpoints"]["test-endpoint"]
    del endpoint["baseUrl"]

    with pytest.raises(ValueError, match="must declare baseUrl or baseUrlEnv"):
        validate_model_registry_raw(raw)


@pytest.mark.parametrize("value", ["", "   "])
def test_endpoint_rejects_empty_base_url(value: str) -> None:
    raw = _registry_raw(endpoint_extra={"baseUrl": value})

    with pytest.raises(ValueError, match="baseUrl"):
        validate_model_registry_raw(raw)


def test_endpoint_accepts_base_url_env_without_literal_url() -> None:
    raw = _registry_raw(
        endpoint_adapter={"developerRole": False},
        endpoint_extra={"baseUrlEnv": "CUSTOM_BASE_URL"},
    )
    endpoint = raw["providers"]["custom"]["endpoints"]["test-endpoint"]
    del endpoint["baseUrl"]

    validate_model_registry_raw(raw)


def test_model_registry_accepts_generic_oauth_configuration(tmp_path: Path) -> None:
    oauth = {
        "client_id": "client",
        "authorization_endpoint": "https://oauth.test/authorize",
        "token_endpoint": "https://oauth.test/token",
        "scopes": ["model.invoke"],
    }
    raw = _registry_raw(
        endpoint_adapter={"developerRole": False},
        endpoint_extra={"auth": {"kind": "oauth", "oauth": oauth}},
    )

    registry = load_model_registry_from_file(_write_registry(tmp_path, raw))
    model = registry.get_model("custom", "test-endpoint", "test-model")

    assert model.auth is not None
    assert model.auth.oauth is not None
    assert model.auth.oauth.client_id == "client"
    assert model.auth.oauth.scopes == ("model.invoke",)


@pytest.mark.parametrize(
    "oauth",
    [
        {
            "authorization_endpoint": "https://oauth.test/authorize",
            "token_endpoint": "https://oauth.test/token",
        },
        {
            "client_id": "client",
            "authorization_endpoint": "https://oauth.test/authorize",
            "token_endpoint": "https://oauth.test/token",
            "scopes": ["same", "same"],
        },
        {
            "client_id": "client",
            "authorization_endpoint": "https://oauth.test/authorize",
            "token_endpoint": "https://oauth.test/token",
            "vendor_extension": True,
        },
    ],
)
def test_model_registry_rejects_invalid_generic_oauth_configuration(
    oauth: dict[str, object],
) -> None:
    raw = _registry_raw(endpoint_extra={"auth": {"kind": "oauth", "oauth": oauth}})

    with pytest.raises(ValueError, match="oauth"):
        validate_model_registry_raw(raw)


def _set_nested(
    raw: dict[str, object],
    path: tuple[str, ...],
    value: object,
) -> None:
    target: object = raw
    for key in path[:-1]:
        assert isinstance(target, dict)
        target = target[key]
    assert isinstance(target, dict)
    target[path[-1]] = value


def test_builtin_model_registry_loads_adapter_configs() -> None:
    registry = load_builtin_model_registry()

    adapter_types = {type(model.adapter) for model in registry.list_models()}

    assert OpenAICompletionsConfig in adapter_types
    assert OpenAIResponsesConfig in adapter_types
    assert AnthropicMessagesConfig in adapter_types


def test_registry_rejects_root_schema_version() -> None:
    raw = _registry_raw(endpoint_adapter={"developerRole": False})
    raw["schemaVersion"] = 2

    with pytest.raises(ValueError, match="no longer supported"):
        validate_model_registry_raw(raw)


@pytest.mark.parametrize("removed_field", ["compat", "protocol", "dialect"])
def test_registry_rejects_removed_endpoint_fields(removed_field: str) -> None:
    raw = _registry_raw(
        endpoint_adapter={"developerRole": False},
        endpoint_extra={removed_field: {}},
    )

    with pytest.raises(ValueError, match="no longer supported"):
        validate_model_registry_raw(raw)


@pytest.mark.parametrize("removed_field", ["compat", "protocol", "dialect"])
def test_registry_rejects_removed_model_fields(removed_field: str) -> None:
    raw = _registry_raw(
        endpoint_adapter={"developerRole": False},
        model_extra={removed_field: {}},
    )

    with pytest.raises(ValueError, match="no longer supported"):
        validate_model_registry_raw(raw)


def test_registry_rejects_unknown_adapter_field() -> None:
    raw = _registry_raw(endpoint_adapter={"futureFlag": True})

    with pytest.raises(ValueError, match="unknown keys"):
        validate_model_registry_raw(raw)


def test_registry_rejects_reserved_extra_body_fields() -> None:
    raw = _registry_raw(endpoint_adapter={"extra" + "Body": {"model": "other"}})

    with pytest.raises(ValueError, match="unknown keys"):
        validate_model_registry_raw(raw)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("providers", "custom"), "bad", "must be an object"),
        (("providers", "custom", "displayName"), "", "non-empty string"),
        (
            ("providers", "custom", "endpoints", "test-endpoint", "api"),
            "",
            "non-empty string",
        ),
        (
            ("providers", "custom", "endpoints", "test-endpoint", "preferred"),
            "yes",
            "must be a boolean",
        ),
        (
            ("providers", "custom", "endpoints", "test-endpoint", "auth"),
            {"apiKeyEnvs": [""]},
            "string list",
        ),
        (
            ("providers", "custom", "endpoints", "test-endpoint", "auth"),
            {"futureAuthField": "value"},
            "unknown keys",
        ),
        (
            (
                "providers",
                "custom",
                "endpoints",
                "test-endpoint",
                "models",
                "test-model",
                "pricing",
            ),
            {"input": -1},
            "non-negative number",
        ),
        (
            (
                "providers",
                "custom",
                "endpoints",
                "test-endpoint",
                "models",
                "test-model",
                "upstreamId",
            ),
            " ",
            "non-empty string",
        ),
        (
            (
                "providers",
                "custom",
                "endpoints",
                "test-endpoint",
                "models",
                "test-model",
                "capabilities",
                "input",
            ),
            ["audio"],
            "invalid modalities",
        ),
    ],
)
def test_registry_rejects_invalid_catalog_boundary_values(
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    raw = _registry_raw(endpoint_adapter={"developerRole": False})
    _set_nested(raw, path, value)

    with pytest.raises(ValueError, match=message):
        validate_model_registry_raw(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reasoning", None, "must be a boolean"),
        ("stream", "false", "must be a boolean"),
        ("toolUse", 1, "must be a boolean"),
        ("contextWindow", 1.5, "positive integer"),
        ("maxTokens", True, "positive integer"),
        ("maxTokens", 0, "positive integer"),
        ("maxTokens", -1, "positive integer"),
        ("input", [], "invalid modalities"),
        ("input", "text", "invalid modalities"),
        ("output", ["text", "text"], "invalid modalities"),
    ],
)
def test_registry_rejects_invalid_capability_values(
    field: str,
    value: object,
    message: str,
) -> None:
    raw = _registry_raw(endpoint_adapter={"developerRole": False})
    capabilities = raw["providers"]["custom"]["endpoints"]["test-endpoint"][
        "models"
    ]["test-model"]["capabilities"]
    assert isinstance(capabilities, dict)
    capabilities[field] = value

    with pytest.raises(ValueError, match=message):
        validate_model_registry_raw(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("contextWindow", True, "positive integer"),
        ("maxTokens", 0, "positive integer"),
        ("maxOutputTokens", 1.5, "positive integer"),
        ("temperature", True, "finite number"),
        ("temperature", float("nan"), "finite number"),
        ("reasoningEffort", "", "non-empty string"),
    ],
)
@pytest.mark.parametrize("scope", ["endpoint", "model"])
def test_registry_rejects_invalid_defaults(
    scope: str,
    field: str,
    value: object,
    message: str,
) -> None:
    defaults = {field: value}
    raw = _registry_raw(
        endpoint_adapter={"developerRole": False},
        endpoint_extra={"defaults": defaults} if scope == "endpoint" else None,
        model_extra={"defaults": defaults} if scope == "model" else None,
    )

    with pytest.raises(ValueError, match=message):
        validate_model_registry_raw(raw)


def test_registry_rejects_removed_auth_override() -> None:
    raw = _registry_raw(endpoint_adapter={"developerRole": False})
    endpoint = raw["providers"]["custom"]["endpoints"]["test-endpoint"]
    assert isinstance(endpoint, dict)
    endpoint["auth" + "Override"] = {"apiKeyEnv": "OVERRIDE_KEY"}

    with pytest.raises(ValueError, match="unknown keys"):
        validate_model_registry_raw(raw)


def test_registry_rejects_adapter_for_unsupported_api() -> None:
    raw = _registry_raw(api="custom-api", endpoint_adapter={"developerRole": False})

    with pytest.raises(ValueError, match="not supported for api"):
        validate_model_registry_raw(raw)


def test_openai_style_endpoint_requires_adapter_for_custom_base_url() -> None:
    raw = _registry_raw(endpoint_adapter=None)

    with pytest.raises(ValueError, match="must declare adapter"):
        validate_model_registry_raw(raw)


def test_model_adapter_json_override_is_shallow(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        _registry_raw(
            endpoint_adapter={
                "developerRole": False,
                "maxOutputTokensField": "max_tokens",
            },
            model_adapter={"reasoningFormat": "moonshot"},
        ),
    )

    registry = load_model_registry_from_file(path)
    model = registry.get_model("custom", "test-endpoint", "test-model")

    assert isinstance(model.adapter, OpenAICompletionsConfig)
    assert model.adapter.developer_role is False
    assert model.adapter.max_output_tokens_field == "max_tokens"
    assert model.adapter.reasoning_format == "moonshot"


def test_model_adapter_json_override_can_restore_default_value(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        _registry_raw(
            endpoint_adapter={"developerRole": False},
            model_adapter={"developerRole": True},
        ),
    )

    registry = load_model_registry_from_file(path)
    model = registry.get_model("custom", "test-endpoint", "test-model")

    assert isinstance(model.adapter, OpenAICompletionsConfig)
    assert model.adapter.developer_role is True


def test_openai_responses_adapter_schema_accepts_core_fields(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        _registry_raw(
            provider_id="openai",
            api="openai-responses",
            endpoint_adapter={
                "developerRole": True,
                "maxOutputTokens": False,
                "promptCacheKey": True,
                "longCacheRetention": True,
            },
        ),
    )

    model = load_model_registry_from_file(path).get_model(
        "openai",
        "test-endpoint",
        "test-model",
    )

    assert isinstance(model.adapter, OpenAIResponsesConfig)
    assert model.adapter.max_output_tokens is False
    assert model.adapter.prompt_cache_key is True


def test_anthropic_adapter_schema_accepts_tristate_fields(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        _registry_raw(
            api="anthropic-messages",
            endpoint_adapter={
                "fineGrainedTools": True,
                "interleavedThinking": False,
                "longCacheRetention": False,
            },
        ),
    )

    model = load_model_registry_from_file(path).get_model(
        "custom",
        "test-endpoint",
        "test-model",
    )

    assert isinstance(model.adapter, AnthropicMessagesConfig)
    assert model.adapter.fine_grained_tools is True
    assert model.adapter.interleaved_thinking is False


def test_load_registry_binds_adapter_auth_headers_and_defaults_once(
    tmp_path: Path,
) -> None:
    raw = _registry_raw(
        endpoint_adapter={
            "developerRole": False,
            "maxOutputTokensField": "max_tokens",
            "reasoningEffort": True,
        },
        model_adapter={"reasoningFormat": "moonshot"},
        endpoint_extra={
            "lane": "coding",
            "auth": {"apiKeyEnv": "ENDPOINT_KEY"},
            "headers": {"x-endpoint": "endpoint"},
        },
        model_extra={
            "auth": {"apiKeyEnv": "MODEL_KEY"},
            "upstreamId": "vendor/test-model",
        },
    )

    model = load_model_registry_from_file(_write_registry(tmp_path, raw)).get_model(
        "custom",
        "test-endpoint",
        "test-model",
    )

    assert model.api == "openai-completions"
    assert isinstance(model.adapter, OpenAICompletionsConfig)
    assert model.adapter.developer_role is False
    assert model.adapter.max_output_tokens_field == "max_tokens"
    assert model.adapter.reasoning_format == "moonshot"
    assert model.auth is not None
    assert model.auth.api_key_env == "MODEL_KEY"
    assert dict(model.headers) == {"x-endpoint": "endpoint"}
    assert isinstance(model.defaults.get("maxOutputTokens"), int)
    assert model.defaults.get("reasoningEffort") == "medium"
    assert model.defaults.get("temperature") == 0.2
    assert model.defaults.get("contextWindow") == 128000
    assert model.upstream_id == "vendor/test-model"


def test_directory_and_layered_registry_loading(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    (registry_dir / "custom.json").write_text(
        json.dumps(_registry_raw(endpoint_adapter={"developerRole": False})),
        encoding="utf-8",
    )

    registry = load_model_registry_from_directory(registry_dir)

    assert (
        registry.get_model("custom", "test-endpoint", "test-model").id == "test-model"
    )

    user_dir = tmp_path / "user"
    project_dir = tmp_path / "project"
    user_dir.mkdir()
    project_dir.mkdir()
    (user_dir / "provider.json").write_text(
        json.dumps(
            _registry_raw(
                provider_id="custom-user",
                endpoint_adapter={"developerRole": False},
            )
        ),
        encoding="utf-8",
    )
    (project_dir / "provider.json").write_text(
        json.dumps(
            _registry_raw(
                provider_id="custom-project",
                endpoint_adapter={"developerRole": False},
                model_extra={"displayName": "Project Model"},
            )
        ),
        encoding="utf-8",
    )

    layered = _load_layered_model_registry(
        user_dir=user_dir,
        project_dir=project_dir,
    )

    assert (
        layered.get_model("custom-user", "test-endpoint", "test-model").id
        == "test-model"
    )
    assert (
        layered.get_model("custom-project", "test-endpoint", "test-model").name
        == "Project Model"
    )


def test_directory_registry_rejects_duplicate_full_model_id(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    raw = _registry_raw(endpoint_adapter={"developerRole": False})
    first_file = registry_dir / "a.json"
    duplicate_file = registry_dir / "z.json"
    duplicate_file.write_text(json.dumps(raw), encoding="utf-8")
    first_file.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate model id") as exc_info:
        load_model_registry_from_directory(registry_dir)

    message = str(exc_info.value)
    assert f"at {duplicate_file}" in message
    assert f"first defined at {first_file}" in message


def test_directory_registry_rejects_conflicting_provider_metadata(
    tmp_path: Path,
) -> None:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    first_file = registry_dir / "a.json"
    conflict_file = registry_dir / "b.json"
    first_file.write_text(
        json.dumps(_registry_raw(endpoint_adapter={"developerRole": False})),
        encoding="utf-8",
    )
    raw = _registry_raw(endpoint_adapter={"developerRole": False})
    provider = raw["providers"]["custom"]
    assert isinstance(provider, dict)
    provider["displayName"] = "Other Custom"
    endpoints = provider["endpoints"]
    assert isinstance(endpoints, dict)
    endpoints["other-endpoint"] = endpoints.pop("test-endpoint")
    conflict_file.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting provider metadata") as exc_info:
        load_model_registry_from_directory(registry_dir)

    message = str(exc_info.value)
    assert str(conflict_file) in message
    assert str(first_file) in message
    assert "providers.custom" in message


def test_directory_registry_rejects_conflicting_endpoint_metadata(
    tmp_path: Path,
) -> None:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    first_file = registry_dir / "a.json"
    conflict_file = registry_dir / "b.json"
    first_file.write_text(
        json.dumps(_registry_raw(endpoint_adapter={"developerRole": False})),
        encoding="utf-8",
    )
    raw = _registry_raw(
        endpoint_adapter={"developerRole": False},
        endpoint_extra={"baseUrl": "https://other.example.test/v1"},
    )
    providers = raw["providers"]
    assert isinstance(providers, dict)
    provider = providers["custom"]
    assert isinstance(provider, dict)
    endpoints = provider["endpoints"]
    assert isinstance(endpoints, dict)
    endpoint = endpoints["test-endpoint"]
    assert isinstance(endpoint, dict)
    models = endpoint["models"]
    assert isinstance(models, dict)
    models["other-model"] = models.pop("test-model")
    conflict_file.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting endpoint metadata") as exc_info:
        load_model_registry_from_directory(registry_dir)

    message = str(exc_info.value)
    assert str(conflict_file) in message
    assert str(first_file) in message
    assert "providers.custom.endpoints.test-endpoint" in message


def test_layered_registry_rejects_user_duplicate_of_builtin_model(
    tmp_path: Path,
) -> None:
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    raw = _registry_raw(
        provider_id="openai",
        api="openai-responses",
        endpoint_adapter={"developerRole": True},
    )
    providers = raw["providers"]
    assert isinstance(providers, dict)
    provider = providers["openai"]
    assert isinstance(provider, dict)
    endpoints = provider["endpoints"]
    assert isinstance(endpoints, dict)
    endpoints["openai-responses"] = endpoints.pop("test-endpoint")
    endpoint = endpoints["openai-responses"]
    assert isinstance(endpoint, dict)
    models = endpoint["models"]
    assert isinstance(models, dict)
    models["gpt-5.5"] = models.pop("test-model")
    user_file = user_dir / "openai.json"
    user_file.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate model id") as exc_info:
        _load_layered_model_registry(user_dir=user_dir)

    message = str(exc_info.value)
    assert str(user_file) in message
    assert "<builtin>" in message


def test_layered_registry_rejects_project_duplicate_instead_of_deep_merge(
    tmp_path: Path,
) -> None:
    user_dir = tmp_path / "user"
    project_dir = tmp_path / "project"
    user_dir.mkdir()
    project_dir.mkdir()
    (user_dir / "custom.json").write_text(
        json.dumps(
            _registry_raw(
                endpoint_adapter={"developerRole": False},
                model_extra={"displayName": "User Model"},
            )
        ),
        encoding="utf-8",
    )
    (project_dir / "custom.json").write_text(
        json.dumps(
            _registry_raw(
                endpoint_adapter={"developerRole": False},
                model_extra={"displayName": "Project Override"},
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        _load_layered_model_registry(user_dir=user_dir, project_dir=project_dir)

    message = str(exc_info.value)
    assert "duplicate model id custom:test-endpoint:test-model" in message
    assert "providers.custom.endpoints.test-endpoint.models.test-model" in message
    assert str(user_dir) in message
    assert str(project_dir) in message


def test_directory_registry_error_includes_file_and_field_path(
    tmp_path: Path,
) -> None:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    raw = _registry_raw(endpoint_adapter={"developerRole": False})
    _set_nested(
        raw,
        (
            "providers",
            "custom",
            "endpoints",
            "test-endpoint",
            "models",
            "test-model",
            "capabilities",
            "input",
        ),
        ["audio"],
    )
    bad_file = registry_dir / "bad.json"
    bad_file.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_model_registry_from_directory(registry_dir)

    message = str(exc_info.value)
    assert str(bad_file) in message
    assert "providers.custom.endpoints.test-endpoint.models.test-model" in message
    assert "capabilities.input" in message


def test_explicit_model_registry_loaders_match_path_type(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        _registry_raw(endpoint_adapter={"developerRole": False}),
    )
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "models.json").write_text(path.read_text(encoding="utf-8"))
    assert (
        load_model_registry_from_file(path)
        .get_model("custom", "test-endpoint", "test-model")
        .id
        == "test-model"
    )
    assert (
        load_model_registry_from_directory(directory)
        .get_model("custom", "test-endpoint", "test-model")
        .id
        == "test-model"
    )
    with pytest.raises(FileNotFoundError):
        load_model_registry_from_file(tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        load_model_registry_from_directory(tmp_path / "missing")

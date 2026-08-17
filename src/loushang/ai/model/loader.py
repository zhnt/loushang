from __future__ import annotations

import json
from dataclasses import replace
from importlib.resources import files
from math import isfinite
from pathlib import Path
from typing import Any

from loushang.ai.model.domain import (
    ALLOWED_MODALITIES,
    AdapterConfig,
    Auth,
    Capabilities,
    Defaults,
    Endpoint,
    Model,
    Pricing,
    Provider,
    adapter_config_allowed_keys,
    adapter_config_from_raw,
)
from loushang.ai.model.registry import ModelRegistry

ALLOWED_ROOT_KEYS = frozenset({"providers"})
ALLOWED_PROVIDER_KEYS = frozenset({"displayName", "website", "auth", "endpoints"})
ALLOWED_ENDPOINT_KEYS = frozenset(
    {
        "api",
        "displayName",
        "baseUrl",
        "baseUrlEnv",
        "region",
        "lane",
        "preferred",
        "docs",
        "auth",
        "headers",
        "adapter",
        "defaults",
        "models",
    }
)
ALLOWED_MODEL_KEYS = frozenset(
    {
        "displayName",
        "family",
        "alias",
        "knowledge",
        "releaseDate",
        "lastUpdated",
        "capabilities",
        "pricing",
        "auth",
        "adapter",
        "defaults",
        "upstreamId",
    }
)
ALLOWED_DEFAULT_KEYS = frozenset(
    {
        "contextWindow",
        "maxOutputTokens",
        "maxTokens",
        "reasoningEffort",
        "temperature",
    }
)
ALLOWED_CAPABILITY_KEYS = frozenset(
    {
        "attachment",
        "contextWindow",
        "input",
        "maxTokens",
        "output",
        "reasoning",
        "stream",
        "structuredOutput",
        "temperature",
        "toolUse",
    }
)
ALLOWED_PRICING_KEYS = frozenset(
    {"currency", "input", "output", "cacheRead", "cacheWrite"}
)
ALLOWED_AUTH_KEYS = frozenset(
    {"kind", "provider", "oauth", "apiKeyEnv", "apiKeyEnvs", "header", "prefix"}
)
ALLOWED_OAUTH_KEYS = frozenset(
    {
        "client_id",
        "authorization_endpoint",
        "token_endpoint",
        "scopes",
        "redirect_uri",
        "revocation_endpoint",
        "token_endpoint_auth_method",
    }
)
REMOVED_CATALOG_FIELDS = frozenset({"compat", "protocol", "dialect"})


def validate_model_registry_raw(raw: dict[str, Any]) -> None:
    root = _require_mapping(raw, "<root>")
    _reject_removed_field(root, "<root>", fields=frozenset({"schemaVersion"}))
    _validate_keyed_mapping(root, ALLOWED_ROOT_KEYS, "<root>")
    providers = _require_mapping(root.get("providers"), "providers")
    for provider_id, provider_raw in providers.items():
        provider_path = f"providers.{provider_id}"
        _validate_ref_segment_key(provider_id, provider_path)
        provider = _require_mapping(provider_raw, provider_path)
        _validate_keyed_mapping(provider, ALLOWED_PROVIDER_KEYS, provider_path)
        _validate_optional_str(
            provider.get("displayName"), f"{provider_path}.displayName"
        )
        _validate_optional_str(provider.get("website"), f"{provider_path}.website")
        _validate_auth_mapping(provider.get("auth"), f"{provider_path}.auth")
        endpoints = _require_mapping(
            provider.get("endpoints"), f"{provider_path}.endpoints"
        )
        for endpoint_key, endpoint_raw in endpoints.items():
            endpoint_path = f"{provider_path}.endpoints.{endpoint_key}"
            _validate_ref_segment_key(endpoint_key, endpoint_path)
            endpoint = _require_mapping(endpoint_raw, endpoint_path)
            _reject_removed_field(endpoint, endpoint_path)
            _validate_keyed_mapping(endpoint, ALLOWED_ENDPOINT_KEYS, endpoint_path)
            endpoint_api = _require_str(endpoint.get("api"), f"{endpoint_path}.api")
            _validate_optional_str(
                endpoint.get("displayName"), f"{endpoint_path}.displayName"
            )
            _validate_optional_str(endpoint.get("baseUrl"), f"{endpoint_path}.baseUrl")
            _validate_optional_str(
                endpoint.get("baseUrlEnv"), f"{endpoint_path}.baseUrlEnv"
            )
            if "baseUrl" not in endpoint and "baseUrlEnv" not in endpoint:
                raise ValueError(
                    "models registry endpoint must declare baseUrl or baseUrlEnv: "
                    f"{endpoint_path}"
                )
            _validate_optional_str(endpoint.get("region"), f"{endpoint_path}.region")
            _validate_optional_str(endpoint.get("lane"), f"{endpoint_path}.lane")
            _validate_optional_str(endpoint.get("docs"), f"{endpoint_path}.docs")
            _validate_optional_bool(
                endpoint.get("preferred"), f"{endpoint_path}.preferred"
            )
            _validate_auth_mapping(endpoint.get("auth"), f"{endpoint_path}.auth")
            if "headers" in endpoint:
                _as_str_mapping(endpoint["headers"], f"{endpoint_path}.headers")
            _validate_adapter_mapping(
                endpoint.get("adapter"), endpoint_api, f"{endpoint_path}.adapter"
            )
            _validate_openai_compatible_endpoint_contract(
                endpoint,
                endpoint_path,
                provider_id=provider_id,
            )
            _validate_defaults_mapping(
                endpoint.get("defaults"),
                f"{endpoint_path}.defaults",
            )
            models = _require_mapping(endpoint.get("models"), f"{endpoint_path}.models")
            for model_id, model_raw in models.items():
                model_path = f"{endpoint_path}.models.{model_id}"
                _validate_ref_segment_key(model_id, model_path)
                model = _require_mapping(model_raw, model_path)
                _reject_removed_field(model, model_path)
                _validate_keyed_mapping(model, ALLOWED_MODEL_KEYS, model_path)
                _validate_auth_mapping(model.get("auth"), f"{model_path}.auth")
                _validate_adapter_mapping(
                    model.get("adapter"), endpoint_api, f"{model_path}.adapter"
                )
                _validate_upstream_id(
                    model.get("upstreamId"), f"{model_path}.upstreamId"
                )
                _validate_defaults_mapping(
                    model.get("defaults"),
                    f"{model_path}.defaults",
                )
                _validate_pricing_mapping(model.get("pricing"), f"{model_path}.pricing")
                capabilities = _require_mapping(
                    model.get("capabilities"),
                    f"{model_path}.capabilities",
                )
                _validate_keyed_mapping(
                    capabilities,
                    ALLOWED_CAPABILITY_KEYS,
                    f"{model_path}.capabilities",
                )
                _validate_modalities(
                    capabilities.get("input"), f"{model_path}.capabilities.input"
                )
                _validate_modalities(
                    capabilities.get("output"), f"{model_path}.capabilities.output"
                )
                for key in (
                    "reasoning",
                    "stream",
                    "toolUse",
                    "structuredOutput",
                    "attachment",
                    "temperature",
                ):
                    if key in capabilities:
                        _validate_bool(
                            capabilities[key],
                            f"{model_path}.capabilities.{key}",
                        )
                for key in ("contextWindow", "maxTokens"):
                    if key in capabilities:
                        _validate_positive_int(
                            capabilities[key],
                            f"{model_path}.capabilities.{key}",
                        )


def _require_mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"models registry field must be an object: {path}")
    return value


def _require_str(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"models registry field must be a non-empty string: {path}")
    return value


def _validate_optional_str(value: object, path: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"models registry field must be a non-empty string: {path}")


def _validate_optional_bool(value: object, path: str) -> None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"models registry field must be a boolean: {path}")


def _validate_bool(value: object, path: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"models registry field must be a boolean: {path}")


def _validate_positive_int(value: object, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"models registry field must be a positive integer: {path}")


def _validate_optional_non_negative_number(value: object, path: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"models registry field must be a non-negative number or null: {path}"
        )


def _validate_ref_segment_key(value: object, path: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"models registry key must be a non-empty string: {path}")
    if ":" in value:
        raise ValueError(
            f"models registry provider, endpoint, and model keys must not contain ':': {path}"
        )


def _validate_keyed_mapping(
    value: object,
    allowed_keys: frozenset[str],
    path: str,
) -> None:
    if value is None:
        return
    mapping = _require_mapping(value, path)
    unknown = sorted(set(mapping) - allowed_keys)
    if unknown:
        raise ValueError(f"models registry field has unknown keys at {path}: {unknown}")


def _reject_removed_field(
    mapping: dict[str, Any],
    path: str,
    *,
    fields: frozenset[str] = REMOVED_CATALOG_FIELDS,
) -> None:
    present = sorted(set(mapping) & fields)
    if present:
        raise ValueError(
            f"models registry field is no longer supported at {path}: {present}"
        )


def _validate_adapter_mapping(value: object, api: str, path: str) -> None:
    if value is None:
        return
    mapping = _require_mapping(value, path)
    allowed_keys = adapter_config_allowed_keys(api)
    if not allowed_keys:
        raise ValueError(
            f"models registry field is not supported for api {api!r}: {path}"
        )
    unknown = sorted(set(mapping) - allowed_keys)
    if unknown:
        raise ValueError(f"models registry field has unknown keys at {path}: {unknown}")
    try:
        adapter_config_from_raw(api, mapping)
    except ValueError as error:
        raise ValueError(
            f"models registry field has invalid adapter config: {path}"
        ) from error


def _validate_auth_mapping(value: object, path: str) -> None:
    if value is None:
        return
    mapping = _require_mapping(value, path)
    unknown = sorted(set(mapping) - ALLOWED_AUTH_KEYS)
    if unknown:
        raise ValueError(f"models registry field has unknown keys at {path}: {unknown}")
    for key in ("kind", "provider", "apiKeyEnv", "header"):
        if key in mapping:
            _require_str(mapping[key], f"{path}.{key}")
    if "prefix" in mapping and not isinstance(mapping["prefix"], str):
        raise ValueError(f"models registry field must be a string: {path}.prefix")
    api_key_envs = mapping.get("apiKeyEnvs")
    if api_key_envs is not None and (
        not isinstance(api_key_envs, list)
        or not all(isinstance(item, str) and item for item in api_key_envs)
    ):
        raise ValueError(
            f"models registry field must be a string list: {path}.apiKeyEnvs"
        )
    oauth = mapping.get("oauth")
    if oauth is not None:
        oauth_mapping = _require_mapping(oauth, f"{path}.oauth")
        unknown_oauth = sorted(set(oauth_mapping) - ALLOWED_OAUTH_KEYS)
        if unknown_oauth:
            raise ValueError(
                f"models registry field has unknown keys at {path}.oauth: "
                f"{unknown_oauth}"
            )
        for key in ("client_id", "authorization_endpoint", "token_endpoint"):
            if key not in oauth_mapping:
                raise ValueError(
                    f"models registry field is required: {path}.oauth.{key}"
                )
            _require_str(oauth_mapping[key], f"{path}.oauth.{key}")
        for key in (
            "redirect_uri",
            "revocation_endpoint",
            "token_endpoint_auth_method",
        ):
            if key in oauth_mapping:
                _require_str(oauth_mapping[key], f"{path}.oauth.{key}")
        scopes = oauth_mapping.get("scopes")
        if scopes is not None and (
            not isinstance(scopes, list)
            or not all(isinstance(scope, str) and scope.strip() for scope in scopes)
            or len(set(scopes)) != len(scopes)
        ):
            raise ValueError(
                f"models registry field must be a unique string list: "
                f"{path}.oauth.scopes"
            )


def _validate_pricing_mapping(value: object, path: str) -> None:
    if value is None:
        return
    mapping = _require_mapping(value, path)
    unknown = sorted(set(mapping) - ALLOWED_PRICING_KEYS)
    if unknown:
        raise ValueError(f"models registry field has unknown keys at {path}: {unknown}")
    if "currency" in mapping and mapping["currency"] is not None:
        _require_str(mapping["currency"], f"{path}.currency")
    for key in ("input", "output", "cacheRead", "cacheWrite"):
        if key in mapping:
            _validate_optional_non_negative_number(mapping[key], f"{path}.{key}")


def _validate_defaults_mapping(value: object, path: str) -> None:
    _validate_keyed_mapping(value, ALLOWED_DEFAULT_KEYS, path)
    if value is None:
        return
    mapping = _require_mapping(value, path)
    for key in ("contextWindow", "maxTokens", "maxOutputTokens"):
        if key in mapping:
            _validate_positive_int(mapping[key], f"{path}.{key}")
    if "temperature" in mapping:
        temperature = mapping["temperature"]
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, int | float)
            or not isfinite(temperature)
        ):
            raise ValueError(
                f"models registry field must be a finite number: {path}.temperature"
            )
    if "reasoningEffort" in mapping:
        _require_str(mapping["reasoningEffort"], f"{path}.reasoningEffort")


def _validate_upstream_id(value: object, path: str) -> None:
    if value is None:
        return
    upstream_id = _require_str(value, path)
    if not upstream_id.strip():
        raise ValueError(f"models registry field must be a non-empty string: {path}")


def _validate_modalities(value: object, path: str) -> None:
    if value is None:
        return
    if (
        not isinstance(value, list)
        or not value
        or not all(
            isinstance(item, str) and item in ALLOWED_MODALITIES for item in value
        )
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"models registry field has invalid modalities: {path}")


def _validate_openai_compatible_endpoint_contract(
    endpoint: dict[str, Any],
    path: str,
    *,
    provider_id: str,
) -> None:
    if provider_id == "openai" or endpoint.get("api") != "openai-completions":
        return
    models = endpoint.get("models")
    if not isinstance(models, dict) or not models:
        return
    if not _non_empty_str(endpoint.get("baseUrl")) and not _non_empty_str(
        endpoint.get("baseUrlEnv")
    ):
        return
    if _non_empty_mapping(endpoint.get("adapter")):
        return
    raise ValueError(
        "openai-completions endpoints for non-openai providers must declare adapter: "
        f"{path}"
    )


def _non_empty_mapping(value: object) -> bool:
    return isinstance(value, dict) and bool(value)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_str_mapping(value: object, path: str) -> dict[str, str]:
    mapping = _require_mapping(value, path)
    if not all(
        isinstance(key, str) and isinstance(entry, str)
        for key, entry in mapping.items()
    ):
        raise ValueError(f"models registry field must be a string map: {path}")
    return mapping


def _auth_raw(raw: dict[str, Any]) -> dict[str, Any] | None:
    value = raw.get("auth")
    return dict(value) if isinstance(value, dict) and value else None


def _adapter_raw(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _model_adapter_config(
    endpoint_api: str,
    model_raw: dict[str, object],
) -> AdapterConfig | None:
    model_adapter_raw = _adapter_raw(model_raw.get("adapter"))
    return adapter_config_from_raw(endpoint_api, model_adapter_raw)


def _build_provider_tree(raw: dict[str, Any]) -> dict[str, Provider]:
    validate_model_registry_raw(raw)
    providers: dict[str, Provider] = {}
    for provider_id, provider_raw in raw.get("providers", {}).items():
        provider_auth_raw = _auth_raw(provider_raw)
        provider_auth = Auth.from_raw(provider_auth_raw)
        endpoints: dict[str, Endpoint] = {}
        for endpoint_key, endpoint_raw in provider_raw.get("endpoints", {}).items():
            endpoint_api = str(endpoint_raw.get("api", ""))
            endpoint_id = endpoint_key
            endpoint_specific_auth_raw = _auth_raw(endpoint_raw)
            endpoint_auth = Auth.from_raw(endpoint_specific_auth_raw)
            endpoint_adapter_raw = _adapter_raw(endpoint_raw.get("adapter"))
            endpoint_adapter = adapter_config_from_raw(
                endpoint_api, endpoint_adapter_raw
            )
            endpoint = Endpoint(
                id=endpoint_id,
                provider=provider_id,
                api=endpoint_api,
                name=endpoint_raw.get("displayName"),
                base_url=endpoint_raw.get("baseUrl"),
                base_url_env=endpoint_raw.get("baseUrlEnv"),
                region=endpoint_raw.get("region"),
                lane=endpoint_raw.get("lane"),
                preferred=bool(endpoint_raw.get("preferred", False)),
                docs=endpoint_raw.get("docs"),
                auth=endpoint_auth,
                headers=_as_str_mapping(
                    endpoint_raw.get("headers", {}),
                    f"providers.{provider_id}.endpoints.{endpoint_id}.headers",
                ),
                adapter=endpoint_adapter,
                defaults=Defaults.from_raw(endpoint_raw.get("defaults")),
            )
            models: dict[str, Model] = {}
            for model_id, model_raw in endpoint_raw.get("models", {}).items():
                model_auth_raw = _auth_raw(model_raw)
                model_auth = Auth.from_raw(model_auth_raw)
                model_adapter = _model_adapter_config(
                    endpoint.api,
                    model_raw,
                )
                model = Model(
                    id=model_id,
                    name=model_raw.get("displayName"),
                    family=model_raw.get("family"),
                    alias=model_raw.get("alias"),
                    upstream_id=model_raw.get("upstreamId"),
                    capabilities=Capabilities.from_raw(model_raw),
                    knowledge=model_raw.get("knowledge"),
                    release_date=model_raw.get("releaseDate"),
                    last_updated=model_raw.get("lastUpdated"),
                    auth=model_auth,
                    pricing=Pricing.from_raw(model_raw.get("pricing")),
                    adapter=model_adapter,
                    defaults=Defaults.from_raw(model_raw.get("defaults")),
                )
                models[model_id] = model
            endpoints[endpoint.id] = Endpoint(
                id=endpoint.id,
                provider=provider_id,
                api=endpoint.api,
                name=endpoint.name,
                base_url=endpoint.base_url,
                base_url_env=endpoint.base_url_env,
                region=endpoint.region,
                lane=endpoint.lane,
                preferred=endpoint.preferred,
                docs=endpoint.docs,
                auth=endpoint.auth,
                headers=endpoint.headers,
                defaults=endpoint.defaults,
                models=models,
                adapter=endpoint.adapter,
            )
        providers[provider_id] = Provider(
            id=provider_id,
            name=provider_raw.get("displayName"),
            website=provider_raw.get("website"),
            auth=provider_auth,
            endpoints=endpoints,
        )
    return providers


def _build_registry(raw: dict[str, Any]) -> ModelRegistry:
    return ModelRegistry.from_providers(_build_provider_tree(raw))


_BUILTIN_CATALOG_RESOURCE = "models.json"


def _load_builtin_raw() -> dict[str, Any]:
    return json.loads(
        files("loushang.ai.model")
        .joinpath(_BUILTIN_CATALOG_RESOURCE)
        .read_text(encoding="utf-8")
    )


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("models registry file has invalid JSON") from error


def _build_provider_tree_from_file(path: Path) -> dict[str, Provider]:
    try:
        return _build_provider_tree(_load_json_file(path))
    except ValueError as error:
        raise ValueError(f"models registry file {path}: {error}") from error


def load_builtin_model_registry() -> ModelRegistry:
    return _build_registry(_load_builtin_raw())


def load_model_registry_from_file(path: str | Path) -> ModelRegistry:
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return ModelRegistry.from_providers(_build_provider_tree_from_file(resolved))


def load_model_registry_from_directory(path: str | Path) -> ModelRegistry:
    resolved = Path(path)
    if not resolved.is_dir():
        raise FileNotFoundError(str(resolved))
    return _combine_model_registries(_model_registry_sources_from_directory(resolved))


def _model_registry_sources_from_directory(
    path: Path,
) -> list[tuple[str, dict[str, Provider]]]:
    return [
        (str(child), _build_provider_tree_from_file(child))
        for child in sorted(path.glob("*.json"))
    ]


def _provider_metadata(provider: Provider) -> Provider:
    return replace(provider, endpoints={})


def _endpoint_metadata(endpoint: Endpoint) -> Endpoint:
    return replace(endpoint, models={})


def _combine_model_registries(
    sources: list[tuple[str, dict[str, Provider]]],
) -> ModelRegistry:
    providers: dict[str, Provider] = {}
    seen_providers: dict[str, tuple[str, str]] = {}
    seen_endpoints: dict[tuple[str, str], tuple[str, str]] = {}
    seen_models: dict[tuple[str, str, str], tuple[str, str]] = {}
    for source, provider_tree in sources:
        for provider in provider_tree.values():
            provider_path = f"providers.{provider.id}"
            existing_provider = providers.get(provider.id)
            for endpoint in provider.list_endpoints():
                for model in endpoint.list_models():
                    model_key = (provider.id, endpoint.id, model.id)
                    field_path = (
                        f"providers.{provider.id}.endpoints.{endpoint.id}."
                        f"models.{model.id}"
                    )
                    if model_key in seen_models:
                        first_source, first_path = seen_models[model_key]
                        raise ValueError(
                            "duplicate model id "
                            f"{provider.id}:{endpoint.id}:{model.id} at "
                            f"{source}:{field_path}; first defined at "
                            f"{first_source}:{first_path}"
                        )
                    seen_models[model_key] = (source, field_path)

            if existing_provider is None:
                seen_providers[provider.id] = (source, provider_path)
            elif _provider_metadata(existing_provider) != _provider_metadata(provider):
                first_source, first_path = seen_providers[provider.id]
                raise ValueError(
                    "conflicting provider metadata "
                    f"{provider.id} at {source}:{provider_path}; "
                    f"first defined at {first_source}:{first_path}"
                )

            endpoints = dict(existing_provider.endpoints) if existing_provider else {}
            for endpoint in provider.list_endpoints():
                endpoint_key = (provider.id, endpoint.id)
                endpoint_path = f"{provider_path}.endpoints.{endpoint.id}"
                existing_endpoint = endpoints.get(endpoint.id)
                if existing_endpoint is None:
                    seen_endpoints[endpoint_key] = (source, endpoint_path)
                elif _endpoint_metadata(existing_endpoint) != _endpoint_metadata(
                    endpoint
                ):
                    first_source, first_path = seen_endpoints[endpoint_key]
                    raise ValueError(
                        "conflicting endpoint metadata "
                        f"{provider.id}:{endpoint.id} at {source}:{endpoint_path}; "
                        f"first defined at {first_source}:{first_path}"
                    )

                models = dict(existing_endpoint.models) if existing_endpoint else {}
                for model in endpoint.list_models():
                    models[model.id] = model
                if existing_endpoint is None:
                    endpoints[endpoint.id] = endpoint
                else:
                    endpoints[endpoint.id] = replace(existing_endpoint, models=models)
            if existing_provider is None:
                providers[provider.id] = replace(provider, endpoints=endpoints)
            else:
                providers[provider.id] = replace(existing_provider, endpoints=endpoints)
    return ModelRegistry.from_providers(providers)


def _load_layered_model_registry(
    *,
    user_dir: Path | None = None,
    project_dir: Path | None = None,
) -> ModelRegistry:
    sources = [("<builtin>", _build_provider_tree(_load_builtin_raw()))]
    for directory in (user_dir, project_dir):
        if directory is not None and directory.is_dir():
            sources.extend(_model_registry_sources_from_directory(directory))
    return _combine_model_registries(sources)

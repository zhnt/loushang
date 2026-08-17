"""Normalize native extension provider configuration into AI value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from loushang.ai.model import (
    Auth,
    Capabilities,
    Defaults,
    Endpoint,
    Model,
    OpenAICompletionsConfig,
    Pricing,
    Provider,
    adapter_config_from_raw,
    merge_adapter_config,
)


def provider_from_extension_config(
    name: str,
    config: object,
    *,
    existing_provider: Provider | None = None,
) -> Provider:
    if isinstance(config, Provider):
        return config
    if not isinstance(config, dict):
        raise TypeError("Extension provider config must be a Provider or dict.")
    return _native_provider_from_extension_dict(name, config, existing_provider=existing_provider)


def _native_provider_from_extension_dict(
    name: str,
    config: dict[object, object],
    *,
    existing_provider: Provider | None = None,
) -> Provider:
    _reject_pi_style_provider_config(name, config)
    endpoints_raw = config.get("endpoints")
    if endpoints_raw is None and existing_provider is None:
        raise ValueError(f'Provider {name}: loushang-native "endpoints" schema is required.')
    if endpoints_raw is not None and not isinstance(endpoints_raw, Mapping):
        raise TypeError(f'Provider {name}: "endpoints" must be a dict.')

    provider = existing_provider or Provider(id=name)
    endpoints = dict(provider.endpoints)
    if isinstance(endpoints_raw, Mapping):
        for endpoint_id, endpoint_raw in endpoints_raw.items():
            if not isinstance(endpoint_id, str):
                raise TypeError(f"Provider {name}: endpoint ids must be strings.")
            if not isinstance(endpoint_raw, Mapping):
                raise TypeError(f"Provider {name}, endpoint {endpoint_id}: endpoint config must be a dict.")
            endpoints[endpoint_id] = _native_endpoint_from_extension_dict(
                provider=name,
                endpoint_id=endpoint_id,
                config=endpoint_raw,
                existing_endpoint=endpoints.get(endpoint_id),
            )

    auth = _auth_from_native_raw(config.get("auth"))
    return replace(
        provider,
        name=_optional_string(config.get("displayName") or config.get("name")) or provider.name,
        website=_optional_string(config.get("website")) or provider.website,
        auth=auth or provider.auth,
        endpoints=endpoints,
    )


_PI_STYLE_PROVIDER_KEYS: frozenset[str] = frozenset(
    {
        "api",
        "endpoint",
        "endpointId",
        "endpoint_id",
        "baseUrl",
        "base_url",
        "apiKey",
        "api_key",
        "headers",
        "authHeader",
        "auth_header",
        "models",
    }
)
_MIXED_PROVIDER_CONCERN_KEYS: frozenset[str] = frozenset({"streamSimple", "stream_simple", "oauth"})


def _reject_pi_style_provider_config(name: str, config: Mapping[object, object]) -> None:
    mixed_keys = sorted(key for key in _MIXED_PROVIDER_CONCERN_KEYS if key in config)
    if mixed_keys:
        raise ValueError(
            f"Provider {name}: {', '.join(mixed_keys)} must be registered through explicit API/OAuth APIs, "
            "not provider/model config."
        )
    pi_keys = sorted(key for key in _PI_STYLE_PROVIDER_KEYS if key in config)
    if "endpoints" not in config and pi_keys:
        raise ValueError(
            f'Provider {name}: loushang-native "endpoints" schema is required; '
            "pi-style flat provider config is not supported by register_provider()."
        )
    if pi_keys:
        raise ValueError(
            f"Provider {name}: top-level {', '.join(pi_keys)} are pi-style provider fields; "
            'put endpoint/model fields under "endpoints".'
        )


def _native_endpoint_from_extension_dict(
    *,
    provider: str,
    endpoint_id: str,
    config: Mapping[object, object],
    existing_endpoint: Endpoint | None = None,
) -> Endpoint:
    api = _optional_string(config.get("api")) or (existing_endpoint.api if existing_endpoint is not None else None)
    if api is None:
        raise ValueError(f'Provider {provider}, endpoint {endpoint_id}: "api" is required.')
    defaults = Defaults.from_raw(_optional_mapping(config.get("defaults")))
    adapter = merge_adapter_config(
        existing_endpoint.adapter if existing_endpoint is not None else None,
        _adapter_config_from_native_raw(
            api,
            _optional_mapping(config.get("adapter"))
            or _optional_mapping(config.get("compat")),
        ),
    )
    endpoint = Endpoint(
        id=endpoint_id,
        api=api,
        provider=provider,
        name=_optional_string(config.get("displayName") or config.get("name"))
        or (existing_endpoint.name if existing_endpoint is not None else None),
        base_url=_optional_string(config.get("baseUrl")) or (existing_endpoint.base_url if existing_endpoint is not None else None),
        base_url_env=_optional_string(config.get("baseUrlEnv"))
        or (existing_endpoint.base_url_env if existing_endpoint is not None else None),
        region=_optional_string(config.get("region")) or (existing_endpoint.region if existing_endpoint is not None else None),
        lane=_optional_string(config.get("lane")) or (existing_endpoint.lane if existing_endpoint is not None else None),
        preferred=_optional_bool(config.get("preferred"))
        if "preferred" in config
        else (existing_endpoint.preferred if existing_endpoint is not None else False),
        docs=_optional_string(config.get("docs")) or (existing_endpoint.docs if existing_endpoint is not None else None),
        auth=_auth_from_native_raw(
            config.get("auth") if "auth" in config else config.get("authOverride")
        )
        or (existing_endpoint.auth if existing_endpoint is not None else None),
        adapter=adapter,
        defaults=(existing_endpoint.defaults if existing_endpoint is not None else Defaults()).merged(defaults),
    )
    models_raw = config.get("models")
    if models_raw is None:
        models = dict(existing_endpoint.models) if existing_endpoint is not None else {}
    else:
        models = _native_models_from_extension_dict(
            provider=provider,
            endpoint=endpoint_id,
            endpoint_api=api,
            models=models_raw,
        )
    if models:
        endpoint = replace(endpoint, models=models)
    return endpoint


def _native_models_from_extension_dict(
    provider: str,
    endpoint: str,
    endpoint_api: str,
    models: object,
) -> dict[str, Model]:
    if not isinstance(models, Mapping):
        raise TypeError(f'Provider {provider}, endpoint {endpoint}: "models" must be a dict.')
    parsed: dict[str, Model] = {}
    for model_id, raw in models.items():
        if isinstance(raw, Model):
            parsed[model_id if isinstance(model_id, str) else raw.id] = raw
            continue
        if not isinstance(model_id, str):
            raise TypeError(f"Provider {provider}, endpoint {endpoint}: model ids must be strings.")
        if not isinstance(raw, Mapping):
            raise TypeError(f"Provider {provider}, endpoint {endpoint}, model {model_id}: model config must be a dict.")
        parsed[model_id] = Model(
            id=model_id,
            provider=provider,
            endpoint=endpoint,
            name=_optional_string(raw.get("displayName") or raw.get("name")),
            family=_optional_string(raw.get("family")),
            alias=_optional_string(raw.get("alias")),
            knowledge=_optional_string(raw.get("knowledge")),
            release_date=_optional_string(raw.get("releaseDate")),
            last_updated=_optional_string(raw.get("lastUpdated")),
            capabilities=Capabilities.from_raw(raw),
            pricing=Pricing.from_raw(_optional_mapping(raw.get("pricing")) or _optional_mapping(raw.get("cost"))),
            adapter=_adapter_config_from_native_raw(
                endpoint_api,
                _optional_mapping(raw.get("adapter"))
                or _optional_mapping(raw.get("compat")),
            ),
            defaults=Defaults.from_raw(_optional_mapping(raw.get("defaults"))),
        )
    return parsed


def _adapter_config_from_native_raw(api: str, raw: Mapping[str, object] | None):
    if raw is None:
        return None
    if api == "openai-completions" and any(
        key.startswith("supports") or key in {"maxTokensField", "thinkingFormat"}
        for key in raw
    ):
        return OpenAICompletionsConfig.from_raw(
            {
                new_key: raw[old_key]
                for old_key, new_key in {
                    "supportsStore": "store",
                    "supportsDeveloperRole": "developerRole",
                    "supportsUsageInStreaming": "streamingUsage",
                    "supportsReasoningEffort": "reasoningEffort",
                    "supportsStrictMode": "strictSchema",
                    "supportsPromptCacheKey": "promptCacheKey",
                    "supportsLongCacheRetention": "longCacheRetention",
                    "maxTokensField": "maxOutputTokensField",
                    "thinkingFormat": "reasoningFormat",
                }.items()
                if old_key in raw and raw[old_key] is not None
            }
        )
    return adapter_config_from_raw(api, raw)


def _auth_from_native_raw(raw: object) -> Auth | None:
    return Auth.from_raw(raw) if isinstance(raw, Mapping) else None


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_bool(value: object) -> bool:
    return value if isinstance(value, bool) else False

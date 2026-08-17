from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from loushang.ai.auth.credentials import OAuthCredential
from loushang.ai.auth.oauth.base import OAuthProvider
from loushang.ai.auth.resolver import resolve_auth
from loushang.ai.auth.sources import CredentialSource
from loushang.ai.auth.store import FileCredentialStore
from loushang.ai.auth.support import resolve_auth_for_model
from loushang.ai.context import NormalizedContext
from loushang.ai.model import Model
from loushang.ai.model.domain import (
    AdapterConfig,
    AnthropicMessagesConfig,
    Endpoint,
    OpenAICompletionsConfig,
    OpenAIResponsesConfig,
    default_adapter_config,
)
from loushang.ai.options import (
    CallOptions,
    get_max_output_tokens,
    get_reasoning_options,
)
from loushang.ai.provider.protocol import ProviderContext, ProviderRequest


def ensure_request_api(provider_api: str, request: ProviderRequest) -> ProviderRequest:
    if request.model.api != provider_api:
        raise ValueError(
            f"Mismatched api: provider={provider_api!r} "
            f"request.model.api={request.model.api!r}"
        )
    return request


def normalize_provider_request_for_api(
    provider_api: str,
    request: ProviderRequest,
) -> ProviderRequest:
    request = ensure_request_api(provider_api, request)
    adapter_config = request.model.adapter
    if provider_api == "openai-completions":
        _ensure_core_adapter_config(
            adapter_config, provider_api, OpenAICompletionsConfig
        )
    if provider_api == "openai-responses":
        _ensure_core_adapter_config(adapter_config, provider_api, OpenAIResponsesConfig)
    if provider_api == "anthropic-messages":
        _ensure_core_adapter_config(
            adapter_config, provider_api, AnthropicMessagesConfig
        )
    return request


def _ensure_core_adapter_config(
    adapter_config: object | None,
    api: str,
    expected_type: type[AdapterConfig],
) -> AdapterConfig:
    if adapter_config is None:
        resolved = default_adapter_config(api)
        if resolved is None:
            raise ValueError(f"No default adapter config for api: {api}")
        return resolved
    if not isinstance(adapter_config, expected_type):
        raise TypeError(f"adapter_config for {api} must be {expected_type.__name__}")
    return adapter_config


def resolve_endpoint_for_model(
    model: Model,
) -> Endpoint | None:
    identity = _concrete_model_identity(model)
    if identity is None:
        return None
    provider_id, endpoint_id, api = identity
    return Endpoint(
        id=endpoint_id,
        provider=provider_id,
        api=api,
        base_url=model.base_url,
        base_url_env=model.base_url_env,
        region=model.region,
        lane=model.lane,
        preferred=model.preferred_endpoint,
        auth=model.auth,
        headers=model.headers,
        adapter=model.adapter,
        defaults=model.defaults,
        models={model.id: model},
    )


def resolve_request_for_model(
    model: Model,
    *,
    context: ProviderContext | None = None,
    options=None,
    env: dict[str, str] | None = None,
) -> ProviderRequest:
    if not isinstance(model, Model):
        raise TypeError("resolve_request_for_model model must be Model")
    identity = _concrete_model_identity(model)
    if identity is None:
        raise ValueError(
            f"Model {model.id!r} is not bound to a concrete provider endpoint"
        )
    resolved_env = dict(os.environ) if env is None else env
    base_url = _resolve_base_url(model, resolved_env)
    auth_view = resolve_auth_for_model(
        model,
        options=options,
        env=resolved_env,
    )
    defaults = dict(model.defaults)
    headers = dict(auth_view.headers)
    max_tokens = _resolve_max_tokens(options, defaults)
    reasoning_enabled, reasoning_effort = _resolve_reasoning(options, defaults)
    temperature = _resolve_temperature(options, defaults)
    return ProviderRequest(
        model=model,
        context=context or NormalizedContext(system_prompt=None),
        options=options,
        base_url=base_url,
        headers=headers,
        max_output_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        reasoning_enabled=reasoning_enabled,
        temperature=temperature,
    )


async def prepare_request_for_model(
    model: Model,
    *,
    context: ProviderContext | None = None,
    options: CallOptions | None = None,
    credential: OAuthCredential | None = None,
    credential_file: str | Path | None = None,
    store: FileCredentialStore | None = None,
    providers: Mapping[str, OAuthProvider] | None = None,
    sources: Mapping[str, CredentialSource] | None = None,
    env: Mapping[str, str] | None = None,
    refresh_window_seconds: float = 60.0,
    now: float | None = None,
) -> ProviderRequest:
    """Resolve lifecycle credentials before creating the provider request."""

    resolved_env = dict(os.environ) if env is None else dict(env)
    request_auth = await resolve_auth(
        model,
        options=options,
        credential=credential,
        credential_file=credential_file,
        store=store,
        providers=providers,
        sources=sources,
        env=resolved_env,
        refresh_window_seconds=refresh_window_seconds,
        now=now,
    )
    if options is None:
        prepared_options = CallOptions(auth=request_auth) if request_auth else None
    else:
        prepared_options = replace(
            options,
            auth=request_auth,
            credential=None,
            credential_file=None,
        )
    return resolve_request_for_model(
        model,
        context=context,
        options=prepared_options,
        env=resolved_env,
    )


def _concrete_model_identity(model: Model) -> tuple[str, str, str] | None:
    if not isinstance(model, Model):
        return None
    provider_id = model.provider_id
    endpoint_id = model.endpoint_id
    api = model.api
    if not provider_id or not endpoint_id or not isinstance(api, str) or not api:
        return None
    return provider_id, endpoint_id, api


def _resolve_base_url(
    model: Model,
    env: dict[str, str] | None,
) -> str:
    resolved_env = env or {}
    base_url_env = model.base_url_env
    if base_url_env and base_url_env in resolved_env:
        value = resolved_env[base_url_env]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Environment variable {base_url_env} must contain a non-empty base URL"
            )
        return _validate_resolved_base_url(value)
    base_url = model.base_url
    if base_url is None:
        if base_url_env:
            raise ValueError(
                f"Environment variable {base_url_env} is required for provider base URL"
            )
        raise ValueError(f"Model {model.id!r} has no configured provider base URL")
    return _validate_resolved_base_url(_expand_env_template(base_url, resolved_env))


def _expand_env_template(value: str, env: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        replacement = env.get(name)
        if not isinstance(replacement, str) or not replacement.strip():
            raise ValueError(
                f"Environment variable {name} is required by baseUrl template"
            )
        return replacement

    return re.sub(r"\{([A-Z_][A-Z0-9_]*)\}", _replace, value)


def _validate_resolved_base_url(value: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ValueError("Provider base URL must be a non-empty string")
    if "{" in resolved or "}" in resolved:
        raise ValueError("Provider base URL contains an unresolved template")
    return resolved


def _resolve_max_tokens(options, defaults: dict[str, object]) -> int | None:
    value = get_max_output_tokens(options)
    if isinstance(value, int):
        return value
    if value is None:
        default_value = defaults.get("maxOutputTokens")
        if not isinstance(default_value, int):
            default_value = defaults.get("maxTokens")
        if isinstance(default_value, int):
            value = default_value
    return value if isinstance(value, int) else None


def _resolve_reasoning(
    options,
    defaults: dict[str, Any],
) -> tuple[bool | None, str | None]:
    default_effort = defaults.get("reasoningEffort")
    if not isinstance(default_effort, str):
        default_effort = None

    reasoning = get_reasoning_options(options)
    if reasoning is None:
        return (True, default_effort) if default_effort is not None else (None, None)
    if reasoning.enabled is False:
        return False, None

    has_explicit_request = (
        reasoning.enabled is True
        or reasoning.effort is not None
        or reasoning.budget_tokens is not None
        or reasoning.expose_summary
    )
    if has_explicit_request:
        return True, reasoning.effort or default_effort
    return (True, default_effort) if default_effort is not None else (None, None)


def _resolve_temperature(options, defaults: dict[str, Any]) -> float | int | None:
    value = getattr(options, "temperature", None) if options is not None else None
    if value is None:
        default_value = defaults.get("temperature")
        if isinstance(default_value, int | float):
            value = default_value
    return value if isinstance(value, int | float) else None

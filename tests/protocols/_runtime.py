from __future__ import annotations

from dataclasses import replace

from loushang.ai.context import NormalizedContext
from loushang.ai.model import (
    AdapterConfig,
    Auth,
    Capabilities,
    Defaults,
    Endpoint,
    Model,
    ModelRegistry,
    Pricing,
    Provider,
)
from loushang.ai.provider import (
    ProviderRequest,
    normalize_provider_request_for_api,
    resolve_request_for_model,
)
from loushang.ai.provider.runtime import start_provider_runtime


def start_test_provider_stream(
    provider,
    model,
    normalized_context,
    options=None,
    *,
    request: ProviderRequest | None = None,
):
    resolved = provider_request_for_test(
        provider,
        model,
        normalized_context,
        options=options,
        request=request,
    )
    return start_provider_runtime(
        lambda: provider.invoke_raw(resolved),
        options=options,
        request=resolved,
    )


def provider_request_for_test(
    provider,
    model,
    normalized_context,
    *,
    options=None,
    request: ProviderRequest | None = None,
) -> ProviderRequest:
    if request is None:
        if not isinstance(model, Model) or not model.api:
            model = bound_test_model(model, api=provider.api, options=options)
        resolved = resolve_request_for_model(
            model,
            context=normalized_context,
            options=options,
        )
    else:
        resolved = request
    resolved = replace(
        resolved,
        context=normalized_context,
        options=options,
    )
    return normalize_provider_request_for_api(provider.api, resolved)


def bound_test_model(
    model: object,
    *,
    api: str,
    provider_id: str | None = None,
    endpoint_id: str | None = None,
    options: object | None = None,
    base_url: str | None = None,
    adapter_config: AdapterConfig | None = None,
    capabilities: Capabilities | None = None,
    defaults: dict[str, object] | None = None,
    auth: Auth | None = None,
    endpoint_headers: dict[str, str] | None = None,
    upstream_model_id: str | None = None,
) -> Model:
    provider_id = provider_id or str(getattr(model, "provider_id", "test-provider"))
    endpoint_id = endpoint_id or str(getattr(model, "endpoint_id", api))
    model_id = str(getattr(model, "id", "test-model"))
    if capabilities is None:
        capabilities = Capabilities(
            input=tuple(getattr(model, "input", ("text",))),
            reasoning=bool(getattr(model, "reasoning", False)),
            max_tokens=getattr(model, "max_tokens", None),
        )
    pricing = getattr(model, "pricing", None)
    if not isinstance(pricing, Pricing):
        pricing = None
    auth = auth or _test_auth(options)
    resolved_base_url = (
        base_url or getattr(model, "base_url", None) or "https://provider.test/v1"
    )
    endpoint = Endpoint(
        id=endpoint_id,
        provider=provider_id,
        api=api,
        base_url=resolved_base_url,
        auth=auth,
        headers=endpoint_headers or {},
        adapter=adapter_config,
        defaults=Defaults.from_raw(defaults or getattr(model, "defaults", None)),
        models={
            model_id: Model(
                id=model_id,
                provider=provider_id,
                endpoint=endpoint_id,
                capabilities=capabilities,
                pricing=pricing,
                upstream_id=upstream_model_id,
            )
        },
    )
    return ModelRegistry.from_providers(
        {
            provider_id: Provider(
                id=provider_id,
                endpoints={endpoint_id: endpoint},
            )
        }
    ).get_model(provider_id, endpoint_id, model_id)


def make_provider_request(
    model: object,
    *,
    api: str,
    provider_id: str | None = None,
    endpoint_id: str | None = None,
    options: object | None = None,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    adapter_config: AdapterConfig | None = None,
    capabilities: Capabilities | None = None,
    defaults: dict[str, object] | None = None,
    auth: Auth | None = None,
    endpoint_headers: dict[str, str] | None = None,
    upstream_model_id: str | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    reasoning_enabled: bool | None = None,
    temperature: float | int | None = None,
) -> ProviderRequest:
    request_model = bound_test_model(
        model,
        api=api,
        provider_id=provider_id,
        endpoint_id=endpoint_id,
        options=options,
        base_url=base_url,
        adapter_config=adapter_config,
        capabilities=capabilities,
        defaults=defaults,
        auth=auth,
        endpoint_headers=endpoint_headers,
        upstream_model_id=upstream_model_id,
    )
    return ProviderRequest(
        model=request_model,
        context=NormalizedContext(system_prompt=None),
        options=options,
        base_url=request_model.base_url or "https://provider.test/v1",
        headers=dict(headers or {}),
        max_output_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        reasoning_enabled=reasoning_enabled,
        temperature=temperature,
    )


def _test_auth(options: object | None) -> Auth:
    from loushang.ai.auth import ApiKeyAuth, OAuthBearerAuth

    if isinstance(getattr(options, "auth", None), OAuthBearerAuth):
        return Auth(kind="oauth")
    if isinstance(getattr(options, "auth", None), ApiKeyAuth):
        return Auth(kind="apiKey")
    return Auth(kind="none")

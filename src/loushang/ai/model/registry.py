from __future__ import annotations

from dataclasses import replace

from loushang.ai.model.domain import (
    Auth,
    Defaults,
    Endpoint,
    Model,
    OpenAICompletionsConfig,
    Provider,
    merge_adapter_config,
)
from loushang.ai.model.selection import ModelSelection
from loushang.ai.output_budget import default_output_tokens_from_capability

# 全局
_default_model_registry: ModelRegistry | None = None


def get_default_model_registry() -> "ModelRegistry":
    global _default_model_registry
    if _default_model_registry is None:
        from pathlib import Path

        from loushang.ai.model.loader import _load_layered_model_registry

        _default_model_registry = _load_layered_model_registry(
            user_dir=Path.home() / ".loushang" / "models",
        )
    return _default_model_registry


def clear_default_model_registry() -> None:
    global _default_model_registry
    _default_model_registry = None


def reload_default_model_registry() -> "ModelRegistry":
    global _default_model_registry
    from pathlib import Path

    from loushang.ai.model.loader import _load_layered_model_registry

    _default_model_registry = _load_layered_model_registry(
        user_dir=Path.home() / ".loushang" / "models",
    )
    return _default_model_registry


def resolve_model_endpoint(
    model: Model,
    *,
    registry: "ModelRegistry | None" = None,
) -> Endpoint | None:
    if registry is None and has_bound_endpoint_context(model):
        return _endpoint_snapshot_from_model(model)
    resolved_registry = (
        registry if registry is not None else get_default_model_registry()
    )
    return resolved_registry.get_endpoint(model.provider_id, model.endpoint_id)


def has_bound_endpoint_context(model: Model) -> bool:
    model_api = getattr(model, "api", None)
    if not isinstance(model_api, str) or not model_api:
        return False
    if (
        getattr(model, "base_url", None)
        or getattr(model, "base_url_env", None)
        or getattr(model, "region", None)
        or getattr(model, "lane", None)
        or getattr(model, "preferred_endpoint", False)
        or getattr(model, "auth", None) is not None
        or getattr(model, "headers", None)
    ):
        return True
    return False


def _endpoint_snapshot_from_model(model: Model) -> Endpoint:
    defaults = getattr(model, "defaults", Defaults())
    if not isinstance(defaults, Defaults):
        defaults = Defaults.from_raw(defaults)
    return Endpoint(
        id=model.endpoint_id,
        provider=model.provider_id,
        api=getattr(model, "api", None) or model.endpoint_id,
        base_url=getattr(model, "base_url", None),
        base_url_env=getattr(model, "base_url_env", None),
        region=getattr(model, "region", None),
        lane=getattr(model, "lane", None),
        preferred=getattr(model, "preferred_endpoint", False),
        auth=getattr(model, "auth", None),
        headers=getattr(model, "headers", {}),
        adapter=getattr(model, "adapter", None),
        defaults=defaults,
        models={model.id: model},
    )


def _normalize_providers(providers: dict[str, Provider]) -> dict[str, Provider]:
    return {
        provider_id: _normalize_provider(provider_id, provider)
        for provider_id, provider in providers.items()
    }


def _normalize_provider(provider_id: str, provider: Provider) -> Provider:
    provider_auth = getattr(provider, "auth", None)
    endpoints = {
        endpoint_id: _normalize_endpoint(
            provider_id,
            endpoint,
            provider_auth=provider_auth,
        )
        for endpoint_id, endpoint in provider.endpoints.items()
    }
    return replace(provider, id=provider_id, endpoints=endpoints)


def _normalize_endpoint(
    provider_id: str,
    endpoint: Endpoint,
    *,
    provider_auth: Auth | None = None,
) -> Endpoint:
    normalized_endpoint = replace(
        endpoint,
        _provider_key=provider_id,
    )
    if not normalized_endpoint.models:
        return normalized_endpoint
    return replace(
        normalized_endpoint,
        models={
            model_id: _model_with_effective_context(
                model,
                normalized_endpoint,
                provider_auth=provider_auth,
            )
            for model_id, model in normalized_endpoint.models.items()
        },
    )


def _model_with_effective_context(
    model: Model,
    endpoint: Endpoint,
    *,
    provider_auth: Auth | None = None,
) -> Model:
    adapter = merge_adapter_config(endpoint.adapter, model.adapter)
    auth = _merge_effective_auth(provider_auth, endpoint.auth, model.auth)
    return replace(
        model,
        _endpoint_key=endpoint.endpoint_key,
        api=endpoint.api,
        base_url=endpoint.base_url,
        base_url_env=endpoint.base_url_env,
        region=endpoint.region,
        lane=endpoint.lane,
        preferred_endpoint=endpoint.preferred,
        auth=auth,
        headers=endpoint.headers,
        adapter=adapter,
        defaults=_effective_model_defaults(endpoint, model, adapter),
    )


def _merge_effective_auth(
    provider_auth: Auth | None,
    endpoint_auth: Auth | None,
    model_auth: Auth | None,
) -> Auth | None:
    if model_auth is not None:
        return model_auth
    if endpoint_auth is not None:
        return endpoint_auth
    return provider_auth


def _effective_model_defaults(
    endpoint: Endpoint,
    model: Model,
    adapter: object | None,
) -> Defaults:
    defaults = dict(endpoint.defaults)
    defaults.update(model.defaults)
    capabilities = model.capabilities
    max_tokens = capabilities.max_tokens
    if endpoint.api == "anthropic-messages":
        defaults.setdefault(
            "maxTokens",
            default_output_tokens_from_capability(max_tokens),
        )
    elif endpoint.lane == "coding" and endpoint.api == "openai-completions":
        if isinstance(max_tokens, int):
            defaults.setdefault(
                "maxOutputTokens",
                default_output_tokens_from_capability(max_tokens),
            )
        if capabilities.temperature:
            defaults.setdefault("temperature", 0.2)
        if isinstance(adapter, OpenAICompletionsConfig) and adapter.reasoning_effort:
            defaults.setdefault("reasoningEffort", "medium")
        if isinstance(capabilities.context_window, int):
            defaults.setdefault("contextWindow", capabilities.context_window)
    elif endpoint.api == "openai-responses" and isinstance(max_tokens, int):
        defaults.setdefault(
            "maxOutputTokens",
            default_output_tokens_from_capability(max_tokens),
        )
    return Defaults.from_raw(defaults)


def resolve_model_api(
    model: Model,
    *,
    registry: "ModelRegistry | None" = None,
) -> str:
    model_api = getattr(model, "api", None)
    if isinstance(model_api, str) and model_api:
        return model_api
    endpoint = resolve_model_endpoint(model, registry=registry)
    if endpoint is None:
        raise ValueError(
            f"Endpoint not found for model: {model.provider_id}:{model.endpoint_id}:{model.id}"
        )
    return endpoint.api


def format_model_ref(model: Model) -> str:
    return f"{model.provider_id}:{model.endpoint_id}:{model.id}"


def _parse_explicit_model_ref(ref: str) -> tuple[str, str, str] | None:
    if ref.count(":") < 2:
        return None
    provider, rest = ref.split(":", 1)
    endpoint, model_id = rest.rsplit(":", 1)
    if not provider or not endpoint or not model_id:
        return None
    return provider, endpoint, model_id


class AmbiguousModelReference(ValueError):
    def __init__(self, ref: str, candidates: list[Model]) -> None:
        self.ref = ref
        self.candidates = tuple(format_model_ref(model) for model in candidates)
        message = f"Ambiguous model reference {ref!r}; use one of: " + ", ".join(
            self.candidates
        )
        super().__init__(message)


def resolve_model_ref(
    registry: "ModelRegistry",
    ref: str,
    *,
    provider: str | None = None,
    endpoint: str | None = None,
    api: str | None = None,
) -> Model:
    if explicit_ref := _parse_explicit_model_ref(ref):
        p, e, mid = explicit_ref
        return registry.get_model(p, e, mid)
    if ref.count(":") == 1 and provider is None and endpoint is None:
        p, mid = ref.split(":", 1)
        if p and mid:
            return _resolve_provider_model_ref(registry, p, mid, ref=ref)
    if "/" in ref and provider is None and endpoint is None:
        p, mid = ref.split("/", 1)
        if p and mid:
            return _resolve_provider_model_ref(registry, p, mid)
    if provider and endpoint:
        return registry.get_model(provider, endpoint, ref)
    if provider:
        return _resolve_provider_model_ref(registry, provider, ref)
    if api:
        candidates = [
            model
            for model in registry.list_models(model_id=ref)
            if resolve_model_api(model, registry=registry) == api
        ]
        return _resolve_candidates(registry, ref, candidates)
    return registry.get_model(ref)


def _resolve_provider_model_ref(
    registry: "ModelRegistry",
    provider: str,
    model_id: str,
    *,
    ref: str | None = None,
) -> Model:
    candidates = registry.list_models(provider=provider, model_id=model_id)
    return _resolve_candidates(registry, ref or f"{provider}/{model_id}", candidates)


def _resolve_candidates(
    _registry: "ModelRegistry",
    ref: str,
    candidates: list[Model],
) -> Model:
    if not candidates:
        raise KeyError(ref)
    if len(candidates) == 1:
        return candidates[0]
    raise AmbiguousModelReference(ref, candidates)


class ModelRegistry:
    def __init__(self, providers: dict[str, Provider] | None = None) -> None:
        raw_providers = dict(providers or {})
        self._providers = _normalize_providers(raw_providers)
        self._endpoints = {
            (provider.id, endpoint.id): endpoint
            for provider in self._providers.values()
            for endpoint in provider.endpoints.values()
        }
        self._models = {
            (provider.id, endpoint.id, model.id): model
            for provider in self._providers.values()
            for endpoint in provider.endpoints.values()
            for model in endpoint.models.values()
        }

    @property
    def providers(self) -> dict[str, Provider]:
        return dict(self._providers)

    @classmethod
    def from_providers(
        cls,
        providers: dict[str, Provider],
    ) -> "ModelRegistry":
        return cls(providers=providers)

    def get_provider(self, provider_id: str) -> Provider | None:
        return self._providers.get(provider_id)

    def list_providers(self) -> list[Provider]:
        return sorted(self._providers.values(), key=lambda item: item.id)

    def get_providers(self) -> list[str]:
        return [provider.id for provider in self.list_providers()]

    def get_endpoint(self, provider_id: str, endpoint_id: str) -> Endpoint | None:
        return self._endpoints.get((provider_id, endpoint_id))

    def list_endpoints(self, *, provider: str | None = None) -> list[Endpoint]:
        if provider is not None:
            resolved_provider = self.get_provider(provider)
            if resolved_provider is None:
                return []
            return resolved_provider.list_endpoints()
        return sorted(
            self._endpoints.values(),
            key=lambda item: (item.provider_id, item.id),
        )

    def get_model(self, *args: str) -> Model:
        if len(args) == 1:
            matches = self.list_models(model_id=args[0])
            if not matches:
                raise KeyError(args[0])
            if len(matches) > 1:
                raise ValueError(
                    f"Ambiguous model_id {args[0]!r}; use (provider, endpoint, model_id)"
                )
            return matches[0]
        if len(args) != 3:
            raise TypeError(
                "get_model expects either (model_id) or (provider, endpoint, model_id)"
            )
        provider_id, endpoint_id, model_id = args
        try:
            return self._models[(provider_id, endpoint_id, model_id)]
        except KeyError as error:
            raise KeyError((provider_id, endpoint_id, model_id)) from error

    def resolve_model_selection(self, selection: ModelSelection) -> Model:
        if not isinstance(selection, ModelSelection):
            raise TypeError("selection must be ModelSelection")
        return self.get_model(
            selection.provider,
            selection.endpoint_id,
            selection.model_id,
        )

    def find_model(self, *args: str) -> Model | None:
        if len(args) == 1:
            matches = self.list_models(model_id=args[0])
            if len(matches) == 1:
                return matches[0]
            return None
        if len(args) != 3:
            raise TypeError(
                "find_model expects either (model_id) or (provider, endpoint, model_id)"
            )
        provider_id, endpoint_id, model_id = args
        return self._models.get((provider_id, endpoint_id, model_id))

    def list_models(
        self,
        *,
        provider: str | None = None,
        endpoint: str | None = None,
        model_id: str | None = None,
    ) -> list[Model]:
        models = sorted(
            self._models.values(),
            key=lambda item: (item.provider_id, item.endpoint_id, item.id),
        )
        if provider is not None:
            models = [model for model in models if model.provider_id == provider]
        if endpoint is not None:
            models = [model for model in models if model.endpoint_id == endpoint]
        if model_id is None:
            return models
        return [model for model in models if model.id == model_id]

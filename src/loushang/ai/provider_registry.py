from __future__ import annotations

from dataclasses import dataclass

from loushang.ai.api_registry import (
    APIRegistry,
    _validate_api_adapter,
    get_default_api_registry,
)
from loushang.ai.provider.protocol import APIAdapter

__all__ = [
    "ProviderRegistry",
    "ProviderRoute",
    "get_default_provider_registry",
]


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    provider_id: str
    api: str

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "api"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())


class ProviderRegistry:
    """Select an exact vendor/API adapter before the generic API fallback."""

    def __init__(self, api_registry: APIRegistry | None = None) -> None:
        self._api_registry = api_registry or get_default_api_registry()
        self._adapters: dict[
            ProviderRoute,
            tuple[APIAdapter, str | None],
        ] = {}

    @property
    def api_registry(self) -> APIRegistry:
        return self._api_registry

    def register_provider_adapter(
        self,
        provider_id: str,
        api: str,
        adapter: APIAdapter,
        *,
        source_id: str | None = None,
    ) -> None:
        route = ProviderRoute(provider_id, api)
        adapter_api = _validate_api_adapter(adapter)
        if adapter_api != route.api:
            raise ValueError(
                "Provider adapter api does not match registration route: "
                f"{adapter_api!r} != {route.api!r}"
            )
        if route in self._adapters:
            raise ValueError(
                "Provider adapter already registered: "
                f"{route.provider_id}:{route.api}"
            )
        self._adapters[route] = (adapter, source_id)

    def get_provider_adapter(
        self,
        provider_id: str,
        api: str,
    ) -> APIAdapter | None:
        entry = self._adapters.get(ProviderRoute(provider_id, api))
        return entry[0] if entry is not None else None

    def resolve_api_adapter(self, provider_id: str, api: str) -> APIAdapter:
        adapter = self.get_provider_adapter(provider_id, api)
        if adapter is not None:
            return adapter
        return self._api_registry.get_api_adapter(api)

    def unregister_provider_adapters(self, source_id: str) -> None:
        routes = [
            route
            for route, (_adapter, registered_source_id) in self._adapters.items()
            if registered_source_id == source_id
        ]
        for route in routes:
            del self._adapters[route]

    def clear_provider_adapters(self) -> None:
        self._adapters.clear()


_default_provider_registry: ProviderRegistry | None = None


def get_default_provider_registry() -> ProviderRegistry:
    global _default_provider_registry
    if _default_provider_registry is None:
        _default_provider_registry = ProviderRegistry(get_default_api_registry())
    return _default_provider_registry

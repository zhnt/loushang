from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loushang.ai.auth.sources.base import CredentialSource


@dataclass(frozen=True, slots=True)
class AuthRoute:
    auth_kind: str
    model_provider_id: str
    endpoint_id: str
    model_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("auth_kind", "model_provider_id", "endpoint_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        if self.model_id is not None:
            if not isinstance(self.model_id, str) or not self.model_id.strip():
                raise ValueError("model_id must be a non-empty string or None")
            object.__setattr__(self, "model_id", self.model_id.strip())


class AuthRegistry:
    """Registry for exact route-specific additions to standard auth resolution."""

    def __init__(self, sources: Iterable[CredentialSource] = ()) -> None:
        self._credential_sources: dict[str, CredentialSource] = {}
        self._route_sources: dict[AuthRoute, str] = {}
        for source in sources:
            self.register_credential_source(source)

    @property
    def credential_sources(self) -> Mapping[str, CredentialSource]:
        return MappingProxyType(dict(self._credential_sources))

    def register_auth_adapter(
        self,
        route: AuthRoute,
        adapter: CredentialSource,
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(route, AuthRoute):
            raise TypeError("route must be AuthRoute")
        _validate_source(adapter)
        if route in self._route_sources and not replace:
            raise ValueError(
                "Auth adapter already registered: "
                f"{route.auth_kind}:{route.model_provider_id}:"
                f"{route.endpoint_id}:{route.model_id or '*'}"
            )
        existing = self._credential_sources.get(adapter.id)
        if existing is not None and existing is not adapter and not replace:
            raise ValueError(f"Credential source already registered: {adapter.id}")
        self._credential_sources[adapter.id] = adapter
        self._route_sources[route] = adapter.id

    def get_auth_adapter(self, route: AuthRoute) -> CredentialSource | None:
        source_id = self._route_sources.get(route)
        if source_id is None:
            return None
        return self._credential_sources[source_id]

    def resolve_auth_adapter(self, model: object) -> CredentialSource | None:
        declaration = getattr(model, "auth", None)
        auth_kind = getattr(declaration, "kind", None)
        model_provider_id = getattr(model, "provider_id", None)
        endpoint_id = getattr(model, "endpoint_id", None)
        model_id = getattr(model, "id", None)
        if (
            not isinstance(auth_kind, str)
            or not auth_kind
            or not isinstance(model_provider_id, str)
            or not model_provider_id
            or not isinstance(endpoint_id, str)
            or not endpoint_id
        ):
            return None
        if isinstance(model_id, str) and model_id:
            exact = self.get_auth_adapter(
                AuthRoute(
                    auth_kind=auth_kind,
                    model_provider_id=model_provider_id,
                    endpoint_id=endpoint_id,
                    model_id=model_id,
                )
            )
            if exact is not None:
                return exact
        return self.get_auth_adapter(
            AuthRoute(
                auth_kind=auth_kind,
                model_provider_id=model_provider_id,
                endpoint_id=endpoint_id,
            )
        )

    def register_credential_source(
        self,
        source: CredentialSource,
        *,
        replace: bool = False,
    ) -> None:
        """Register a legacy source without adding an implicit route."""

        _validate_source(source)
        if source.id in self._credential_sources and not replace:
            raise ValueError(f"Credential source already registered: {source.id}")
        self._credential_sources[source.id] = source

    def get_credential_source(self, source_id: str) -> CredentialSource | None:
        return self._credential_sources.get(source_id)

    def find_credential_source(self, model: object) -> CredentialSource | None:
        """Resolve an exact route, then support explicit legacy source ids."""

        resolved = self.resolve_auth_adapter(model)
        if resolved is not None:
            return resolved
        declaration = getattr(model, "auth", None)
        source_id = getattr(declaration, "provider", None)
        if not isinstance(source_id, str) or not source_id:
            return None
        source = self.get_credential_source(source_id)
        if source is None or not source.matches(model):
            return None
        return source


AuthExtensionRegistry = AuthRegistry


def register_auth_adapter(
    route: AuthRoute,
    adapter: CredentialSource,
    *,
    replace: bool = False,
) -> None:
    get_auth_registry().register_auth_adapter(route, adapter, replace=replace)


def register_credential_source(
    source: CredentialSource,
    *,
    replace: bool = False,
) -> None:
    get_auth_registry().register_credential_source(source, replace=replace)


def get_credential_source(source_id: str) -> CredentialSource | None:
    return get_auth_registry().get_credential_source(source_id)


def get_auth_registry() -> AuthRegistry:
    global _default_registry
    if _default_registry is None:
        from loushang.ai.auth.sources.openai_codex import (
            OpenAICodexCredentialSource,
        )

        registry = AuthRegistry()
        registry.register_auth_adapter(
            AuthRoute(
                auth_kind="oauth",
                model_provider_id="openai",
                endpoint_id="coding-responses",
            ),
            OpenAICodexCredentialSource(),
        )
        _default_registry = registry
    return _default_registry


def get_auth_extension_registry() -> AuthRegistry:
    """Compatibility spelling for :func:`get_auth_registry`."""

    return get_auth_registry()


def _validate_source(source: CredentialSource) -> None:
    if (
        not isinstance(getattr(source, "id", None), str)
        or not source.id.strip()
        or not isinstance(getattr(source, "description", None), str)
        or not source.description.strip()
        or not isinstance(getattr(source, "recovery_hint", None), str)
        or not source.recovery_hint.strip()
        or not isinstance(getattr(source, "experimental", None), bool)
        or not isinstance(getattr(source, "supports_refresh", None), bool)
        or not callable(getattr(source, "matches", None))
        or not callable(getattr(source, "load", None))
        or not callable(getattr(source, "load_file", None))
    ):
        raise TypeError(
            "Credential source must define id, description, recovery_hint, "
            "experimental, supports_refresh, matches, load, and load_file"
        )


_default_registry: AuthRegistry | None = None


__all__ = [
    "AuthExtensionRegistry",
    "AuthRegistry",
    "AuthRoute",
    "get_auth_extension_registry",
    "get_auth_registry",
    "get_credential_source",
    "register_auth_adapter",
    "register_credential_source",
]

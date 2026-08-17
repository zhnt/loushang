from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from loushang.ai.auth.credentials import AuthCredential, OAuthCredential
from loushang.ai.auth.errors import (
    AuthenticationRequiredError,
    InvalidCredentialError,
    MissingCredentialError,
    OAuthProviderNotConfiguredError,
)
from loushang.ai.auth.oauth.base import OAuthProvider
from loushang.ai.auth.oauth.client import (
    AuthlibOAuthProvider,
    OAuthClientConfig,
    OAuthLoginSession,
)
from loushang.ai.auth.registry import AuthRegistry, get_auth_registry
from loushang.ai.auth.sources import (
    AuthExtensionRegistry,
    get_credential_source,
)
from loushang.ai.auth.store import FileCredentialStore
from loushang.ai.auth.support import normalize_auth_kind, resolve_api_key_auth

CredentialState = Literal["missing", "valid", "expiring", "expired"]


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    provider: str
    state: CredentialState
    expires_at: float | int | None = None
    source: str | None = None

    @property
    def authenticated(self) -> bool:
        return self.state in {"valid", "expiring"}


AuthAction = Literal["configure_api_key", "external_credential", "login"]


@dataclass(frozen=True, slots=True)
class AuthStatus:
    authenticated: bool
    auth_kind: str
    actions: tuple[AuthAction, ...] = ()
    state: CredentialState | None = None
    provider: str | None = None
    source: str | None = None
    source_description: str | None = None
    source_recovery_hint: str | None = None
    experimental: bool = False

    @property
    def available_actions(self) -> tuple[AuthAction, ...]:
        return self.actions

    def to_dict(self) -> dict[str, object]:
        return {
            "authenticated": self.authenticated,
            "auth_kind": self.auth_kind,
            "actions": list(self.actions),
            "state": self.state,
            "provider": self.provider,
            "source": self.source,
            "source_description": self.source_description,
            "source_recovery_hint": self.source_recovery_hint,
            "experimental": self.experimental,
        }


_oauth_providers: dict[str, OAuthProvider] = {}


def register_oauth_provider(provider: OAuthProvider, *, replace: bool = False) -> None:
    _validate_provider(provider)
    if provider.id in _oauth_providers and not replace:
        raise ValueError(f"OAuth provider already registered: {provider.id}")
    _oauth_providers[provider.id] = provider


def get_oauth_provider(provider_id: str) -> OAuthProvider | None:
    return _oauth_providers.get(provider_id)


async def get_auth(
    model,
    *,
    store: FileCredentialStore | None = None,
    env: Mapping[str, str] | None = None,
    auth_registry: AuthRegistry | None = None,
    extensions: AuthExtensionRegistry | None = None,
    refresh_window_seconds: float = 60.0,
    now: float | None = None,
) -> AuthCredential | None:
    """Return request authentication without starting an interactive login."""

    from loushang.ai.auth.resolver import resolve_auth

    registry = _resolve_auth_registry(auth_registry, extensions)
    try:
        return await resolve_auth(
            model,
            store=store,
            auth_registry=registry,
            env=env,
            refresh_window_seconds=refresh_window_seconds,
            now=now,
        )
    except MissingCredentialError as error:
        details = dict(error.info.details)
        details.update(
            {
                "reason": "missing_credential",
                "available_actions": list(_available_actions(model, registry)),
            }
        )
        raise AuthenticationRequiredError(
            error.info.message,
            provider=error.info.provider,
            endpoint=error.info.endpoint,
            model=error.info.model,
            details=details,
        ) from error


async def login(
    model,
    *,
    store: FileCredentialStore | None = None,
    auth_registry: AuthRegistry | None = None,
    extensions: AuthExtensionRegistry | None = None,
) -> OAuthLoginSession:
    """Start configured OAuth login without opening a browser or waiting for it."""

    provider = _generic_oauth_provider(model)
    if provider is None:
        registry = _resolve_auth_registry(auth_registry, extensions)
        raise AuthenticationRequiredError(
            "Model does not provide a generic OAuth login flow.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details={
                "reason": "login_unavailable",
                "available_actions": list(_available_actions(model, registry)),
            },
        )
    return await provider.start_login(store=store)


async def status(
    model,
    *,
    store: FileCredentialStore | None = None,
    env: Mapping[str, str] | None = None,
    auth_registry: AuthRegistry | None = None,
    extensions: AuthExtensionRegistry | None = None,
    refresh_window_seconds: float = 60.0,
    now: float | None = None,
) -> AuthStatus:
    """Inspect model authentication without login, refresh, or user interaction."""

    declaration = getattr(model, "auth", None)
    kind = normalize_auth_kind(getattr(declaration, "kind", None))
    if declaration is None or kind == "none":
        return AuthStatus(authenticated=True, auth_kind="none")
    registry = _resolve_auth_registry(auth_registry, extensions)
    if kind == "api_key":
        try:
            resolve_api_key_auth(
                declaration,
                model=model,
                env=os.environ if env is None else env,
            )
        except MissingCredentialError:
            return AuthStatus(
                authenticated=False,
                auth_kind="api_key",
                actions=("configure_api_key",),
                state="missing",
            )
        return AuthStatus(
            authenticated=True,
            auth_kind="api_key",
            state="valid",
        )
    if kind != "oauth":
        raise OAuthProviderNotConfiguredError(
            "Model has an unsupported authentication kind.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details={"auth_kind": str(kind), "recovery": "reconfigure"},
        )

    source = registry.find_credential_source(model)
    provider_id = source.id if source is not None else _oauth_provider_id(model)
    resolved_store = store or FileCredentialStore()
    credential = resolved_store.load(provider_id)
    source_name: str | None = "default_store" if credential is not None else None
    if credential is None and source is not None:
        credential = source.load()
        if credential is not None:
            source_name = "credential_source"
    if credential is None:
        return AuthStatus(
            authenticated=False,
            auth_kind="oauth",
            actions=_available_actions(model, registry),
            state="missing",
            provider=provider_id,
            source=source.id if source is not None else None,
            source_description=(source.description if source is not None else None),
            source_recovery_hint=(
                source.recovery_hint if source is not None else None
            ),
            experimental=(source.experimental if source is not None else False),
        )
    _validate_credential_owner(provider_id, credential)
    timestamp = time.time() if now is None else now
    state = _credential_state(
        credential,
        refresh_window_seconds=refresh_window_seconds,
        now=timestamp,
    )
    authenticated = state in {"valid", "expiring"}
    return AuthStatus(
        authenticated=authenticated,
        auth_kind="oauth",
        actions=() if authenticated else _available_actions(model, registry),
        state=state,
        provider=provider_id,
        source=source_name,
        source_description=(source.description if source is not None else None),
        source_recovery_hint=(source.recovery_hint if source is not None else None),
        experimental=(source.experimental if source is not None else False),
    )


async def logout(
    provider: object,
    *,
    store: FileCredentialStore | None = None,
    revoke: bool = True,
) -> bool:
    """Delete stored authentication for a model or legacy OAuth provider target."""

    if isinstance(provider, str) or isinstance(provider, OAuthProvider):
        resolved_adapter = _resolve_provider(provider)
        provider_id = resolved_adapter.id
        adapter: OAuthProvider | None = resolved_adapter
    else:
        declaration = getattr(provider, "auth", None)
        if normalize_auth_kind(getattr(declaration, "kind", None)) != "oauth":
            raise OAuthProviderNotConfiguredError(
                "Model does not use OAuth authentication.",
                provider=getattr(provider, "provider_id", None),
                endpoint=getattr(provider, "endpoint_id", None),
                model=getattr(provider, "id", None),
                details={"recovery": "reconfigure"},
            )
        source = get_auth_registry().resolve_auth_adapter(provider)
        provider_id = source.id if source is not None else _oauth_provider_id(provider)
        adapter = get_oauth_provider(provider_id) or _generic_oauth_provider(provider)
    resolved_store = store or FileCredentialStore()
    credential = resolved_store.load(provider_id)
    if credential is None:
        return False
    if revoke and adapter is not None:
        await adapter.revoke(credential)
    return resolved_store.delete(provider_id)


def credential_status(
    provider: str | OAuthProvider,
    *,
    store: FileCredentialStore | None = None,
    refresh_window_seconds: float = 60.0,
    now: float | None = None,
) -> CredentialStatus:
    if isinstance(provider, str):
        provider_id = provider
        adapter = get_oauth_provider(provider_id)
        source_adapter = get_credential_source(provider_id)
        if adapter is None and source_adapter is None:
            raise KeyError(
                "OAuth provider or credential source is not registered: "
                f"{provider_id}"
            )
    else:
        _validate_provider(provider)
        provider_id = provider.id
        source_adapter = get_credential_source(provider_id)
    resolved_store = store or FileCredentialStore()
    credential = resolved_store.load(provider_id)
    source = "default_store"
    if credential is None and source_adapter is not None:
        credential = source_adapter.load()
        source = "credential_source"
    if credential is None:
        return CredentialStatus(provider=provider_id, state="missing")
    _validate_credential_owner(provider_id, credential)
    timestamp = time.time() if now is None else now
    state = _credential_state(
        credential,
        refresh_window_seconds=refresh_window_seconds,
        now=timestamp,
    )
    return CredentialStatus(
        provider=provider_id,
        state=state,
        expires_at=credential.expires_at,
        source=source,
    )


def _resolve_provider(provider: str | OAuthProvider) -> OAuthProvider:
    if isinstance(provider, str):
        adapter = get_oauth_provider(provider)
        if adapter is None:
            raise KeyError(f"OAuth provider is not registered: {provider}")
        return adapter
    _validate_provider(provider)
    return provider


def _oauth_provider_id(model) -> str:
    declaration = getattr(model, "auth", None)
    configured = getattr(declaration, "provider", None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    provider_id = getattr(model, "provider_id", None)
    if not isinstance(provider_id, str) or not provider_id:
        raise OAuthProviderNotConfiguredError(
            "OAuth model has no provider identity.",
            details={"recovery": "reconfigure"},
        )
    return provider_id


def _generic_oauth_provider(model) -> AuthlibOAuthProvider | None:
    declaration = getattr(model, "auth", None)
    if normalize_auth_kind(getattr(declaration, "kind", None)) != "oauth":
        return None
    config = getattr(declaration, "oauth", None)
    if config is None:
        return None
    return AuthlibOAuthProvider(
        _oauth_provider_id(model),
        OAuthClientConfig(
            client_id=config.client_id,
            authorization_endpoint=config.authorization_endpoint,
            token_endpoint=config.token_endpoint,
            redirect_uri=config.redirect_uri,
            scopes=config.scopes,
            revocation_endpoint=config.revocation_endpoint,
            token_endpoint_auth_method=config.token_endpoint_auth_method,
        ),
    )


def _available_actions(
    model,
    registry: AuthRegistry,
) -> tuple[AuthAction, ...]:
    declaration = getattr(model, "auth", None)
    kind = normalize_auth_kind(getattr(declaration, "kind", None))
    if kind == "api_key":
        return ("configure_api_key",)
    if kind != "oauth":
        return ()
    actions: list[AuthAction] = []
    if getattr(declaration, "oauth", None) is not None:
        actions.append("login")
    if registry.find_credential_source(model) is not None:
        actions.append("external_credential")
    return tuple(actions)


def _resolve_auth_registry(
    auth_registry: AuthRegistry | None,
    extensions: AuthExtensionRegistry | None,
) -> AuthRegistry:
    if auth_registry is not None and extensions is not None:
        raise TypeError("auth_registry and extensions cannot both be provided")
    return auth_registry or extensions or get_auth_registry()


def _credential_state(
    credential: OAuthCredential,
    *,
    refresh_window_seconds: float,
    now: float,
) -> CredentialState:
    if credential.is_expired(now=now):
        return "expired"
    if credential.expires_within(refresh_window_seconds, now=now):
        return "expiring"
    return "valid"


def _validate_provider(provider: OAuthProvider) -> None:
    if (
        not isinstance(getattr(provider, "id", None), str)
        or not provider.id.strip()
        or not callable(getattr(provider, "login", None))
        or not callable(getattr(provider, "refresh", None))
        or not callable(getattr(provider, "revoke", None))
    ):
        raise TypeError("OAuth provider must define id, login, refresh, and revoke")


def _validate_credential_owner(
    provider_id: str,
    credential: OAuthCredential,
) -> None:
    if not isinstance(credential, OAuthCredential):
        raise InvalidCredentialError(
            "Authentication component returned an unsupported credential type.",
            provider=provider_id,
            details={"recovery": "reconfigure"},
        )
    if credential.provider != provider_id:
        raise InvalidCredentialError(
            "Authentication component returned a credential for a different provider.",
            provider=provider_id,
            details={
                "credential_provider": credential.provider,
                "recovery": "reconfigure",
            },
        )


__all__ = [
    "AuthAction",
    "AuthStatus",
    "CredentialState",
    "CredentialStatus",
    "credential_status",
    "get_auth",
    "get_oauth_provider",
    "login",
    "logout",
    "register_oauth_provider",
    "status",
]

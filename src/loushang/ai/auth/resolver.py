from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from loushang.ai.auth.core import _generic_oauth_provider, get_oauth_provider
from loushang.ai.auth.credentials import (
    AuthCredential,
    OAuthCredential,
)
from loushang.ai.auth.errors import (
    CredentialExpiredError,
    InvalidCredentialError,
    MissingCredentialError,
    RefreshFailedError,
)
from loushang.ai.auth.oauth.base import OAuthProvider
from loushang.ai.auth.registry import AuthRegistry, get_auth_registry
from loushang.ai.auth.sources import (
    CredentialSource,
    get_credential_source,
)
from loushang.ai.auth.store import (
    FileCredentialStore,
    load_credential_file,
    save_credential_file,
)
from loushang.ai.auth.support import normalize_auth_kind, resolve_api_key_auth


@dataclass(frozen=True, slots=True)
class _ResolvedCredential:
    credential: OAuthCredential
    source: str
    path: Path | None = None


async def resolve_auth(
    model,
    *,
    options=None,
    credential: OAuthCredential | None = None,
    credential_file: str | Path | None = None,
    store: FileCredentialStore | None = None,
    providers: Mapping[str, OAuthProvider] | None = None,
    sources: Mapping[str, CredentialSource] | None = None,
    auth_registry: AuthRegistry | None = None,
    env: Mapping[str, str] | None = None,
    refresh_window_seconds: float = 60.0,
    now: float | None = None,
) -> AuthCredential | None:
    """Resolve request auth by explicit-auth, credential, file, store, then env."""

    declaration = getattr(model, "auth", None)
    explicit_auth = getattr(options, "auth", None) if options is not None else None
    if explicit_auth is not None:
        return explicit_auth

    explicit_credential = credential
    if explicit_credential is None and options is not None:
        explicit_credential = getattr(options, "credential", None)
    explicit_file = credential_file
    if explicit_file is None and options is not None:
        explicit_file = getattr(options, "credential_file", None)

    kind = normalize_auth_kind(getattr(declaration, "kind", None))
    if declaration is None or kind == "none":
        if explicit_credential is None and explicit_file is None:
            return None
        kind = "oauth"
    if kind == "api_key":
        if explicit_credential is not None or explicit_file is not None:
            raise InvalidCredentialError(
                "OAuth credentials cannot authenticate a model configured for API key auth.",
                provider=getattr(model, "provider_id", None),
                endpoint=getattr(model, "endpoint_id", None),
                model=getattr(model, "id", None),
                details={"recovery": "reconfigure"},
            )
        return resolve_api_key_auth(
            declaration,
            model=model,
            env=os.environ if env is None else env,
        )
    if kind != "oauth":
        raise InvalidCredentialError(
            "Model has an unsupported authentication kind.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details={"auth_kind": str(kind), "recovery": "reconfigure"},
        )

    registry = auth_registry or get_auth_registry()
    source_adapter = registry.resolve_auth_adapter(model)
    legacy_provider_id = _oauth_provider_id(model, declaration)
    if source_adapter is None:
        source_adapter = _legacy_source_for(
            legacy_provider_id,
            sources,
            registry=registry,
            model=model,
        )
    elif sources is not None and source_adapter.id in sources:
        source_adapter = sources[source_adapter.id]
    provider_id = source_adapter.id if source_adapter is not None else legacy_provider_id
    resolved = _load_oauth_credential(
        provider_id,
        credential=explicit_credential,
        credential_file=explicit_file,
        store=store,
        source_adapter=source_adapter,
    )
    if resolved is None:
        recovery, source_id = _credential_recovery(
            source_adapter,
        )
        details = {
            "oauth_provider": provider_id,
            "recovery": recovery,
        }
        if source_id is not None:
            details["credential_source"] = source_id
        raise MissingCredentialError(
            "Model requires an OAuth credential but none was found.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details=details,
        )
    _validate_credential_provider(resolved.credential, provider_id, model=model)
    timestamp = time.time() if now is None else now
    prepared = await _refresh_if_needed(
        resolved,
        provider_id=provider_id,
        store=store,
        providers=providers,
        source_adapter=source_adapter,
        refresh_window_seconds=refresh_window_seconds,
        now=timestamp,
        model=model,
    )
    return prepared.to_auth()


def _load_oauth_credential(
    provider_id: str,
    *,
    credential: OAuthCredential | None,
    credential_file: str | Path | None,
    store: FileCredentialStore | None,
    source_adapter: CredentialSource | None,
) -> _ResolvedCredential | None:
    if credential is not None:
        if not isinstance(credential, OAuthCredential):
            raise InvalidCredentialError(
                "credential must be OAuthCredential.",
                details={"recovery": "reconfigure"},
            )
        return _ResolvedCredential(credential=credential, source="explicit")
    if credential_file is not None:
        path = Path(credential_file).expanduser()
        if source_adapter is not None:
            return _ResolvedCredential(
                credential=source_adapter.load_file(path),
                source="credential_source_file",
                path=path,
            )
        return _ResolvedCredential(
            credential=load_credential_file(path),
            source="credential_file",
            path=path,
        )
    resolved_store = store or FileCredentialStore()
    stored = resolved_store.load(provider_id)
    if stored is not None:
        return _ResolvedCredential(credential=stored, source="default_store")
    if source_adapter is not None:
        external = source_adapter.load()
        if external is not None:
            return _ResolvedCredential(
                credential=external,
                source="credential_source",
            )
    return None


async def _refresh_if_needed(
    resolved: _ResolvedCredential,
    *,
    provider_id: str,
    store: FileCredentialStore | None,
    providers: Mapping[str, OAuthProvider] | None,
    source_adapter: CredentialSource | None,
    refresh_window_seconds: float,
    now: float,
    model,
) -> OAuthCredential:
    credential = resolved.credential
    recovery, source_id = _credential_recovery(
        source_adapter,
    )
    recovery_details = {
        "oauth_provider": provider_id,
        "recovery": recovery,
    }
    if source_id is not None:
        recovery_details["credential_source"] = source_id
    if not credential.expires_within(refresh_window_seconds, now=now):
        return credential
    if resolved.source in {
        "credential_source",
        "credential_source_file",
    } and (
        source_adapter is None
        or getattr(source_adapter, "supports_refresh", False) is not True
    ):
        raise CredentialExpiredError(
            "OAuth credential source does not support refresh.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details=recovery_details,
        )
    if credential.refresh_token is None:
        raise CredentialExpiredError(
            "OAuth credential is expired or near expiry and has no refresh token.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details=recovery_details,
        )
    adapter = _provider_for(provider_id, providers, model=model)
    if adapter is None:
        raise RefreshFailedError(
            "OAuth credential needs refresh but no provider adapter is registered.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details=recovery_details,
        )
    try:
        refreshed = await adapter.refresh(credential)
    except RefreshFailedError:
        raise
    except Exception as error:
        raise RefreshFailedError(
            "OAuth credential refresh failed.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details={
                "oauth_provider": provider_id,
                "cause": type(error).__name__,
                "recovery": "login",
            },
        ) from error
    _validate_credential_provider(refreshed, provider_id, model=model)
    if refreshed.is_expired(now=now):
        raise RefreshFailedError(
            "OAuth provider returned an expired credential.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details={"oauth_provider": provider_id, "recovery": "login"},
        )
    if resolved.source == "credential_file" and resolved.path is not None:
        save_credential_file(resolved.path, refreshed)
    elif resolved.source == "default_store":
        (store or FileCredentialStore()).save(refreshed)
    return refreshed


def _oauth_provider_id(model, declaration) -> str:
    configured = getattr(declaration, "provider", None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    provider_id = getattr(model, "provider_id", None)
    if not isinstance(provider_id, str) or not provider_id:
        raise InvalidCredentialError(
            "OAuth model has no provider identity.",
            details={"recovery": "reconfigure"},
        )
    return provider_id


def _provider_for(
    provider_id: str,
    providers: Mapping[str, OAuthProvider] | None,
    *,
    model,
) -> OAuthProvider | None:
    if providers is not None and provider_id in providers:
        return providers[provider_id]
    registered = get_oauth_provider(provider_id)
    if registered is not None:
        return registered
    return _generic_oauth_provider(model)


def _legacy_source_for(
    provider_id: str,
    sources: Mapping[str, CredentialSource] | None,
    *,
    registry: AuthRegistry,
    model,
) -> CredentialSource | None:
    source: CredentialSource | None
    if sources is not None and provider_id in sources:
        source = sources[provider_id]
    else:
        source = registry.get_credential_source(provider_id)
        if source is None:
            source = get_credential_source(provider_id)
    if source is None or not source.matches(model):
        return None
    return source


def _credential_recovery(
    source: CredentialSource | None,
) -> tuple[str, str | None]:
    if source is None:
        return "login", None
    recovery = getattr(source, "recovery", "external_login")
    if not isinstance(recovery, str) or not recovery:
        recovery = "external_login"
    return recovery, source.id


def _validate_credential_provider(
    credential: OAuthCredential,
    provider_id: str,
    *,
    model,
) -> None:
    if not isinstance(credential, OAuthCredential):
        raise InvalidCredentialError(
            "OAuth provider returned an unsupported credential.",
            details={"recovery": "reconfigure"},
        )
    if credential.provider != provider_id:
        raise InvalidCredentialError(
            "OAuth credential provider does not match the model auth provider.",
            provider=getattr(model, "provider_id", None),
            endpoint=getattr(model, "endpoint_id", None),
            model=getattr(model, "id", None),
            details={
                "credential_provider": credential.provider,
                "oauth_provider": provider_id,
                "recovery": "reconfigure",
            },
        )


__all__ = ["resolve_auth"]

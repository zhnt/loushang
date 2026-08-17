from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from loushang.ai import ApiKeyAuth, CallOptions, OAuthBearerAuth, OAuthCredential
from loushang.ai.auth import (
    CredentialExpiredError,
    FileCredentialStore,
    RefreshFailedError,
    resolve_auth,
)
from loushang.ai.auth.store import save_credential_file
from loushang.ai.model import Auth, Model


def _oauth_model() -> Model:
    return Model(
        id="model-a",
        provider="model-provider",
        endpoint="endpoint-a",
        api="openai-responses",
        base_url="https://example.test/v1",
        auth=Auth(kind="oauth", provider="example-oauth"),
    )


def _api_key_model() -> Model:
    return Model(
        id="model-a",
        provider="model-provider",
        endpoint="endpoint-a",
        api="openai-responses",
        base_url="https://example.test/v1",
        auth=Auth(kind="apiKey", api_key_env="EXAMPLE_API_KEY"),
    )


def _credential(token: str, *, expires_at: int = 2000) -> OAuthCredential:
    return OAuthCredential(
        provider="example-oauth",
        access_token=token,
        refresh_token=f"refresh-{token}",
        expires_at=expires_at,
        extra_headers={"x-account": token},
    )


@dataclass
class _FakeProvider:
    id: str = "example-oauth"
    refreshed: list[OAuthCredential] = field(default_factory=list)
    fail_refresh: bool = False

    async def login(self, *, authorize=None) -> OAuthCredential:
        del authorize
        return _credential("login")

    async def refresh(self, credential: OAuthCredential) -> OAuthCredential:
        self.refreshed.append(credential)
        if self.fail_refresh:
            raise RuntimeError("refresh failed")
        return _credential("refreshed", expires_at=4000)

    async def revoke(self, credential: OAuthCredential) -> None:
        del credential


@dataclass
class _FakeSource:
    supports_refresh: bool
    id: str = "example-oauth"
    description: str = "Fake external credential"
    recovery_hint: str = "Sign in with the external application"
    experimental: bool = False
    credential: OAuthCredential = field(
        default_factory=lambda: _credential("source", expires_at=1030)
    )

    def matches(self, model: object) -> bool:
        declaration = getattr(model, "auth", None)
        return getattr(declaration, "provider", None) == self.id

    def load(self) -> OAuthCredential | None:
        return self.credential

    def load_file(self, path: str | Path) -> OAuthCredential:
        del path
        return self.credential


def test_resolver_priority_explicit_auth_then_credential_file_store_and_env(
    tmp_path: Path,
) -> None:
    store = FileCredentialStore(tmp_path / "store")
    store.save(_credential("store"))
    file_path = tmp_path / "file-auth.json"
    save_credential_file(file_path, _credential("file"))
    explicit_credential = _credential("explicit-credential")
    provider = _FakeProvider()

    async def scenario():
        explicit_auth = await resolve_auth(
            _oauth_model(),
            options=CallOptions(
                auth=OAuthBearerAuth("explicit-auth"),
                credential=explicit_credential,
                credential_file=file_path,
            ),
            store=store,
            providers={provider.id: provider},
            now=1000,
        )
        direct_credential = await resolve_auth(
            _oauth_model(),
            options=CallOptions(
                credential=explicit_credential,
                credential_file=file_path,
            ),
            store=store,
            providers={provider.id: provider},
            now=1000,
        )
        file_credential = await resolve_auth(
            _oauth_model(),
            options=CallOptions(credential_file=file_path),
            store=store,
            providers={provider.id: provider},
            now=1000,
        )
        stored_credential = await resolve_auth(
            _oauth_model(),
            store=store,
            providers={provider.id: provider},
            now=1000,
        )
        env_api_key = await resolve_auth(
            _api_key_model(),
            env={"EXAMPLE_API_KEY": "env-key"},
        )
        return (
            explicit_auth,
            direct_credential,
            file_credential,
            stored_credential,
            env_api_key,
        )

    (
        explicit_auth,
        direct_credential,
        file_credential,
        stored_credential,
        env_api_key,
    ) = asyncio.run(scenario())

    assert explicit_auth == OAuthBearerAuth("explicit-auth")
    assert direct_credential == OAuthBearerAuth(
        "explicit-credential", extra_headers={"x-account": "explicit-credential"}
    )
    assert file_credential == OAuthBearerAuth(
        "file", extra_headers={"x-account": "file"}
    )
    assert stored_credential == OAuthBearerAuth(
        "store", extra_headers={"x-account": "store"}
    )
    assert env_api_key == ApiKeyAuth("env-key")


def test_unexpired_oauth_token_is_not_refreshed(tmp_path: Path) -> None:
    provider = _FakeProvider()
    auth = asyncio.run(
        resolve_auth(
            _oauth_model(),
            credential=_credential("current", expires_at=2000),
            providers={provider.id: provider},
            now=1000,
        )
    )

    assert auth == OAuthBearerAuth("current", extra_headers={"x-account": "current"})
    assert provider.refreshed == []


def test_expiring_store_token_is_refreshed_and_saved(tmp_path: Path) -> None:
    provider = _FakeProvider()
    store = FileCredentialStore(tmp_path)
    expiring = _credential("expiring", expires_at=1030)
    store.save(expiring)

    auth = asyncio.run(
        resolve_auth(
            _oauth_model(),
            store=store,
            providers={provider.id: provider},
            now=1000,
        )
    )

    assert provider.refreshed == [expiring]
    assert auth == OAuthBearerAuth(
        "refreshed", extra_headers={"x-account": "refreshed"}
    )
    assert store.load(provider.id) == _credential("refreshed", expires_at=4000)


def test_refresh_failure_is_structured(tmp_path: Path) -> None:
    provider = _FakeProvider(fail_refresh=True)

    with pytest.raises(RefreshFailedError) as exc_info:
        asyncio.run(
            resolve_auth(
                _oauth_model(),
                credential=_credential("expired", expires_at=900),
                providers={provider.id: provider},
                now=1000,
            )
        )

    assert exc_info.value.info.details == {
        "oauth_provider": "example-oauth",
        "cause": "RuntimeError",
        "recovery": "login",
    }


def test_credential_source_without_refresh_support_expires_structurally(
    tmp_path: Path,
) -> None:
    source = _FakeSource(supports_refresh=False)
    provider = _FakeProvider()

    with pytest.raises(
        CredentialExpiredError,
        match="credential source does not support refresh",
    ) as exc_info:
        asyncio.run(
            resolve_auth(
                _oauth_model(),
                store=FileCredentialStore(tmp_path),
                sources={source.id: source},
                providers={provider.id: provider},
                now=1000,
            )
        )

    assert provider.refreshed == []
    assert exc_info.value.info.details == {
        "oauth_provider": "example-oauth",
        "recovery": "external_login",
        "credential_source": "example-oauth",
    }


def test_credential_source_with_refresh_support_uses_registered_provider(
    tmp_path: Path,
) -> None:
    source = _FakeSource(supports_refresh=True)
    provider = _FakeProvider()

    auth = asyncio.run(
        resolve_auth(
            _oauth_model(),
            store=FileCredentialStore(tmp_path),
            sources={source.id: source},
            providers={provider.id: provider},
            now=1000,
        )
    )

    assert provider.refreshed == [source.credential]
    assert auth == OAuthBearerAuth(
        "refreshed",
        extra_headers={"x-account": "refreshed"},
    )


def test_openai_codex_source_file_resolves_without_oauth_provider(
    tmp_path: Path,
) -> None:
    path = tmp_path / "auth.json"
    path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "codex-access",
                    "account_id": "account-id",
                },
            }
        ),
        encoding="utf-8",
    )
    model = Model(
        id="codex-model",
        provider="openai",
        endpoint="coding-responses",
        api="openai-responses",
        base_url="https://chatgpt.com/backend-api/codex",
        auth=Auth(kind="oauth", provider="openai-codex"),
    )

    auth = asyncio.run(
        resolve_auth(
            model,
            options=CallOptions(credential_file=path),
            providers={},
            now=1000,
        )
    )

    assert auth == OAuthBearerAuth(
        "codex-access",
        extra_headers={"ChatGPT-Account-ID": "account-id"},
    )


def test_openai_codex_source_never_impersonates_refresh_provider(
    tmp_path: Path,
) -> None:
    path = tmp_path / "auth.json"
    path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "codex-access",
                    "refresh_token": "codex-refresh",
                    "expires_at": 1030,
                },
            }
        ),
        encoding="utf-8",
    )
    model = Model(
        id="codex-model",
        provider="openai",
        endpoint="coding-responses",
        api="openai-responses",
        base_url="https://chatgpt.com/backend-api/codex",
        auth=Auth(kind="oauth", provider="openai-codex"),
    )

    with pytest.raises(
        CredentialExpiredError,
        match="credential source does not support refresh",
    ) as exc_info:
        asyncio.run(
            resolve_auth(
                model,
                options=CallOptions(credential_file=path),
                providers={},
                now=1000,
            )
        )

    assert exc_info.value.info.details == {
        "oauth_provider": "openai-codex",
        "recovery": "codex_login",
        "credential_source": "openai-codex",
    }

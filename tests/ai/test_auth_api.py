from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

import loushang.ai.auth as auth
from loushang.ai import ApiKeyAuth, OAuthBearerAuth, OAuthCredential
from loushang.ai.model import Auth, Model, OAuthConfig


def _model(declaration: Auth) -> Model:
    return Model(
        id="auth-api-model",
        provider="example",
        endpoint="oauth",
        api="openai-responses",
        base_url="https://model.test/v1",
        auth=declaration,
    )


def _generic_oauth() -> Auth:
    return Auth(
        kind="oauth",
        provider="example-oauth",
        oauth=OAuthConfig(
            client_id="example-client",
            authorization_endpoint="https://oauth.test/authorize",
            token_endpoint="https://oauth.test/token",
            scopes=("model.invoke",),
        ),
    )


@dataclass
class _ExternalSource:
    credential: OAuthCredential | None = None
    id: str = "external-oauth"
    description: str = "Use external application login"
    recovery_hint: str = "Sign in with the external application"
    experimental: bool = True
    supports_refresh: bool = False

    def matches(self, model: object) -> bool:
        declaration = getattr(model, "auth", None)
        return getattr(declaration, "provider", None) == self.id

    def load(self) -> OAuthCredential | None:
        return self.credential

    def load_file(self, path: str | Path) -> OAuthCredential:
        del path
        if self.credential is None:
            raise RuntimeError("fixture credential is missing")
        return self.credential


def test_get_auth_and_status_resolve_api_key_without_login() -> None:
    model = _model(Auth(kind="apiKey", api_key_env="EXAMPLE_KEY"))

    async def scenario():
        request_auth = await auth.get_auth(model, env={"EXAMPLE_KEY": "secret"})
        current = await auth.status(model, env={"EXAMPLE_KEY": "secret"})
        missing = await auth.status(model, env={})
        return request_auth, current, missing

    request_auth, current, missing = asyncio.run(scenario())

    assert request_auth == ApiKeyAuth("secret")
    assert current.authenticated is True
    assert current.auth_kind == "api_key"
    assert current.actions == ()
    assert missing.authenticated is False
    assert missing.actions == ("configure_api_key",)


def test_get_auth_missing_oauth_is_structured_and_never_starts_login() -> None:
    model = _model(_generic_oauth())

    with pytest.raises(auth.AuthenticationRequiredError) as exc_info:
        asyncio.run(auth.get_auth(model, extensions=auth.AuthExtensionRegistry()))

    assert exc_info.value.info.details["reason"] == "missing_credential"
    assert exc_info.value.info.details["available_actions"] == ["login"]


@pytest.mark.requires_host_runtime
def test_login_returns_session_without_opening_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model(_generic_oauth())

    def fail_if_opened(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        raise AssertionError("auth.login must not open a browser")

    monkeypatch.setattr("webbrowser.open", fail_if_opened)

    async def scenario():
        session = await auth.login(model)
        try:
            assert session.authorization_url.startswith("https://oauth.test/authorize?")
            assert session.redirect_uri.startswith("http://127.0.0.1:")
            return session
        finally:
            await session.close()

    session = asyncio.run(scenario())
    assert isinstance(session, auth.OAuthLoginSession)


def test_status_and_get_auth_use_extension_registry_metadata() -> None:
    credential = OAuthCredential(
        provider="external-oauth",
        access_token="external-access",
        expires_at=4102444800,
    )
    source = _ExternalSource(credential=credential)
    registry = auth.AuthExtensionRegistry([source])
    model = _model(Auth(kind="oauth", provider=source.id))

    async def scenario():
        current = await auth.status(model, extensions=registry)
        request_auth = await auth.get_auth(model, extensions=registry)
        source.credential = None
        missing = await auth.status(model, extensions=registry)
        return current, request_auth, missing

    current, request_auth, missing = asyncio.run(scenario())

    assert current.authenticated is True
    assert current.experimental is True
    assert current.source_description == source.description
    assert current.source_recovery_hint == source.recovery_hint
    assert request_auth == OAuthBearerAuth("external-access")
    assert missing.authenticated is False
    assert missing.actions == ("external_credential",)
    assert missing.to_dict()["actions"] == ["external_credential"]
    assert missing.to_dict()["source_recovery_hint"] == source.recovery_hint


def test_auth_registry_prefers_model_route_then_endpoint_fallback() -> None:
    endpoint_source = _ExternalSource(id="endpoint-oauth")
    model_source = _ExternalSource(id="model-oauth")
    registry = auth.AuthRegistry()
    endpoint_route = auth.AuthRoute(" oauth ", " example ", " oauth ")
    model_route = auth.AuthRoute(
        "oauth",
        "example",
        "oauth",
        model_id="auth-api-model",
    )

    registry.register_auth_adapter(endpoint_route, endpoint_source)
    registry.register_auth_adapter(model_route, model_source)

    assert endpoint_route == auth.AuthRoute("oauth", "example", "oauth")
    assert registry.resolve_auth_adapter(_model(Auth(kind="oauth"))) is model_source
    assert (
        registry.resolve_auth_adapter(
            Model(
                id="other-model",
                provider="example",
                endpoint="oauth",
                api="openai-responses",
                base_url="https://model.test/v1",
                auth=Auth(kind="oauth"),
            )
        )
        is endpoint_source
    )
    assert registry.resolve_auth_adapter(object()) is None
    assert registry.find_credential_source(_model(Auth(kind="oauth"))) is model_source
    assert dict(registry.credential_sources) == {
        endpoint_source.id: endpoint_source,
        model_source.id: model_source,
    }
    with pytest.raises(TypeError, match="route must be AuthRoute"):
        registry.register_auth_adapter("oauth:example:oauth", endpoint_source)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Auth adapter already registered"):
        registry.register_auth_adapter(endpoint_route, endpoint_source)
    with pytest.raises(ValueError, match="Credential source already registered"):
        registry.register_auth_adapter(
            auth.AuthRoute("oauth", "example", "other-endpoint"),
            _ExternalSource(id=endpoint_source.id),
        )


def test_auth_registry_explicit_replace_compatibility_baseline() -> None:
    route = auth.AuthRoute("oauth", "example", "oauth")
    first = _ExternalSource(id="first-oauth")
    replacement = _ExternalSource(id="replacement-oauth")
    registry = auth.AuthRegistry()

    assert registry.register_auth_adapter(route, first) is None
    assert registry.register_auth_adapter(route, replacement, replace=True) is None

    assert registry.get_auth_adapter(route) is replacement
    assert dict(registry.credential_sources) == {
        first.id: first,
        replacement.id: replacement,
    }


def test_public_auth_registry_helpers_share_the_default_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = auth.AuthRegistry()
    monkeypatch.setattr("loushang.ai.auth.registry._default_registry", registry)
    source = _ExternalSource(id="route-oauth")
    route = auth.AuthRoute("oauth", "example", "oauth")

    auth.register_auth_adapter(route, source)

    assert auth.get_auth_registry() is registry
    assert auth.get_auth_extension_registry() is registry
    assert registry.get_auth_adapter(route) is source


def test_source_only_model_cannot_be_treated_as_generic_login() -> None:
    model = _model(Auth(kind="oauth", provider="openai-codex"))

    with pytest.raises(auth.AuthenticationRequiredError) as exc_info:
        asyncio.run(auth.login(model))

    assert exc_info.value.info.details == {
        "reason": "login_unavailable",
        "available_actions": ["external_credential"],
    }


def test_get_auth_imports_codex_source_through_public_api(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    path.write_text(
        """{
  "auth_mode": "chatgpt",
  "tokens": {
    "access_token": "codex-access",
    "account_id": "account-id"
  }
}
""",
        encoding="utf-8",
    )
    source = auth.OpenAICodexCredentialSource(path)
    model = _model(Auth(kind="oauth", provider=source.id))

    request_auth = asyncio.run(
        auth.get_auth(model, extensions=auth.AuthExtensionRegistry([source]))
    )

    assert request_auth == OAuthBearerAuth(
        "codex-access",
        extra_headers={"ChatGPT-Account-ID": "account-id"},
    )


def test_logout_model_resolves_owner_and_preserves_registered_revoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class RevokingProvider:
        id = "example-oauth"

        def __init__(self) -> None:
            self.revoked: list[OAuthCredential] = []

        async def login(self, *, authorize=None) -> OAuthCredential:
            del authorize
            raise AssertionError("logout must not start login")

        async def refresh(self, credential: OAuthCredential) -> OAuthCredential:
            raise AssertionError(f"logout must not refresh {credential.provider}")

        async def revoke(self, credential: OAuthCredential) -> None:
            self.revoked.append(credential)

    provider = RevokingProvider()
    monkeypatch.setattr(
        "loushang.ai.auth.core._oauth_providers",
        {provider.id: provider},
    )
    model = _model(Auth(kind="oauth", provider=provider.id))
    store = auth.FileCredentialStore(tmp_path)
    credential = OAuthCredential(provider=provider.id, access_token="stored-access")
    store.save(credential)

    deleted = asyncio.run(auth.logout(model, store=store))

    assert deleted is True
    assert provider.revoked == [credential]
    assert store.load(provider.id) is None


def test_logout_model_deletes_owned_store_without_provider_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("loushang.ai.auth.core._oauth_providers", {})
    model = _model(Auth(kind="oauth", provider="openai-codex"))
    store = auth.FileCredentialStore(tmp_path)
    store.save(
        OAuthCredential(provider="openai-codex", access_token="stored-access")
    )

    assert asyncio.run(auth.logout(model, store=store)) is True
    assert store.load("openai-codex") is None

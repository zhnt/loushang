from __future__ import annotations

from types import MappingProxyType

import pytest

from loushang.ai import ApiKeyAuth, CallOptions, OAuthBearerAuth
from loushang.ai.auth import MissingAuthError
from loushang.ai.auth.support import AuthResolutionError, resolve_auth_for_model
from loushang.ai.model import Auth, Model


def _model(
    auth: Auth | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> Model:
    return Model(
        id="model-a",
        provider="provider-a",
        endpoint="endpoint-a",
        api="openai-responses",
        base_url="https://provider.test/v1",
        auth=auth,
        headers=headers or {},
    )


def test_default_api_key_uses_catalog_declaration_and_endpoint_headers() -> None:
    view = resolve_auth_for_model(
        _model(
            Auth(
                kind="apiKey",
                api_key_env="DEMO_API_KEY",
                header="x-api-key",
                prefix="",
            ),
            headers={"x-static": "catalog"},
        ),
        env={"DEMO_API_KEY": "secret"},
    )

    assert view.headers == {"x-static": "catalog", "x-api-key": "secret"}


def test_explicit_api_key_uses_catalog_header_and_prefix() -> None:
    view = resolve_auth_for_model(
        _model(Auth(header="X-Custom-Auth", prefix="Token ")),
        options=CallOptions(auth=ApiKeyAuth("secret")),
        env={},
    )

    assert view.headers == {"X-Custom-Auth": "Token secret"}


def test_oauth_extra_and_call_headers_follow_documented_order() -> None:
    view = resolve_auth_for_model(
        _model(
            Auth(kind="oauth"),
            headers={"x-layer": "static", "x-static": "yes"},
        ),
        options=CallOptions(
            auth=OAuthBearerAuth(
                "oauth-token",
                extra_headers={"x-layer": "credential", "x-account": "acct"},
            ),
            headers={"x-layer": "call", "x-call": "yes"},
        ),
        env={},
    )

    assert view.headers == {
        "x-static": "yes",
        "Authorization": "Bearer oauth-token",
        "x-account": "acct",
        "x-layer": "call",
        "x-call": "yes",
    }


@pytest.mark.parametrize(
    "options",
    [
        CallOptions(
            auth=OAuthBearerAuth(
                "token",
                extra_headers={"authorization": "Bearer replacement"},
            )
        ),
        CallOptions(
            auth=ApiKeyAuth("token"),
            headers={"AUTHORIZATION": "Bearer replacement"},
        ),
    ],
)
def test_later_headers_cannot_override_primary_auth(options: CallOptions) -> None:
    with pytest.raises(AuthResolutionError, match="cannot override"):
        resolve_auth_for_model(_model(Auth()), options=options, env={})


def test_primary_auth_overrides_same_static_header() -> None:
    view = resolve_auth_for_model(
        _model(
            Auth(),
            headers={"authorization": "Bearer static", "x-static": "yes"},
        ),
        options=CallOptions(auth=ApiKeyAuth("explicit")),
        env={},
    )

    assert view.headers == {
        "x-static": "yes",
        "Authorization": "Bearer explicit",
    }


def test_model_without_auth_declaration_requires_no_credentials() -> None:
    view = resolve_auth_for_model(
        _model(headers={"x-static": "yes"}),
        options=CallOptions(headers={"x-call": "yes"}),
        env={},
    )

    assert view.headers == {"x-static": "yes", "x-call": "yes"}


def test_explicit_auth_is_allowed_without_catalog_declaration() -> None:
    view = resolve_auth_for_model(
        _model(),
        options=CallOptions(auth=OAuthBearerAuth("token")),
        env={},
    )

    assert view.headers == {"Authorization": "Bearer token"}


def test_default_oauth_requires_explicit_credential() -> None:
    with pytest.raises(MissingAuthError, match="OAuthBearerAuth"):
        resolve_auth_for_model(_model(Auth(kind="oauth")), env={})


def test_missing_default_api_key_reports_expected_env() -> None:
    with pytest.raises(MissingAuthError) as exc_info:
        resolve_auth_for_model(
            _model(Auth(api_key_envs=("PRIMARY_KEY", "SECONDARY_KEY"))),
            env={},
        )

    assert exc_info.value.info.details == {
        "expected_env": ["PRIMARY_KEY", "SECONDARY_KEY"],
        "recovery": "configure",
    }


@pytest.mark.parametrize(
    "auth",
    [ApiKeyAuth(""), ApiKeyAuth("line\nfeed"), OAuthBearerAuth("   ")],
)
def test_explicit_secrets_are_strict(auth: object) -> None:
    with pytest.raises(AuthResolutionError):
        resolve_auth_for_model(
            _model(Auth()),
            options=CallOptions(auth=auth),  # type: ignore[arg-type]
            env={},
        )


def test_resolved_headers_are_read_only_and_redacted() -> None:
    auth = OAuthBearerAuth("super-secret", extra_headers={"x-account": "acct"})
    view = resolve_auth_for_model(
        _model(Auth(kind="oauth")),
        options=CallOptions(auth=auth),
        env={},
    )

    assert isinstance(view.headers, MappingProxyType)
    assert "super-secret" not in repr(auth)
    with pytest.raises(TypeError):
        view.headers["x-new"] = "value"  # type: ignore[index]

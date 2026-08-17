from __future__ import annotations

from types import MappingProxyType

import pytest

from loushang.ai.auth.credentials import (
    ApiKeyAuth,
    OAuthBearerAuth,
    OAuthCredential,
)


def test_auth_credentials_are_minimal_and_redacted() -> None:
    api_key = ApiKeyAuth("api-secret")
    oauth = OAuthBearerAuth(
        "oauth-secret",
        extra_headers={"chatgpt-account-id": "account"},
    )

    assert set(ApiKeyAuth.__dataclass_fields__) == {"value"}
    assert set(OAuthBearerAuth.__dataclass_fields__) == {
        "access_token",
        "extra_headers",
    }
    assert isinstance(oauth.extra_headers, MappingProxyType)
    assert "api-secret" not in repr(api_key)
    assert "oauth-secret" not in repr(oauth)


def test_oauth_extra_headers_are_defensively_copied() -> None:
    source = {"x-account": "one"}
    auth = OAuthBearerAuth("token", extra_headers=source)

    source["x-account"] = "two"

    assert auth.extra_headers == {"x-account": "one"}
    with pytest.raises(TypeError):
        auth.extra_headers["x-new"] = "value"  # type: ignore[index]


def test_oauth_credential_serializes_and_deserializes_stable_format() -> None:
    credential = OAuthCredential(
        provider="example-oauth",
        access_token="access-secret",
        refresh_token="refresh-secret",
        expires_at=1234567890,
        token_type="Bearer",
        extra_headers={"ChatGPT-Account-ID": "account-id"},
    )

    raw = credential.to_dict()

    assert raw == {
        "version": 1,
        "provider": "example-oauth",
        "credential_type": "oauth",
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "expires_at": 1234567890,
        "token_type": "Bearer",
        "extra_headers": {"ChatGPT-Account-ID": "account-id"},
    }
    assert OAuthCredential.from_dict(raw) == credential
    assert credential.to_auth() == OAuthBearerAuth(
        "access-secret",
        extra_headers={"ChatGPT-Account-ID": "account-id"},
    )
    assert "access-secret" not in repr(credential)
    assert "refresh-secret" not in repr(credential)


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"version": 2, "credential_type": "oauth"},
        {
            "version": 1,
            "credential_type": "api_key",
            "provider": "example",
            "access_token": "token",
        },
    ],
)
def test_oauth_credential_rejects_invalid_serialized_data(raw: object) -> None:
    from loushang.ai.auth import InvalidCredentialError

    with pytest.raises(InvalidCredentialError):
        OAuthCredential.from_dict(raw)  # type: ignore[arg-type]

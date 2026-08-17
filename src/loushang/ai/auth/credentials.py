from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import TypeAlias

from loushang.ai.auth.errors import InvalidCredentialError

_CREDENTIAL_VERSION = 1


@dataclass(frozen=True, slots=True)
class ApiKeyAuth:
    value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class OAuthBearerAuth:
    access_token: str = field(repr=False)
    extra_headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "extra_headers",
            MappingProxyType(dict(self.extra_headers)),
        )


@dataclass(frozen=True, slots=True)
class OAuthCredential:
    """Persistable OAuth credential used for loading and refresh."""

    access_token: str = field(repr=False)
    provider: str
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: float | int | None = None
    token_type: str = "Bearer"
    extra_headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        _validate_secret(self.access_token, "access_token")
        if self.refresh_token is not None:
            _validate_secret(self.refresh_token, "refresh_token")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise InvalidCredentialError(
                "OAuth credential provider must be a non-empty string.",
                details={"field": "provider", "recovery": "reconfigure"},
            )
        if any(character in self.provider for character in ("/", "\\", "\r", "\n")):
            raise InvalidCredentialError(
                "OAuth credential provider contains invalid characters.",
                details={"field": "provider", "recovery": "reconfigure"},
            )
        if self.expires_at is not None and (
            isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, int | float)
            or not isfinite(self.expires_at)
            or self.expires_at <= 0
        ):
            raise InvalidCredentialError(
                "OAuth credential expires_at must be a positive finite timestamp or null.",
                details={"field": "expires_at", "recovery": "login"},
            )
        if not isinstance(self.token_type, str) or not self.token_type.strip():
            raise InvalidCredentialError(
                "OAuth credential token_type must be a non-empty string.",
                details={"field": "token_type", "recovery": "login"},
            )
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "token_type", self.token_type.strip())
        object.__setattr__(
            self,
            "extra_headers",
            MappingProxyType(_validate_headers(self.extra_headers)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": _CREDENTIAL_VERSION,
            "provider": self.provider,
            "credential_type": "oauth",
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
            "extra_headers": dict(self.extra_headers),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "OAuthCredential":
        if not isinstance(raw, Mapping):
            raise InvalidCredentialError(
                "OAuth credential file must contain a JSON object.",
                details={"recovery": "login"},
            )
        if raw.get("version") != _CREDENTIAL_VERSION:
            raise InvalidCredentialError(
                "Unsupported OAuth credential file version.",
                details={
                    "version": str(raw.get("version")),
                    "recovery": "reconfigure",
                },
            )
        if raw.get("credential_type") != "oauth":
            raise InvalidCredentialError(
                "Credential file does not contain an OAuth credential.",
                details={"recovery": "reconfigure"},
            )
        access_token = raw.get("access_token")
        provider = raw.get("provider")
        refresh_token = raw.get("refresh_token")
        expires_at = raw.get("expires_at")
        token_type = raw.get("token_type", "Bearer")
        extra_headers = raw.get("extra_headers", {})
        if not isinstance(access_token, str):
            raise InvalidCredentialError(
                "OAuth credential access_token must be a string.",
                details={"field": "access_token", "recovery": "login"},
            )
        if not isinstance(provider, str):
            raise InvalidCredentialError(
                "OAuth credential provider must be a string.",
                details={"field": "provider", "recovery": "reconfigure"},
            )
        if refresh_token is not None and not isinstance(refresh_token, str):
            raise InvalidCredentialError(
                "OAuth credential refresh_token must be a string or null.",
                details={"field": "refresh_token", "recovery": "login"},
            )
        if expires_at is not None and (
            isinstance(expires_at, bool) or not isinstance(expires_at, int | float)
        ):
            raise InvalidCredentialError(
                "OAuth credential expires_at must be a number or null.",
                details={"field": "expires_at", "recovery": "login"},
            )
        if not isinstance(token_type, str):
            raise InvalidCredentialError(
                "OAuth credential token_type must be a string.",
                details={"field": "token_type", "recovery": "login"},
            )
        if not isinstance(extra_headers, Mapping):
            raise InvalidCredentialError(
                "OAuth credential extra_headers must be a string mapping.",
                details={"field": "extra_headers", "recovery": "reconfigure"},
            )
        return cls(
            access_token=access_token,
            provider=provider,
            refresh_token=refresh_token,
            expires_at=expires_at,
            token_type=token_type,
            extra_headers=extra_headers,  # type: ignore[arg-type]
        )

    def to_auth(self) -> OAuthBearerAuth:
        if self.token_type.casefold() != "bearer":
            raise InvalidCredentialError(
                "Only bearer OAuth credentials can authenticate model requests.",
                provider=self.provider,
                details={"token_type": self.token_type, "recovery": "login"},
            )
        return OAuthBearerAuth(
            access_token=self.access_token,
            extra_headers=self.extra_headers,
        )

    def is_expired(self, *, now: float) -> bool:
        return self.expires_at is not None and self.expires_at <= now

    def expires_within(self, seconds: float, *, now: float) -> bool:
        return self.expires_at is not None and self.expires_at <= now + seconds


def _validate_secret(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\r" in value
        or "\n" in value
    ):
        raise InvalidCredentialError(
            f"OAuth credential {field_name} must be a non-empty single-line string.",
            details={"field": field_name, "recovery": "login"},
        )


def _validate_headers(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise InvalidCredentialError(
            "OAuth credential extra_headers must be a string mapping.",
            details={"field": "extra_headers", "recovery": "reconfigure"},
        )
    headers: dict[str, str] = {}
    normalized: set[str] = set()
    for key, entry in value.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(entry, str)
            or not entry
            or "\r" in key
            or "\n" in key
            or "\r" in entry
            or "\n" in entry
        ):
            raise InvalidCredentialError(
                "OAuth credential extra_headers contains an invalid header.",
                details={"field": "extra_headers", "recovery": "reconfigure"},
            )
        folded = key.casefold()
        if folded in normalized:
            raise InvalidCredentialError(
                "OAuth credential extra_headers contains duplicate header names.",
                details={"field": "extra_headers", "recovery": "reconfigure"},
            )
        normalized.add(folded)
        headers[key] = entry
    return headers


AuthCredential: TypeAlias = ApiKeyAuth | OAuthBearerAuth


__all__ = [
    "ApiKeyAuth",
    "AuthCredential",
    "OAuthBearerAuth",
    "OAuthCredential",
]

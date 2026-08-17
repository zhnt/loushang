from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from loushang.ai.auth.credentials import ApiKeyAuth, AuthCredential, OAuthBearerAuth
from loushang.ai.auth.errors import MissingCredentialError
from loushang.ai.errors import AIAuthenticationError, AIConfigurationError
from loushang.ai.model import Auth
from loushang.foundation.json import JSONValue

AuthConfig = Auth

_HTTP_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class MissingAuthError(MissingCredentialError):
    pass


class MissingAuthConfigError(AIConfigurationError):
    pass


class InvalidAuthConfigError(AIConfigurationError):
    pass


class AuthResolutionError(AIAuthenticationError):
    pass


@dataclass(frozen=True)
class AuthView:
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


def resolve_auth_for_model(
    model,
    *,
    options=None,
    env: Mapping[str, str] | None = None,
) -> AuthView:
    return resolve_auth_for_request(model, options=options, env=env)


def resolve_auth_for_request(
    model,
    *,
    options=None,
    env: Mapping[str, str] | None = None,
) -> AuthView:
    declaration = getattr(model, "auth", None)
    explicit_auth = getattr(options, "auth", None) if options is not None else None
    call_headers = getattr(options, "headers", {}) if options is not None else {}
    static_headers = getattr(model, "headers", {})
    resolved_env = os.environ if env is None else env

    headers = _validated_headers(
        static_headers,
        source="model endpoint headers",
        invalid_config=True,
    )
    primary_header: str | None = None
    credential_headers: dict[str, str] = {}
    if explicit_auth is not None:
        primary_header, credential_headers = _resolve_explicit_credential(
            explicit_auth,
            declaration=declaration,
        )
    else:
        primary_header, credential_headers = _resolve_default_credential(
            declaration,
            model=model,
            env=resolved_env,
        )

    _merge_headers(headers, credential_headers)
    credential_extra_headers = (
        explicit_auth.extra_headers
        if isinstance(explicit_auth, OAuthBearerAuth)
        else {}
    )
    _merge_non_primary_headers(
        headers,
        _validated_headers(
            credential_extra_headers,
            source="OAuthBearerAuth.extra_headers",
        ),
        primary_header=primary_header,
        source="OAuthBearerAuth.extra_headers",
    )
    _merge_non_primary_headers(
        headers,
        _validated_headers(call_headers, source="CallOptions.headers"),
        primary_header=primary_header,
        source="CallOptions.headers",
    )
    return AuthView(headers=headers)


def resolve_explicit_auth(
    auth: AuthCredential,
    *,
    declaration_hint=None,
    provider_id: str | None = None,
    env: Mapping[str, str] | None = None,
) -> AuthView:
    del provider_id, env
    primary_header, headers = _resolve_explicit_credential(
        auth,
        declaration=declaration_hint,
    )
    if isinstance(auth, OAuthBearerAuth):
        _merge_non_primary_headers(
            headers,
            _validated_headers(
                auth.extra_headers,
                source="OAuthBearerAuth.extra_headers",
            ),
            primary_header=primary_header,
            source="OAuthBearerAuth.extra_headers",
        )
    return AuthView(headers=headers)


def resolve_default_auth(
    declaration,
    *,
    model,
    env: Mapping[str, str] | None = None,
) -> AuthView:
    _primary_header, headers = _resolve_default_credential(
        declaration,
        model=model,
        env=os.environ if env is None else env,
    )
    return AuthView(headers=headers)


def normalize_auth_kind(kind: str | None) -> str | None:
    if kind is None:
        return None
    normalized = kind.strip().replace("-", "_").lower()
    if normalized in {"apikey", "api_key"}:
        return "api_key"
    if normalized in {"oauth", "none"}:
        return normalized
    return normalized


def _resolve_explicit_credential(
    auth: AuthCredential,
    *,
    declaration,
) -> tuple[str, dict[str, str]]:
    header, prefix = _resolve_header_prefix(declaration)
    if isinstance(auth, ApiKeyAuth):
        secret = _validated_secret(auth.value, field_name="auth.value")
    elif isinstance(auth, OAuthBearerAuth):
        secret = _validated_secret(
            auth.access_token,
            field_name="auth.access_token",
        )
    else:
        raise AuthResolutionError(
            "Unsupported CallOptions.auth credential type.",
            details={"auth_type": type(auth).__name__},
        )
    return header, {header: f"{prefix}{secret}"}


def _resolve_default_credential(
    declaration,
    *,
    model,
    env: Mapping[str, str],
) -> tuple[str | None, dict[str, str]]:
    if declaration is None or normalize_auth_kind(declaration.kind) == "none":
        return None, {}
    kind = normalize_auth_kind(declaration.kind)
    if kind == "oauth":
        raise MissingAuthError(
            "Model declares oauth auth; provide CallOptions.auth=OAuthBearerAuth(...).",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=model.id,
            details={"expected_auth": "oauth"},
        )
    if kind != "api_key":
        raise InvalidAuthConfigError(
            "Unsupported model auth kind.",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=model.id,
            details={"auth_kind": str(kind)},
        )

    api_key = resolve_api_key_auth(declaration, model=model, env=env).value
    header, prefix = _resolve_header_prefix(declaration)
    return header, {header: f"{prefix}{api_key}"}


def resolve_api_key_auth(
    declaration,
    *,
    model,
    env: Mapping[str, str],
) -> ApiKeyAuth:
    env_names = _api_key_env_names(declaration)
    api_key = next(
        (
            value.strip()
            for name in env_names
            if isinstance((value := env.get(name)), str) and value.strip()
        ),
        None,
    )
    if api_key is None:
        raise MissingAuthError(
            "Model requires api_key auth but no configured API key env is set.",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=model.id,
            details={"expected_env": list(env_names), "recovery": "configure"},
        )
    return ApiKeyAuth(api_key)


def _resolve_header_prefix(declaration) -> tuple[str, str]:
    header = (
        getattr(declaration, "header", "Authorization")
        if declaration
        else "Authorization"
    )
    prefix = getattr(declaration, "prefix", "Bearer ") if declaration else "Bearer "
    if not isinstance(header, str) or not header or not _HTTP_TOKEN.fullmatch(header):
        raise InvalidAuthConfigError(
            "models.json.auth.header must be a valid HTTP header name.",
            details={"field": "header"},
        )
    if not isinstance(prefix, str) or "\r" in prefix or "\n" in prefix:
        raise InvalidAuthConfigError(
            "models.json.auth.prefix must be a string without CR or LF.",
            details={"field": "prefix"},
        )
    return header, prefix


def _api_key_env_names(declaration) -> tuple[str, ...]:
    names: list[str] = []
    if isinstance(declaration.api_key_env, str) and declaration.api_key_env:
        names.append(declaration.api_key_env)
    names.extend(
        name for name in declaration.api_key_envs if isinstance(name, str) and name
    )
    return tuple(dict.fromkeys(names))


def _merge_headers(target: dict[str, str], incoming: Mapping[str, str]) -> None:
    for key, value in incoming.items():
        existing = _find_header(target, key)
        if existing is not None and existing != key:
            del target[existing]
        target[key] = value


def _merge_non_primary_headers(
    target: dict[str, str],
    incoming: Mapping[str, str],
    *,
    primary_header: str | None,
    source: str,
) -> None:
    for key in incoming:
        if primary_header is not None and key.casefold() == primary_header.casefold():
            raise AuthResolutionError(
                f"{source} cannot override the primary authentication header.",
                details={"header": key, "primary_header": primary_header},
            )
    _merge_headers(target, incoming)


def _find_header(headers: Mapping[str, str], name: str) -> str | None:
    normalized = name.casefold()
    return next((key for key in headers if key.casefold() == normalized), None)


def _validated_secret(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthResolutionError(
            f"{field_name} must be a non-empty string.",
            details={"field": field_name},
        )
    resolved = value.strip()
    if "\r" in resolved or "\n" in resolved:
        raise AuthResolutionError(
            f"{field_name} must not contain CR or LF.",
            details={"field": field_name},
        )
    return resolved


def _validated_headers(
    value: object,
    *,
    source: str,
    invalid_config: bool = False,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise _auth_validation_error(
            f"{source} must be a mapping of strings.",
            details={"field": source},
            invalid_config=invalid_config,
        )
    headers: dict[str, str] = {}
    normalized_names: set[str] = set()
    for key, entry in value.items():
        if (
            not isinstance(key, str)
            or not key
            or not _HTTP_TOKEN.fullmatch(key)
            or not isinstance(entry, str)
            or not entry
            or "\r" in entry
            or "\n" in entry
        ):
            raise _auth_validation_error(
                f"{source} must contain valid non-empty HTTP header strings.",
                details={"field": source},
                invalid_config=invalid_config,
            )
        normalized = key.casefold()
        if normalized in normalized_names:
            raise _auth_validation_error(
                f"{source} contains duplicate case-insensitive header names.",
                details={"field": source, "header": key},
                invalid_config=invalid_config,
            )
        normalized_names.add(normalized)
        headers[key] = entry
    return headers


def _auth_validation_error(
    message: str,
    *,
    details: Mapping[str, JSONValue],
    invalid_config: bool,
) -> AIAuthenticationError | AIConfigurationError:
    error_type = InvalidAuthConfigError if invalid_config else AuthResolutionError
    return error_type(message, details=details)


__all__ = [
    "AuthConfig",
    "AuthResolutionError",
    "AuthView",
    "InvalidAuthConfigError",
    "MissingAuthConfigError",
    "MissingAuthError",
    "normalize_auth_kind",
    "resolve_auth_for_model",
    "resolve_auth_for_request",
    "resolve_default_auth",
    "resolve_explicit_auth",
    "resolve_api_key_auth",
]

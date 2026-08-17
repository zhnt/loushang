from __future__ import annotations

from loushang.ai.errors import AIAuthenticationError, AIConfigurationError


class AuthError(AIAuthenticationError):
    """Base error for credential lifecycle failures."""


class AuthenticationRequiredError(AuthError):
    """Authentication is missing and the caller must choose an available action."""


class MissingCredentialError(AuthenticationRequiredError):
    """No usable credential was found; the user should log in or configure one."""


class CredentialExpiredError(AuthError):
    """A credential cannot be used because it is expired or about to expire."""


class RefreshFailedError(AuthError):
    """An OAuth refresh attempt failed and interactive login may be required."""


class InvalidCredentialError(AuthError):
    """Credential data is malformed or incompatible with the selected provider."""


class OAuthProviderNotConfiguredError(AIConfigurationError):
    """An OAuth adapter is present but lacks an authorized client configuration."""


__all__ = [
    "AuthenticationRequiredError",
    "AuthError",
    "CredentialExpiredError",
    "InvalidCredentialError",
    "MissingCredentialError",
    "OAuthProviderNotConfiguredError",
    "RefreshFailedError",
]

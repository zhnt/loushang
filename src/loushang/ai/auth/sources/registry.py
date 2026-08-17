from __future__ import annotations

from loushang.ai.auth.registry import (
    AuthExtensionRegistry,
    AuthRegistry,
    AuthRoute,
    get_auth_extension_registry,
    get_auth_registry,
    get_credential_source,
    register_auth_adapter,
    register_credential_source,
)

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

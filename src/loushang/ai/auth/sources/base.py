from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from loushang.ai.auth.credentials import OAuthCredential


@runtime_checkable
class CredentialSource(Protocol):
    """Imports an existing external credential without owning OAuth login."""

    id: str
    description: str = ""
    recovery_hint: str = ""
    experimental: bool = False
    supports_refresh: bool = False

    def matches(self, model: object) -> bool: ...

    def load(self) -> OAuthCredential | None: ...

    def load_file(self, path: str | Path) -> OAuthCredential: ...


__all__ = ["CredentialSource"]

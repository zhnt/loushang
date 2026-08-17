from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from pathlib import Path

from loushang.ai.auth.credentials import OAuthCredential
from loushang.ai.auth.errors import InvalidCredentialError


class OpenAICodexCredentialSource:
    """Experimental importer for an existing Codex CLI file credential."""

    id = "openai-codex"
    description = "Use existing Codex CLI login"
    recovery_hint = "Run codex login"
    experimental = True
    recovery = "codex_login"
    supports_refresh = False

    def __init__(self, auth_path: str | Path | None = None) -> None:
        self._auth_path = (
            Path(auth_path).expanduser() if auth_path is not None else None
        )

    @property
    def auth_path(self) -> Path:
        return self._auth_path or Path.home() / ".codex" / "auth.json"

    def matches(self, model: object) -> bool:
        declaration = getattr(model, "auth", None)
        kind = getattr(declaration, "kind", None)
        if not isinstance(kind, str) or kind.strip().lower() != "oauth":
            return False
        provider_id = getattr(model, "provider_id", None)
        endpoint_id = getattr(model, "endpoint_id", None)
        if provider_id == "openai" and endpoint_id == "coding-responses":
            return True
        return getattr(declaration, "provider", None) == self.id

    def load(self) -> OAuthCredential | None:
        if not self.auth_path.exists():
            return None
        return load_codex_credential(self.auth_path)

    def load_file(self, path: str | Path) -> OAuthCredential:
        return load_codex_credential(path)


def load_codex_credential(path: str | Path) -> OAuthCredential:
    resolved = Path(path).expanduser()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InvalidCredentialError(
            "Codex auth file could not be read.",
            provider="openai-codex",
            details={
                "path": str(resolved),
                "cause": type(error).__name__,
                "experimental": True,
                "recovery": "codex_login",
            },
        ) from error
    if not isinstance(raw, Mapping) or raw.get("auth_mode") != "chatgpt":
        raise InvalidCredentialError(
            "Codex auth file does not contain a ChatGPT login.",
            provider="openai-codex",
            details={"experimental": True, "recovery": "codex_login"},
        )
    tokens = raw.get("tokens")
    if not isinstance(tokens, Mapping):
        raise InvalidCredentialError(
            "Codex auth file is missing its token object.",
            provider="openai-codex",
            details={"experimental": True, "recovery": "codex_login"},
        )
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    account_id = tokens.get("account_id")
    if not isinstance(access_token, str) or not access_token.strip():
        raise InvalidCredentialError(
            "Codex auth file is missing access_token.",
            provider="openai-codex",
            details={"experimental": True, "recovery": "codex_login"},
        )
    extra_headers = (
        {"ChatGPT-Account-ID": account_id}
        if isinstance(account_id, str) and account_id.strip()
        else {}
    )
    expires_at = tokens.get("expires_at")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int | float):
        expires_at = _jwt_exp(access_token)
    return OAuthCredential(
        provider="openai-codex",
        access_token=access_token,
        refresh_token=(
            refresh_token
            if isinstance(refresh_token, str) and refresh_token.strip()
            else None
        ),
        expires_at=expires_at,
        token_type="Bearer",
        extra_headers=extra_headers,
    )


def _jwt_exp(token: str) -> int | float | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(parts[1] + padding).decode("utf-8")
        )
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    expires_at = payload.get("exp")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int | float):
        return None
    return expires_at if expires_at > 0 else None


__all__ = ["OpenAICodexCredentialSource", "load_codex_credential"]

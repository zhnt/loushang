from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from loushang.ai.auth.credentials import OAuthCredential
from loushang.ai.auth.errors import InvalidCredentialError


class FileCredentialStore:
    """Versioned JSON OAuth credential store with atomic, mode-0600 writes."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = (
            Path(directory).expanduser()
            if directory is not None
            else Path.home() / ".loushang" / "auth"
        )

    def path_for(self, provider: str) -> Path:
        normalized = _validated_provider(provider)
        return self.directory / f"{normalized}-auth.json"

    def save(self, credential: OAuthCredential) -> Path:
        path = self.path_for(credential.provider)
        save_credential_file(path, credential)
        return path

    def load(self, provider: str) -> OAuthCredential | None:
        path = self.path_for(provider)
        if not path.exists():
            return None
        return load_credential_file(path)

    def delete(self, provider: str) -> bool:
        path = self.path_for(provider)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True


def load_credential_file(path: str | Path) -> OAuthCredential:
    resolved = Path(path).expanduser()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InvalidCredentialError(
            "OAuth credential file could not be read.",
            details={
                "path": str(resolved),
                "cause": type(error).__name__,
                "recovery": "reconfigure",
            },
        ) from error
    if not isinstance(raw, dict):
        raise InvalidCredentialError(
            "OAuth credential file must contain a JSON object.",
            details={"path": str(resolved), "recovery": "reconfigure"},
        )
    return OAuthCredential.from_dict(raw)


def save_credential_file(path: str | Path, credential: OAuthCredential) -> None:
    resolved = Path(path).expanduser()
    directory = resolved.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with suppress(OSError):
        directory.chmod(0o700)
    payload = (
        json.dumps(
            credential.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=directory,
        prefix=f".{resolved.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, resolved)
        resolved.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            temporary_path.unlink()


def _validated_provider(provider: str) -> str:
    if (
        not isinstance(provider, str)
        or not provider.strip()
        or any(character in provider for character in ("/", "\\", "\r", "\n"))
    ):
        raise InvalidCredentialError(
            "OAuth provider id is not valid for credential storage.",
            details={"field": "provider", "recovery": "reconfigure"},
        )
    return provider.strip()


__all__ = [
    "FileCredentialStore",
    "load_credential_file",
    "save_credential_file",
]

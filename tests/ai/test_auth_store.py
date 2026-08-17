from __future__ import annotations

import stat
from pathlib import Path

from loushang.ai.auth import FileCredentialStore, OAuthCredential


def _credential() -> OAuthCredential:
    return OAuthCredential(
        provider="example-oauth",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=2000,
        extra_headers={"x-account": "account"},
    )


def test_file_credential_store_save_load_delete(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "auth")

    path = store.save(_credential())

    assert path == tmp_path / "auth" / "example-oauth-auth.json"
    assert store.load("example-oauth") == _credential()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not list(path.parent.glob("*.tmp"))
    assert store.delete("example-oauth") is True
    assert store.load("example-oauth") is None
    assert store.delete("example-oauth") is False


def test_file_credential_store_atomically_replaces_existing_file(
    tmp_path: Path,
) -> None:
    store = FileCredentialStore(tmp_path)
    first = _credential()
    second = OAuthCredential(
        provider="example-oauth",
        access_token="new-access-token",
        refresh_token="new-refresh-token",
        expires_at=3000,
    )

    path = store.save(first)
    first_inode = path.stat().st_ino
    store.save(second)

    assert store.load("example-oauth") == second
    assert path.stat().st_ino != first_inode
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

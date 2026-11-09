"""Host-owned client navigation state; display preferences remain client-local."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from loushang.foundation.platform_paths import resolve_platform_home


class ClientPreferences:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or resolve_platform_home()
        self.path = self.home / "data" / "client-preferences.sqlite3"

    def apply(self, scope: str, action: str = "read", session: str = "") -> dict:
        if not isinstance(scope, str) or not 1 <= len(scope) <= 1024:
            raise ValueError("invalid preference scope")
        if action not in {"read", "visit", "pin", "unpin"}:
            raise ValueError("invalid preference action")
        if action != "read" and (
            not isinstance(session, str) or not 1 <= len(session) <= 512
        ):
            raise ValueError("invalid session")
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as db:
            self.path.chmod(0o600)
            db.execute(
                "CREATE TABLE IF NOT EXISTS preferences (scope TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT value FROM preferences WHERE scope = ?", (scope,)
            ).fetchone()
            value = (
                json.loads(row[0])
                if row
                else {"pinned": [], "recent": [], "selected": ""}
            )
            if action == "visit":
                value["recent"] = [
                    session,
                    *[item for item in value["recent"] if item != session],
                ][:128]
                value["selected"] = session
            if action in {"pin", "unpin"}:
                value["pinned"] = [item for item in value["pinned"] if item != session]
                if action == "pin":
                    value["pinned"] = [session, *value["pinned"]][:128]
            if action != "read":
                db.execute(
                    "INSERT OR REPLACE INTO preferences VALUES (?, ?)",
                    (scope, json.dumps(value)),
                )
            return value

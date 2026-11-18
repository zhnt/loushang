"""Host-owned client navigation state; display preferences remain client-local."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

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


def connections() -> dict:
    path = resolve_platform_home() / "connections.json"
    if not path.exists():
        return {"version": 1, "lastWorkspace": "", "servers": []}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("invalid_connections")
    servers = value.get("servers")
    if not isinstance(servers, list) or len(servers) > 128:
        raise ValueError("invalid_connections")
    ids = set()
    for server in servers:
        if not isinstance(server, dict):
            raise ValueError("invalid_connection")
        identifier = server.get("id")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier)
            or identifier == "local"
            or identifier in ids
        ):
            raise ValueError("invalid_connection_id")
        ids.add(identifier)
        port = server.get("tunnelPort")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid_tunnel_port")
        url = server.get("webUrl")
        if url is not None:
            if not isinstance(url, str) or len(url) > 4096:
                raise ValueError("invalid_server_url")
            parsed = urlsplit(url)
            if (
                not parsed.hostname
                or "@" in parsed.netloc
                or parsed.query
                or parsed.fragment
                or parsed.scheme not in {"http", "https"}
            ):
                raise ValueError("invalid_server_url")
    if value.get("defaultConnection") and value["defaultConnection"] not in ids:
        raise ValueError("unknown_connection")
    return value


def remember_workspace(workspace: str) -> None:
    home = resolve_platform_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    mutate_connections(lambda value: value.update(lastWorkspace=workspace))


def mutate_connections(change) -> None:
    home = resolve_platform_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = home / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    with sqlite3.connect(state / "connection-config-lock.sqlite3", timeout=10) as lock:
        lock.execute("BEGIN IMMEDIATE")
        value = connections()
        change(value)
        write_connections(value)


def write_connections(value: dict) -> None:
    from loushang.harness.config.store import _write_json_atomically

    home = resolve_platform_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_json_atomically(
        home / "connections.json", value, temporary_prefix=".connections-"
    )


def connection_list() -> dict:
    home = resolve_platform_home()
    value = connections()
    selected = value.get("defaultConnection") or "local"
    host_path = home / "host.json"
    web = json.loads(host_path.read_text()).get("web", {}) if host_path.exists() else {}
    port = web.get("port", 1422)
    scheme = "https" if web.get("certificate") else "http"
    bind = web.get("bind", "127.0.0.1")
    address = "127.0.0.1" if bind in {"localhost", "0.0.0.0"} else bind
    web_url = f"{scheme}://{address}:{port}" if port else None
    endpoint = home / "state" / "web" / "endpoint.json"
    if endpoint.exists():
        web_url = json.loads(endpoint.read_text())["url"]
    if web_url is not None:
        if not isinstance(web_url, str):
            raise ValueError("invalid_web_url")
        parsed = urlsplit(web_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname != address
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid_web_url")
    entries = [
        {
            "id": "local",
            "name": "Local",
            "kind": "local",
            "selected": selected == "local",
            "webUrl": web_url,
        }
    ]
    entries.extend(
        {
            "id": item["id"],
            "name": item.get("name", item["id"]),
            "kind": "remote",
            "selected": item["id"] == selected,
            "webUrl": item.get("webUrl"),
        }
        for item in value["servers"]
    )
    return {"selectedId": selected, "connections": entries}

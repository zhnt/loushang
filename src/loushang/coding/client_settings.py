"""Shared connection configuration and Host-owned navigation state access."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

from loushang.apphost.client_preferences import ClientPreferences
from loushang.foundation.platform_paths import resolve_platform_home

TEMPORARY_WORKSPACE = "@temporary"


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
    _write_json_atomically(home / "connections.json", value, temporary_prefix=".connections-")


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


def settings_request(request: dict):
    if request.get("operation") == "connections/list":
        return connection_list()
    if request.get("operation") == "connections/select":
        selected = request["connectionId"]
        if selected not in {item["id"] for item in connection_list()["connections"]}:
            raise ValueError("unknown_connection")

        def select(value):
            if selected == "local":
                value.pop("defaultConnection", None)
            else:
                value["defaultConnection"] = selected

        mutate_connections(select)
        return connection_list()
    if request.get("operation") == "environment":
        return {
            "supported": sys.platform == "linux",
            "workspace": connections().get("lastWorkspace", ""),
            "connections": connection_list()["connections"],
        }
    if request.get("operation") == "remember-workspace":
        path = request["workspace"]
        if (
            not isinstance(path, str)
            or (path != TEMPORARY_WORKSPACE and not Path(path).is_absolute())
            or len(path) > 4096
        ):
            raise ValueError("invalid_workspace")
        remember_workspace(path)
        return {}
    if request.get("operation") == "preferences":
        return ClientPreferences().apply(
            request["scope"], request.get("action", "read"), request.get("session", "")
        )
    raise ValueError("unknown_operation")

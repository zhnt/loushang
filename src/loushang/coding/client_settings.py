"""Shared connection configuration and Host-owned navigation state access."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from loushang.apphost.client_preferences import ClientPreferences
from loushang.foundation.platform_paths import resolve_platform_home


def connections() -> dict:
    path = resolve_platform_home() / "connections.json"
    if not path.exists():
        return {"version": 1, "defaultWorkspace": "", "servers": []}
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
        url = server.get("url")
        if not isinstance(url, str) or len(url) > 4096:
            raise ValueError("invalid_server_url")
        parsed = urlsplit(url)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.scheme not in {"http", "https"}
        ):
            raise ValueError("invalid_server_url")
        if parsed.scheme == "http" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("https_required")
    if value.get("defaultConnection") and value["defaultConnection"] not in ids:
        raise ValueError("unknown_connection")
    return value


def remember_workspace(workspace: str) -> None:
    home = resolve_platform_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    mutate_connections(lambda value: value.update(defaultWorkspace=workspace))


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
    home = resolve_platform_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=home, prefix=".connections-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, home / "connections.json")
    finally:
        Path(name).unlink(missing_ok=True)


def selected_server() -> dict | None:
    value = connections()
    selected = value.get("defaultConnection")
    if not selected:
        return None
    server = next(
        (entry for entry in value["servers"] if entry.get("id") == selected), None
    )
    if server is None:
        raise ValueError("unknown_connection")
    return server


def remote_request(request: dict, connection_id: str | None = None):
    import httpx

    if connection_id == "local":
        server = None
    elif connection_id is not None:
        server = next(
            (
                item
                for item in connections()["servers"]
                if item.get("id") == connection_id
            ),
            None,
        )
        if server is None:
            raise ValueError("unknown_connection")
    else:
        server = selected_server()
    if server is None:
        from .web_endpoint import local_endpoint

        url, token = local_endpoint()
    else:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", server["id"]):
            raise ValueError("invalid_connection")
        url = server["url"].rstrip("/")
        parsed = urlsplit(url)
        if (
            (
                parsed.scheme != "https"
                and not (
                    parsed.scheme == "http"
                    and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                )
            )
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid_server_url")
        credential = (
            resolve_platform_home() / "auth" / "connections" / (server["id"] + ".json")
        )
        token = json.loads(credential.read_text())["token"]
    with httpx.Client(timeout=80, follow_redirects=False, trust_env=False) as client:
        with client.stream(
            "POST",
            url + "/api/loushang",
            json=request,
            headers={"Authorization": "Bearer " + token, "X-Loushang-Client": "1"},
        ) as response:
            response.raise_for_status()
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > 16_777_216:
                    raise ValueError("response_too_large")
            value = json.loads(payload)
    if "result" not in value:
        raise ValueError("remote_request_failed")
    return value["result"]


def connection_list() -> dict:
    home = resolve_platform_home()
    value = connections()
    selected = value.get("defaultConnection") or "local"
    host_path = home / "host.json"
    web = json.loads(host_path.read_text()).get("web", {}) if host_path.exists() else {}
    port = web.get("port", 1422)
    scheme = "https" if web.get("certificate") else "http"
    web_url = f"{scheme}://127.0.0.1:{port}" if port else None
    endpoint = home / "state" / "web" / "endpoint.json"
    if endpoint.exists():
        web_url = json.loads(endpoint.read_text())["url"]
    if web_url is not None:
        if not isinstance(web_url, str):
            raise ValueError("invalid_web_url")
        parsed = urlsplit(web_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
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
            "workspace": value.get("defaultWorkspace", ""),
        }
    ]
    entries.extend(
        {
            "id": item["id"],
            "name": item.get("name", item["id"]),
            "kind": "remote",
            "selected": item["id"] == selected,
            "webUrl": item["url"],
            "workspace": item.get("workspace", ""),
        }
        for item in value["servers"]
    )
    return {"selectedId": selected, "connections": entries}


def settings_request(request: dict, *, local: bool = False):
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
    if request.get("operation") == "host/request":
        if local:
            raise ValueError("proxy_not_available")
        return remote_request(request["request"], request["connectionId"])
    if not local and request.get("operation") == "remote-call":
        return remote_request(request["request"])
    if not local:
        selected = connections().get("defaultConnection") or "local"
        value = remote_request(request, selected)
        if request.get("operation") == "environment":
            value["remote"] = True
            value["connectionId"] = selected
        return value
    if request.get("operation") == "environment":
        return {
            "supported": sys.platform == "linux",
            "workspace": connections().get("defaultWorkspace") or str(Path.cwd()),
            "connections": connection_list()["connections"],
        }
    if request.get("operation") == "remember-workspace":
        path = request["workspace"]
        if (
            not isinstance(path, str)
            or not Path(path).is_absolute()
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


def main():
    try:
        raw = sys.stdin.buffer.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("request_too_large")
        result = settings_request(json.loads(raw))
        print(json.dumps({"result": result}))
    except Exception:
        print(json.dumps({"error": "settings_unavailable"}))


if __name__ == "__main__":
    main()

"""Real local Host smoke: no provider requests and no external network."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from loushang.apphost.client_preferences import ClientPreferences
from loushang.coding.client_settings import connections, remember_workspace


def test_preferences_merge_across_clients_and_restart(tmp_path):
    def pin(index):
        ClientPreferences(tmp_path).apply("mux:one", "pin", f"session-{index}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(pin, range(12)))
    store = ClientPreferences(tmp_path)
    assert len(store.apply("mux:one")["pinned"]) == 12
    store.apply("mux:one", "visit", "session-2")
    store.apply("mux:one", "visit", "session-3")
    value = ClientPreferences(tmp_path).apply("mux:one")
    assert value["recent"] == ["session-3", "session-2"]
    assert value["selected"] == "session-3"
    assert store.apply("mux:other")["pinned"] == []
    store.apply("mux:one", "unpin", "session-2")
    assert "session-2" not in store.apply("mux:one")["pinned"]


def test_connections_preserve_server_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path))
    value = {"version": 1, "servers": [{"id": "remote", "webUrl": "https://example.test", "tunnelPort": 24420}]}
    (tmp_path / "connections.json").write_text(json.dumps(value))
    remember_workspace("/workspace")
    assert connections() == {**value, "lastWorkspace": "/workspace"}




def test_connection_listing_selection_and_secret_rejection(tmp_path, monkeypatch):
    from loushang.coding.client_settings import settings_request

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path))
    saved = {
        "version": 1,
        "defaultWorkspace": "/work",
        "servers": [
            {"id": "office", "name": "Office", "webUrl": "http://192.0.2.10:1422", "tunnelPort": 24420}
        ],
    }
    (tmp_path / "connections.json").write_text(json.dumps(saved))
    listing = settings_request({"operation": "connections/list"})
    assert listing["selectedId"] == "local"
    assert [item["id"] for item in listing["connections"]] == ["local", "office"]
    selected = settings_request(
        {"operation": "connections/select", "connectionId": "office"}
    )
    assert selected["selectedId"] == "office"
    assert connections()["defaultWorkspace"] == "/work"
    with pytest.raises(ValueError):
        settings_request({"operation": "connections/select", "connectionId": "missing"})
    settings_request({"operation": "connections/select", "connectionId": "local"})
    assert "defaultConnection" not in connections()
    saved["servers"][0]["webUrl"] = "https://user:secret@host.example"
    (tmp_path / "connections.json").write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="invalid_server_url"):
        settings_request({"operation": "connections/list"})






def test_connection_listing_rejects_secret_endpoint(tmp_path, monkeypatch):
    from loushang.coding import client_settings

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path))
    endpoint = tmp_path / "state/web/endpoint.json"
    endpoint.parent.mkdir(parents=True)
    endpoint.write_text(
        json.dumps({"url": "http://secret@localhost:1422/?token=secret"})
    )
    with pytest.raises(ValueError, match="invalid_web_url"):
        client_settings.connection_list()

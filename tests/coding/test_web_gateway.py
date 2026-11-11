"""Real local Host smoke: no provider requests and no external network."""

from __future__ import annotations

import asyncio
import json
import sys
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
    value = {"version": 1, "servers": [{"id": "remote", "url": "https://example.test"}]}
    (tmp_path / "connections.json").write_text(json.dumps(value))
    remember_workspace("/workspace")
    assert connections() == {**value, "defaultWorkspace": "/workspace"}


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="managed Host is Linux-only")
def test_web_gateway_real_host_snapshot_create_and_shared_state(tmp_path, monkeypatch):
    from loushang.coding.web_gateway import WebGateway

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name, leaf in (
        ("LOUSHANG_HOME", "home"),
        ("LOUSHANG_RUNTIME_DIR", "runtime"),
        ("LOUSHANG_TMPDIR", "temporary"),
    ):
        monkeypatch.setenv(name, str(tmp_path / leaf))

    async def run():
        gateway = WebGateway()
        status = None
        base = {"workspace": str(workspace)}
        try:
            status = await gateway.dispatch(
                {**base, "operation": "manage", "action": "start"}
            )
            assert status["state"] == "running", status
            assert not status.get("errorCode"), status
            assert "recordRoot" not in status
            snapshot = await gateway.dispatch(
                {**base, "operation": "live", "action": "snapshot"}
            )
            assert snapshot["sessions"]
            assert isinstance(snapshot["muxSpace"]["revision"], str)
            created = await gateway.dispatch(
                {
                    **base,
                    "operation": "live",
                    "action": "create",
                    "input": {"title": "Web session"},
                }
            )
            updated = await gateway.dispatch(
                {**base, "operation": "live", "action": "snapshot"}
            )
            assert created["sessionId"] in [
                item["source"]["source"]["identity"]["sessionId"]
                for item in updated["sessions"]
            ]
            # Another authenticated client can observe the same mux, and a
            # repeated browser connect must preserve the existing adapter owner.
            first_client = gateway.clients[str(workspace)]
            again = await gateway.dispatch(
                {**base, "operation": "manage", "action": "connect"}
            )
            assert again["state"] == "running"
            assert gateway.clients[str(workspace)] is first_client
            assert (await first_client.call("snapshot", {}))["sessions"]
            key = "mux:" + snapshot["muxSpace"]["muxSpaceId"]
            await gateway.dispatch(
                {
                    "operation": "preferences",
                    "scope": key,
                    "action": "pin",
                    "session": created["sessionId"],
                }
            )
            assert ClientPreferences().apply(key)["pinned"] == [created["sessionId"]]
        finally:
            await gateway.close()
            if status and status.get("instanceId"):
                from loushang.coding.gui_local_host import operate

                await operate(
                    {**base, "action": "stop", "instanceId": status["instanceId"]}
                )

    asyncio.run(run())


def test_connection_listing_selection_and_secret_rejection(tmp_path, monkeypatch):
    from loushang.coding.client_settings import settings_request

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path))
    saved = {
        "version": 1,
        "defaultWorkspace": "/work",
        "servers": [
            {"id": "office", "name": "Office", "url": "http://192.0.2.10:1422"}
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
    saved["servers"][0]["url"] = "https://user:secret@host.example"
    (tmp_path / "connections.json").write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="invalid_server_url"):
        settings_request({"operation": "connections/list"})


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="managed Host is Linux-only")
def test_web_execution_streaming_idempotency_and_interrupt(tmp_path, monkeypatch):
    import os
    from dataclasses import replace
    from pathlib import Path

    from loushang.coding import web_gateway
    from loushang.coding.gui_local_host import operate
    from loushang.coding.managed_process import coding_managed_process_request

    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "desktop-scenario-v2").touch()
    for name, leaf in (
        ("LOUSHANG_HOME", "home"),
        ("LOUSHANG_RUNTIME_DIR", "runtime"),
        ("LOUSHANG_TMPDIR", "temporary"),
    ):
        monkeypatch.setenv(name, str(tmp_path / leaf))

    def factory(invocation, descriptor):
        original = coding_managed_process_request(
            invocation, descriptor, executable=sys.executable, environment=os.environ
        )
        return replace(
            original,
            argv=(
                sys.executable,
                str(Path(__file__).with_name("_managed_execution_host.py")),
                *original.argv[3:],
            ),
        )

    async def managed(request):
        return await operate(request, request_factory=factory)

    monkeypatch.setattr(web_gateway, "operate", managed)

    async def run():
        gateway = web_gateway.WebGateway()
        status = None
        base = {"workspace": str(workspace)}

        async def live(action, **value):
            return await gateway.dispatch(
                {**base, "operation": "live", "action": action, "input": value}
            )

        async def until(predicate):
            async with asyncio.timeout(30):
                while True:
                    snapshot = await live("snapshot")
                    if predicate(snapshot["sessions"][0]):
                        return snapshot["sessions"][0]
                    await asyncio.sleep(0.05)

        try:
            status = await gateway.dispatch(
                {**base, "operation": "manage", "action": "start"}
            )
            assert status["state"] == "running", status
            snapshot = await live("snapshot")
            session_id = snapshot["sessions"][0]["source"]["source"]["identity"][
                "sessionId"
            ]
            request = {
                "sessionId": session_id,
                "submissionId": "web-submit-1",
                "text": "Test streaming without external API",
            }
            receipt = await live("submit", **request)
            assert receipt["accepted"]
            assert (await live("submit", **request))["executionId"] == receipt[
                "executionId"
            ]
            streaming = await until(lambda session: bool(session["source"]["draft"]))
            assert "正在执行" in streaming["source"]["draft"]
            assert (
                await live(
                    "interrupt",
                    sessionId=session_id,
                    executionId=receipt["executionId"],
                )
            )["accepted"]
            stopped = await until(
                lambda session: (
                    session["executions"]["active"] is None
                    and session["executions"]["latestTerminal"] is not None
                )
            )
            assert stopped["executions"]["latestTerminal"]["status"] == "interrupted"
        finally:
            await gateway.close()
            if status and status.get("instanceId"):
                await managed(
                    {**base, "action": "stop", "instanceId": status["instanceId"]}
                )

    asyncio.run(run())


def test_uncertain_submit_is_not_replayed(tmp_path):
    from types import SimpleNamespace

    from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
    from loushang.coding.web_client import WebHostClient

    class LostExecution:
        service_instance_id = "instance"
        calls = 0

        async def submit_execution(self, *_):
            self.calls += 1
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)

    async def run():
        client = WebHostClient(tmp_path, "main")
        execution = LostExecution()
        client.connection = SimpleNamespace(execution_client=execution)
        client.control = lambda _: None
        receipt = await client.call(
            "submit",
            {"sessionId": "session", "submissionId": "submission", "text": "hello"},
        )
        assert receipt == {
            "accepted": False,
            "submissionId": "submission",
            "reason": "submission_outcome_unknown",
        }
        assert execution.calls == 1

    asyncio.run(run())


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

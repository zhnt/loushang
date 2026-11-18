from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from loushang.coding.cli.mux import main


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native AppHost lifecycle")
def test_loushang_mux_service_manages_one_windows_instance(tmp_path):
    environment = {
        **os.environ,
        "LOUSHANG_HOME": str(tmp_path / "home"),
        "LOUSHANG_RUNTIME_DIR": str(tmp_path / "run"),
        "LOUSHANG_TMPDIR": str(tmp_path / "scratch"),
    }

    def command(action, *args):
        return [
            sys.executable, "-m", "loushang.coding.cli.mux",
            "service", action, "--json", *args,
        ]

    def invoke(action, *args, status=0):
        result = subprocess.run(
            command(action, *args), cwd=tmp_path, env=environment,
            capture_output=True, text=True, timeout=75,
        )
        assert result.returncode == status, result.stderr
        return json.loads(result.stdout)

    try:
        assert invoke("status")["state"] == "not_running"
        first = invoke("start")
        assert first["state"] == "running"
        assert first["recordRoot"]
        assert invoke("status") == first
        assert invoke("start") == first

        second = invoke("restart", "--instance", first["instanceId"])
        assert second["state"] == "running"
        assert second["instanceId"] != first["instanceId"]
        assert second["recordRoot"] == first["recordRoot"]
        stale = invoke("stop", "--instance", first["instanceId"], status=1)
        assert stale["errorCode"] == "instance_changed"
        assert invoke("status") == second

        assert invoke("stop", "--instance", second["instanceId"])["state"] == "not_running"
        assert invoke("status")["state"] == "not_running"
    finally:
        subprocess.run(
            command("stop"), cwd=tmp_path, env=environment,
            capture_output=True, text=True, timeout=45,
        )

def test_service_run_requires_systemd_notify_socket(monkeypatch, capsys):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert main(["service", "run"]) == 1
    assert "notification socket" in capsys.readouterr().err


def test_systemd_status_uses_the_published_managed_connection_root(tmp_path, monkeypatch):
    from loushang.coding.cli import mux_service

    endpoint = tmp_path / "endpoint.json"
    record_root = str(tmp_path / "managed/connection")
    endpoint.write_text(json.dumps({"recordRoot": record_root}))
    monkeypatch.setattr(mux_service, "_systemd_endpoint", lambda: endpoint)
    monkeypatch.setattr(mux_service.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        stdout="LoadState=loaded\nActiveState=active\nInvocationID=" + "a" * 32,
    ))
    assert mux_service._systemd_state()["recordRoot"] == record_root
    endpoint.write_text('{"recordRoot": "relative"}')
    from loushang.coding.managed_service import ServiceControlError
    with pytest.raises(ServiceControlError, match="management_unavailable"):
        mux_service._systemd_state()

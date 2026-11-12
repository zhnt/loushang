from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


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

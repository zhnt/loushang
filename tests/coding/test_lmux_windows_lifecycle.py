"""Exercise the installed lmux lifecycle through independent Windows processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows managed AppHost lifecycle")


def test_windows_lmux_starts_reuses_stops_and_restarts(tmp_path):
    env = {
        **os.environ,
        "LOUSHANG_HOME": str(tmp_path / "home"),
        "LOUSHANG_RUNTIME_DIR": str(tmp_path / "run"),
        "LOUSHANG_TMPDIR": str(tmp_path / "scratch"),
    }
    command = [sys.executable, "-m", "loushang.coding.cli.lmux"]

    def invoke(*args):
        completed = subprocess.run(
            [*command, *args], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=45,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout.splitlines()[-1])

    name = "windows-native"
    active = False
    try:
        first = invoke("server", "start", "--name", name)
        active = True
        assert first["status"] == "service_ready"
        assert invoke("server", "start", "--name", name)["instanceId"] == first["instanceId"]

        observed = invoke("status", "--server", name)
        assert observed["serviceId"] == first["serviceId"]
        assert observed["instanceId"] == first["instanceId"]
        assert observed["recordedPhase"] == "committed"
        assert not observed["cleanlyStopped"]

        stopped = invoke("stop", "--server", name, "--yes")
        active = False
        assert stopped["status"] == "stopped"
        assert invoke("status", "--server", name)["cleanlyStopped"]

        second = invoke("server", "start", "--name", name)
        active = True
        assert second["status"] == "service_ready"
        assert second["serviceId"] == first["serviceId"]
        assert second["instanceId"] != first["instanceId"]
        assert invoke("stop", "--server", name, "--yes")["status"] == "stopped"
        active = False
    finally:
        if active:
            subprocess.run(
                [*command, "stop", "--server", name, "--yes"], env=env, cwd=tmp_path,
                capture_output=True, text=True, timeout=45,
            )

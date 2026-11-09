"""Desktop helper uses production managed processes, without an in-process Host."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

pytestmark = [pytest.mark.requires_host_runtime,
              pytest.mark.skipif(sys.platform != "linux", reason="Linux managed lifecycle")]


def test_failed_native_spawn_is_not_reported_as_ready(tmp_path, monkeypatch):
    from loushang.coding.gui_local_host import operate
    from loushang.coding.managed_process import coding_managed_process_request

    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    for name, leaf in (("LOUSHANG_HOME", "home"), ("LOUSHANG_RUNTIME_DIR", "runtime"),
                       ("LOUSHANG_TMPDIR", "temporary")):
        monkeypatch.setenv(name, str(tmp_path / leaf))

    def missing_executable(invocation, descriptor):
        original = coding_managed_process_request(invocation, descriptor,
            executable=sys.executable, environment=os.environ)
        return replace(original, argv=(str(tmp_path / "missing-python"),))

    failed = asyncio.run(operate({"action": "start", "workspace": str(workspace)},
                                 request_factory=missing_executable))
    assert failed["state"] == "unknown", failed
    assert failed["errorCode"] is not None
    assert not failed.get("serviceInstanceId")
    assert not failed.get("pid")
    inspected = asyncio.run(operate({"action": "status", "workspace": str(workspace)}))
    assert inspected["state"] != "running", inspected


def test_desktop_management_cold_start_reuse_restart_and_stop(tmp_path):
    home, workspace = tmp_path / "home", tmp_path / "workspace"
    home.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    environment = {**os.environ, "LOUSHANG_HOME": str(home),
                   "LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime"),
                   "LOUSHANG_TMPDIR": str(tmp_path / "temporary")}

    def call(action, instance=None):
        request = {"action": action, "workspace": str(workspace)}
        if instance is not None:
            request["instanceId"] = instance
        result = subprocess.run([sys.executable, "-m", "loushang.coding.gui_local_host"],
            input=json.dumps(request), capture_output=True, text=True, env=environment, timeout=90)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    initial = call("status")
    assert initial["state"] == "not_running", initial
    assert not (home / "lmux").exists(), "status must not initialize managed storage"
    latest = None
    try:
        latest = call("start")
        assert latest["state"] == "running", latest
        assert latest["pid"] != os.getpid()
        original = latest
        with ThreadPoolExecutor(max_workers=2) as callers:
            concurrent = list(callers.map(lambda _: call("start"), range(2)))
        assert all(item["instanceId"] == original["instanceId"] for item in concurrent)
        probe = Path(__file__).resolve().parents[2] / "gui/contracts/rust/target/debug/snapshot_probe"
        assert probe.is_file(), "build existing Rust probes before G1 process acceptance"

        def snapshot(status, prepare=False):
            result = subprocess.run([str(probe), status["recordRoot"], "5000", status["muxName"],
                *(["--prepare-default"] if prepare else [])], capture_output=True, text=True, timeout=15)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)

        before = snapshot(original, prepare=True)
        session_id = before["sessions"][0]["source"]["source"]["identity"]["sessionId"]
        histories = {str(path): path.read_bytes().splitlines()[0]
                     for path in (home / "data/sessions").rglob("*.jsonl")}
        assert histories
        reused = call("start")
        for key in ("instanceId", "serviceInstanceId", "pid", "muxName"):
            assert reused[key] == original[key]
        assert call("stop", "0" * 32)["errorCode"] == "instance_changed"
        connected = call("connect")
        assert connected["serviceInstanceId"] == original["serviceInstanceId"]
        record = next(Path(original["recordRoot"]).glob("*.json"))
        saved = record.read_bytes()
        try:
            corrupted = json.loads(saved)
            corrupted["key"] = "00" * 32
            record.write_text(json.dumps(corrupted))
            assert call("status")["errorCode"] == "authentication_failed"
            corrupted["protocolVersion"] = "unsupported/v99"
            record.write_text(json.dumps(corrupted))
            assert call("start")["state"] == "unknown"
        finally:
            record.write_bytes(saved)
        assert call("status")["pid"] == original["pid"]
        latest = call("restart", original["instanceId"])
        assert latest["state"] == "running", latest
        assert latest["instanceId"] != original["instanceId"]
        assert latest["serviceInstanceId"] != original["serviceInstanceId"]
        after = snapshot(latest)
        assert after["sessions"][0]["source"]["source"]["identity"]["sessionId"] == session_id
        assert before["muxSpace"]["muxSpaceId"] == after["muxSpace"]["muxSpaceId"]
        assert all(Path(path).read_bytes().splitlines()[0] == header for path, header in histories.items())
        stopped = call("stop", latest["instanceId"])
        assert stopped["cleanlyStopped"] is True
        assert call("status")["state"] == "not_running"
        assert call("stop", latest["instanceId"])["cleanlyStopped"] is True
    finally:
        observed = call("status")
        if observed.get("instanceId") and observed["state"] != "not_running":
            assert call("stop", observed["instanceId"])["cleanlyStopped"] is True

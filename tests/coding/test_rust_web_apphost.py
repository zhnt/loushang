"""The Rust Web process uses the existing Host protocol and owns no executions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

pytestmark = [
    pytest.mark.requires_host_runtime,
    pytest.mark.skipif(sys.platform != "linux", reason="Linux managed lifecycle"),
]


def call(endpoint, operation, **request):
    message = Request(
        endpoint + "/api/loushang",
        data=json.dumps({"operation": operation, **request}).encode(),
        headers={"X-Loushang-Client": "1", "Content-Type": "application/json"},
    )
    try:
        with urlopen(message, timeout=20) as response:
            return json.load(response)["result"]
    except HTTPError as error:
        raise AssertionError((operation, error.read())) from error


@contextmanager
def web_server(binary, env, home):
    child = subprocess.Popen([str(binary)], env=env, stdout=subprocess.DEVNULL)
    endpoint = home / "state/web/endpoint.json"
    deadline = monotonic() + 15
    try:
        while monotonic() < deadline and child.poll() is None:
            if endpoint.exists():
                data = json.loads(endpoint.read_text())
                if data["pid"] == child.pid:
                    url = data["url"]
                    yield url
                    call(url, "shutdown-adapter")
                    assert child.wait(timeout=15) == 0
                    return
            sleep(.05)
        raise AssertionError("Rust Web did not start")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def snapshot(endpoint, path):
    return call(endpoint, "live", workspace=str(path), action="snapshot")


def test_rust_web_reconnect_preserves_managed_executions(tmp_path):
    root = Path(__file__).resolve().parents[2]
    manifest = root / "gui/web/Cargo.toml"
    subprocess.run(
        ["cargo", "build", "--locked", "--offline", "--manifest-path", str(manifest)],
        check=True, timeout=120,
    )
    binary = manifest.parent / "target/debug/loushang-web"
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / "host.json").write_text('{"web":{"port":0}}')
    workspaces = [tmp_path / "a", tmp_path / "b"]
    for path in workspaces:
        path.mkdir()
        (path / "marker").write_text(path.name)
    env = {
        **os.environ, "LOUSHANG_HOME": str(home),
        "LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "LOUSHANG_TMPDIR": str(tmp_path / "temporary"),
        "LOUSHANG_GUI_PYTHON": str(tmp_path / "missing-python"),
    }
    manager = Path(__file__).with_name("_host_first_manager.py")

    def manage(request):
        result = subprocess.run(
            [sys.executable, str(manager)], input=json.dumps(request), text=True,
            capture_output=True, env=env, timeout=90, check=True,
        )
        return json.loads(result.stdout)

    host = manage({"action": "start"})
    assert host["state"] == "running", host
    env["LOUSHANG_APP_RECORD_ROOT"] = host["recordRoot"]
    try:
        executions = {}
        with web_server(binary, env, home) as endpoint:
            assert call(endpoint, "manage", action="connect")["serviceInstanceId"] == host["serviceInstanceId"]
            scratch = call(endpoint, "workspace", action="create-chat", title="Temporary")
            assert scratch["workspace"] == "@temporary"
            assert len(snapshot(endpoint, "@temporary")["sessions"]) == 1

            for path in workspaces:
                call(endpoint, "workspace", action="register", path=str(path))
                call(endpoint, "workspace", action="open", path=str(path))
                call(endpoint, "workspace", action="create-chat", path=str(path), title="Second Session")
                first = snapshot(endpoint, path)
                assert len(first["sessions"]) == 2
                executions[path] = {}
                for index, member in enumerate(first["muxSpace"]["members"]):
                    session = member["session"]["sessionId"]
                    label = f"{path.name}-{index}"
                    reply = call(endpoint, "live", workspace=str(path), action="submit",
                                 input={"sessionId": session, "submissionId": label, "text": label})
                    assert reply["accepted"], reply
                    repeated = call(endpoint, "live", workspace=str(path), action="submit",
                                    input={"sessionId": session, "submissionId": label, "text": label})
                    assert repeated == reply
                    executions[path][session] = reply["executionId"]
            directory = call(endpoint, "workspace", action="navigation")
            assert {item["path"] for item in directory["projects"]} == {str(p) for p in workspaces}
            assert all(len(item["sessions"]) == 2 for item in directory["projects"])
            deadline = monotonic() + 20
            while not (home / "entered.jsonl").exists() or len((home / "entered.jsonl").read_text().splitlines()) < 4:
                assert monotonic() < deadline
                sleep(.05)

        assert manage({"action": "status"})["pid"] == host["pid"]
        with web_server(binary, env, home) as endpoint:
            assert call(endpoint, "manage", action="connect")["serviceInstanceId"] == host["serviceInstanceId"]
            for path, expected in executions.items():
                observed = {
                    session["source"]["source"]["identity"]["sessionId"]: session["executions"]["active"]["executionId"]
                    for session in snapshot(endpoint, path)["sessions"]
                }
                assert observed == expected
            (home / "release").touch()
            for path in workspaces:
                while True:
                    sessions = snapshot(endpoint, path)["sessions"]
                    if all(item["executions"]["latestTerminal"] and
                           item["executions"]["latestTerminal"]["status"] == "succeeded"
                           for item in sessions):
                        break
                    assert monotonic() < deadline
                    sleep(.05)
                effects = [json.loads(row) for row in (path / "effects.jsonl").read_text().splitlines()]
                assert len(effects) == 2
                assert {row["marker"] for row in effects} == {path.name}
                assert {row["cwd"] for row in effects} == {str(path)}

        assert manage({"action": "stop", "instanceId": host["instanceId"]}).get("cleanlyStopped")
        previous = host["serviceInstanceId"]
        host = manage({"action": "start"})
        assert host["state"] == "running" and host["serviceInstanceId"] != previous
        env["LOUSHANG_APP_RECORD_ROOT"] = host["recordRoot"]
        with web_server(binary, env, home) as endpoint:
            for path, expected in executions.items():
                restored = {
                    item["source"]["source"]["identity"]["sessionId"]
                    for item in snapshot(endpoint, path)["sessions"]
                }
                assert restored == set(expected)
                assert len((path / "effects.jsonl").read_text().splitlines()) == 2
    finally:
        (home / "release").touch()
        if host.get("instanceId"):
            status = manage({"action": "status"})
            if status["state"] == "running":
                assert manage({"action": "stop", "instanceId": host["instanceId"]}).get("cleanlyStopped")

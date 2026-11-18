"""Exercise installed Mac programs outside the checkout without provider keys."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import uuid4

APP = Path("/Applications/loushang-gui.app")
BIN = APP / "Contents/MacOS"
RESOURCES = APP / "Contents/Resources"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    evidence = parser.parse_args().evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"buildHost": os.uname().release, "macOS12ActuallyTested": False}
    info = plistlib.loads((APP / "Contents/Info.plist").read_bytes())
    assert info["LSMinimumSystemVersion"] == "12.0", info
    with tempfile.TemporaryDirectory(prefix="loushang-installed-mac-") as temporary:
        root = Path(temporary).resolve()
        home = root / "product-home"
        home.mkdir(mode=0o700)
        workspace = root / "workspace with spaces"
        workspace.mkdir()
        env = {name: os.environ[name] for name in ("HOME", "USER", "TMPDIR") if name in os.environ}
        env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin", LOUSHANG_HOME=str(home))

        def command(*args: str, success: bool = True) -> dict:
            completed = subprocess.run(
                ["/usr/local/bin/loushang-mux", "service", *args, "--json"],
                cwd=root, env=env, capture_output=True, text=True, timeout=75,
            )
            assert (completed.returncode == 0) == success, (completed.stdout, completed.stderr)
            return json.loads(completed.stdout)

        python = str(RESOURCES / "runtime/bin/python3")
        locations = subprocess.check_output([
            python, "-I", "-c",
            "import loushang.apphost,loushang.appservice,loushang.coding,sys;"
            "print(sys.prefix);print(loushang.apphost.__file__);"
            "print(loushang.appservice.__file__);print(loushang.coding.__file__)",
        ], cwd=root, env=env, text=True).splitlines()
        assert all(Path(location).is_relative_to(APP) for location in locations), locations
        subprocess.run(["/usr/local/bin/loushang", "--help"], cwd=root, env=env,
                       check=True, timeout=45, stdout=subprocess.DEVNULL)
        subprocess.run(["/usr/local/bin/loushang-host", "--help"], cwd=root, env=env,
                       check=True, timeout=15, stdout=subprocess.DEVNULL)
        report["bundledPythonPaths"] = locations
        try:
            assert command("status")["state"] == "not_running"
            first = command("start")
            assert first["state"] == "running", first
            assert command("start")["instanceId"] == first["instanceId"]
            report["initialHost"] = first
            with (evidence / "gui.log").open("w") as log:
                gui = subprocess.Popen([str(BIN / "loushang-gui")], cwd=root, env=env,
                                       stdout=log, stderr=log)
                try:
                    sleep(5)
                    assert gui.poll() is None, (evidence / "gui.log").read_text()
                    report["nativeGuiLaunched"] = True
                finally:
                    if gui.poll() is None:
                        gui.terminate()
                    gui.wait(timeout=20)
            assert command("status")["instanceId"] == first["instanceId"]
            report["hostSurvivesGuiExit"] = True
            (home / "host.json").write_text(json.dumps({"web": {"port": 0, "manageLocal": True}}))
            with (evidence / "web.log").open("w") as log:
                web = subprocess.Popen(["/usr/local/bin/loushang-web"], cwd=root, env=env,
                                       stdout=log, stderr=log)
                try:
                    endpoint = home / "state/web/endpoint.json"
                    deadline = monotonic() + 20
                    while not endpoint.exists() and web.poll() is None and monotonic() < deadline:
                        sleep(0.1)
                    assert endpoint.exists(), (evidence / "web.log").read_text()
                    url = json.loads(endpoint.read_text())["url"]

                    def call(operation: str, **fields: object) -> dict:
                        request = Request(url + "/api/loushang", data=json.dumps({
                            "operation": operation, **fields,
                        }).encode(), headers={"Content-Type": "application/json", "X-Loushang-Client": "1"})
                        with urlopen(request, timeout=60) as response:
                            return json.load(response)["result"]

                    with urlopen(url, timeout=10) as response:
                        assert "text/html" in response.headers["Content-Type"]
                    assert call("manage", action="connect")["state"] == "running"
                    call("workspace", action="register", path=str(workspace))
                    call("workspace", action="open", path=str(workspace))
                    directory = call("workspace", action="navigation")
                    assert any(project["path"] == str(workspace) for project in directory["projects"])
                    assert call("workspace", action="models", path=str(workspace))["models"]
                    view = str(uuid4())
                    snapshot = call("live", action="snapshot", viewId=view, workspace=str(workspace))
                    assert len(snapshot["sessions"]) == 1, snapshot
                    identity = snapshot["sessions"][0]["executions"]["identity"]
                    call("live", action="close", viewId=view, workspace=str(workspace))
                    report["webAndHostSession"] = {"directory": True, "models": True, "snapshot": True}
                    second = command("restart", "--instance", first["instanceId"])
                    assert second["state"] == "running" and second["instanceId"] != first["instanceId"]
                    reopened_view = str(uuid4())
                    restored = call("live", action="snapshot", viewId=reopened_view, workspace=str(workspace))
                    assert restored["sessions"][0]["executions"]["identity"] == identity
                    call("live", action="close", viewId=reopened_view, workspace=str(workspace))
                    report["sessionSurvivesHostRestart"] = True
                    call("shutdown-adapter")
                    assert web.wait(timeout=15) == 0
                finally:
                    if web.poll() is None:
                        web.terminate()
                        web.wait(timeout=15)
            rejected = command("stop", "--instance", first["instanceId"], success=False)
            assert rejected["errorCode"] == "instance_changed", rejected
            assert command("status")["instanceId"] == second["instanceId"]
            assert command("stop", "--instance", second["instanceId"])["state"] == "not_running"
            report["restartAndInstanceFence"] = True
        finally:
            command("stop")
            backend_log = home / "state/macos-host/host.log"
            if backend_log.exists():
                (evidence / "host.log").write_text(backend_log.read_text())
            (evidence / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

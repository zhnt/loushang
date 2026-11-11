"""Opt-in smoke test of an extracted Linux portable package."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from time import monotonic, sleep
from urllib.request import Request, urlopen


def check_web(
    command: list[str], env: dict[str, str], host: dict, workspace: Path
) -> None:
    home = Path(env["LOUSHANG_HOME"])
    (home / "host.json").write_text('{"web":{"port":0}}')
    endpoint = home / "state/web/endpoint.json"
    with subprocess.Popen(
        command, env={**env, "LOUSHANG_APP_RECORD_ROOT": host["recordRoot"]}
    ) as web:
        try:
            deadline = monotonic() + 15
            while web.poll() is None and monotonic() < deadline:
                if endpoint.exists():
                    state = json.loads(endpoint.read_text())
                    if state["pid"] == web.pid:
                        url = state["url"]
                        break
                sleep(0.05)
            else:
                raise AssertionError("Packaged Rust Web server did not start")

            def call(operation: str, **fields: str) -> dict:
                request = Request(
                    url + "/api/loushang",
                    data=json.dumps({"operation": operation, **fields}).encode(),
                    headers={
                        "X-Loushang-Client": "1",
                        "Content-Type": "application/json",
                    },
                )
                with urlopen(request, timeout=20) as response:
                    return json.load(response)["result"]

            with urlopen(url, timeout=5) as response:
                assert "text/html" in response.headers["Content-Type"]
            instance = call("manage", action="connect")["serviceInstanceId"]
            assert instance and instance == host.get("serviceInstanceId", instance)
            call("workspace", action="register", path=str(workspace))
            call("workspace", action="open", path=str(workspace))
            snapshot = call("live", action="snapshot", workspace=str(workspace))
            assert snapshot["serviceInstanceId"] == instance
            assert len(snapshot["sessions"]) == 1
            call("shutdown-adapter")
            assert web.wait(timeout=15) == 0
        finally:
            if web.poll() is None:
                web.kill()
                web.wait(timeout=5)


def check_host(package: Path, launcher: Path, root: Path) -> None:
    workspace = root / "workspace with spaces"
    workspace.mkdir(mode=0o700)
    home = root / "home"
    home.mkdir(mode=0o700)
    # No inherited provider keys, source paths, developer environment or tools.
    env = {
        "HOME": str(home),
        "PATH": "/nonexistent",
        "LANG": "C.UTF-8",
        "LOUSHANG_HOME": str(home / ".loushang"),
        "LOUSHANG_RUNTIME_DIR": str(root / "runtime"),
        "PYTHONPATH": "/nonexistent",
    }

    def call(*flags: str) -> dict:
        result = subprocess.run(
            [str(launcher), "--workspace", str(workspace), *flags],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=100,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        return json.loads(result.stdout)

    locations = subprocess.check_output(
        [
            str(package / "runtime/bin/python3"),
            "-I",
            "-c",
            "import loushang.apphost,loushang.appservice,loushang.coding,sys; "
            "print(sys.prefix); print(loushang.apphost.__file__); "
            "print(loushang.appservice.__file__); print(loushang.coding.__file__)",
        ],
        cwd=root,
        env=env,
        text=True,
    ).splitlines()
    assert all(Path(path).is_relative_to(package) for path in locations), locations
    assert (package / "web/index.html").is_file()
    assert (package / "bin/harness-gui").read_bytes()[:4] == b"\x7fELF"
    assert (package / "bin/loushang-web").read_bytes()[:4] == b"\x7fELF"
    state_before = call("--status")
    assert state_before["state"] == "not_running"
    try:
        started = call("--start-only")
        assert started["state"] == "running" and started["recordRoot"]
        assert call("--status")["instanceId"] == started["instanceId"]
        reused = call("--start-only")
        assert reused["instanceId"] == started["instanceId"]
        assert reused["recordRoot"] == started["recordRoot"]
        check_web(
            [str(package / "bin/loushang-web"), "--dist", str(package / "web")],
            env,
            reused,
            workspace,
        )
        assert call("--status")["instanceId"] == started["instanceId"]
        stopped = call("--stop")
        assert stopped["state"] == "not_running" and stopped["cleanlyStopped"]
        assert call("--status")["state"] == "not_running"
        restarted = call("--start-only")
        assert restarted["instanceId"] != started["instanceId"]
        assert restarted["recordRoot"] == started["recordRoot"]
    finally:
        stopped = call("--stop")
        assert stopped["state"] == "not_running"
        assert call("--status")["state"] == "not_running"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    launcher = package / "loushang"
    with launcher.open("rb") as executable:
        entry = executable.read(18)
    assert entry[:4] == b"\x7fELF", "file-manager entry must be a native executable"
    assert int.from_bytes(entry[16:18], "little") == 2, "entry must be ELF ET_EXEC"
    assert os.access(launcher, os.X_OK)
    with tempfile.TemporaryDirectory(prefix="loushang-portable-check-") as directory:
        root = Path(directory)
        check_host(package, launcher, root)
    print("PASS: extracted portable GUI, bundled Web and managed AppHost")


if __name__ == "__main__":
    main()

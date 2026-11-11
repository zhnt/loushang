"""Opt-in acceptance of the actual deb payload; no model requests or installation."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deb", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="loushang-deb-check-") as directory:
        root = Path(directory)
        subprocess.run(
            ["dpkg-deb", "-x", str(args.deb.resolve()), str(root / "extracted")],
            check=True,
        )
        package = root / "extracted/opt/loushang"
        launcher = root / "extracted/usr/bin/loushang"
        assert launcher.resolve() == package / "loushang"
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
        state_before = call("--status")
        assert state_before["state"] == "not_running"
        try:
            started = call("--start-only")
            assert started["state"] == "running" and started["muxName"]
            assert call("--status")["instanceId"] == started["instanceId"]
            reused = call("--start-only")
            assert reused["instanceId"] == started["instanceId"]
            assert reused["muxName"] == started["muxName"]
            stopped = call("--stop")
            assert stopped["state"] == "not_running" and stopped["cleanlyStopped"]
            assert call("--status")["state"] == "not_running"
            restarted = call("--start-only")
            assert restarted["instanceId"] != started["instanceId"]
            assert restarted["muxName"] == started["muxName"]
            print(
                "PASS: actual deb payload; bundled imports; native launcher symlink; "
                "Web assets; authenticated Host startup/status/reuse/stop/restart; retained mux"
            )
        finally:
            stopped = call("--stop")
            assert stopped["state"] == "not_running"
            assert call("--status")["state"] == "not_running"


if __name__ == "__main__":
    main()

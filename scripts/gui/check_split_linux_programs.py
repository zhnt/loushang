"""Opt-in smoke test of independently staged Linux AppHost and GUI/Web programs."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from check_portable_package import check_web


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", type=Path)
    parser.add_argument("gui", type=Path)
    args = parser.parse_args()
    host = args.host.resolve(strict=True) / "loushang-mux"
    gui = args.gui.resolve(strict=True) / "loushang-gui"
    assert not (gui.parent / "runtime").exists()
    assert not any(gui.parent.rglob("*.py"))
    with tempfile.TemporaryDirectory(prefix="loushang-split-check-") as directory:
        root = Path(directory)
        home = root / "home"
        workspace = root / "workspace with spaces"
        home.mkdir(mode=0o700)
        workspace.mkdir(mode=0o700)
        env = {
            "HOME": str(home),
            "PATH": "/nonexistent",
            "LANG": "C.UTF-8",
            "LOUSHANG_HOME": str(home / ".loushang"),
            "LOUSHANG_RUNTIME_DIR": str(root / "runtime"),
            "LOUSHANG_TMPDIR": str(root / "temporary"),
        }

        def call(action: str, *flags: str) -> dict:
            stdout = subprocess.check_output(
                [str(host), "service", action, "--json", *flags],
                cwd=root,
                env=env,
                text=True,
                timeout=90,
            )
            return json.loads(stdout)

        started = call("start")
        try:
            assert started["state"] == "running", started
            assert call("start") == started
            check_web([str(gui), "web"], env, started, workspace)
            assert call("start") == started
        finally:
            stopped = call("stop", "--instance", started["instanceId"])
            assert stopped["state"] == "not_running" and stopped["cleanlyStopped"]
    print(
        "PASS: Python-free GUI/Web package connected to the standalone AppHost package"
    )


if __name__ == "__main__":
    main()

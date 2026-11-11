"""Installed desktop entry using the same managed Host as GUI/tray controls."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Loushang with bundled backend")
    parser.add_argument("--workspace", type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--start-only", action="store_true")
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    from loushang.coding.client_settings import connections, remember_workspace

    workspace = (
        (args.workspace or Path(connections().get("defaultWorkspace") or Path.home()))
        .expanduser()
        .resolve(strict=True)
    )
    if not workspace.is_dir():
        parser.error("workspace must be a directory")
    package = Path(__file__).resolve().parent
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["LOUSHANG_GUI_PYTHON"] = sys.executable

    def operate(action: str, **fields: object) -> dict:
        result = subprocess.run(
            [sys.executable, "-I", "-m", "loushang.coding.gui_local_host"],
            input=json.dumps({"action": action, "workspace": str(workspace), **fields}),
            text=True,
            capture_output=True,
            check=True,
            timeout=90,
            cwd=workspace,
            env=environment,
        )
        value = json.loads(result.stdout)
        if value.get("errorCode"):
            raise RuntimeError(f"Host operation failed: {value['errorCode']}")
        return value

    if args.status or args.stop:
        status = operate("status")
        if args.stop and status["state"] == "running":
            status = operate("stop", instanceId=status["instanceId"])
        print(json.dumps(status))
        return 0
    # A saved remote connection remains authoritative for normal desktop opens.
    if not args.start_only and connections().get("defaultConnection"):
        return subprocess.call(
            [str(package / "bin/harness-gui")], cwd=workspace, env=environment
        )
    host = operate("start")
    if (
        host.get("state") != "running"
        or not host.get("recordRoot")
        or not host.get("muxName")
    ):
        raise RuntimeError("Host did not become ready")
    if args.start_only:
        print(json.dumps(host))
        return 0
    remember_workspace(str(workspace))
    # Let the current GUI connection/tray flow attach through the shared settings;
    # explicit connection arguments would enable its legacy connection mode.
    return subprocess.call(
        [str(package / "bin/harness-gui")], cwd=workspace, env=environment
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Loushang: {error}", file=sys.stderr)
        raise SystemExit(1) from None

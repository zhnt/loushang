"""Installed desktop entry using the same managed Host as lmux."""

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
    from loushang.coding.client_settings import connections

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

    def operate(action: str, **fields: object) -> dict:
        result = subprocess.run(
            [sys.executable, "-I", "-m", "loushang.coding.gui_local_host"],
            input=json.dumps({"action": action, **fields}),
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

    if args.start_only:
        host = operate("start")
        if host.get("state") != "running" or not host.get("recordRoot"):
            raise RuntimeError("Host did not become ready")
        print(json.dumps(host))
        return 0

    if args.status or args.stop:
        status = operate("status")
        if args.stop and status["state"] == "running":
            status = operate("stop", instanceId=status["instanceId"])
        print(json.dumps(status))
        return 0

    if "LOUSHANG_APP_RECORD_ROOT" not in environment and not connections().get(
        "defaultConnection"
    ):
        try:
            status = operate("status")
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            print(f"Loushang: {error}", file=sys.stderr)
        else:
            if status.get("state") == "running":
                environment["LOUSHANG_APP_RECORD_ROOT"] = status["recordRoot"]
    return subprocess.call(
        [str(package / "bin/harness-gui")], cwd=workspace, env=environment
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Loushang: {error}", file=sys.stderr)
        raise SystemExit(1) from None

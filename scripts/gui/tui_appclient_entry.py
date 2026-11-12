"""Terminal client entry for an already running Coding AppHost."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from loushang.coding.cli.mux import main as mux_main


def main() -> int:
    manager = Path(__file__).with_name("loushang-mux")
    if sys.argv[1:2] == ["service"]:
        return subprocess.call([str(manager), *sys.argv[1:]])
    parser = argparse.ArgumentParser(
        description=__doc__, epilog="Use loushang-tui service for local Host management.",
    )
    parser.add_argument("--connection-root", type=Path)
    parser.add_argument("--endpoint", default="workspace")
    parser.add_argument("mux", help="name of an existing Host Mux")
    args = parser.parse_args()
    if args.connection_root is None:
        status = subprocess.run(
            [str(manager), "service", "status", "--json"],
            check=False, capture_output=True, text=True, timeout=15,
        )
        if status.returncode:
            parser.error("cannot query local AppHost via loushang-mux service")
        result = json.loads(status.stdout)
        if result.get("state") != "running":
            parser.error("AppHost is stopped. Run loushang-tui service start.")
        args.connection_root = Path(result["recordRoot"])
    return mux_main(
        [
            "--connection-root",
            str(args.connection_root),
            "--endpoint",
            args.endpoint,
            "attach",
            "--",
            args.mux,
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())

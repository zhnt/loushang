"""Terminal client entry for an already running Coding AppHost."""

from __future__ import annotations

import argparse
from pathlib import Path

from loushang.coding.cli.mux import main as mux_main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection-root", required=True, type=Path)
    parser.add_argument("--endpoint", default="workspace")
    parser.add_argument("mux", help="name of an existing Host Mux")
    args = parser.parse_args()
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

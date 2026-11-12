from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from loushang.coding.cli.__main__ import run_cli


def main() -> None:
    if sys.argv[1:2] == ["service"]:
        name = "loushang-mux.exe" if sys.platform == "win32" else "loushang-mux"
        manager = Path(sys.executable).with_name(name)
        try:
            status = subprocess.call([str(manager), *sys.argv[1:]])
        except OSError:
            raise SystemExit("loushang-mux is unavailable") from None
        raise SystemExit(status)
    raise SystemExit(asyncio.run(run_cli(("--tui", *sys.argv[1:]))))


__all__ = ["main"]

"""Run one native Windows Worker probe with a shorter evidence deadline.

The child writes pytest and faulthandler output to an artifact before the
Actions job limit. A stalled probe is stopped while the runner can still
upload that artifact; this script does not change the required Worker gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_CHILD_TIMEOUT_SECONDS = 25 * 60
_STOP_TIMEOUT_SECONDS = 30
_BOOTSTRAP = (
    "import faulthandler, runpy, sys\n"
    "faulthandler.dump_traceback_later(600, repeat=True)\n"
    "sys.argv = ['scripts/dev/run_pytest.py', *sys.argv[1:]]\n"
    "runpy.run_path('scripts/dev/run_pytest.py', run_name='__main__')\n"
)


def main(argv: list[str]) -> int:
    if os.name != "nt" or not argv:
        raise SystemExit("native Windows pytest arguments are required")

    root = Path(__file__).resolve().parents[2]
    report = root / ".artifacts" / "windows-worker-diagnostic.log"
    report.parent.mkdir(exist_ok=True)
    # Arm a native watchdog before the leased pytest runner imports or obtains
    # its scratch lease. Its own watchdog adds later cleanup traces.
    command = [sys.executable, "-u", "-c", _BOOTSTRAP, *argv]
    with report.open("wb", buffering=0) as output:
        output.write(b"Windows Worker diagnostic pytest started\n")
        child = subprocess.Popen(
            command,
            cwd=root,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            return child.wait(timeout=_CHILD_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            output.write(b"Windows Worker diagnostic evidence deadline reached\n")
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(child.pid)],
                    cwd=root,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=_STOP_TIMEOUT_SECONDS,
                    check=False,
                )
                child.wait(timeout=_STOP_TIMEOUT_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                output.write(b"Windows Worker diagnostic child stop incomplete\n")
            return 124


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

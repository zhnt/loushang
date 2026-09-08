"""Same-ConPTY stdlib observer; leaves mode restoration entirely to the CLI.

Every invocation is inside the separately supervised, non-breakaway pytest
Job. The witness never reads terminal input and cannot release itself on a
receipt failure; the outer observer or its Job retains cleanup authority.
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path


def publish(root, name, value):
    pending = root / (name + ".pending")
    pending.write_text(json.dumps(value), encoding="utf-8")
    pending.replace(root / name)


def witness(root, arguments, *, api, spawn=subprocess.Popen):
    process = None
    status = 1
    try:
        api.protect_witness_interrupt()
        baseline = api.modes()
        process = spawn(arguments)
        publish(root, "started", {"pid": process.pid, "witness": os.getpid(), "baseline": baseline})
        sampled = False
        while process.poll() is None:
            if not sampled and (root / "sample.request").exists():
                publish(root, "sample", {"modes": api.modes(), "console": api.console_processes()})
                sampled = True
            if (root / "release").exists():
                raise RuntimeError("observer released a live controller")
            time.sleep(0.01)
        code = process.wait()
        # The CLI has exited, but our ConPTY and its native modes remain live.
        publish(root, "finished", {"code": code, "modes": api.modes()})
        status = 0
    except BaseException as error:
        # No raw exception material; these receipts only describe the fixture.
        with suppress(Exception):
            publish(root, "failed", {"type": type(error).__name__})
    finally:
        # IO failures and missing observers never manufacture release. The
        # supervisor's Job is the backstop if this rendezvous cannot complete.
        while not (root / "release").exists():
            time.sleep(0.01)
    return status


if __name__ == "__main__":
    definitions = runpy.run_path(str(Path(__file__).with_name("_hosted_windows_api.py")))
    raise SystemExit(witness(Path(sys.argv[1]), sys.argv[2:], api=definitions["WindowsObservationApi"]()))

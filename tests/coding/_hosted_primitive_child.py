"""Stdlib-only primitive fixture owners, separate from Product launch code."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from contextlib import contextmanager, suppress


@contextmanager
def _child(code, *, forking=False):
    # New session prevents the observer's terminal SIGINT from killing a child
    # before Python installs its own handler. -S excludes site startup hooks.
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c", code], stdin=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    try:
        yield process
    finally:
        if forking:
            _settle_fork_parent(process)
        else:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdin.close()


def _settle_fork_parent(process):
    # Continuous guard including descriptor close, diagnostics and retries.
    previous = signal.signal(signal.SIGINT, lambda *_: None)
    try:
        while True:
            try:
                process.stdin.close()  # EOF before admission exits without fork.
                process.wait(timeout=5)
                return
            except (Exception, KeyboardInterrupt):
                with suppress(OSError, ValueError):
                    print("native fork fixture cleanup pending; parent retained", flush=True)
    finally:
        signal.signal(signal.SIGINT, previous)

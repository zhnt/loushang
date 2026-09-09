"""Test-only foreground ownership; never kill the owner before its children.

POSIX fallback is for this controlled Python process tree (normal child reaping),
not a general hostile-process containment implementation.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import contextmanager, suppress

from tests.tui.terminal_process_support import spawn_terminal_process


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("foreground test process-tree adoption exceeded its deadline")
    return remaining


def process_table(*, deadline=None):
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,stat="],
        check=True, capture_output=True, text=True,
        timeout=5 if deadline is None else min(5, _remaining(deadline)),
    )
    return {
        int(pid): (int(parent), state)
        for pid, parent, state in (line.split() for line in result.stdout.splitlines())
    }


def _reclaim_posix_descendants(root):
    """Freeze parents before enumeration, keeping unreaped child IDs reserved."""
    assert root is not None and root > 1
    stopped = {}
    tree = []
    deadline = time.monotonic() + 10

    def freeze(pid):
        _remaining(deadline)
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGSTOP)
            stopped[pid] = None
        while True:
            entry = process_table(deadline=deadline).get(pid)
            if entry is None or "Z" in entry[1]:
                stopped.pop(pid, None)
                return False
            if "T" in entry[1]:
                return True
            if time.monotonic() >= deadline:
                raise TimeoutError("foreground test could not stop its process tree")
            time.sleep(0.01)

    try:
        # Do not poll/reap the controller while descendants are being adopted.
        if not freeze(root):
            return
        pending = [root]
        while pending:
            _remaining(deadline)
            parent = pending.pop()
            children = [
                pid for pid, entry in process_table(deadline=deadline).items() if entry[0] == parent
            ]
            for child in children:
                _remaining(deadline)
                if len(tree) >= 128:
                    raise TimeoutError("foreground test process-tree adoption exceeded its bound")
                if freeze(child):
                    tree.append(child)
                    pending.append(child)
        # Every live parent is stopped: children cannot be reaped and their PIDs
        # cannot be reused until we resume the owning parent below.
        _remaining(deadline)
        for child in reversed(tree):
            os.kill(child, signal.SIGKILL)
            stopped.pop(child, None)
        while True:
            table = process_table(deadline=deadline)
            if not any(pid in table and "Z" not in table[pid][1] for pid in tree):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("foreground test child reclamation did not finish")
            time.sleep(0.01)
    finally:
        for pid in reversed(stopped):
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGCONT)


def _wait_exit(driver, timeout):
    # Cleanup must still work if the output reader/query responder has failed.
    # Some native drivers' wait() raises that error before waiting for exit.
    deadline = time.monotonic() + timeout
    while driver.is_alive():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def _settle(driver, *, graceful_timeout=25):
    root = driver.diagnostics.pid
    if driver.is_alive():
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.kill(root, signal.SIGINT)
        else:
            # ConPTY translates Ctrl+C when cooked, and the shell handles the
            # detach chord when raw. Its existing fallback uses taskkill /T.
            with suppress(OSError, RuntimeError):
                driver.write("\x03\x02d")
        if not _wait_exit(driver, graceful_timeout) and os.name == "posix" and driver.is_alive():
            _reclaim_posix_descendants(root)
            with suppress(ProcessLookupError):
                os.kill(root, signal.SIGINT)
            _wait_exit(driver, 25)
    driver.close()


@contextmanager
def foreground_terminal(*args, **kwargs):
    driver = spawn_terminal_process(*args, **kwargs)
    try:
        yield driver
    finally:
        _settle(driver)

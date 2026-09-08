"""Reclaim a controlled Python tree without abandoning unreaped descendants."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import suppress


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("evidence process-tree cleanup pending")
    return value


def _table(deadline):
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,stat="], check=True,
        capture_output=True, text=True, timeout=min(5, _remaining(deadline)),
    )
    return {int(pid): (int(parent), state) for pid, parent, state in (
        row.split() for row in result.stdout.splitlines()
    )}


def _reconcile(root, ledger, table):
    members, lost = ledger["members"], ledger["lost"]
    for pid in list(members):
        if pid not in table:
            del members[pid]
            lost.discard(pid)
    # Parents were registered before their children. Once ancestry is lost,
    # matching numeric IDs on a later retry never grant signal authority again.
    for pid, parent in members.items():
        if table[pid][0] != parent or (parent != root and (
            parent not in members or parent in lost
        )):
            lost.add(pid)


def reclaim_descendants(root, reap, *, ledger=None, timeout=30):
    """Freeze parents to reserve IDs; kill one leaf and let its parent reap.

    The root wrapper is retained by the release protocol and is never polled
    during adoption. Other parents must retain normal Python reaping semantics.
    An uncooperative parent produces cleanup debt, never an orphaning shortcut.
    The caller retains the ledger across retries. This accounts for observed
    descendants, not children orphaned before the first controlled-tree scan.
    """
    if type(root) is not int or root <= 1:
        raise ValueError("invalid retained process root")
    if ledger is None:
        ledger = {}
    ledger.setdefault("members", {})
    ledger.setdefault("lost", set())
    ledger.setdefault("reclaimed", 0)
    deadline = time.monotonic() + timeout
    while True:
        stopped, tree = {}, []

        def freeze(pid, stopped=stopped):
            _remaining(deadline)
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGSTOP)
                stopped[pid] = None
            while True:
                entry = _table(deadline).get(pid)
                if entry is None or "Z" in entry[1]:
                    stopped.pop(pid, None)
                    return False
                if "T" in entry[1]:
                    return True
                time.sleep(min(0.01, _remaining(deadline)))

        try:
            if not freeze(root):
                raise RuntimeError("evidence root exited without release")
            _reconcile(root, ledger, _table(deadline))
            if ledger["lost"]:
                raise RuntimeError("evidence adopted process lost parent; cleanup pending")
            pending = [root]
            while pending:
                parent = pending.pop()
                children = [pid for pid, entry in _table(deadline).items() if entry[0] == parent]
                for child in children:
                    _remaining(deadline)
                    if len(tree) >= 128 or ledger["reclaimed"] >= 128:
                        raise TimeoutError("evidence process-tree bound exceeded")
                    ledger["members"].setdefault(child, parent)
                    live = freeze(child)
                    tree.append((child, parent))
                    if live:
                        pending.append(child)
            if not tree:
                if ledger["members"]:
                    raise RuntimeError("evidence adopted process missing from parent tree")
                stopped.pop(root)  # Transfer a still-frozen root to the caller.
                return ledger["reclaimed"]
            child, parent = tree[-1]
            _remaining(deadline)
            if child in stopped:
                os.kill(child, signal.SIGKILL)
                stopped.pop(child)
            if parent == root:
                reap(child)
            os.kill(parent, signal.SIGCONT)
            stopped.pop(parent, None)
            # Keep the owning parent alive until its exact child PID is gone.
            # Never accept a zombie as evidence that its parent can be killed.
            while True:
                table = _table(deadline)
                _reconcile(root, ledger, table)
                if ledger["lost"]:
                    raise RuntimeError("evidence adopted process lost parent; cleanup pending")
                if child not in table:
                    break
                time.sleep(min(0.01, _remaining(deadline)))
            ledger["reclaimed"] += 1
        finally:
            try:
                _reconcile(root, ledger, _table(deadline))
                for pid in reversed(stopped):
                    if (
                        pid != root and pid in ledger["members"] and pid not in ledger["lost"]
                        and ledger["members"][pid] in stopped
                    ):
                        # A parent resumed to reap a sibling can exit after ps.
                        # Keep its other children frozen until the next scan
                        # freezes that parent again and proves their ancestry.
                        with suppress(ProcessLookupError):
                            os.kill(pid, signal.SIGCONT)
            finally:
                if root in stopped:
                    with suppress(ProcessLookupError):
                        os.kill(root, signal.SIGCONT)

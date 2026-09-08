"""Stdlib-only primitive fixture owners, separate from Product launch code."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from contextlib import contextmanager, suppress
from pathlib import Path


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


def _publish_group_ready(root, identities):
    pending = root / "family-ready.pending"
    pending.write_text(json.dumps(identities), encoding="utf-8")
    pending.replace(root / "family-ready")


def _group_family(root):
    """An external actual parent owns both group members through zombie proof."""
    signal.signal(signal.SIGINT, lambda *_: None)
    children = []
    try:
        for index in range(2):
            children.append(subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", "import sys; sys.stdin.buffer.read()"],
                stdin=subprocess.PIPE, process_group=0 if index == 0 else children[0].pid,
            ))
        leader, helper = children
        _publish_group_ready(root, [leader.pid, helper.pid])
        if sys.stdin.readline() != "root\n":
            return
        leader.stdin.close()
        leader.wait()
        (root / "root-reaped").touch()
        if sys.stdin.readline() != "helper\n":
            return
        helper.stdin.close()  # Hold the exited helper unreaped until ordered.
        if sys.stdin.readline() != "reap\n":
            return
        helper.wait()
        (root / "family-reaped").touch()
        sys.stdin.readline()  # Retain the external parent through final proof.
    finally:
        for process in children:
            while True:
                try:
                    process.stdin.close()
                    process.wait()
                    break
                except (Exception, KeyboardInterrupt):
                    continue  # Never abandon the actual reaper on interruption.


@contextmanager
def group_family(root):
    code = (
        "import runpy\nfrom pathlib import Path\n"
        f"fixture=runpy.run_path({str(Path(__file__).resolve())!r})\n"
        f"fixture['_group_family'](Path({str(root)!r}))\n"
    )
    with _child(code, forking=True) as process:
        yield process

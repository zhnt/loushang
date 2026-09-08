"""Linux-only isolated subreaper protecting the intentional orphan regression."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_ROOT = """
import os, sys, time
from pathlib import Path
middle = os.fork()
if middle == 0:
    for name in ('A', 'B'):
        child = os.fork()
        if child == 0:
            time.sleep(60)
            os._exit(0)
        Path(name).write_text(str(child))
    os.waitpid(-1, 0)
    os._exit(0)  # Deliberately leave the other sibling for the outer reaper.
Path('middle').write_text(str(middle))
for line in sys.stdin:
    if line.startswith('reap '):
        os.waitpid(int(line.split()[1]), 0)
"""


def main():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER, this process only.
        raise OSError(ctypes.get_errno(), "fixture subreaper admission failed")
    path = Path(__file__).resolve().parents[2] / "scripts/dev/_evidence_posix.py"
    spec = importlib.util.spec_from_file_location("_evidence_posix", path)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    root = subprocess.Popen([sys.executable, "-I", "-c", _ROOT], stdin=subprocess.PIPE)
    Path("branch.root").write_text(str(root.pid))
    ledger = {}

    def reap(pid):
        root.stdin.write(f"reap {pid}\n".encode())
        root.stdin.flush()

    try:
        deadline = time.monotonic() + 5
        while not all(Path(name).is_file() and Path(name).read_text() for name in ("A", "B")):
            if time.monotonic() >= deadline:
                raise TimeoutError("branch fixture startup")
            time.sleep(0.01)
        Path("branch.ready").touch()
        if Path("hold-branch").exists():
            while True:
                time.sleep(0.01)  # Supervisor timeout must enter finally, not kill us.
        for _ in range(2):
            try:
                native.reclaim_descendants(root.pid, reap, ledger=ledger, timeout=3)
            except RuntimeError as error:
                assert "adopted" in str(error) and "parent" in str(error)
            else:
                raise AssertionError("lost branch incorrectly established empty-tree proof")
            os.kill(root.pid, 0)  # Neither root release nor root kill was granted.
            assert len(ledger["lost"]) == 1
            orphan = next(iter(ledger["lost"]))
            table = native._table(time.monotonic() + 1)
            assert table[orphan][0] == os.getpid()
            assert "T" in table[orphan][1]  # Lost branch was not even resumed.
        # Only this independent, actual parent has authority to kill/reap it.
        os.kill(orphan, signal.SIGKILL)
        assert os.waitpid(orphan, 0)[0] == orphan
        native.reclaim_descendants(root.pid, reap, ledger=ledger, timeout=3)
        assert not ledger["members"] and not ledger["lost"]
        assert "T" in native._table(time.monotonic() + 1)[root.pid][1]
        root.kill()
        root.wait(timeout=3)
        print("branch debt retained across retries; native reaper cleared it", flush=True)
    finally:
        # Every fixture descendant is adopted here after its parent exits.
        # Reap before each new direct-child snapshot; never signal an old PID.
        deadline = time.monotonic() + 5
        while True:
            try:
                child, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if child:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("fixture direct-child cleanup pending")
            # A ps snapshot includes its own already-reaped subprocess. Read
            # this Linux-only reaper's direct children without spawning one.
            children = Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children")
            for pid in map(int, children.read_text().split()):
                os.kill(pid, signal.SIGKILL)
            time.sleep(0.01)
        root.wait(timeout=1)
        root.stdin.close()
        Path("branch.settled").write_text("fixture reaped")
    Path("branch.done").write_text("native reaper cleared it")


if __name__ == "__main__":
    main()

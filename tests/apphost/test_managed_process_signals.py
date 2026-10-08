from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic

import pytest

from loushang.hosting.service import LinuxServiceObserverV1

from ..hosting._pidfd_signal import send_signal

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux process-shell signal policy")


@pytest.mark.parametrize("fault", ["init", "close", "install", "success"])
def test_process_policy_survives_real_signals_with_an_unmasked_thread(fault):
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("_managed_process_fault.py")), fault],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    observer = None

    def receipt():
        result = bytearray()
        deadline = monotonic() + 8
        while not result.endswith(b"\n"):
            remaining = deadline - monotonic()
            assert remaining > 0, "child receipt timed out"
            assert select.select([child.stdout], [], [], remaining)[0], "child receipt timed out"
            data = os.read(child.stdout.fileno(), 1)
            assert data, "child exited before receipt"
            result.extend(data)
            assert len(result) < 1024
        return json.loads(result)

    def check():
        facts = receipt()
        assert facts["unknown"] == facts["pending"] == (fault != "success")
        assert facts["protected"]
        assert child.poll() is None
        return facts

    try:
        check()
        observer = LinuxServiceObserverV1.capture(child.pid)
        for kind in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            send_signal(observer, kind)
            child.stdin.write(b"status\n")
            child.stdin.flush()
            facts = check()
            if kind != signal.SIGHUP:
                assert facts["stopRequested"]
        child.stdin.write(b"quit\n")
        child.stdin.flush()
        assert child.wait(timeout=8) == (9 if fault == "success" else 7)
    finally:
        if child.poll() is None:
            child.kill()  # Exact retained test child; only failure hygiene.
        _, errors = child.communicate(timeout=8)
        if observer is not None:
            observer.close()
        assert not errors, errors.decode(errors="replace")

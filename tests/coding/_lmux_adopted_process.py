"""Test-observer wait duty for one exact adopted managed leader.

No signals, process scans, journal writes or production stop substitutes. The
original stopper must still prove application and process-group settlement.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from loushang.hosting.service import LinuxServiceObserverV1


class AdoptedLeader:
    def __init__(self, identity):
        if sys.platform != "linux" or not callable(getattr(os, "waitid", None)):
            raise RuntimeError("managed measurement requires P_PIDFD")
        self._observer = LinuxServiceObserverV1.reopen(identity)
        self._result = None
        self._close_unknown = False
        self._closed = False
        try:
            # A retained pidfd and before/after liveness bind this parent check
            # to the original live leader, not a recycled numeric PID.
            assert not self._observer.exited(), "leader exited before adoption check"
            status = Path(f"/proc/{identity.pid}/status").read_text()
            parents = [line.split()[1] for line in status.splitlines() if line.startswith("PPid:")]
            assert parents == [str(os.getpid())], "leader is not adopted by this observer"
            assert not self._observer.exited(), "leader exited during adoption check"
        except BaseException as primary:
            try:
                self.close()
            except BaseException as cleanup:
                primary.add_note("adopted observer close failed: " + type(cleanup).__name__)
            raise

    def poll(self) -> bool:
        if self._closed or self._close_unknown:
            raise RuntimeError("adopted leader close is complete or unknown")
        # Deliberate test-only borrow, serialized with the original pidfd owner.
        # Do not expose raw pidfds or wait/reap in the production observation API.
        with self._observer._mutex:
            if self._observer._fd is None:
                raise RuntimeError("adopted leader observer closed")
            if self._result is None:
                self._result = os.waitid(
                    # Linux UAPI linux/wait.h: P_PIDFD = 3. Standalone
                    # CPython may omit the name while exposing native waitid.
                    # Unsupported kernels fail here; never fall back to P_PID.
                    getattr(os, "P_PIDFD", 3), self._observer._fd, os.WEXITED | os.WNOHANG,
                )
            result = self._result
            if result is None:
                return False
            assert result.si_pid == self._observer.identity.pid
            assert result.si_code == os.CLD_EXITED and result.si_status == 0, (
                "managed leader did not exit successfully"
            )
            return True

    def close(self) -> None:
        if self._close_unknown:
            raise RuntimeError("adopted leader close outcome unknown")
        if self._closed:
            return
        self._close_unknown = True
        self._observer.close()
        self._closed = True
        self._close_unknown = False


def stop_command(argv, *, cwd, env, leader, timeout=45):
    """Wait for stop while fulfilling only the original adopted leader wait."""
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + timeout
    primary = None
    try:
        while True:
            leader.poll()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("managed stop command deadline")
            try:
                stdout, stderr = process.communicate(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        assert process.returncode == 0, (stdout, stderr)
        assert leader.poll(), "stop returned without exact leader reap"
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []

        def attempt(operation):
            try:
                operation()
            except BaseException as cleanup:
                failures.append(cleanup)

        def stop_foreground():
            if process.poll() is None:
                process.kill()  # Only our foreground stop command, never the service.

        attempt(stop_foreground)
        attempt(lambda: process.communicate(timeout=10))
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                attempt(stream.close)
        if failures:
            if primary is None:
                raise failures[0]
            primary.add_note("stop command cleanup failed: " + type(failures[0]).__name__)

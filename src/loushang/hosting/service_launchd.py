"""Native per-user launchd job commands and PID observation."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from typing import Literal


class LaunchdJobError(RuntimeError):
    """A stable operation failure without native output or local paths."""


def _launchctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *arguments], capture_output=True, text=True, check=False, timeout=45,
    )


class LaunchdUserJob:
    """Manage only the supplied job label in the current user's domain."""

    _domain: str
    _target: str

    def __init__(self, label: str) -> None:
        getuid = getattr(os, "getuid", None)
        if sys.platform != "darwin" or getuid is None:
            raise LaunchdJobError("platform_unsupported")
        self._domain = f"user/{getuid()}"
        self._target = f"{self._domain}/{label}"

    def observe(self) -> tuple[Literal["not_running", "exited", "running"], int | None]:
        printed = _launchctl("print", self._target)
        if printed.returncode:
            if _launchctl("print", self._domain).returncode:
                raise LaunchdJobError("management_unavailable")
            return "not_running", None
        match = re.search(r"^\s*pid = ([0-9]+)\s*$", printed.stdout, re.MULTILINE)
        if match is None:
            return "exited", None
        return "running", int(match[1])

    def wait_for_exit(self, pid: int) -> None:
        deadline = monotonic() + 40
        while monotonic() < deadline:
            _, observed_pid = self.observe()
            if observed_pid is None:
                return
            if observed_pid != pid:
                raise LaunchdJobError("instance_changed")
            sleep(0.1)
        raise LaunchdJobError("stop_failed")

    def remove(self, *, was_registered: bool) -> None:
        stopped = _launchctl("bootout", self._target)
        if stopped.returncode and was_registered:
            raise LaunchdJobError("stop_failed")
        state, _ = self.observe()
        if state != "not_running":
            raise LaunchdJobError("stop_failed")

    def bootstrap(self, plist: Path) -> None:
        if _launchctl("bootstrap", self._domain, str(plist)).returncode:
            raise LaunchdJobError("start_failed")

    def discard_after_start_timeout(self) -> None:
        _launchctl("bootout", self._target)

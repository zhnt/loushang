"""Read-only detection of the previous per-user launchd installation."""

from __future__ import annotations

import os
import subprocess
import sys


class LaunchdJobError(RuntimeError):
    """A stable failure without native output or local paths."""


def _launchctl(*arguments: str) -> int:
    try:
        return subprocess.run(
            ["/bin/launchctl", *arguments], capture_output=True, check=False, timeout=5,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        raise LaunchdJobError("management_unavailable") from None


class LaunchdUserJob:
    """Check whether an old job is still registered in the user's domain."""

    _domain: str
    _target: str

    def __init__(self, label: str) -> None:
        if sys.platform != "darwin":
            raise LaunchdJobError("platform_unsupported")
        getuid = getattr(os, "getuid", None)
        if not callable(getuid):
            raise LaunchdJobError("platform_unsupported")
        self._domain = f"user/{getuid()}"
        self._target = f"{self._domain}/{label}"

    def observe(self) -> str:
        if _launchctl("print", self._target) == 0:
            return "registered"
        if _launchctl("print", self._domain) != 0:
            raise LaunchdJobError("management_unavailable")
        return "not_running"

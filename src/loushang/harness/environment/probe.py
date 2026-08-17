from __future__ import annotations

import os
import platform
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .types import HostEnvironment, operating_system_family


class HostEnvironmentProbe(Protocol):
    def detect(self) -> HostEnvironment: ...


@dataclass(frozen=True, slots=True)
class LocalHostEnvironmentProbe:
    """Detect host facts while allowing deterministic platform injection."""

    platform_name: str | None = None
    architecture: str | None = None
    environ: Mapping[str, str] | None = None

    def detect(self) -> HostEnvironment:
        platform_name = self.platform_name or sys.platform
        architecture = self.architecture or platform.machine() or "unknown"
        os_family = operating_system_family(platform_name)
        environ = os.environ if self.environ is None else self.environ
        is_wsl = os_family == "linux" and bool(
            environ.get("WSL_DISTRO_NAME") or environ.get("WSL_INTEROP")
        )
        return HostEnvironment(
            os_family=os_family,
            platform_name=platform_name.lower(),
            architecture=architecture.lower(),
            is_wsl=is_wsl,
        )


__all__ = ["HostEnvironmentProbe", "LocalHostEnvironmentProbe"]

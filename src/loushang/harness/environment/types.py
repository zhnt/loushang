from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OperatingSystemFamily = Literal["linux", "macos", "windows", "other"]

_OS_FAMILIES: frozenset[str] = frozenset({"linux", "macos", "windows", "other"})


@dataclass(frozen=True, slots=True)
class HostEnvironment:
    """Stable host facts used to select platform-specific runtime backends."""

    os_family: OperatingSystemFamily
    platform_name: str
    architecture: str
    is_wsl: bool = False

    def __post_init__(self) -> None:
        if self.os_family not in _OS_FAMILIES:
            raise ValueError(f"unsupported operating-system family: {self.os_family!r}")
        if not self.platform_name:
            raise ValueError("platform_name must be non-empty")
        if not self.architecture:
            raise ValueError("architecture must be non-empty")
        if self.is_wsl and self.os_family != "linux":
            raise ValueError("is_wsl requires the linux operating-system family")


def operating_system_family(platform_name: str) -> OperatingSystemFamily:
    """Normalize the existing ``sys.platform`` vocabulary for backend routing."""

    normalized = platform_name.strip().lower()
    if normalized.startswith("linux"):
        return "linux"
    if normalized == "darwin":
        return "macos"
    if normalized.startswith(("win32", "cygwin", "msys")):
        return "windows"
    return "other"


__all__ = [
    "HostEnvironment",
    "OperatingSystemFamily",
    "operating_system_family",
]

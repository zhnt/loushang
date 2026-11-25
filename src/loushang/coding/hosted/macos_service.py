"""Coding launch profile for the per-user AppHost service on macOS."""

from __future__ import annotations

import sys
from functools import partial
from hashlib import sha256
from pathlib import Path

from loushang.apphost.managed.launchd import (
    ManagedLaunchdService,
    ManagedLaunchdServiceError,
)
from loushang.coding.hosted.managed.service import ServiceControlError
from loushang.foundation.platform_paths import resolve_platform_home


def _python() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent / "Resources/runtime/bin/python3"
    return Path(sys.executable)


def _launch_arguments(home: Path) -> tuple[tuple[str, ...], dict[str, str]]:
    # Provider credentials stay in launchd's environment or normal user configuration.
    environment = {
        "LOUSHANG_HOME": str(home),
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin",
    }
    return (str(_python()), "-I", "-m", "loushang.coding.hosted.foreground"), environment


def control_launchd_service(operation: str, expected: str | None) -> dict[str, object]:
    home = resolve_platform_home()
    service = ManagedLaunchdService(
        label="ai.loushang.host." + sha256(str(home).encode()).hexdigest()[:20],
        product_id="coding",
        endpoint="workspace",
        state_root=home / "state/macos-host",
        working_directory=home,
        launch_arguments=partial(_launch_arguments, home),
    )
    try:
        return service.control(operation, expected)
    except ManagedLaunchdServiceError as error:
        raise ServiceControlError(str(error)) from error


def print_logs() -> int:
    path = resolve_platform_home() / "state/macos-host/host.log"
    if not path.exists():
        return 0
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        print(stream.read(65536).decode("utf-8", errors="replace"), end="")
    return 0

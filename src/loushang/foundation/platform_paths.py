"""Pure machine-local path resolution shared below Product boundaries.

The resolver performs no filesystem I/O. Products bind concrete leaf paths,
persistence rules, permissions, and cleanup policy at their composition edge.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PlatformPaths:
    """Resolved machine-local roots grouped by lifecycle semantics."""

    home: Path
    data: Path
    state: Path
    cache: Path
    runtime: Path
    temporary: Path


def resolve_platform_home(
    *,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    """Resolve the user-global Loushang root without touching the filesystem."""

    values = os.environ if environ is None else environ
    configured = values.get("LOUSHANG_HOME")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    base = Path.home() if home is None else Path(home).expanduser()
    return (base / ".loushang").resolve(strict=False)


def resolve_platform_paths(
    *,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
    temporary_root: str | Path | None = None,
) -> PlatformPaths:
    """Resolve durable, cached, runtime, and temporary platform roots."""

    values = os.environ if environ is None else environ
    platform_home = resolve_platform_home(environ=values, home=home)
    runtime = _configured_path(values.get("LOUSHANG_RUNTIME_DIR"))
    base_temporary = (
        Path(temporary_root).expanduser()
        if temporary_root is not None
        else Path(tempfile.gettempdir())
    )
    if runtime is None:
        xdg_runtime = _configured_path(values.get("XDG_RUNTIME_DIR"))
        runtime = (
            xdg_runtime / "loushang"
            if xdg_runtime is not None
            else base_temporary / _temporary_user_segment(platform_home)
        )
    temporary = _configured_path(values.get("LOUSHANG_TMPDIR"))
    if temporary is None:
        temporary = runtime / "tmp"
    return PlatformPaths(
        home=platform_home,
        data=platform_home / "data",
        state=platform_home / "state",
        cache=platform_home / "cache",
        runtime=runtime.resolve(strict=False),
        temporary=temporary.resolve(strict=False),
    )


def _configured_path(value: str | None) -> Path | None:
    if not value or not value.strip():
        return None
    return Path(value).expanduser().resolve(strict=False)


def _temporary_user_segment(platform_home: Path) -> str:
    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        return f"loushang-{getuid()}"
    identity = sha256(str(platform_home).encode("utf-8")).hexdigest()[:12]
    return f"loushang-{identity}"


__all__ = [
    "PlatformPaths",
    "resolve_platform_home",
    "resolve_platform_paths",
]

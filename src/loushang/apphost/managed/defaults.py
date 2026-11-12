"""Shared managed default selection, separate from native deployment admission.

No deployment directories or Session stores are created. Platform path
normalization may inspect symlinks; OS machine identity is explicitly read.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from loushang.foundation.platform_paths import (
    PlatformPaths,
    resolve_platform_home,
    resolve_platform_paths,
)
from loushang.hosting.errors import HostingError, HostingFailureCategory
from loushang.hosting.machine_identity import linux_machine_key, windows_machine_key

from .contracts import ManagedContractError, ManagedNamespaceV1

MACHINE_DOMAIN = "loushang.managed.machine/v1"


@dataclass(frozen=True, slots=True)
class ManagedDefaultsV1:
    namespace: ManagedNamespaceV1
    platform: PlatformPaths = field(repr=False)
    temporary_override: str | None = field(default=None, repr=False)


def resolve_managed_defaults(
    *, environ: Mapping[str, str] | None = None, home: str | Path | None = None,
) -> ManagedDefaultsV1:
    """Resolve one user/home/machine context, independent of the attach cwd.

    Relative root overrides are rejected: otherwise reconnecting from another
    cwd would silently select a different namespace. Existing Foundation path
    overrides keep Foundation precedence. Linux managed fallback is explicitly
    /tmp (not TMPDIR/TEMP): reconnect must not depend on a shell's scratch path,
    and read-only listing must not trigger tempfile's writable-directory probe.
    """
    values = dict(os.environ if environ is None else environ)
    if sys.platform not in {"linux", "win32"}:
        raise HostingError(HostingFailureCategory.PLATFORM_UNSUPPORTED, "managed_defaults_platform_unsupported")
    for key in ("LOUSHANG_HOME", "LOUSHANG_RUNTIME_DIR", "LOUSHANG_TMPDIR", "XDG_RUNTIME_DIR"):
        if key == "XDG_RUNTIME_DIR" and values.get("LOUSHANG_RUNTIME_DIR"):
            continue
        value = values.get(key)
        if value and (not value.strip() or not Path(value).expanduser().is_absolute()):
            raise ManagedContractError()
    if not values.get("LOUSHANG_HOME") and home is not None and not Path(home).expanduser().is_absolute():
        raise ManagedContractError()
    if sys.platform == "win32":
        paths = _windows_paths(values, home)
        machine = windows_machine_key(domain=MACHINE_DOMAIN)
    else:
        paths = resolve_platform_paths(environ=values, home=home, temporary_root="/tmp")
        machine = linux_machine_key(domain=MACHINE_DOMAIN)
    namespace = ManagedNamespaceV1(str(paths.home), current_managed_user(), machine)
    runtime = paths.runtime / "hosts" / namespace.namespace_key
    # Reject conflicting default roots before granting any creation intent.
    for durable in (paths.home / "hosts", paths.state, paths.data):
        if runtime.is_relative_to(durable) or durable.is_relative_to(runtime):
            raise ManagedContractError()
    temporary_override = str(paths.temporary) if values.get("LOUSHANG_TMPDIR") else None
    if temporary_override is not None:
        temporary = Path(temporary_override) / "hosts" / namespace.namespace_key
        for other in (paths.home / "hosts", paths.state, paths.data, runtime):
            if temporary.is_relative_to(other) or other.is_relative_to(temporary):
                raise ManagedContractError()
    return ManagedDefaultsV1(namespace, paths, temporary_override)


def _windows_paths(values: dict[str, str], home: str | Path | None) -> PlatformPaths:
    # A detached process and any later caller use the same runtime location,
    # even when launched under a different shell or temporary directory.
    default_runtime = resolve_platform_home(environ=values, home=home) / "run"
    if not values.get("LOUSHANG_RUNTIME_DIR"):
        values["LOUSHANG_RUNTIME_DIR"] = str(default_runtime)
    return resolve_platform_paths(environ=values, home=home, temporary_root=default_runtime)


def current_managed_user() -> int | str:
    """Read the effective Linux user or the native Windows process token SID."""
    if sys.platform == "linux":
        return os.geteuid()
    if sys.platform != "win32":
        raise HostingError(HostingFailureCategory.PLATFORM_UNSUPPORTED, "managed_defaults_platform_unsupported")
    from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl

    try:
        with WindowsPrivateDirectoryAcl() as acl:
            return acl.user_sid
    except OSError:
        raise HostingError(HostingFailureCategory.PREPARATION_FAILED, "managed_windows_identity_unavailable") from None


__all__ = ["ManagedDefaultsV1", "resolve_managed_defaults"]

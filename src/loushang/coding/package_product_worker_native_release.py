"""Read one generated Linux H6 release as inert Worker closure evidence.

The release directory is a build input, not an installed native distribution.
This reader cannot issue a Product receipt or authorize a Worker launch.
"""

from __future__ import annotations

import json
import os
import platform
import stat
import sys
from hashlib import sha256
from pathlib import Path

from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.worker.native_executable_format import (
    WorkerNativeExecutableFormatError,
    verify_worker_native_executable_format,
)

from .package_product_worker_policy import (
    CodingWorkerNativeClosureReadError,
    CodingWorkerNativeClosureV1,
)

_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "hosting/native/contained_launcher_linux_x86_64.c"
)
_CATALOG_FIELDS = frozenset(
    {
        "catalogVersion",
        "platform",
        "profileSourceSha256",
        "launcherSha256",
        "launcherFile",
        "buildFlags",
    }
)
_MAX_CATALOG_BYTES = 4096
_MAX_LAUNCHER_BYTES = 16 * 1024 * 1024


class CodingWorkerNativeReleaseError(CodingWorkerNativeClosureReadError):
    """The generated release cannot supply exact native closure facts."""


class CodingLinuxWorkerReleaseCatalogReader:
    """Reopen generated build bytes under the Product GC gate identity.

    This candidate accepts a caller-selected private release directory. A
    production reader must instead bind an installed platform distribution.
    """

    def __init__(
        self,
        *,
        release_root: Path,
        gc_gate: PluginPackageGcReservationJournal,
    ) -> None:
        if not isinstance(release_root, Path) or not release_root.is_absolute():
            raise ValueError("Worker release root must be absolute")
        if not isinstance(gc_gate, PluginPackageGcReservationJournal):
            raise TypeError("Worker release requires a Product GC gate")
        self._release_root = release_root
        self._gc_gate = gc_gate

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    def current_closure(self) -> CodingWorkerNativeClosureV1:
        if sys.platform != "linux" or platform.machine().lower() not in {
            "x86_64",
            "amd64",
        }:
            raise CodingWorkerNativeReleaseError("Linux x86-64 release is required")
        try:
            root = os.open(
                self._release_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                metadata = os.fstat(root)
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                ):
                    raise CodingWorkerNativeReleaseError(
                        "Worker release root is not private"
                    )
                catalog_bytes = _read_member(root, "catalog.json", _MAX_CATALOG_BYTES)
                launcher = _read_member(
                    root, "containment-launcher", _MAX_LAUNCHER_BYTES,
                    executable=True,
                )
                return _verify_release_bytes(catalog_bytes, launcher)
            finally:
                os.close(root)
        except (
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
            WorkerNativeExecutableFormatError,
        ) as exc:
            raise CodingWorkerNativeReleaseError(
                "Worker release cannot be verified"
            ) from exc


def _verify_release_bytes(
    catalog_bytes: bytes, launcher: bytes
) -> CodingWorkerNativeClosureV1:
    source_digest = sha256(_SOURCE.read_bytes()).hexdigest()
    catalog = json.loads(catalog_bytes)
    if (
        type(catalog) is not dict
        or set(catalog) != _CATALOG_FIELDS
        or type(catalog["catalogVersion"]) is not int
        or catalog["catalogVersion"] != 1
        or catalog["platform"] != "linux-x86_64"
        or catalog["profileSourceSha256"] != source_digest
        or catalog["launcherFile"] != "containment-launcher"
        or not isinstance(catalog["buildFlags"], list)
        or any(type(flag) is not str for flag in catalog["buildFlags"])
        or catalog_bytes
        != (
            json.dumps(catalog, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
    ):
        raise CodingWorkerNativeReleaseError("Worker release catalog changed")
    launcher_digest = sha256(launcher).hexdigest()
    if catalog["launcherSha256"] != launcher_digest:
        raise CodingWorkerNativeReleaseError("Worker release launcher changed")
    verify_worker_native_executable_format(launcher, platform="linux-x86_64")
    return CodingWorkerNativeClosureV1(
        native_platform="linux-x86_64",
        native_profile_catalog_revision=(
            "h6-linux:" + sha256(catalog_bytes).hexdigest()
        ),
        containment_launcher_digest=launcher_digest,
        containment_profile_digest=source_digest,
    )


def _read_member(
    root: int,
    name: str,
    limit: int,
    *,
    executable: bool = False,
    installed: bool = False,
) -> bytes:
    member = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root
    )
    try:
        metadata = os.fstat(member)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or metadata.st_size > limit
            or (
                executable
                and (
                    not stat.S_IMODE(metadata.st_mode) & 0o100
                    if installed
                    else stat.S_IMODE(metadata.st_mode) != 0o500
                )
            )
        ):
            raise CodingWorkerNativeReleaseError("Worker release member is unsafe")
        data = bytearray()
        while chunk := os.read(member, min(64 * 1024, limit + 1 - len(data))):
            data.extend(chunk)
            if len(data) > limit:
                raise CodingWorkerNativeReleaseError(
                    "Worker release member exceeds budget"
                )
        after = os.fstat(member)
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_mode != metadata.st_mode
            or after.st_uid != metadata.st_uid
            or after.st_nlink != metadata.st_nlink
            or after.st_size != metadata.st_size
            or after.st_mtime_ns != metadata.st_mtime_ns
            or after.st_ctime_ns != metadata.st_ctime_ns
        ):
            raise CodingWorkerNativeReleaseError("Worker release member changed")
        return bytes(data)
    finally:
        os.close(member)

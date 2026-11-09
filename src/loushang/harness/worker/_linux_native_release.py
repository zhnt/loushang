"""Inert H6 Linux release verification; no Product approval or launch authority."""

from __future__ import annotations

import csv
import io
import json
import os
import platform
import re
import stat
import sys
from base64 import urlsafe_b64encode
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from loushang.harness.resources.packages._file_consumption import read_bounded_prefix

from .native_executable_format import (
    WorkerNativeExecutableFormatError,
    verify_worker_native_executable_format,
)

_PACKAGE = "loushang_h6_native"
_SAFE_MEMBER = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
_MAX_RECORD_BYTES = 16 * 1024
_MAX_METADATA_BYTES = 64 * 1024
_MAX_CATALOG_BYTES = 4096
_MAX_LAUNCHER_BYTES = 16 * 1024 * 1024
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

ClosureT = TypeVar("ClosureT")
ClosureT_co = TypeVar("ClosureT_co", covariant=True)


class _ClosureFactory(Protocol[ClosureT_co]):
    def __call__(
        self,
        *,
        native_platform: str,
        native_profile_catalog_revision: str,
        containment_launcher_digest: str,
        containment_profile_digest: str,
    ) -> ClosureT_co: ...


@dataclass(frozen=True, slots=True)
class _LinuxNativeReleaseVerifier(Generic[ClosureT]):
    """Read generated or installed H6 bytes with the caller's pure value bindings.

    Borrowed descriptors remain caller-owned. Path methods own their descriptors.
    The version leaf is read only at installed admission, after platform checking.
    """

    source_path: Path
    error_type: Callable[[str], Exception]
    closure_type: _ClosureFactory[ClosureT]

    def generated_closure(self, release_root: Path) -> ClosureT:
        if sys.platform != "linux" or platform.machine().lower() not in {
            "x86_64",
            "amd64",
        }:
            raise self.error_type("Linux x86-64 release is required")
        try:
            root = os.open(
                release_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                metadata = os.fstat(root)
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                ):
                    raise self.error_type("Worker release root is not private")
                catalog_bytes = self.read_member(
                    root, "catalog.json", _MAX_CATALOG_BYTES
                )
                launcher = self.read_member(
                    root,
                    "containment-launcher",
                    _MAX_LAUNCHER_BYTES,
                    executable=True,
                )
                return self.verify_release_bytes(catalog_bytes, launcher)
            finally:
                os.close(root)
        except (
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
            WorkerNativeExecutableFormatError,
        ) as exc:
            raise self.error_type("Worker release cannot be verified") from exc

    def installed_closure(
        self, installation_root: Path, *, version_provider: Callable[[], str]
    ) -> ClosureT:
        try:
            root = os.open(
                installation_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                return self.verify_installed_root_descriptor(
                    root, version_provider=version_provider
                )
            finally:
                os.close(root)
        except (
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
            csv.Error,
            PackageNotFoundError,
            WorkerNativeExecutableFormatError,
        ) as exc:
            raise self.error_type(
                "Installed Worker native release cannot be verified"
            ) from exc

    def verify_installed_root_descriptor(
        self, root: int, *, version_provider: Callable[[], str]
    ) -> ClosureT:
        if sys.platform != "linux" or platform.machine().lower() not in {
            "x86_64",
            "amd64",
        }:
            raise self.error_type("Linux x86-64 release is required")
        installed_version = version_provider()
        dist_info = f"{_PACKAGE}-{installed_version}.dist-info"
        root_stat = os.fstat(root)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or root_stat.st_uid != os.geteuid()
            or stat.S_IMODE(root_stat.st_mode) & 0o077
        ):
            raise self.error_type("Worker native installation root is not private")
        package = self._open_directory(root, _PACKAGE)
        try:
            release = self._open_directory(package, "release")
            try:
                metadata = self._open_directory(root, dist_info)
                try:
                    files = self._verify_record(
                        package=package,
                        release=release,
                        metadata=metadata,
                        dist_info=dist_info,
                        installed_version=installed_version,
                    )
                finally:
                    os.close(metadata)
            finally:
                os.close(release)
        finally:
            os.close(package)
        return self.verify_release_bytes(
            files[f"{_PACKAGE}/release/catalog.json"],
            files[f"{_PACKAGE}/release/containment-launcher"],
        )

    def verify_release_bytes(self, catalog_bytes: bytes, launcher: bytes) -> ClosureT:
        source_digest = sha256(self.source_path.read_bytes()).hexdigest()
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
            raise self.error_type("Worker release catalog changed")
        launcher_digest = sha256(launcher).hexdigest()
        if catalog["launcherSha256"] != launcher_digest:
            raise self.error_type("Worker release launcher changed")
        verify_worker_native_executable_format(launcher, platform="linux-x86_64")
        return self.closure_type(
            native_platform="linux-x86_64",
            native_profile_catalog_revision=(
                "h6-linux:" + sha256(catalog_bytes).hexdigest()
            ),
            containment_launcher_digest=launcher_digest,
            containment_profile_digest=source_digest,
        )

    def read_member(
        self,
        root: int,
        name: str,
        limit: int,
        *,
        executable: bool = False,
        installed: bool = False,
    ) -> bytes:
        member = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
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
                raise self.error_type("Worker release member is unsafe")
            data = read_bounded_prefix(member, limit, chunk_size=64 * 1024)
            if len(data) > limit:
                raise self.error_type("Worker release member exceeds budget")
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
                raise self.error_type("Worker release member changed")
            return data
        finally:
            os.close(member)

    def _open_directory(self, parent: int, name: str) -> int:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            os.close(descriptor)
            raise self.error_type("Installed Worker native directory is unsafe")
        return descriptor

    def _verify_record(
        self,
        *,
        package: int,
        release: int,
        metadata: int,
        dist_info: str,
        installed_version: str,
    ) -> dict[str, bytes]:
        record_name = f"{dist_info}/RECORD"
        record = self.read_member(metadata, "RECORD", _MAX_RECORD_BYTES, installed=True)
        rows = tuple(csv.reader(io.StringIO(record.decode("utf-8")), strict=True))
        required = {
            f"{_PACKAGE}/__init__.py",
            f"{_PACKAGE}/release/catalog.json",
            f"{_PACKAGE}/release/containment-launcher",
            f"{dist_info}/METADATA",
            f"{dist_info}/WHEEL",
            record_name,
        }
        if not 6 <= len(rows) <= 16 or any(len(row) != 3 for row in rows):
            raise self.error_type("Installed Worker RECORD is invalid")
        files: dict[str, bytes] = {}
        for name, digest, size in rows:
            if name in files:
                raise self.error_type("Installed Worker RECORD is duplicated")
            if name == record_name:
                if digest or size:
                    raise self.error_type("Installed Worker RECORD is invalid")
                files[name] = record
                continue
            parts = name.split("/")
            if len(parts) == 2 and parts[0] == _PACKAGE and parts[1] == "__init__.py":
                body = self.read_member(package, parts[1], 4096, installed=True)
            elif (
                len(parts) == 3
                and parts[:2] == [_PACKAGE, "release"]
                and parts[2] in {"catalog.json", "containment-launcher"}
            ):
                body = self.read_member(
                    release,
                    parts[2],
                    _MAX_LAUNCHER_BYTES if parts[2] == "containment-launcher" else 4096,
                    installed=True,
                    executable=parts[2] == "containment-launcher",
                )
            elif (
                len(parts) == 2
                and parts[0] == dist_info
                and _SAFE_MEMBER.fullmatch(parts[1]) is not None
            ):
                body = self.read_member(
                    metadata, parts[1], _MAX_METADATA_BYTES, installed=True
                )
            else:
                raise self.error_type("Installed Worker RECORD member is unsupported")
            expected = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode()
            if digest != f"sha256={expected}" or size != str(len(body)):
                raise self.error_type("Installed Worker RECORD changed")
            files[name] = body
        if not required.issubset(files):
            raise self.error_type("Installed Worker RECORD is incomplete")
        recorded_metadata = {
            name.split("/", 1)[1] for name in files if name.startswith(f"{dist_info}/")
        }
        if (
            set(os.listdir(package)) != {"__init__.py", "release"}
            or set(os.listdir(release)) != {"catalog.json", "containment-launcher"}
            or set(os.listdir(metadata)) != recorded_metadata
        ):
            raise self.error_type(
                "Installed Worker distribution contains unrecorded members"
            )
        if files[f"{_PACKAGE}/__init__.py"] != b"":
            raise self.error_type("Installed Worker package changed")
        expected_metadata = (
            "Metadata-Version: 2.1\n"
            "Name: loushang-h6-native\n"
            f"Version: {installed_version}\n\n"
        ).encode("ascii")
        expected_wheel = (
            "Wheel-Version: 1.0\n"
            "Generator: loushang-h6-release\n"
            "Root-Is-Purelib: false\n"
            "Tag: py3-none-linux_x86_64\n\n"
        ).encode("ascii")
        if (
            files[f"{dist_info}/METADATA"] != expected_metadata
            or files[f"{dist_info}/WHEEL"] != expected_wheel
        ):
            raise self.error_type("Installed Worker distribution identity changed")
        return files

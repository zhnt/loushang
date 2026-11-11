"""Publish and inspect exact Product Source bytes using the existing native IO.

These private operations retain direct-target publication, including partial
files on failure. They do not grant Source admission or replace staged Sources.
"""

from __future__ import annotations

import csv
import io
import json
import os
import stat
import zipfile
from base64 import urlsafe_b64encode
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal._io_loops import write_all

from .windows_epoch_cutover import _PinnedWindowsAuthority
from .windows_quarantine import (
    open_windows_regular_file_at,
    supports_windows_rooted_io,
    windows_flush_directory,
    windows_flush_file,
)


class InstalledProductWheelSpec(Protocol):
    @property
    def plugin_id(self) -> str: ...
    @property
    def package_name(self) -> str: ...
    @property
    def members(self) -> tuple[str, ...]: ...
    @property
    def dist_info(self) -> str: ...
    @property
    def distribution_name(self) -> str: ...


@dataclass(frozen=True, slots=True)
class InstalledProductWheelRecipe:
    module_file: Callable[[], str]
    package_directory: str
    version: str
    metadata_version: str
    wheel_metadata: bytes
    maximum_member_bytes: Callable[[], int]


def resolve_installed_product_root(module_file: str, parts: tuple[str, ...]) -> Path:
    """Keep the original module resolution and independent strict root lookup."""
    root = Path(module_file).resolve().parent
    for part in parts:
        root = root / part
    return root.resolve(strict=True)


class ExactProductSourceFiles:
    """Fixed Product text and a live budget; each call owns its native scope."""

    def __init__(self, product: str, maximum_bytes: Callable[[], int]) -> None:
        self._product = product
        self._maximum_bytes = maximum_bytes

    def inspect_windows(
        self, source_root: Path, *, filename: str, body: bytes, label: str
    ) -> tuple[Path, str, int]:
        self._validate_windows(source_root, body, label)
        source = _PinnedWindowsAuthority.open(source_root, read_control=True)
        try:
            with WindowsPrivateDirectoryAcl() as acl:
                acl.validate(source.descriptor)
                member = open_windows_regular_file_at(
                    source.descriptor,
                    filename,
                    create_new=False,
                    write=False,
                    read_control=True,
                )
                try:
                    acl.validate(member)
                    metadata = os.fstat(member)
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_nlink != 1
                        or metadata.st_size != len(body)
                        or os.read(member, len(body) + 1) != body
                    ):
                        raise ValueError(
                            f"{self._product} {label} Product Wheel changed on disk"
                        )
                finally:
                    os.close(member)
            source.assert_visible()
        finally:
            source.close()
        return source_root / filename, sha256(body).hexdigest(), len(body)

    def publish_windows(
        self, source_root: Path, *, filename: str, body: bytes, label: str
    ) -> tuple[Path, str, int]:
        self._validate_windows(source_root, body, label)
        source = _PinnedWindowsAuthority.open(source_root, read_control=True)
        try:
            with WindowsPrivateDirectoryAcl() as acl:
                acl.validate(source.descriptor)
                try:
                    member = open_windows_regular_file_at(
                        source.descriptor,
                        filename,
                        create_new=True,
                        write=True,
                        security_descriptor=acl.security_descriptor,
                        read_control=True,
                    )
                except FileExistsError:
                    pass
                else:
                    try:
                        acl.validate(member)
                        self._write(member, body, label)
                        windows_flush_file(member)
                    finally:
                        os.close(member)
                    windows_flush_directory(source.descriptor)
                source.assert_visible()
        finally:
            source.close()
        return self.inspect_windows(
            source_root, filename=filename, body=body, label=label
        )

    def inspect_posix(
        self, source_root: Path, *, filename: str, body: bytes, label: str
    ) -> tuple[Path, str, int]:
        directory = self._open_posix(source_root, body, label)
        try:
            member = os.open(
                filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
            )
            try:
                self._verify_posix(member, body, label)
            finally:
                os.close(member)
        finally:
            os.close(directory)
        return source_root / filename, sha256(body).hexdigest(), len(body)

    def publish_posix(
        self, source_root: Path, *, filename: str, body: bytes, label: str
    ) -> tuple[Path, str, int]:
        directory = self._open_posix(source_root, body, label)
        try:
            try:
                member = os.open(
                    filename,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory,
                )
            except FileNotFoundError:
                member = os.open(
                    filename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory,
                )
                try:
                    os.fchmod(member, 0o600)
                    self._write(member, body, label)
                    os.fsync(member)
                finally:
                    os.close(member)
                os.fsync(directory)
            else:
                try:
                    self._verify_posix(member, body, label)
                finally:
                    os.close(member)
        finally:
            os.close(directory)
        return source_root / filename, sha256(body).hexdigest(), len(body)

    def _write(self, member: int, body: bytes, label: str) -> None:
        write_all(
            lambda pending: os.write(member, pending),
            body,
            message="",
            error_factory=lambda _: OSError(
                f"{self._product} {label} Product Wheel write made no progress"
            ),
        )

    def _validate_windows(self, root: Path, body: bytes, label: str) -> None:
        if (
            os.name != "nt"
            or not supports_windows_rooted_io()
            or not isinstance(root, Path)
            or not root.is_absolute()
            or ".." in root.parts
            or len(body) > self._maximum_bytes()
        ):
            raise ValueError(
                f"Windows {self._product} {label} Product Source is invalid"
            )

    def _open_posix(self, root: Path, body: bytes, label: str) -> int:
        if (
            os.name != "posix"
            or not isinstance(root, Path)
            or not root.is_absolute()
            or ".." in root.parts
            or not all(
                hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
            )
        ):
            raise ValueError(
                f"POSIX {self._product} {label} Product Source root is required"
            )
        if len(body) > self._maximum_bytes():
            raise ValueError(
                f"Installed {self._product} {label} Product Wheel exceeds budget"
            )
        descriptor = os.open(
            root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            directory = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(directory.st_mode)
                or stat.S_IMODE(directory.st_mode) & 0o077
                or directory.st_uid != os.getuid()
            ):
                raise ValueError(
                    f"{self._product} {label} Product Source root is not private"
                )
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def _verify_posix(self, descriptor: int, body: bytes, label: str) -> None:
        member = os.fstat(descriptor)
        if (
            not stat.S_ISREG(member.st_mode)
            or member.st_nlink != 1
            or member.st_uid != os.getuid()
            or stat.S_IMODE(member.st_mode) & 0o077
            or member.st_size != len(body)
            or os.read(descriptor, len(body) + 1) != body
        ):
            raise ValueError(f"{self._product} {label} Product Wheel changed on disk")

    def build_installed_wheel(
        self, spec: InstalledProductWheelSpec, *, recipe: InstalledProductWheelRecipe
    ) -> bytes:
        root = resolve_installed_product_root(
            recipe.module_file(), (recipe.package_directory, spec.package_name)
        )
        files = {
            f"{spec.package_name}/{relative}": self.read_installed_member(
                root, relative, maximum_bytes=recipe.maximum_member_bytes
            )
            for relative in spec.members
        }
        manifest = json.loads(files[f"{spec.package_name}/plugin.json"])
        if not isinstance(manifest, dict) or (
            manifest.get("name"),
            manifest.get("version"),
        ) != (spec.plugin_id, recipe.version):
            raise ValueError(f"Installed {spec.plugin_id} Product manifest changed")
        files[f"{spec.dist_info}/METADATA"] = (
            f"Metadata-Version: {recipe.metadata_version}\nName: {spec.distribution_name}\nVersion: {recipe.version}\n\n".encode(
                "utf-8"
            )
        )
        files[f"{spec.dist_info}/WHEEL"] = recipe.wheel_metadata
        record = io.StringIO(newline="")
        writer = csv.writer(record, lineterminator="\n")
        for name, body in sorted(files.items()):
            digest = (
                urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode("ascii")
            )
            writer.writerow((name, f"sha256={digest}", str(len(body))))
        record_name = f"{spec.dist_info}/RECORD"
        writer.writerow((record_name, "", ""))
        files[record_name] = record.getvalue().encode("utf-8")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, body in sorted(files.items()):
                member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                member.create_system = 3
                member.external_attr = (stat.S_IFREG | 420) << 16
                member.compress_type = zipfile.ZIP_STORED
                archive.writestr(member, body)
        return output.getvalue()

    def read_installed_member(
        self, root: Path, relative: str, *, maximum_bytes: Callable[[], int]
    ) -> bytes:
        path = root / relative
        current = path.parent
        while current != root:
            directory = current.lstat()
            if not stat.S_ISDIR(directory.st_mode) or _installed_member_is_reparse(
                directory
            ):
                raise ValueError(
                    f"Installed {self._product} base Product directory is unsafe"
                )
            current = current.parent
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or _installed_member_is_reparse(before)
            or before.st_size > maximum_bytes()
        ):
            raise ValueError(f"Installed {self._product} base Product member is unsafe")
        body = path.read_bytes()
        after = path.lstat()
        if (
            len(body) > maximum_bytes()
            or _installed_member_is_reparse(after)
            or (
                before.st_dev,
                before.st_ino,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            )
        ):
            raise ValueError(
                f"Installed {self._product} base Product member changed during read"
            )
        return body


def _installed_member_is_reparse(metadata: os.stat_result) -> bool:
    return os.name == "nt" and bool(
        getattr(metadata, "st_reparse_tag", 0)
        or getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )

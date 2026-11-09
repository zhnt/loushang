"""Publish and inspect exact Product Source bytes using the existing native IO.

These private operations retain direct-target publication, including partial
files on failure. They do not grant Source admission or replace staged Sources.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal._io_loops import write_all

from .windows_epoch_cutover import _PinnedWindowsAuthority
from .windows_quarantine import (
    open_windows_regular_file_at,
    supports_windows_rooted_io,
    windows_flush_directory,
    windows_flush_file,
)


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

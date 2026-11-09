"""Directory-relative Continuity payload custody and cancellation settlement."""

from __future__ import annotations

import asyncio
import os
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.journal._io_loops import write_all
from loushang.harness.runtime import await_owned_task

from .import_provider import ContinuityActivationPayload


@dataclass(frozen=True, slots=True)
class _PrivateContinuityPayload:
    path: Path
    file_identity: tuple[int, int]
    root_identity: tuple[int, int]
    root_descriptor: int
    file_descriptor: int  # Pin the inode until identity-checked cleanup finishes.


@dataclass(frozen=True, slots=True)
class _ContinuityPayloadStaging:
    """Complete private-file custody for one Continuity diagnostic vocabulary."""

    label: str

    def write(
        self, root: Path, payload: ContinuityActivationPayload
    ) -> _PrivateContinuityPayload:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._validate_path_chain(root)
        if not self.supports_directory_handles():
            raise OSError(
                "Secure directory-relative Continuity staging is unavailable on this platform"
            )
        return self._write_at(root, payload)

    def _write_at(
        self, root: Path, payload: ContinuityActivationPayload
    ) -> _PrivateContinuityPayload:
        root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        root_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        root_descriptor = os.open(root, root_flags)
        descriptor = -1
        name = ""
        try:
            root_status = os.fstat(root_descriptor)
            path_status = root.lstat()
            self._validate_root(root, root_status)
            if not os.path.samestat(root_status, path_status):
                raise OSError(f"{self.label} temporary root identity changed")
            os.fchmod(root_descriptor, 0o700)
            root_identity = (root_status.st_dev, root_status.st_ino)
            suffix = self._suffix(payload)
            file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            file_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            for _attempt in range(128):
                name = f"continuity-{secrets.token_hex(16)}{suffix}"
                try:
                    descriptor = os.open(
                        name, file_flags, 0o600, dir_fd=root_descriptor
                    )
                except FileExistsError:
                    continue
                break
            else:
                raise FileExistsError(f"{self.label} temporary namespace is exhausted")
            os.fchmod(descriptor, 0o600)
            self._write_bytes(descriptor, payload.data)
            status = os.fstat(descriptor)
            file_identity = (status.st_dev, status.st_ino)
            return _PrivateContinuityPayload(
                path=root / name,
                file_identity=file_identity,
                root_identity=root_identity,
                root_descriptor=root_descriptor,
                file_descriptor=descriptor,
            )
        except BaseException:
            try:
                if descriptor >= 0:
                    with suppress(OSError):
                        current = os.stat(
                            name, dir_fd=root_descriptor, follow_symlinks=False
                        )
                        if os.path.samestat(os.fstat(descriptor), current):
                            os.unlink(name, dir_fd=root_descriptor)
            finally:
                try:
                    if descriptor >= 0:
                        os.close(descriptor)
                finally:
                    os.close(root_descriptor)
            raise

    def _validate_root(self, root: Path, root_status: os.stat_result) -> None:
        if (
            not stat.S_ISDIR(root_status.st_mode)
            or stat.S_ISLNK(root_status.st_mode)
            or bool(getattr(root_status, "st_reparse_tag", 0))
        ):
            raise OSError(f"{self.label} temporary root is unsafe")
        getuid = getattr(os, "getuid", None)
        if os.name == "posix" and callable(getuid) and (root_status.st_uid != getuid()):
            raise PermissionError(
                f"{self.label} temporary root belongs to another user: {root}"
            )

    def _validate_path_chain(self, root: Path) -> None:
        for directory in (root, *root.parents):
            metadata = directory.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or bool(getattr(metadata, "st_reparse_tag", 0))
            ):
                raise OSError(f"{self.label} temporary path contains an unsafe link")
            if (
                os.name == "posix"
                and metadata.st_mode & 0o022
                and (not metadata.st_mode & stat.S_ISVTX)
            ):
                raise PermissionError(
                    f"{self.label} temporary path has a writable ancestor"
                )

    def _suffix(self, payload: ContinuityActivationPayload) -> str:
        return (
            ".loushang.zip"
            if payload.media_type.endswith("session-bundle+zip")
            else ".jsonl"
        )

    def _write_bytes(self, descriptor: int, data: bytes) -> None:
        write_all(
            lambda pending: os.write(descriptor, pending),
            data,
            message=f"{self.label} temporary write made no progress",
        )
        os.fsync(descriptor)

    def supports_directory_handles(self) -> bool:
        supports_dir_fd = getattr(os, "supports_dir_fd", ())
        return (
            os.name == "posix"
            and isinstance(getattr(os, "O_DIRECTORY", None), int)
            and isinstance(getattr(os, "O_NOFOLLOW", None), int)
            and (os.open in supports_dir_fd)
            and (os.stat in supports_dir_fd)
            and (os.unlink in supports_dir_fd)
        )

    def remove(self, staged: _PrivateContinuityPayload) -> None:
        try:
            root_status = os.fstat(staged.root_descriptor)
            if (root_status.st_dev, root_status.st_ino) != staged.root_identity:
                raise OSError(f"{self.label} temporary root identity changed")
            try:
                status = os.stat(
                    staged.path.name,
                    dir_fd=staged.root_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return
            if (
                stat.S_ISLNK(status.st_mode)
                or bool(getattr(status, "st_reparse_tag", 0))
                or (status.st_dev, status.st_ino) != staged.file_identity
            ):
                raise OSError(f"{self.label} temporary file identity changed")
            os.unlink(staged.path.name, dir_fd=staged.root_descriptor)
        finally:
            try:
                os.close(staged.file_descriptor)
            finally:
                os.close(staged.root_descriptor)

    async def remove_atomic(self, staged: _PrivateContinuityPayload) -> None:
        task = asyncio.create_task(asyncio.to_thread(self.remove, staged))
        await await_owned_task(task)

    async def write_atomic(
        self, root: Path, payload: ContinuityActivationPayload
    ) -> _PrivateContinuityPayload:
        task = asyncio.create_task(asyncio.to_thread(self.write, root, payload))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as first_cancellation:
            cancellation = first_cancellation
            caller = asyncio.current_task()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError as repeated:
                    if caller is None or caller.cancelling() == 0:
                        return task.result()
                    cancellation = repeated
            try:
                staged = task.result()
            except BaseException as write_error:
                cancellation.add_note(
                    f"{self.label} temporary write also failed: {type(write_error).__name__}"
                )
                raise cancellation
            try:
                await self.remove_atomic(staged)
            except BaseException as cleanup_error:
                cancellation.add_note(
                    f"{self.label} cancelled-write cleanup also failed: {type(cleanup_error).__name__}"
                )
            raise cancellation

"""Product-neutral bounded regular-file capture below one trusted directory."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class ContainedFileCaptureError(OSError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class CapturedRegularFile:
    path: Path
    relative_path: str
    body: bytes
    device: int
    inode: int


def capture_contained_regular_file(
    root: str | Path,
    relative_path: str | PurePosixPath,
    *,
    max_bytes: int,
    read_probe: Callable[[], None] | None = None,
) -> CapturedRegularFile:
    """Open below ``root`` without following links and read at most limit+1."""

    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("Contained file byte limit must be positive")
    if read_probe is not None and not callable(read_probe):
        raise TypeError("Contained file read probe must be callable")
    resolved_root = Path(root).resolve(strict=True)
    relative = _canonical_relative_path(relative_path)
    display_path = resolved_root / relative
    if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
        return _capture_descriptor_relative(
            resolved_root,
            relative,
            display_path=display_path,
            max_bytes=max_bytes,
            read_probe=read_probe,
        )
    return _capture_portable(
        resolved_root,
        relative,
        display_path=display_path,
        max_bytes=max_bytes,
        read_probe=read_probe,
    )


def _capture_descriptor_relative(
    root: Path,
    relative: PurePosixPath,
    *,
    display_path: Path,
    max_bytes: int,
    read_probe: Callable[[], None] | None,
) -> CapturedRegularFile:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | os.O_NOFOLLOW
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | os.O_NOFOLLOW
    )
    opened: list[int] = []
    try:
        current = os.open(root, directory_flags)
        opened.append(current)
        for part in relative.parts[:-1]:
            current = os.open(part, directory_flags, dir_fd=current)
            opened.append(current)
        descriptor = os.open(relative.parts[-1], file_flags, dir_fd=current)
        opened.append(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ContainedFileCaptureError(
                "Contained path is not a regular file",
                code="contained_file_not_regular",
                path=display_path,
            )
        body = _bounded_read(
            descriptor,
            max_bytes=max_bytes,
            path=display_path,
            read_probe=read_probe,
        )
        after = os.fstat(descriptor)
        if not _same_file_snapshot(metadata, after) or len(body) != metadata.st_size:
            raise ContainedFileCaptureError(
                "Contained file changed while being captured",
                code="contained_file_identity_changed",
                path=display_path,
            )
        return CapturedRegularFile(
            path=display_path,
            relative_path=relative.as_posix(),
            body=body,
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )
    except ContainedFileCaptureError:
        raise
    except OSError as exc:
        raise ContainedFileCaptureError(
            "Contained regular file could not be opened",
            code="contained_file_unreadable",
            path=display_path,
        ) from exc
    finally:
        for descriptor in reversed(opened):
            with suppress(OSError):
                os.close(descriptor)


def _capture_portable(
    root: Path,
    relative: PurePosixPath,
    *,
    display_path: Path,
    max_bytes: int,
    read_probe: Callable[[], None] | None,
) -> CapturedRegularFile:
    before = _portable_path_metadata(root, relative, display_path=display_path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(display_path, flags)
        metadata = os.fstat(descriptor)
        after_open = _portable_path_metadata(
            root,
            relative,
            display_path=display_path,
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != (before.st_dev, before.st_ino)
            or (metadata.st_dev, metadata.st_ino)
            != (after_open.st_dev, after_open.st_ino)
        ):
            raise ContainedFileCaptureError(
                "Contained file identity changed while opening",
                code="contained_file_identity_changed",
                path=display_path,
            )
        body = _bounded_read(
            descriptor,
            max_bytes=max_bytes,
            path=display_path,
            read_probe=read_probe,
        )
        after_read = os.fstat(descriptor)
        after_path = _portable_path_metadata(
            root,
            relative,
            display_path=display_path,
        )
        if (
            not _same_file_snapshot(metadata, after_read)
            or not _same_file_snapshot(metadata, after_path)
            or len(body) != metadata.st_size
        ):
            raise ContainedFileCaptureError(
                "Contained file changed while being captured",
                code="contained_file_identity_changed",
                path=display_path,
            )
    except ContainedFileCaptureError:
        raise
    except OSError as exc:
        raise ContainedFileCaptureError(
            "Contained regular file could not be opened",
            code="contained_file_unreadable",
            path=display_path,
        ) from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
    return CapturedRegularFile(
        path=display_path,
        relative_path=relative.as_posix(),
        body=body,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _portable_path_metadata(
    root: Path,
    relative: PurePosixPath,
    *,
    display_path: Path,
) -> os.stat_result:
    current = root
    final_metadata: os.stat_result | None = None
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ContainedFileCaptureError(
                "Contained regular file could not be inspected",
                code="contained_file_unreadable",
                path=display_path,
            ) from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (attributes & reparse_flag):
            raise ContainedFileCaptureError(
                "Contained path must not traverse a link or reparse point",
                code="contained_file_link_rejected",
                path=display_path,
            )
        is_final = index == len(relative.parts) - 1
        if (is_final and not stat.S_ISREG(metadata.st_mode)) or (
            not is_final and not stat.S_ISDIR(metadata.st_mode)
        ):
            raise ContainedFileCaptureError(
                "Contained path is not a regular file below directories",
                code="contained_file_not_regular",
                path=display_path,
            )
        final_metadata = metadata
    assert final_metadata is not None
    return final_metadata


def _bounded_read(
    descriptor: int,
    *,
    max_bytes: int,
    path: Path,
    read_probe: Callable[[], None] | None,
) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        if read_probe is not None:
            read_probe()
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    if len(body) > max_bytes:
        raise ContainedFileCaptureError(
            "Contained regular file exceeds its byte limit",
            code="contained_file_too_large",
            path=path,
        )
    return body


def _same_file_snapshot(
    before: os.stat_result,
    after: os.stat_result,
) -> bool:
    return (
        stat.S_ISREG(before.st_mode)
        and stat.S_ISREG(after.st_mode)
        and before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


def _canonical_relative_path(value: str | PurePosixPath) -> PurePosixPath:
    if not isinstance(value, str | PurePosixPath):
        raise TypeError("Contained file path must be relative")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("Contained file path must be canonical and relative")
    return path


__all__ = [
    "CapturedRegularFile",
    "ContainedFileCaptureError",
    "capture_contained_regular_file",
]

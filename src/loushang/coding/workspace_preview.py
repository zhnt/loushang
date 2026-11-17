"""Read bounded current Workspace content through no-follow native handles."""

from __future__ import annotations

import errno
import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from loushang.apphost.managed.contracts import _invalid_windows_part
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appserver.protocol.workspace_preview import (
    MAX_PREVIEW_BYTES,
    MAX_PREVIEW_ENTRIES,
    MAX_PREVIEW_PATH,
    WorkspaceDirectoryPreviewV1,
    WorkspaceFilePreviewV1,
    WorkspacePreviewEntryV1,
    WorkspacePreviewV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_final_directory_path,
    windows_stat_at,
)

_WINDOWS = os.name == "nt"
_MAX_COMPONENTS = 128
_BINARY_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]")
_EntryKind = Literal["directory", "file"]


def _relative_parts(value: str) -> list[str]:
    path = value.replace("\\", "/")
    if path.startswith("/") or ":" in path:
        raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
    return path.split("/")


def _resolve_parts(base: str, reference: str) -> list[str]:
    parts: list[str] = []
    for part in (*_relative_parts(base), *_relative_parts(reference)):
        if part == "..":
            if not parts:
                raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
            parts.pop()
        elif part and part != ".":
            parts.append(part)
    if _WINDOWS and any(_invalid_windows_part(part) for part in parts):
        raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
    if len(parts) > _MAX_COMPONENTS or len("/".join(parts)) > MAX_PREVIEW_PATH:
        raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
    return parts


def _open_directory(name: str, parent: int | None = None) -> int:
    if _WINDOWS:
        return open_windows_directory(name, dir_fd=parent, writable=False)
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _open_workspace(root: Path, handles: ExitStack) -> int:
    current = _open_directory(root.anchor)
    handles.callback(os.close, current)
    for part in root.parts[1:]:
        current = _checked_directory(current, part, handles)
    return current


def _metadata(parent: int, name: str) -> os.stat_result:
    if _WINDOWS:
        return windows_stat_at(parent, name)
    return os.stat(name, dir_fd=parent, follow_symlinks=False)


def _kind(metadata: os.stat_result) -> _EntryKind | None:
    if getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return None
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    return None


def _checked_directory(parent: int, name: str, handles: ExitStack) -> int:
    if _kind(_metadata(parent, name)) != "directory":
        raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
    opened = _open_directory(name, parent)
    handles.callback(os.close, opened)
    return opened


def _open_file(parent: int, name: str) -> int:
    if _WINDOWS:
        return open_windows_regular_file_at(parent, name, create_new=False, write=False)
    return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)


def _read_file(parent: int, name: str, path: str) -> WorkspaceFilePreviewV1:
    with os.fdopen(_open_file(parent, name), "rb") as stream:
        info = os.fstat(stream.fileno())
        if _kind(info) != "file":
            raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
        if info.st_size > MAX_PREVIEW_BYTES:
            raise AppServiceError(AppErrorCodeV1.WORKSPACE_PREVIEW_TOO_LARGE)
        data = stream.read(MAX_PREVIEW_BYTES + 1)
    if len(data) > MAX_PREVIEW_BYTES:
        raise AppServiceError(AppErrorCodeV1.WORKSPACE_PREVIEW_TOO_LARGE)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppServiceError(AppErrorCodeV1.WORKSPACE_PREVIEW_BINARY) from None
    if _BINARY_CONTROLS.search(text):
        raise AppServiceError(AppErrorCodeV1.WORKSPACE_PREVIEW_BINARY)
    return WorkspaceFilePreviewV1(path, text)


def _read_directory(descriptor: int, path: str) -> WorkspaceDirectoryPreviewV1:
    entries: list[WorkspacePreviewEntryV1] = []
    with os.scandir(windows_final_directory_path(descriptor) if _WINDOWS else descriptor) as scan:
        for index, entry in enumerate(scan):
            if index == MAX_PREVIEW_ENTRIES:
                return _directory_result(path, entries, limited=True)
            try:
                kind = _kind(_metadata(descriptor, entry.name))
                if kind:
                    entries.append(WorkspacePreviewEntryV1(entry.name, kind))
            except (OSError, ValueError):
                continue
    return _directory_result(path, entries, limited=False)


def _directory_result(
    path: str, entries: list[WorkspacePreviewEntryV1], *, limited: bool,
) -> WorkspaceDirectoryPreviewV1:
    ordered = sorted(entries, key=lambda item: (item.kind, item.name.casefold(), item.name))
    return WorkspaceDirectoryPreviewV1(path, tuple(ordered), limited)


def read_workspace_preview(root: Path, reference: str, base: str) -> WorkspacePreviewV1:
    parts = _resolve_parts(base, reference)
    path = "/".join(parts) or "."
    try:
        with ExitStack() as handles:
            parent = _open_workspace(root, handles)
            if not parts:
                return _read_directory(parent, path)
            for part in parts[:-1]:
                parent = _checked_directory(parent, part, handles)
            name = parts[-1]
            kind = _kind(_metadata(parent, name))
            if kind == "file":
                if reference.endswith(("/", "\\")):
                    raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
                return _read_file(parent, name, path)
            if kind == "directory":
                return _read_directory(_checked_directory(parent, name, handles), path)
    except FileNotFoundError:
        raise AppServiceError(AppErrorCodeV1.NOT_FOUND) from None
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EPERM, errno.ELOOP, errno.ENOTDIR}:
            raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED) from None
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
    raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)

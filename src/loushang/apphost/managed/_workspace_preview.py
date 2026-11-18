"""Read bounded current Workspace content through no-follow native handles."""

from __future__ import annotations

import errno
import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from loushang.apphost.workspace_registry import (
    WorkspaceDirectoryRead,
    WorkspaceFileRead,
    WorkspacePreviewError,
)

from ._files import PrivateManagedDirectory
from .contracts import _invalid_windows_part

_MAX_BYTES = 128 * 1024
_MAX_ENTRIES = 128
_MAX_PATH = 4096
_ENTRY_NAME = re.compile(r"[^/\\:\x00-\x1f\x7f-\x9f\ud800-\udfff]{1,255}\Z")
_WINDOWS = os.name == "nt"
_MAX_COMPONENTS = 128
_BINARY_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]")
_EntryKind = Literal["directory", "file"]
_READ_ERRORS: dict[int | None, str] = {
    errno.ENOENT: "not_found",
    errno.EACCES: "permission_denied",
    errno.EPERM: "permission_denied",
    errno.ELOOP: "permission_denied",
    errno.ENOTDIR: "permission_denied",
}


def _relative_parts(value: str) -> list[str]:
    path = value.replace("\\", "/")
    if path.startswith("/") or ":" in path:
        raise WorkspacePreviewError("permission_denied")
    return [part for part in path.split("/") if part not in {"", "."}]


def _resolve_parts(base: str, reference: str) -> list[str]:
    parts: list[str] = []
    for part in (*_relative_parts(base), *_relative_parts(reference)):
        if part == "..":
            if not parts:
                raise WorkspacePreviewError("permission_denied")
            parts.pop()
        else:
            parts.append(part)
    if _WINDOWS and any(_invalid_windows_part(part) for part in parts):
        raise WorkspacePreviewError("permission_denied")
    if len(parts) > _MAX_COMPONENTS or len("/".join(parts)) > _MAX_PATH:
        raise WorkspacePreviewError("invalid_request")
    return parts


def _open_workspace(root: Path, handles: ExitStack) -> int:
    current = PrivateManagedDirectory._open_directory(root.anchor)
    handles.callback(os.close, current)
    for part in root.parts[1:]:
        current = _checked_directory(current, part, handles)
    return current


def _kind(metadata: os.stat_result) -> _EntryKind | None:
    if getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return None
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    return None


def _checked_directory(parent: int, name: str, handles: ExitStack) -> int:
    if _kind(PrivateManagedDirectory._stat(parent, name)) != "directory":
        raise WorkspacePreviewError("permission_denied")
    opened = PrivateManagedDirectory._open_directory(name, parent)
    handles.callback(os.close, opened)
    return opened


def _read_file(parent: int, name: str, path: str) -> WorkspaceFileRead:
    with os.fdopen(PrivateManagedDirectory._open_file(parent, name, os.O_RDONLY), "rb") as stream:
        info = os.fstat(stream.fileno())
        if _kind(info) != "file":
            raise WorkspacePreviewError("permission_denied")
        if info.st_size > _MAX_BYTES:
            raise WorkspacePreviewError("workspace_preview_too_large")
        data = stream.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise WorkspacePreviewError("workspace_preview_too_large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise WorkspacePreviewError("workspace_preview_binary") from None
    if _BINARY_CONTROLS.search(text):
        raise WorkspacePreviewError("workspace_preview_binary")
    return WorkspaceFileRead(path, text)


def _read_directory(descriptor: int, path: str) -> WorkspaceDirectoryRead:
    entries: list[tuple[str, _EntryKind]] = []
    limited = False
    with PrivateManagedDirectory._scan_entries(descriptor) as scan:
        for index, entry in enumerate(scan):
            if index == _MAX_ENTRIES:
                limited = True
                break
            if _ENTRY_NAME.fullmatch(entry.name) is None:
                continue
            try:
                kind = _kind(PrivateManagedDirectory._stat(descriptor, entry.name))
            except OSError:
                continue
            if kind:
                entries.append((entry.name, kind))
    entries.sort(key=lambda item: (item[1], item[0].casefold(), item[0]))
    return WorkspaceDirectoryRead(path, tuple(entries), limited)


def read_workspace_preview(root: Path, reference: str, base: str) -> WorkspaceFileRead | WorkspaceDirectoryRead:
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
            kind = _kind(PrivateManagedDirectory._stat(parent, name))
            if kind == "file":
                if reference.endswith(("/", "\\")):
                    raise WorkspacePreviewError("not_found")
                return _read_file(parent, name, path)
            if kind == "directory":
                return _read_directory(_checked_directory(parent, name, handles), path)
    except OSError as exc:
        code = _READ_ERRORS.get(exc.errno, "operation_unavailable")
        raise WorkspacePreviewError(code) from None
    raise WorkspacePreviewError("permission_denied")

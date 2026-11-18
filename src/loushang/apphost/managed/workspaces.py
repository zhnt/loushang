"""Host-owned workspace membership; no Product, Session or process construction."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from secrets import token_hex
from time import monotonic

from loushang.apphost.workspace_registry import (
    WorkspaceDirectoryRead,
    WorkspaceFileRead,
    WorkspaceRegistrationError,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
)

from ._files import ManagedStorageError, PrivateManagedDirectory
from ._workspace_preview import read_workspace_preview
from .contracts import _invalid_windows_part


def _absolute_workspace_path(value: str) -> Path:
    if type(value) is not str or not value or "\0" in value:
        raise ValueError("invalid_workspace")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("workspace_requires_absolute_path")
    return path


def canonical_workspace(value: str) -> Path:
    """Interpret a client path on the Host, without changing process cwd."""
    path = _absolute_workspace_path(value).resolve(strict=True)
    if not path.is_dir():
        raise ValueError("workspace_requires_directory")
    return path


def _creation_path(value: str) -> Path:
    path = _absolute_workspace_path(value)
    if not path.name or ".." in path.parts:
        raise ValueError("invalid_workspace")
    if os.name == "nt":
        if len(path.drive) != 2 or any(_invalid_windows_part(part) for part in path.parts[1:]):
            raise ValueError("invalid_workspace")
    elif path.anchor != "/":
        raise ValueError("invalid_workspace")
    return path


def _open_directory(path: str, parent: int | None = None) -> int:
    if os.name == "nt":
        return open_windows_directory(path, dir_fd=parent, writable=False)
    flags = os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_PATH", os.O_RDONLY)
    return os.open(path, flags, dir_fd=parent)


def _open_parent(path: Path, handles: ExitStack) -> int:
    parent = _open_directory(path.anchor)
    handles.callback(os.close, parent)
    for part in path.parts[1:-1]:
        parent = _open_directory(part, parent)
        handles.callback(os.close, parent)
    return parent


class WorkspaceRegistry:
    """A retained private store of paths; callers settle Sessions before removal.

    Native operations run off the application event loop. Existing directory
    admission, atomic publication and file locking provide the single writer;
    no process-global selected workspace or Runtime cache lives here.
    """

    def __init__(self, root: Path):
        self._temporary_root = root / "temporary"
        self._directory = PrivateManagedDirectory(
            root, create=True, create_parents=True, defer_open=True,
        )

    def open(self) -> None:
        self._directory.open()

    def close(self) -> None:
        self._directory.close()

    def list(self) -> tuple[Path, ...]:
        with self._directory.lock("workspaces.lock", create=True,
                                  deadline=monotonic() + 10, wait_for_lock=True):
            _, paths = self._read()
            return tuple(Path(path) for path in paths)

    def create(self, value: str) -> Path:
        path = _creation_path(value)
        if self.is_temporary(path):
            raise ValueError("temporary_workspace_reserved")
        with ExitStack() as handles:
            parent = _open_parent(path, handles)
            if os.name == "nt":
                leaf = open_windows_directory(path.name, dir_fd=parent, create_new=True)
                handles.callback(os.close, leaf)
            else:
                os.mkdir(path.name, dir_fd=parent)
                leaf = None
            try:
                if leaf is None:
                    leaf = _open_directory(path.name, parent)
                    handles.callback(os.close, leaf)
                return self.register(str(path), _created_fd=leaf)
            except (OSError, RuntimeError, ValueError) as exc:
                # Publication can have completed before reporting an error.
                raise WorkspaceRegistrationError("workspace_registration_failed") from exc

    def register(self, value: str, *, _created_fd: int | None = None) -> Path:
        path = canonical_workspace(value)
        if _created_fd is not None and (
            path != Path(value) or not os.path.samestat(path.lstat(), os.fstat(_created_fd))
        ):
            raise ValueError("workspace_changed_during_creation")
        if self.is_temporary(path):
            raise ValueError("temporary_workspace_reserved")
        self._update(str(path), remove=False)
        return path

    def is_temporary(self, path: Path) -> bool:
        return path.is_relative_to(self._temporary_root)

    def allocate_temporary(self) -> Path:
        with self._directory.lock("workspaces.lock", create=True,
                                  deadline=monotonic() + 10, wait_for_lock=True):
            previous, paths = self._read()
            if len(paths) >= 128:
                raise ValueError("workspace_limit")
            path = self._temporary_root / token_hex(16)
            directory = PrivateManagedDirectory(
                path, create=True, create_parents=True, exclusive_create=True,
            )
            directory.close()
            updated = sorted([*paths, str(path)])
            # A failed publication can already have replaced the registry.
            # Keep the directory in that case so the admitted path stays valid.
            self._directory.write("workspaces.json", json.dumps(updated).encode(), expected=previous)
        return path

    def unregister(self, value: str) -> None:
        # A deleted workspace must still be unregisterable. No filesystem
        # removal is performed, and the caller supplies the registered path.
        self._update(value, remove=True)

    def select(self, value: str) -> Path:
        path = canonical_workspace(value)
        if path not in self.list():
            raise ValueError("workspace_not_registered")
        return path

    def preview(self, root: Path, reference: str, base: str) -> WorkspaceFileRead | WorkspaceDirectoryRead:
        """Read beneath the selected canonical root after the caller checks its scope."""
        return read_workspace_preview(root, reference, base)

    def _read(self):
        snapshot = self._directory.read("workspaces.json")
        if snapshot is None:
            return None, []
        paths = json.loads(snapshot.content)
        if (type(paths) is not list or len(paths) > 128
                or any(type(p) is not str or not Path(p).is_absolute() for p in paths)
                or paths != sorted(set(paths))):
            raise ManagedStorageError("invalid_record")
        return snapshot, paths

    def _update(self, path: str, *, remove: bool) -> None:
        with self._directory.lock("workspaces.lock", create=True,
                                  deadline=monotonic() + 10, wait_for_lock=True):
            previous, paths = self._read()
            updated = sorted(set(paths) - {path} if remove else set(paths) | {path})
            if len(updated) > 128:
                raise ValueError("workspace_limit")
            if updated != paths:
                self._directory.write("workspaces.json", json.dumps(updated).encode(), expected=previous)

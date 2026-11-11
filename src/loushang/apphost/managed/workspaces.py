"""Host-owned workspace membership; no Product, Session or process construction."""

from __future__ import annotations

import json
from pathlib import Path
from secrets import token_hex
from time import monotonic

from ._files import ManagedStorageError, PrivateManagedDirectory


def canonical_workspace(value: str) -> Path:
    """Interpret a client path on the Host, without changing process cwd."""
    if type(value) is not str or not value or "\0" in value:
        raise ValueError("invalid_workspace")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("workspace_requires_absolute_path")
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError("workspace_requires_directory")
    return path


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

    def register(self, value: str) -> Path:
        path = canonical_workspace(value)
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

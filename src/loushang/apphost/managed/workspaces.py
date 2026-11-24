"""Host-owned workspace membership; no Product, Session or process construction."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from secrets import token_hex
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from loushang.apphost.workspace_registry import (
    Workspace,
    WorkspaceDirectoryRead,
    WorkspaceFileRead,
    WorkspacePath,
    WorkspaceRegistrationError,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
)

from ._files import ManagedStorageError, PrivateManagedDirectory
from ._workspace_preview import read_workspace_preview
from .contracts import _invalid_windows_part

_DEFAULT_WORKSPACE = Workspace("default", "Chats", default=True)
_MAX_WORKSPACES = 128
_MAX_PATHS = 16


def _title(value: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid_workspace_name")
    return value.strip()


def _identifier(value: str) -> str:
    if type(value) is not str or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid_workspace_id")
    return value


def _legacy_id(path: Path, kind: str) -> str:
    return uuid5(NAMESPACE_URL, f"loushang:{kind}:{path}").hex


def _legacy_workspace(path: Path) -> Workspace:
    link = WorkspacePath(_legacy_id(path, "path"), "main", path)
    return Workspace(_legacy_id(path, "workspace"), path.name or str(path),
                     paths=(link,), default_path_id=link.id, legacy_origins=(path,))


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
        self._session_context = root / "session-context"
        self._workspaces: tuple[Workspace, ...] = ()
        self._directory = PrivateManagedDirectory(
            root, create=True, create_parents=True, defer_open=True, maximum_record_bytes=256 * 1024,
        )

    def open(self) -> None:
        self._directory.open()

    def close(self) -> None:
        self._workspaces = ()
        self._directory.close()

    def list(self) -> tuple[Path, ...]:
        with self._directory.lock("workspaces.lock", create=True,
                                  deadline=monotonic() + 10, wait_for_lock=True):
            _, workspaces = self._read()
            return tuple(sorted(origin for item in workspaces for origin in item.legacy_origins))

    def session_context(self, workspace_id: str) -> Path:
        name = workspace_id if workspace_id == _DEFAULT_WORKSPACE.id else _identifier(workspace_id)
        path = self._session_context / name
        directory = PrivateManagedDirectory(path, create=True, create_parents=True)
        directory.close()
        return path

    def _lock(self):
        return self._directory.lock("workspaces.lock", create=True, deadline=monotonic() + 10, wait_for_lock=True)

    def workspaces(self) -> tuple[Workspace, ...]:
        with self._lock():
            _, workspaces = self._read()
            self._workspaces = workspaces
            return workspaces

    def execution_workspace(self, workspace_id: str) -> Workspace | None:
        # All cooperating edits publish under the same retained Host owner.
        # Execution must never acquire a blocking storage lock on the event loop.
        return next((item for item in self._workspaces if item.id == workspace_id), None)

    def workspace(self, workspace_id: str) -> Workspace:
        for item in self.workspaces():
            if item.id == workspace_id:
                return item
        raise ValueError("workspace_not_registered")

    def default_workspace(self) -> Workspace:
        return self.workspace(_DEFAULT_WORKSPACE.id)

    def _change(self, edit: Callable[[tuple[Workspace, ...]], tuple[Workspace, ...]]) -> None:
        with self._lock():
            previous, records = self._read()
            updated = edit(records)
            if updated == records:
                self._workspaces = records
                return
            self._validate(updated)
            rows = [{
                "id": item.id, "name": item.name, "defaultPathId": item.default_path_id,
                "paths": [{"id": link.id, "alias": link.alias, "path": str(link.path)} for link in item.paths],
                "legacyOrigins": [str(path) for path in item.legacy_origins],
            } for item in updated]
            payload = json.dumps({"version": 2, "workspaces": rows}, ensure_ascii=False, separators=(",", ":")).encode()
            if len(payload) > 256 * 1024:
                raise ValueError("workspace_limit")
            # An uncertain write may have replaced the old record. Fence its
            # execution paths until a fresh confirmed read restores authority.
            self._workspaces = ()
            self._directory.write("workspaces.json", payload, expected=previous)
            self._workspaces = updated

    def _edit_workspace(self, workspace_id: str, edit: Callable[[Workspace], Workspace | None]) -> None:
        def update(records: tuple[Workspace, ...]) -> tuple[Workspace, ...]:
            for index, item in enumerate(records):
                if item.id == workspace_id:
                    replacement = edit(item)
                    return records[:index] + ((replacement,) if replacement else ()) + records[index + 1:]
            raise ValueError("workspace_not_registered")

        self._change(update)

    def create_workspace(self, name: str, *, path: str | None = None, alias: str | None = None) -> Workspace:
        if (path is None) != (alias is None):
            raise ValueError("workspace_path_requires_alias")
        link = self._path(token_hex(16), alias, path) if path is not None and alias is not None else None
        workspace = Workspace(
            token_hex(16), _title(name), paths=(link,) if link is not None else (),
            default_path_id=link.id if link is not None else None,
        )
        self._change(lambda records: (*records, workspace))
        return workspace

    def rename_workspace(self, workspace_id: str, name: str) -> None:
        self._edit_workspace(workspace_id, lambda item: replace(item, name=_title(name)))

    def delete_workspace(self, workspace_id: str, *, history_deleted: bool = False) -> None:
        def remove(item: Workspace) -> None:
            if item.default:
                raise ValueError("default_workspace_reserved")
            if item.legacy_origins and not history_deleted:
                # Its sources can hold detached history as well as Mux members.
                raise ValueError("workspace_has_history")

        self._edit_workspace(workspace_id, remove)

    def add_path(self, workspace_id: str, alias: str, value: str) -> WorkspacePath:
        link = self._path(token_hex(16), alias, value)
        self._edit_workspace(workspace_id, lambda item: replace(item, paths=(*item.paths, link)))
        return link

    def update_path(self, workspace_id: str, path_id: str, alias: str, value: str) -> WorkspacePath:
        link = self._path(path_id, alias, value)
        self._edit_workspace(workspace_id, lambda item: self._replace_path(item, path_id, link))
        return link

    def remove_path(self, workspace_id: str, path_id: str) -> None:
        self._edit_workspace(workspace_id, lambda item: self._replace_path(item, path_id, None))

    def set_default_path(self, workspace_id: str, path_id: str | None) -> None:
        self._edit_workspace(workspace_id, lambda item: replace(item, default_path_id=path_id))

    @staticmethod
    def _replace_path(item: Workspace, path_id: str, link: WorkspacePath | None) -> Workspace:
        for index, previous in enumerate(item.paths):
            if previous.id == path_id:
                paths = item.paths[:index] + ((link,) if link else ()) + item.paths[index + 1:]
                default_path_id = None if link is None and item.default_path_id == path_id else item.default_path_id
                return replace(item, paths=paths, default_path_id=default_path_id)
        raise ValueError("workspace_path_not_found")

    def _path(self, path_id: str, alias: str, value: str) -> WorkspacePath:
        link = WorkspacePath(_identifier(path_id), _title(alias), _creation_path(value))
        if self.is_temporary(link.path) or link.path.is_relative_to(self._session_context.parent):
            raise ValueError("temporary_workspace_reserved")
        if (status := self.path_status(link)) != "available":
            raise ValueError(f"workspace_path_{status}")
        return link

    def path_status(self, link: WorkspacePath) -> str:
        return self._observe_path(link)[0]

    def path_identity(self, link: WorkspacePath) -> tuple[int, int] | None:
        return self._observe_path(link)[1]

    @staticmethod
    def _observe_path(link: WorkspacePath) -> tuple[str, tuple[int, int] | None]:
        try:
            if link.path != link.path.resolve(strict=True):
                return "unsafe", None
            if not link.path.is_dir():
                return "not_directory", None
            with ExitStack() as handles:
                parent = _open_parent(link.path, handles)
                leaf = _open_directory(link.path.name, parent)
                handles.callback(os.close, leaf)
                stat = os.fstat(leaf)
                return "available", (stat.st_dev, stat.st_ino)
        except FileNotFoundError:
            return "missing", None
        except PermissionError:
            return "permission_denied", None
        except (OSError, RuntimeError):
            return "unsafe", None

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

    def unregister(self, value: str) -> None:
        # A deleted workspace must still be unregisterable. No filesystem
        # removal is performed, and the caller supplies the registered path.
        self._update(value, remove=True)

    def select(self, value: str) -> Path:
        path = canonical_workspace(value)
        records = self.workspaces()
        if not any(path == link.path for item in records for link in item.paths) and not any(
            item.default and path in item.legacy_origins for item in records
        ):
            raise ValueError("workspace_not_registered")
        return path

    def preview(self, root: Path, reference: str, base: str) -> WorkspaceFileRead | WorkspaceDirectoryRead:
        """Read beneath the selected canonical root after the caller checks its scope."""
        return read_workspace_preview(root, reference, base)

    def _read(self):
        snapshot = self._directory.read("workspaces.json")
        if snapshot is None:
            return None, (_DEFAULT_WORKSPACE,)
        try:
            raw = json.loads(snapshot.content)
            if type(raw) is list:
                if any(type(value) is not str for value in raw) or raw != sorted(set(raw)):
                    raise ValueError("invalid legacy workspaces")
                origins = tuple(_absolute_workspace_path(value) for value in raw)
                default = replace(_DEFAULT_WORKSPACE, legacy_origins=tuple(path for path in origins if self.is_temporary(path)))
                records = (default, *(_legacy_workspace(path) for path in origins if not self.is_temporary(path)))
            else:
                if type(raw) is not dict or set(raw) != {"version", "workspaces"} or raw["version"] != 2:
                    raise ValueError("invalid workspace version")
                records = tuple(self._decode(row) for row in raw["workspaces"])
            self._validate(records)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ManagedStorageError("invalid_record") from exc
        return snapshot, records

    @staticmethod
    def _decode(row) -> Workspace:
        if type(row) is not dict or set(row) != {"id", "name", "paths", "defaultPathId", "legacyOrigins"}:
            raise ValueError("invalid workspace record")
        if type(row["paths"]) is not list or type(row["legacyOrigins"]) is not list:
            raise ValueError("invalid workspace paths")
        paths = []
        for item in row["paths"]:
            if type(item) is not dict or set(item) != {"id", "alias", "path"}:
                raise ValueError("invalid workspace path")
            paths.append(WorkspacePath(_identifier(item["id"]), _title(item["alias"]), _absolute_workspace_path(item["path"])))
        is_default = row["id"] == _DEFAULT_WORKSPACE.id
        return Workspace(
            _DEFAULT_WORKSPACE.id if is_default else _identifier(row["id"]), _title(row["name"]),
            tuple(paths), row["defaultPathId"],
            tuple(_absolute_workspace_path(value) for value in row["legacyOrigins"]), is_default,
        )

    def _validate(self, records: tuple[Workspace, ...]) -> None:
        origins = tuple(path for item in records for path in item.legacy_origins)
        if (len(records) > _MAX_WORKSPACES + 1 or len(origins) > _MAX_WORKSPACES
            or len(set(origins)) != len(origins) or not records or not records[0].default
            or len({item.id for item in records}) != len(records)):
            raise ValueError("invalid workspace membership")
        for item in records:
            links = item.paths
            if (len(links) > _MAX_PATHS or len({link.id for link in links}) != len(links)
                or len({link.alias.casefold() for link in links}) != len(links)
                or len({link.path for link in links}) != len(links)
                or item.default_path_id not in {None, *(link.id for link in links)}
                or any(self.is_temporary(origin) != item.default for origin in item.legacy_origins)
                or (item.default and links)):
                raise ValueError("invalid workspace path associations")

    def _update(self, path: str, *, remove: bool) -> None:
        origin = Path(path)

        def update(records: tuple[Workspace, ...]) -> tuple[Workspace, ...]:
            for index, item in enumerate(records):
                if origin in item.legacy_origins:
                    if not remove:
                        return records
                    if not item.default:
                        return records[:index] + records[index + 1:]
                    default = replace(item, legacy_origins=tuple(p for p in item.legacy_origins if p != origin))
                    return (default, *records[1:])
            if remove:
                return records
            if self.is_temporary(origin):
                default = replace(records[0], legacy_origins=(*records[0].legacy_origins, origin))
                return (default, *records[1:])
            return (*records, _legacy_workspace(origin))

        self._change(update)

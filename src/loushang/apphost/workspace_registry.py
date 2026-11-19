"""Host-owned workspace membership used by Product session catalogs."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol


class WorkspaceRegistrationError(RuntimeError):
    """The new directory exists, but its membership could not be confirmed."""


class WorkspacePreviewError(RuntimeError):
    """Client-safe failure from a bounded Workspace read."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class WorkspaceFileRead:
    path: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class WorkspaceDirectoryRead:
    path: str
    entries: tuple[tuple[str, Literal["directory", "file"]], ...]
    limited: bool


@dataclass(frozen=True, slots=True)
class WorkspacePath:
    id: str
    alias: str
    path: Path


@dataclass(frozen=True, slots=True)
class Workspace:
    id: str
    name: str
    paths: tuple[WorkspacePath, ...] = ()
    default_path_id: str | None = None
    legacy_origins: tuple[Path, ...] = ()
    default: bool = False

    @property
    def default_path(self) -> WorkspacePath | None:
        return next((item for item in self.paths if item.id == self.default_path_id), None)


class HostWorkspaceRegistryPort(Protocol):
    """The blocking registry operations used by a workspace catalog."""

    def open(self) -> None: ...
    def close(self) -> None: ...
    def list(self) -> tuple[Path, ...]: ...
    def create(self, value: str) -> Path: ...
    def register(self, value: str) -> Path: ...
    def unregister(self, value: str) -> None: ...
    def select(self, value: str) -> Path: ...
    def is_temporary(self, path: Path) -> bool: ...

    def workspaces(self) -> tuple[Workspace, ...]: ...
    def execution_workspace(self, workspace_id: str) -> Workspace | None: ...
    def workspace(self, workspace_id: str) -> Workspace: ...
    def default_workspace(self) -> Workspace: ...
    def create_workspace(self, name: str, *, path: str | None = None, alias: str | None = None) -> Workspace: ...
    def rename_workspace(self, workspace_id: str, name: str) -> None: ...
    def delete_workspace(self, workspace_id: str) -> None: ...
    def add_path(self, workspace_id: str, alias: str, value: str) -> WorkspacePath: ...
    def update_path(self, workspace_id: str, path_id: str, alias: str, value: str) -> WorkspacePath: ...
    def remove_path(self, workspace_id: str, path_id: str) -> None: ...
    def set_default_path(self, workspace_id: str, path_id: str | None) -> None: ...
    def path_status(self, link: WorkspacePath) -> str: ...
    def path_identity(self, link: WorkspacePath) -> tuple[int, int] | None: ...
    def session_context(self, workspace_id: str) -> Path: ...

    def preview(self, root: Path, reference: str, base: str) -> WorkspaceFileRead | WorkspaceDirectoryRead: ...

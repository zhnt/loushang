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


class HostWorkspaceRegistryPort(Protocol):
    """The blocking registry operations used by a workspace catalog."""

    def open(self) -> None: ...
    def close(self) -> None: ...
    def list(self) -> tuple[Path, ...]: ...
    def create(self, value: str) -> Path: ...
    def register(self, value: str) -> Path: ...
    def unregister(self, value: str) -> None: ...
    def select(self, value: str) -> Path: ...
    def allocate_temporary(self) -> Path: ...
    def is_temporary(self, path: Path) -> bool: ...

    def preview(self, root: Path, reference: str, base: str) -> WorkspaceFileRead | WorkspaceDirectoryRead: ...

"""Coding Runtime selection for an AppHost-owned logical Workspace."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodingHostedWorkspace:
    cwd: Path
    anchor: Path
    legacy_plugin_origin: Path | None
    project_cwd: Path | None
    roots: tuple[Path, ...]
    private_roots: tuple[Path, ...]
    current_roots: Callable[[], tuple[Path, ...]]
    current_default: Callable[[], Path | None]

    def available_cwd(self) -> Path:
        return self.current_default() or self.anchor

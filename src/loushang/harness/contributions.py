from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loushang.harness.diagnostics.types import DiagnosticDraft

ExtensionSurfaceType = Literal[
    "command",
    "tool",
    "prompt",
    "skill",
    "hook",
    "model_provider",
    "ui",
    "autocomplete",
    "resource_root",
    "policy",
    "approval",
    "runtime_capability",
]


@dataclass(frozen=True)
class ExtensionSurfaceDescriptor:
    type: ExtensionSurfaceType
    name: str
    extension_id: str
    source_path: Path
    active: bool = True
    priority: int = 0
    permission_requirements: tuple[str, ...] = ()
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    after: tuple[str, ...] = ()
    before: tuple[str, ...] = ()
    on_error: Literal["skip", "fail_chain"] = "skip"


class DuplicateExtensionSurfaceKeyError(KeyError):
    def __init__(
        self, surface_type: str, name: str, surfaces: list[ExtensionSurfaceDescriptor]
    ) -> None:
        super().__init__(f"Duplicate extension surface key: {surface_type}:{name}")
        self.surface_type = surface_type
        self.contribution_type = surface_type
        self.name = name
        self.surfaces = list(surfaces)
        self.contributions = list(surfaces)


@dataclass
class ExtensionInventory:
    _surfaces: list[ExtensionSurfaceDescriptor] = field(default_factory=list)
    _by_type: dict[str, list[ExtensionSurfaceDescriptor]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _by_extension: dict[str, list[ExtensionSurfaceDescriptor]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _by_key: dict[tuple[str, str], list[ExtensionSurfaceDescriptor]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @classmethod
    def from_extensions(cls, extensions: Iterable[object]) -> ExtensionInventory:
        inventory = cls()
        for extension in extensions:
            for surface in getattr(
                extension, "surfaces", getattr(extension, "contributions", ())
            ):
                inventory.add(surface)
        return inventory

    def add(self, surface: ExtensionSurfaceDescriptor) -> None:
        self._surfaces.append(surface)
        self._by_type[surface.type].append(surface)
        self._by_extension[surface.extension_id].append(surface)
        self._by_key[(surface.type, surface.name)].append(surface)

    def all(self) -> list[ExtensionSurfaceDescriptor]:
        return list(self._surfaces)

    def by_type(self, surface_type: str) -> list[ExtensionSurfaceDescriptor]:
        return list(self._by_type.get(surface_type, ()))

    def by_extension(self, extension_id: str) -> list[ExtensionSurfaceDescriptor]:
        return list(self._by_extension.get(extension_id, ()))

    def by_key(self, surface_type: str, name: str) -> list[ExtensionSurfaceDescriptor]:
        return list(self._by_key.get((surface_type, name), ()))

    def get(self, surface_type: str, name: str) -> ExtensionSurfaceDescriptor:
        surfaces = self._by_key[(surface_type, name)]
        if len(surfaces) > 1:
            raise DuplicateExtensionSurfaceKeyError(surface_type, name, surfaces)
        return surfaces[0]


ContributionType = ExtensionSurfaceType
ContributionDescriptor = ExtensionSurfaceDescriptor
DuplicateContributionKeyError = DuplicateExtensionSurfaceKeyError
ContributionRegistry = ExtensionInventory

__all__ = [
    "ContributionDescriptor",
    "ContributionRegistry",
    "ContributionType",
    "DuplicateContributionKeyError",
    "DuplicateExtensionSurfaceKeyError",
    "ExtensionInventory",
    "ExtensionSurfaceDescriptor",
    "ExtensionSurfaceType",
]

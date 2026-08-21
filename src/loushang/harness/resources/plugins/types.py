from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class PluginManifest:
    name: str
    root: Path
    version: str | None = None
    enabled: bool = True
    package_root: Path | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class PluginSource:
    path: Path | None = None
    url: str | None = None
    kind: Literal["local", "remote"] = "local"
    enabled: bool = True


@dataclass(frozen=True)
class ResolvedPluginPackage:
    """Canonical inert descriptor produced by the one Plugin manifest parser."""

    root: Path
    package_root: Path
    manifest: PluginManifest
    source: PluginSource
    manifest_path: Path | None = None
    manifest_digest: str | None = None


@dataclass(frozen=True)
class InstalledPlugin:
    manifest: PluginManifest
    source: PluginSource
    enabled: bool = True
    resolved_package: ResolvedPluginPackage | None = None


@dataclass(frozen=True)
class PluginResolvedResources:
    plugin: InstalledPlugin
    package_roots: tuple[Path, ...]

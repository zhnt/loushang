from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle

PluginRevisionKind = Literal[
    "git_commit",
    "python_version",
    "manifest_sha256",
    "content_sha256",
]


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
    content_digest: str | None = None
    package_root_relative: Path = Path(".")
    root_identity: tuple[int, int] | None = None
    package_root_identity: tuple[int, int] | None = None
    revision_handle: VerifiedRevisionHandle | None = field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True)
class PluginSourceBinding:
    """Durable selection evidence for one configured Plugin source.

    The revision fields are audit evidence from materialization or the manifest;
    they do not represent a verified full-content handle or execution authority.
    """

    source: str
    source_identity: str
    source_kind: Literal["local", "remote"]
    plugin_id: str
    manifest_digest: str | None = None
    content_digest: str | None = None
    revision: str | None = None
    revision_kind: PluginRevisionKind | None = None


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
    revision_handle: VerifiedRevisionHandle | None = None

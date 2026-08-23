from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loushang.harness.resources.plugins.declarations import PluginContributionIndex

if TYPE_CHECKING:
    from loushang.harness.resources.plugins.dependencies import (
        PluginDependencyClosureLock,
    )
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
    """Canonical inert descriptor produced by the manifest parser."""

    root: Path
    package_root: Path
    manifest: PluginManifest
    source: PluginSource
    manifest_path: Path | None = None
    manifest_digest: str | None = None
    package_root_relative: Path = Path(".")
    root_identity: tuple[int, int] | None = None
    package_root_identity: tuple[int, int] | None = None
    contribution_index: PluginContributionIndex = field(
        default_factory=PluginContributionIndex
    )


@dataclass(frozen=True, kw_only=True)
class VerifiedPluginRevision(ResolvedPluginPackage):
    """Content-addressed revision leased by one verified live handle."""

    content_digest: str = field()
    revision_handle: VerifiedRevisionHandle = field(
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            self.revision_handle.root != self.root
            or self.revision_handle.content_digest != self.content_digest
            or self.manifest.root != self.root
            or self.package_root != self.root / self.package_root_relative
        ):
            raise ValueError("Verified Plugin revision evidence does not match")


@dataclass(frozen=True, kw_only=True)
class PublishedPluginPackage(VerifiedPluginRevision):
    """Runtime-admissible package with a complete dependency closure lock."""

    dependency_lock: PluginDependencyClosureLock = field()

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            self.dependency_lock is None
            or self.dependency_lock.package_content_digest != self.content_digest
        ):
            raise ValueError("Published Plugin dependency lock does not match")

    @classmethod
    def from_verified_revision(
        cls,
        revision: VerifiedPluginRevision,
        *,
        dependency_lock: PluginDependencyClosureLock,
    ) -> PublishedPluginPackage:
        return cls(
            root=revision.root,
            package_root=revision.package_root,
            manifest=revision.manifest,
            source=revision.source,
            manifest_path=revision.manifest_path,
            manifest_digest=revision.manifest_digest,
            package_root_relative=revision.package_root_relative,
            root_identity=revision.root_identity,
            package_root_identity=revision.package_root_identity,
            contribution_index=revision.contribution_index,
            content_digest=revision.content_digest,
            revision_handle=revision.revision_handle,
            dependency_lock=dependency_lock,
        )


@dataclass(frozen=True)
class PluginSourceBinding:
    """Durable selection evidence for one configured Plugin source.

    The revision and dependency fields are durable audit evidence. They do not
    replace the live verified handle or grant execution authority.
    """

    source: str
    source_identity: str
    source_kind: Literal["local", "remote"]
    plugin_id: str
    manifest_digest: str | None = None
    content_digest: str | None = None
    revision: str | None = None
    revision_kind: PluginRevisionKind | None = None
    dependency_lock: PluginDependencyClosureLock | None = None


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

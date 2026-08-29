"""Immutable legacy-discovery inputs for the private Catalog migration path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)

LegacyPackageResourceKind = Literal["extension", "prompt", "skill", "theme"]


@dataclass(frozen=True, slots=True)
class CatalogPluginPackageInput:
    """Published Plugin evidence bound to one discovery mount."""

    package: PublishedPluginPackage
    binding: PluginSourceBinding
    source_root_order: int

    def __post_init__(self) -> None:
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Catalog Plugin package input requires a published package")
        if not isinstance(self.binding, PluginSourceBinding):
            raise TypeError("Catalog Plugin package input requires a source binding")
        if self.binding.plugin_id != self.package.manifest.name:
            raise ValueError("Catalog Plugin package binding does not match its package")
        if (
            self.binding.content_digest != self.package.content_digest
            or self.binding.manifest_digest != self.package.manifest_digest
            or self.binding.dependency_lock != self.package.dependency_lock
        ):
            raise ValueError("Catalog Plugin package binding lineage is invalid")
        if (
            isinstance(self.source_root_order, bool)
            or not isinstance(self.source_root_order, int)
            or self.source_root_order < 0
        ):
            raise ValueError("Catalog Plugin package root order is invalid")


@dataclass(frozen=True, slots=True)
class LegacyPackageResourceCandidateFact:
    """One candidate already observed by the authoritative legacy discovery."""

    resource_kind: LegacyPackageResourceKind
    source_path: Path
    source_root_order: int
    package_content_digest: str | None

    def __post_init__(self) -> None:
        if self.resource_kind not in {"extension", "prompt", "skill", "theme"}:
            raise ValueError("Legacy package Resource candidate kind is invalid")
        if not isinstance(self.source_path, Path):
            raise TypeError("Legacy package Resource candidate path must be a Path")
        if isinstance(self.source_root_order, bool) or not isinstance(
            self.source_root_order,
            int,
        ):
            raise TypeError("Legacy package Resource root order must be an integer")
        if self.source_root_order < 0:
            raise ValueError("Legacy package Resource root order cannot be negative")
        digest = self.package_content_digest
        if digest is not None and (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("Legacy package Resource digest must be SHA-256")


@dataclass(frozen=True, slots=True)
class ResourceCatalogInputReceipt:
    """Exact normalized source facts consumed by an opt-in Product adapter.

    This is a transitional receipt, not a second discovery request.  The
    legacy loader creates it while building the one authoritative discovery
    result and permits one Product consumer to take it afterwards.
    """

    cwd: Path
    project_resource_root: Path
    project_context_roots: tuple[Path, ...]
    package_mounts: tuple[PackageResourceMount, ...]
    package_resource_candidates: tuple[LegacyPackageResourceCandidateFact, ...]
    package_diagnostic_codes: tuple[str, ...]
    user_resource_roots: tuple[Path, ...]
    explicit_user_resource_roots: frozenset[Path]
    additional_extension_paths: tuple[Path, ...]
    additional_skill_paths: tuple[Path, ...]
    additional_prompt_template_paths: tuple[Path, ...]
    additional_theme_paths: tuple[Path, ...]
    no_extensions: bool
    no_skills: bool
    no_prompt_templates: bool
    no_themes: bool
    no_context_files: bool
    built_in_resource_packages: tuple[str, ...]
    context_file_names: tuple[str, ...]
    catalog_plugin_package_inputs: tuple[CatalogPluginPackageInput, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.cwd, Path) or not isinstance(
            self.project_resource_root, Path
        ):
            raise TypeError("Resource Catalog receipt roots must be Paths")
        for name in (
            "project_context_roots",
            "user_resource_roots",
            "additional_extension_paths",
            "additional_skill_paths",
            "additional_prompt_template_paths",
            "additional_theme_paths",
        ):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, Path) for item in values):
                raise TypeError("Resource Catalog receipt paths must be Paths")
            object.__setattr__(self, name, values)
        package_mounts = tuple(self.package_mounts)
        if any(not isinstance(item, PackageResourceMount) for item in package_mounts):
            raise TypeError("Resource Catalog receipt package mounts are invalid")
        object.__setattr__(self, "package_mounts", package_mounts)
        package_candidates = tuple(self.package_resource_candidates)
        if any(
            not isinstance(item, LegacyPackageResourceCandidateFact)
            for item in package_candidates
        ):
            raise TypeError("Resource Catalog receipt package candidates are invalid")
        object.__setattr__(self, "package_resource_candidates", package_candidates)
        package_diagnostic_codes = tuple(self.package_diagnostic_codes)
        if any(
            not isinstance(item, str) or not item.strip()
            for item in package_diagnostic_codes
        ):
            raise ValueError("Resource Catalog package diagnostic codes are invalid")
        object.__setattr__(
            self,
            "package_diagnostic_codes",
            package_diagnostic_codes,
        )
        object.__setattr__(
            self,
            "explicit_user_resource_roots",
            frozenset(self.explicit_user_resource_roots),
        )
        plugin_inputs = tuple(self.catalog_plugin_package_inputs)
        if any(not isinstance(item, CatalogPluginPackageInput) for item in plugin_inputs):
            raise TypeError("Resource Catalog Plugin package inputs are invalid")
        if len({item.binding.plugin_id for item in plugin_inputs}) != len(plugin_inputs):
            raise ValueError("Resource Catalog Plugin package inputs must be unique")
        for item in plugin_inputs:
            if item.source_root_order >= len(package_mounts):
                raise ValueError("Resource Catalog Plugin package mount is missing")
            mount = package_mounts[item.source_root_order]
            package = item.package
            if (
                not mount.enabled
                or mount.revision_handle is not package.revision_handle
                or mount.content_digest != package.content_digest
                or mount.root != package.package_root
            ):
                raise ValueError(
                    "Resource Catalog Plugin package input does not match its mount"
                )
        object.__setattr__(self, "catalog_plugin_package_inputs", plugin_inputs)
        if any(
            not isinstance(item, Path) for item in self.explicit_user_resource_roots
        ):
            raise TypeError("Explicit Resource Catalog user roots must be Paths")
        object.__setattr__(
            self,
            "built_in_resource_packages",
            tuple(self.built_in_resource_packages),
        )
        object.__setattr__(self, "context_file_names", tuple(self.context_file_names))
        if not self.explicit_user_resource_roots.issubset(self.user_resource_roots):
            raise ValueError(
                "Explicit Resource Catalog user roots must belong to user roots"
            )
        if len(set(self.project_context_roots)) != len(self.project_context_roots):
            raise ValueError("Resource Catalog project context roots must be unique")
        if self.no_context_files and self.project_context_roots:
            raise ValueError(
                "Resource Catalog context roots must be empty when context is disabled"
            )
        for candidate in self.package_resource_candidates:
            if candidate.source_root_order >= len(self.package_mounts):
                raise ValueError("Resource Catalog package candidate mount is missing")
            mount = self.package_mounts[candidate.source_root_order]
            if not mount.enabled:
                raise ValueError("Resource Catalog package candidate mount is disabled")
            try:
                candidate.source_path.relative_to(mount.root)
            except ValueError as exc:
                raise ValueError(
                    "Resource Catalog package candidate escaped its mount"
                ) from exc
            if candidate.package_content_digest != mount.content_digest:
                raise ValueError(
                    "Resource Catalog package candidate revision does not match mount"
                )
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.built_in_resource_packages
        ):
            raise ValueError("Resource Catalog built-in packages must not be empty")
        if len(set(self.built_in_resource_packages)) != len(
            self.built_in_resource_packages
        ):
            raise ValueError("Resource Catalog built-in packages must be unique")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.context_file_names
        ):
            raise ValueError("Resource Catalog context filenames must not be empty")
        if len(set(self.context_file_names)) != len(self.context_file_names):
            raise ValueError("Resource Catalog context filenames must be unique")
        for value in (
            self.no_extensions,
            self.no_skills,
            self.no_prompt_templates,
            self.no_themes,
            self.no_context_files,
        ):
            if not isinstance(value, bool):
                raise TypeError("Resource Catalog receipt switches must be bools")

    @property
    def has_temporary_inputs(self) -> bool:
        return any(
            (
                self.additional_extension_paths,
                self.additional_skill_paths,
                self.additional_prompt_template_paths,
                self.additional_theme_paths,
            )
        )

    @property
    def has_resource_kind_switches(self) -> bool:
        return any(
            (
                self.no_extensions,
                self.no_skills,
                self.no_prompt_templates,
                self.no_themes,
            )
        )

    @property
    def package_roots(self) -> tuple[Path, ...]:
        return tuple(mount.root for mount in self.package_mounts if mount.enabled)


__all__ = [
    "CatalogPluginPackageInput",
    "LegacyPackageResourceCandidateFact",
    "LegacyPackageResourceKind",
    "ResourceCatalogInputReceipt",
]

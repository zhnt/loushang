"""Immutable legacy-discovery inputs for the private Catalog migration path."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.foundation.json import dump_json_value
from loushang.harness.resources.packages.catalog_inputs import (
    CatalogPluginPackageInput,
)
from loushang.harness.resources.packages.mounts import PackageResourceMount

LegacyPackageResourceKind = Literal["extension", "prompt", "skill", "theme"]


@dataclass(frozen=True, slots=True)
class ContextFileInputFact:
    """Bounded content observation; it never selects an effective context."""

    root: Path
    filename: str
    status: Literal["file", "absent", "unavailable"]
    content_digest: str | None = None
    content_length: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not isinstance(self.filename, str):
            raise TypeError("Context input identity is invalid")
        if not self.filename or "/" in self.filename or "\\" in self.filename or self.filename in {".", ".."}:
            raise ValueError("Context input filename is invalid")
        if self.status not in {"file", "absent", "unavailable"}:
            raise ValueError("Context input status is invalid")
        if self.status == "file":
            if (
                self.content_digest is None
                or len(self.content_digest) != 64
                or any(c not in "0123456789abcdef" for c in self.content_digest)
                or type(self.content_length) is not int
                or self.content_length < 0
            ):
                raise ValueError("Context input file digest is invalid")
        elif self.content_digest is not None or self.content_length is not None:
            raise ValueError("Context input without content must not carry a digest")


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
    context_file_facts: tuple[ContextFileInputFact, ...] = ()

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
        context_facts = tuple(self.context_file_facts)
        if any(not isinstance(item, ContextFileInputFact) for item in context_facts):
            raise TypeError("Resource Catalog context input facts are invalid")
        if len({(item.root, item.filename) for item in context_facts}) != len(context_facts):
            raise ValueError("Resource Catalog context input facts must be unique")
        context_roots = set(self.project_context_roots) | set(self.user_resource_roots)
        if self.no_context_files and context_facts:
            raise ValueError("Disabled Resource Catalog context cannot carry facts")
        if any(
            item.root not in context_roots or item.filename not in self.context_file_names
            for item in context_facts
        ):
            raise ValueError("Resource Catalog context input fact is not configured")
        object.__setattr__(self, "context_file_facts", context_facts)
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

    @property
    def context_content_complete(self) -> bool:
        """Whether every configured native context path was observed by content."""

        if self.no_context_files:
            return not self.context_file_facts
        roots = dict.fromkeys((*self.project_context_roots, *self.user_resource_roots))
        expected = {(root, name) for root in roots for name in self.context_file_names}
        return expected == {
            (item.root, item.filename) for item in self.context_file_facts
        } and all(item.status != "unavailable" for item in self.context_file_facts)

    @property
    def input_fingerprint(self) -> str:
        """Digest configured facts and bounded context bytes, excluding handles.

        This does not cover Skill, Prompt, Theme, or Extension file contents or
        grant Resource authority. The owner must revalidate before publication.
        """

        document = {
            "version": 2,
            "cwd": str(self.cwd),
            "projectResourceRoot": str(self.project_resource_root),
            "projectContextRoots": [str(path) for path in self.project_context_roots],
            "packageMounts": [
                {
                    "root": str(mount.root),
                    "enabled": mount.enabled,
                    "contentDigest": mount.content_digest,
                    "sourceFilter": (
                        None if mount.source_filter is None else {
                            "source": mount.source_filter.source,
                            "extensions": _optional_names(
                                mount.source_filter.extensions
                            ),
                            "skills": _optional_names(mount.source_filter.skills),
                            "prompts": _optional_names(mount.source_filter.prompts),
                            "themes": _optional_names(mount.source_filter.themes),
                        }
                    ),
                }
                for mount in self.package_mounts
            ],
            "packageCandidates": [
                {
                    "kind": item.resource_kind,
                    "path": str(item.source_path),
                    "order": item.source_root_order,
                    "contentDigest": item.package_content_digest,
                }
                for item in self.package_resource_candidates
            ],
            "packageDiagnostics": list(self.package_diagnostic_codes),
            "catalogPluginPackages": [
                {
                    "pluginId": item.binding.plugin_id,
                    "sourceRootOrder": item.source_root_order,
                    "sourceIdentity": item.binding.source_identity,
                    "sourceKind": item.binding.source_kind,
                    "contentDigest": item.package.content_digest,
                    "manifestDigest": item.package.manifest_digest,
                    "dependencyLockDigest": item.package.dependency_lock.digest,
                    "revision": item.binding.revision,
                }
                for item in self.catalog_plugin_package_inputs
            ],
            "userResourceRoots": [str(path) for path in self.user_resource_roots],
            "explicitUserResourceRoots": [
                str(path) for path in sorted(self.explicit_user_resource_roots)
            ],
            "additionalExtensionPaths": [
                str(path) for path in self.additional_extension_paths
            ],
            "additionalSkillPaths": [
                str(path) for path in self.additional_skill_paths
            ],
            "additionalPromptTemplatePaths": [
                str(path) for path in self.additional_prompt_template_paths
            ],
            "additionalThemePaths": [
                str(path) for path in self.additional_theme_paths
            ],
            "noExtensions": self.no_extensions,
            "noSkills": self.no_skills,
            "noPromptTemplates": self.no_prompt_templates,
            "noThemes": self.no_themes,
            "noContextFiles": self.no_context_files,
            "builtInResourcePackages": list(self.built_in_resource_packages),
            "contextFileNames": list(self.context_file_names),
            "contextFileFacts": [
                {
                    "root": str(item.root),
                    "filename": item.filename,
                    "status": item.status,
                    "contentDigest": item.content_digest,
                    "contentLength": item.content_length,
                }
                for item in self.context_file_facts
            ],
        }
        encoded = dump_json_value(
            document, name="Resource Catalog input fingerprint",
            ensure_ascii=True, sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(
            b"loushang.resource-catalog-input/v2\0" + encoded
        ).hexdigest()


def _optional_names(values: tuple[str, ...] | None) -> list[str] | None:
    return list(values) if values is not None else None


__all__ = [
    "CatalogPluginPackageInput",
    "ContextFileInputFact",
    "LegacyPackageResourceCandidateFact",
    "LegacyPackageResourceKind",
    "ResourceCatalogInputReceipt",
]

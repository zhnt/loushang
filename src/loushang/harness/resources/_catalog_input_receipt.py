"""Immutable legacy-discovery inputs for the private Catalog migration path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    package_roots: tuple[Path, ...]
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

    def __post_init__(self) -> None:
        if not isinstance(self.cwd, Path) or not isinstance(
            self.project_resource_root, Path
        ):
            raise TypeError("Resource Catalog receipt roots must be Paths")
        for name in (
            "project_context_roots",
            "package_roots",
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
        object.__setattr__(
            self,
            "explicit_user_resource_roots",
            frozenset(self.explicit_user_resource_roots),
        )
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


__all__ = ["ResourceCatalogInputReceipt"]

"""Normalize configured Resource sources into one Catalog input receipt."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path

from loushang.harness.resources._catalog_input_receipt import (
    CatalogPluginPackageInput,
    LegacyPackageResourceCandidateFact,
    LegacyPackageResourceKind,
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources._loader_discovery import (
    _apply_resource_switches,
    _discover_external_package_resources,
)
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    SkillDescriptor,
    ThemeDescriptor,
)


def prepare_resource_catalog_input_receipt(
    *,
    cwd: Path,
    project_resource_root: Path | None,
    package_mounts: tuple[PackageResourceMount, ...],
    catalog_plugin_package_inputs: tuple[CatalogPluginPackageInput, ...],
    user_resource_roots: tuple[Path, ...],
    explicit_user_resource_roots: Collection[Path],
    additional_extension_paths: tuple[Path, ...],
    additional_skill_paths: tuple[Path, ...],
    additional_prompt_template_paths: tuple[Path, ...],
    additional_theme_paths: tuple[Path, ...],
    no_extensions: bool,
    no_skills: bool,
    no_prompt_templates: bool,
    no_themes: bool,
    no_context_files: bool,
    built_in_resource_packages: tuple[str, ...],
    context_file_names: tuple[str, ...],
) -> ResourceCatalogInputReceipt:
    """Observe only source facts; never select or publish effective Resources."""

    target = Path(cwd)
    project_context_roots = (
        () if no_context_files else _project_context_roots(target)
    )
    resolved_project_root = project_resource_root or _project_root_from_context(
        target,
        roots=project_context_roots,
        context_file_names=context_file_names,
    )
    external = _apply_resource_switches(
        _discover_external_package_resources(package_mounts),
        no_prompts=no_prompt_templates,
        no_skills=no_skills,
        no_extensions=no_extensions,
        no_themes=no_themes,
    )
    return ResourceCatalogInputReceipt(
        cwd=target,
        project_resource_root=resolved_project_root,
        project_context_roots=project_context_roots,
        package_mounts=package_mounts,
        package_resource_candidates=_package_resource_candidate_facts(external),
        package_diagnostic_codes=tuple(
            diagnostic.code for diagnostic in external.diagnostics
        ),
        user_resource_roots=user_resource_roots,
        explicit_user_resource_roots=frozenset(explicit_user_resource_roots),
        additional_extension_paths=additional_extension_paths,
        additional_skill_paths=additional_skill_paths,
        additional_prompt_template_paths=additional_prompt_template_paths,
        additional_theme_paths=additional_theme_paths,
        no_extensions=no_extensions,
        no_skills=no_skills,
        no_prompt_templates=no_prompt_templates,
        no_themes=no_themes,
        no_context_files=no_context_files,
        built_in_resource_packages=built_in_resource_packages,
        context_file_names=context_file_names,
        catalog_plugin_package_inputs=catalog_plugin_package_inputs,
    )


def _project_context_roots(start: Path) -> tuple[Path, ...]:
    current = start if start.is_dir() else start.parent
    roots: list[Path] = []
    while True:
        roots.append(current)
        if current.parent == current:
            return tuple(reversed(roots))
        current = current.parent


def _project_root_from_context(
    target: Path,
    *,
    roots: tuple[Path, ...],
    context_file_names: tuple[str, ...],
) -> Path:
    matching = tuple(
        root
        for root in roots
        if any((root / filename).is_file() for filename in context_file_names)
    )
    if matching:
        return matching[-1]
    return target if target.is_dir() else target.parent


def _package_resource_candidate_facts(
    discovery: object,
) -> tuple[LegacyPackageResourceCandidateFact, ...]:
    return (
        *_package_resource_facts_for("prompt", getattr(discovery, "prompts")),
        *_package_resource_facts_for("skill", getattr(discovery, "skills")),
        *_package_resource_facts_for("extension", getattr(discovery, "extensions")),
        *_package_resource_facts_for("theme", getattr(discovery, "themes")),
    )


def _package_resource_facts_for(
    resource_kind: LegacyPackageResourceKind,
    descriptors: Sequence[
        PromptFragmentDescriptor
        | SkillDescriptor
        | ExtensionDescriptor
        | ThemeDescriptor
    ],
) -> tuple[LegacyPackageResourceCandidateFact, ...]:
    return tuple(
        LegacyPackageResourceCandidateFact(
            resource_kind=resource_kind,
            source_path=descriptor.source_path,
            source_root_order=descriptor.source_root_order,
            package_content_digest=(
                descriptor.revision_ref.content_digest
                if descriptor.revision_ref is not None
                else None
            ),
        )
        for descriptor in descriptors
    )


__all__ = ["prepare_resource_catalog_input_receipt"]

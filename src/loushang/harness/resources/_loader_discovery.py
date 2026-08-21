"""User, project, and external-package resource discovery coordination."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_discovery_filesystem import (
    _discover_extensions_from_dir,
    _discover_prompts_from_dir,
    _discover_skills_from_dir,
    _discover_themes_from_dir,
)
from loushang.harness.resources._loader_package_policy import (
    _filter_package_descriptors,
    _package_root_diagnostic,
)
from loushang.harness.resources._loader_types import _SOURCE_LABEL, _SourceDiscovery
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    SkillDescriptor,
    ThemeDescriptor,
)


def _discover_user_global_resources(
    user_resource_roots: tuple[Path, ...],
    *,
    explicit_roots: Collection[Path] | None = None,
) -> _SourceDiscovery:
    prompts: list[PromptFragmentDescriptor] = []
    skills: list[SkillDescriptor] = []
    extensions: list[ExtensionDescriptor] = []
    themes: list[ThemeDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    explicit = explicit_roots or set()

    for index, root in enumerate(user_resource_roots):
        if not root.exists():
            if root in explicit:
                diagnostics.append(
                    resource_diagnostic(
                        code="missing_user_resource_root",
                        message=f"User resource root does not exist: {root}",
                        source_path=root,
                        resource_type="package",
                        source_kind="user_global",
                        metadata={"root": str(root)},
                    )
                )
            continue
        if not root.is_dir():
            if root in explicit:
                diagnostics.append(
                    resource_diagnostic(
                        code="invalid_user_resource_root",
                        message=f"User resource root must be a directory: {root}",
                        source_path=root,
                        resource_type="package",
                        source_kind="user_global",
                        metadata={"root": str(root)},
                    )
                )
            continue
        user_prompts, prompt_diagnostics = _discover_prompts_from_dir(
            root / "prompts",
            source_kind="user_global",
            source_scope="user",
            source_label=_SOURCE_LABEL["user_global"],
            source_root_order=index,
        )
        user_skills, skill_diagnostics = _discover_skills_from_dir(
            root / "skills",
            source_kind="user_global",
            source_scope="user",
            source_label=_SOURCE_LABEL["user_global"],
            source_root_order=index,
        )
        user_extensions, extension_diagnostics = _discover_extensions_from_dir(
            root / "extensions",
            source_kind="user_global",
            source_scope="user",
            source_label=_SOURCE_LABEL["user_global"],
            source_root_order=index,
        )
        user_themes, theme_diagnostics = _discover_themes_from_dir(
            root / "themes",
            source_kind="user_global",
            source_scope="user",
            source_label=_SOURCE_LABEL["user_global"],
            source_root_order=index,
        )
        prompts.extend(user_prompts)
        skills.extend(user_skills)
        extensions.extend(user_extensions)
        themes.extend(user_themes)
        diagnostics.extend(
            [
                *prompt_diagnostics,
                *skill_diagnostics,
                *extension_diagnostics,
                *theme_diagnostics,
            ]
        )

    return _SourceDiscovery(
        prompts=prompts,
        skills=skills,
        extensions=extensions,
        themes=themes,
        diagnostics=diagnostics,
    )


def _discover_project_resources(root: Path) -> _SourceDiscovery:
    prompts, prompt_diagnostics = _discover_prompts(root)
    skills, skill_diagnostics = _discover_skills(root)
    extensions, extension_diagnostics = _discover_extensions(root)
    themes, theme_diagnostics = _discover_themes(root)
    return _SourceDiscovery(
        prompts=prompts,
        skills=skills,
        extensions=extensions,
        themes=themes,
        diagnostics=[
            *prompt_diagnostics,
            *skill_diagnostics,
            *extension_diagnostics,
            *theme_diagnostics,
        ],
    )


def _discover_external_package_resources(
    package_mounts: tuple[PackageResourceMount, ...],
) -> _SourceDiscovery:
    prompts: list[PromptFragmentDescriptor] = []
    skills: list[SkillDescriptor] = []
    extensions: list[ExtensionDescriptor] = []
    themes: list[ThemeDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []

    for index, mount in enumerate(package_mounts):
        if not mount.enabled:
            continue
        root = mount.root
        if not root.exists():
            diagnostics.append(
                _package_root_diagnostic(
                    "missing_package_root", "Package root does not exist.", root
                )
            )
            continue
        if not root.is_dir():
            diagnostics.append(
                _package_root_diagnostic(
                    "invalid_package_root", "Package root must be a directory.", root
                )
            )
            continue
        package_prompts, prompt_diagnostics = _discover_prompts_from_dir(
            root / "prompts",
            source_kind="external_package",
            source_scope="package",
            source_label=_SOURCE_LABEL["external_package"],
            source_root_order=index,
            text_reader=mount.read_text,
        )
        package_skills, skill_diagnostics = _discover_skills_from_dir(
            root / "skills",
            source_kind="external_package",
            source_scope="package",
            source_label=_SOURCE_LABEL["external_package"],
            source_root_order=index,
            text_reader=mount.read_text,
        )
        package_extensions, extension_diagnostics = _discover_extensions_from_dir(
            root / "extensions",
            source_kind="external_package",
            source_scope="package",
            source_label=_SOURCE_LABEL["external_package"],
            source_root_order=index,
        )
        package_themes, theme_diagnostics = _discover_themes_from_dir(
            root / "themes",
            source_kind="external_package",
            source_scope="package",
            source_label=_SOURCE_LABEL["external_package"],
            source_root_order=index,
            text_reader=mount.read_text,
        )
        package_filter = mount.source_filter
        if package_filter is not None:
            package_prompts = _filter_package_descriptors(
                package_prompts, root=root, patterns=package_filter.prompts
            )
            package_skills = _filter_package_descriptors(
                package_skills, root=root, patterns=package_filter.skills
            )
            package_extensions = _filter_package_descriptors(
                package_extensions, root=root, patterns=package_filter.extensions
            )
            package_themes = _filter_package_descriptors(
                package_themes, root=root, patterns=package_filter.themes
            )
        package_prompts = [
            replace(
                descriptor,
                revision_ref=mount.reference(descriptor.source_path),
            )
            for descriptor in package_prompts
        ]
        package_skills = [
            replace(
                descriptor,
                revision_ref=mount.reference(descriptor.source_path),
            )
            for descriptor in package_skills
        ]
        package_extensions = [
            replace(
                descriptor,
                revision_ref=mount.reference(
                    descriptor.entry_path or descriptor.source_path
                ),
            )
            for descriptor in package_extensions
        ]
        package_themes = [
            replace(
                descriptor,
                revision_ref=mount.reference(
                    descriptor.source_path,
                    kind=(
                        "directory" if descriptor.source_path.is_dir() else "file"
                    ),
                ),
            )
            for descriptor in package_themes
        ]
        prompts.extend(package_prompts)
        skills.extend(package_skills)
        extensions.extend(package_extensions)
        themes.extend(package_themes)
        package_diagnostics = [
            *prompt_diagnostics,
            *skill_diagnostics,
            *extension_diagnostics,
            *theme_diagnostics,
        ]
        diagnostics.extend(package_diagnostics)
        if (
            not package_prompts
            and not package_skills
            and not package_extensions
            and not package_themes
            and not package_diagnostics
        ):
            diagnostics.append(
                _package_root_diagnostic(
                    "empty_package_root",
                    "Package root contains no loadable resources.",
                    root,
                )
            )

    return _SourceDiscovery(
        prompts=prompts,
        skills=skills,
        extensions=extensions,
        themes=themes,
        diagnostics=diagnostics,
    )


def _apply_resource_switches(
    discovery: _SourceDiscovery,
    *,
    no_prompts: bool,
    no_skills: bool,
    no_extensions: bool,
    no_themes: bool,
) -> _SourceDiscovery:
    return _SourceDiscovery(
        prompts=[] if no_prompts else discovery.prompts,
        skills=[] if no_skills else discovery.skills,
        extensions=[] if no_extensions else discovery.extensions,
        themes=[] if no_themes else discovery.themes,
        diagnostics=discovery.diagnostics,
    )


def _discover_prompts(
    root: Path,
) -> tuple[list[PromptFragmentDescriptor], list[DiagnosticDraft]]:
    return _discover_prompts_from_dir(
        root / "prompts",
        source_kind="project_local",
        source_scope="project",
        source_label=_SOURCE_LABEL["project_local"],
    )


def _discover_skills(
    root: Path,
) -> tuple[list[SkillDescriptor], list[DiagnosticDraft]]:
    return _discover_skills_from_dir(
        root / "skills",
        source_kind="project_local",
        source_scope="project",
        source_label=_SOURCE_LABEL["project_local"],
    )


def _discover_extensions(
    root: Path,
) -> tuple[list[ExtensionDescriptor], list[DiagnosticDraft]]:
    return _discover_extensions_from_dir(
        root / "extensions",
        source_kind="project_local",
        source_scope="project",
        source_label=_SOURCE_LABEL["project_local"],
    )


def _discover_themes(
    root: Path,
) -> tuple[list[ThemeDescriptor], list[DiagnosticDraft]]:
    return _discover_themes_from_dir(
        root / "themes",
        source_kind="project_local",
        source_scope="project",
        source_label=_SOURCE_LABEL["project_local"],
    )

"""Built-in package resource discovery."""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_descriptor_parsing import (
    _prompt_descriptor_from_text,
    _skill_descriptor_from_text,
)
from loushang.harness.resources._loader_types import _SourceDiscovery
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    SkillDescriptor,
    ThemeDescriptor,
)


def _discover_built_in_resources(
    resource_packages: tuple[str, ...],
) -> _SourceDiscovery:
    prompts: list[PromptFragmentDescriptor] = []
    skills: list[SkillDescriptor] = []
    extensions: list[ExtensionDescriptor] = []
    themes: list[ThemeDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for index, resource_package in enumerate(resource_packages):
        package_prompts, prompt_diagnostics = _discover_built_in_prompts(
            resource_package,
            source_root_order=index,
        )
        package_skills, skill_diagnostics = _discover_built_in_skills(
            resource_package,
            source_root_order=index,
        )
        package_extensions, extension_diagnostics = _discover_built_in_extensions(
            resource_package,
            source_root_order=index,
        )
        package_themes, theme_diagnostics = _discover_built_in_themes(
            resource_package,
            source_root_order=index,
        )
        prompts.extend(package_prompts)
        skills.extend(package_skills)
        extensions.extend(package_extensions)
        themes.extend(package_themes)
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


def _discover_built_in_prompts(
    resource_package: str,
    *,
    source_root_order: int,
) -> tuple[list[PromptFragmentDescriptor], list[DiagnosticDraft]]:
    prompts_root = _built_in_category_root(resource_package, "prompts")
    if prompts_root is None:
        return [], []

    descriptors: list[PromptFragmentDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in _iter_built_in_entries(prompts_root):
        if entry.is_file() and entry.name.endswith(".md"):
            text, read_diagnostics = _read_text_resource(
                entry,
                resource_package=resource_package,
                relative_path=f"prompts/{entry.name}",
                diagnostic_code="unreadable_prompt_entry",
                message_prefix="Failed to read built-in prompt entry",
            )
            diagnostics.extend(read_diagnostics)
            if text is None:
                continue
            descriptor, frontmatter_diagnostics = _prompt_descriptor_from_text(
                name=entry.name.removesuffix(".md"),
                source_path=_package_resource_path(
                    resource_package, f"prompts/{entry.name}"
                ),
                text=text,
                canonical_name=entry.name,
                source_kind="built_in",
                source_scope="builtin",
                source="package_resource",
                source_root=_package_source_root_path(resource_package, "prompts"),
                source_root_order=source_root_order,
            )
            diagnostics.extend(frontmatter_diagnostics)
            if descriptor is not None:
                descriptors.append(descriptor)
            continue
        diagnostics.append(
            resource_diagnostic(
                code="unsupported_prompt_entry",
                message="Built-in prompt entries must be .md files.",
                source_path=_package_resource_path(
                    resource_package, f"prompts/{entry.name}"
                ),
                resource_type="prompt",
                source_kind="built_in",
            )
        )
    return descriptors, diagnostics


def _discover_built_in_skills(
    resource_package: str,
    *,
    source_root_order: int,
) -> tuple[list[SkillDescriptor], list[DiagnosticDraft]]:
    skills_root = _built_in_category_root(resource_package, "skills")
    if skills_root is None:
        return [], []

    descriptors: list[SkillDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in _iter_built_in_entries(skills_root):
        if not entry.is_dir():
            diagnostics.append(
                resource_diagnostic(
                    code="unsupported_skill_entry",
                    message="Built-in skill entries must be directories.",
                    source_path=_package_resource_path(
                        resource_package, f"skills/{entry.name}"
                    ),
                    resource_type="skill",
                    source_kind="built_in",
                )
            )
            continue

        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            diagnostics.append(
                resource_diagnostic(
                    code="missing_skill_entry",
                    message="Built-in skill directories must contain SKILL.md.",
                    source_path=_package_resource_path(
                        resource_package, f"skills/{entry.name}"
                    ),
                    resource_type="skill",
                    source_kind="built_in",
                )
            )
            continue

        content, read_diagnostics = _read_text_resource(
            skill_file,
            resource_package=resource_package,
            relative_path=f"skills/{entry.name}/SKILL.md",
            diagnostic_code="unreadable_skill_entry",
            message_prefix="Failed to read built-in skill entry",
        )
        diagnostics.extend(read_diagnostics)
        if content is None:
            continue
        source_path = _package_resource_path(
            resource_package, f"skills/{entry.name}/SKILL.md"
        )
        descriptor, parsing_diagnostics = _skill_descriptor_from_text(
            parent_name=entry.name,
            source_path=source_path,
            content=content,
            canonical_name=f"{entry.name}/SKILL.md",
            source_kind="built_in",
            source_scope="builtin",
            source="package_resource",
            source_root=_package_source_root_path(resource_package, "skills"),
            source_root_order=source_root_order,
        )
        diagnostics.extend(parsing_diagnostics)
        if descriptor is not None:
            descriptors.append(descriptor)
    return descriptors, diagnostics


def _discover_built_in_extensions(
    resource_package: str,
    *,
    source_root_order: int,
) -> tuple[list[ExtensionDescriptor], list[DiagnosticDraft]]:
    extensions_root = _built_in_category_root(resource_package, "extensions")
    if extensions_root is None:
        return [], []

    descriptors: list[ExtensionDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in _iter_built_in_entries(extensions_root):
        if entry.is_file() and entry.name.endswith(".py"):
            entry_path = _package_resource_path(
                resource_package, f"extensions/{entry.name}"
            )
            descriptors.append(
                ExtensionDescriptor(
                    name=entry.name.removesuffix(".py"),
                    source_path=entry_path,
                    entry_path=entry_path,
                    canonical_name=entry.name,
                    source_kind="built_in",
                    source_scope="builtin",
                    source="package_resource",
                    source_root=_package_source_root_path(
                        resource_package, "extensions"
                    ),
                    source_root_order=source_root_order,
                )
            )
            continue
        if entry.is_dir():
            entry_name = _find_extension_entry_name(entry)
            if entry_name is None:
                diagnostics.append(
                    resource_diagnostic(
                        code="missing_extension_entry",
                        message="Built-in extension directories must contain extension.py or __init__.py.",
                        source_path=_package_resource_path(
                            resource_package, f"extensions/{entry.name}"
                        ),
                        resource_type="extension",
                        source_kind="built_in",
                    )
                )
                continue
            descriptors.append(
                ExtensionDescriptor(
                    name=entry.name,
                    source_path=_package_resource_path(
                        resource_package, f"extensions/{entry.name}"
                    ),
                    entry_path=_package_resource_path(
                        resource_package,
                        f"extensions/{entry.name}/{entry_name}",
                    ),
                    canonical_name=entry.name,
                    source_kind="built_in",
                    source_scope="builtin",
                    source="package_resource",
                    source_root=_package_source_root_path(
                        resource_package, "extensions"
                    ),
                    source_root_order=source_root_order,
                )
            )
            continue
        diagnostics.append(
            resource_diagnostic(
                code="unsupported_extension_entry",
                message="Built-in extension entries must be .py files or directories.",
                source_path=_package_resource_path(
                    resource_package, f"extensions/{entry.name}"
                ),
                resource_type="extension",
                source_kind="built_in",
            )
        )
    return descriptors, diagnostics


def _discover_built_in_themes(
    resource_package: str,
    *,
    source_root_order: int,
) -> tuple[list[ThemeDescriptor], list[DiagnosticDraft]]:
    themes_root = _built_in_category_root(resource_package, "themes")
    if themes_root is None:
        return [], []

    descriptors = [
        ThemeDescriptor(
            name=entry.name.removesuffix(".json") if entry.is_file() else entry.name,
            source_path=_package_resource_path(
                resource_package, f"themes/{entry.name}"
            ),
            canonical_name=entry.name,
            source_kind="built_in",
            source_scope="builtin",
            source="package_resource",
            source_root=_package_source_root_path(resource_package, "themes"),
            source_root_order=source_root_order,
        )
        for entry in _iter_built_in_entries(themes_root)
    ]
    return descriptors, []


def _iter_built_in_entries(root: Traversable) -> list[Traversable]:
    entries = []
    for entry in root.iterdir():
        if entry.name in {"__init__.py", "__pycache__"}:
            continue
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry.name)


def _built_in_category_root(resource_package: str, category: str) -> Traversable | None:
    try:
        root = resources.files(resource_package)
    except ModuleNotFoundError:
        return None
    category_root = root / category
    if not category_root.is_dir():
        return None
    return category_root


def _find_extension_entry_name(entry: Traversable) -> str | None:
    for filename in ("extension.py", "__init__.py"):
        candidate = entry / filename
        if candidate.is_file():
            return filename
    return None


def _read_text_resource(
    resource: Traversable,
    *,
    resource_package: str,
    relative_path: str,
    diagnostic_code: str,
    message_prefix: str,
) -> tuple[str | None, list[DiagnosticDraft]]:
    logical_path = _package_resource_path(resource_package, relative_path)
    try:
        return resource.read_text(encoding="utf-8").strip(), []
    except OSError as exc:
        return (
            None,
            [
                resource_diagnostic(
                    code=diagnostic_code,
                    message=f"{message_prefix}: {exc}",
                    source_path=logical_path,
                    source_kind="built_in",
                )
            ],
        )


def _package_resource_path(resource_package: str, relative_path: str) -> Path:
    return Path(resource_package.replace(".", "/")) / relative_path


def _package_source_root_path(resource_package: str, category: str) -> Path:
    return Path(resource_package.replace(".", "/")) / category

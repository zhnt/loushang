"""Runtime-path resource discovery for temporary loader inputs."""

from __future__ import annotations

from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_descriptor_parsing import (
    _prompt_descriptor_from_text,
)
from loushang.harness.resources._loader_discovery_filesystem import (
    _discover_extensions_from_dir,
    _discover_prompts_from_dir,
    _discover_skills_from_dir,
    _discover_themes_from_dir,
    _find_extension_entry,
    _read_text_file,
    _skill_descriptor_from_file,
    _theme_json_diagnostic,
)
from loushang.harness.resources._loader_types import _SOURCE_LABEL, _SourceDiscovery
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    SkillDescriptor,
    ThemeDescriptor,
)


def _discover_temporary_resources(
    cwd: Path,
    *,
    extension_paths: tuple[Path, ...],
    skill_paths: tuple[Path, ...],
    prompt_paths: tuple[Path, ...],
    theme_paths: tuple[Path, ...],
) -> _SourceDiscovery:
    prompts: list[PromptFragmentDescriptor] = []
    skills: list[SkillDescriptor] = []
    extensions: list[ExtensionDescriptor] = []
    themes: list[ThemeDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []

    for index, raw_path in enumerate(prompt_paths):
        loaded_prompts, loaded_diagnostics = _discover_temporary_prompts_from_path(
            _resolve_runtime_path(raw_path, cwd), index
        )
        prompts.extend(loaded_prompts)
        diagnostics.extend(loaded_diagnostics)
    for index, raw_path in enumerate(skill_paths):
        loaded_skills, loaded_diagnostics = _discover_temporary_skills_from_path(
            _resolve_runtime_path(raw_path, cwd), index
        )
        skills.extend(loaded_skills)
        diagnostics.extend(loaded_diagnostics)
    for index, raw_path in enumerate(extension_paths):
        loaded_extensions, loaded_diagnostics = (
            _discover_temporary_extensions_from_path(
                _resolve_runtime_path(raw_path, cwd), index
            )
        )
        extensions.extend(loaded_extensions)
        diagnostics.extend(loaded_diagnostics)
    for index, raw_path in enumerate(theme_paths):
        loaded_themes, loaded_diagnostics = _discover_temporary_themes_from_path(
            _resolve_runtime_path(raw_path, cwd), index
        )
        themes.extend(loaded_themes)
        diagnostics.extend(loaded_diagnostics)

    return _SourceDiscovery(
        prompts=prompts,
        skills=skills,
        extensions=extensions,
        themes=themes,
        diagnostics=diagnostics,
    )


def _discover_temporary_prompts_from_path(
    path: Path,
    source_root_order: int,
) -> tuple[list[PromptFragmentDescriptor], list[DiagnosticDraft]]:
    if not path.exists():
        return [], [_temporary_missing_path_diagnostic(path, resource_type="prompt")]
    if path.is_file():
        if path.suffix != ".md":
            return [], [
                _temporary_unsupported_path_diagnostic(
                    path,
                    resource_type="prompt",
                    message="Prompt template paths must be .md files or directories.",
                )
            ]
        text, diagnostics = _read_text_file(
            path,
            diagnostic_code="unreadable_prompt_entry",
            message_prefix="Failed to read prompt entry",
        )
        if text is None:
            return [], diagnostics
        descriptor, frontmatter_diagnostics = _prompt_descriptor_from_text(
            name=path.stem,
            source_path=path,
            text=text,
            canonical_name=path.name,
            source_kind="temporary",
            source_scope="temporary",
            source=_SOURCE_LABEL["temporary"],
            source_root=path.parent,
            source_root_order=source_root_order,
        )
        diagnostics.extend(frontmatter_diagnostics)
        return ([descriptor] if descriptor is not None else []), diagnostics
    return _discover_prompts_from_dir(
        path,
        source_kind="temporary",
        source_scope="temporary",
        source_label=_SOURCE_LABEL["temporary"],
        source_root_order=source_root_order,
    )


def _discover_temporary_skills_from_path(
    path: Path,
    source_root_order: int,
) -> tuple[list[SkillDescriptor], list[DiagnosticDraft]]:
    if not path.exists():
        return [], [_temporary_missing_path_diagnostic(path, resource_type="skill")]
    if path.is_file():
        if path.name != "SKILL.md":
            return [], [
                _temporary_unsupported_path_diagnostic(
                    path,
                    resource_type="skill",
                    message="Skill paths must be SKILL.md files or directories.",
                )
            ]
        descriptor, diagnostics = _skill_descriptor_from_file(
            path,
            root_dir=path.parent,
            parent_name=path.parent.name,
            source_kind="temporary",
            source_scope="temporary",
            source_label=_SOURCE_LABEL["temporary"],
            source_root_order=source_root_order,
        )
        return ([descriptor] if descriptor is not None else []), diagnostics
    if (path / "SKILL.md").is_file():
        descriptor, diagnostics = _skill_descriptor_from_file(
            path / "SKILL.md",
            root_dir=path,
            parent_name=path.name,
            source_kind="temporary",
            source_scope="temporary",
            source_label=_SOURCE_LABEL["temporary"],
            source_root_order=source_root_order,
        )
        return ([descriptor] if descriptor is not None else []), diagnostics
    return _discover_skills_from_dir(
        path,
        source_kind="temporary",
        source_scope="temporary",
        source_label=_SOURCE_LABEL["temporary"],
        source_root_order=source_root_order,
    )


def _discover_temporary_extensions_from_path(
    path: Path,
    source_root_order: int,
) -> tuple[list[ExtensionDescriptor], list[DiagnosticDraft]]:
    if not path.exists():
        return [], [_temporary_missing_path_diagnostic(path, resource_type="extension")]
    if path.is_file():
        if path.suffix != ".py":
            return [], [
                _temporary_unsupported_path_diagnostic(
                    path,
                    resource_type="extension",
                    message="Extension paths must be .py files or directories.",
                )
            ]
        return [
            ExtensionDescriptor(
                name=path.stem,
                source_path=path,
                entry_path=path,
                canonical_name=path.name,
                source_kind="temporary",
                source_scope="temporary",
                source=_SOURCE_LABEL["temporary"],
                source_root=path.parent,
                source_root_order=source_root_order,
            )
        ], []
    entry_path = _find_extension_entry(path)
    if entry_path is not None:
        return [
            ExtensionDescriptor(
                name=path.name,
                source_path=path,
                entry_path=entry_path,
                canonical_name=path.name,
                source_kind="temporary",
                source_scope="temporary",
                source=_SOURCE_LABEL["temporary"],
                source_root=path,
                source_root_order=source_root_order,
            )
        ], []
    return _discover_extensions_from_dir(
        path,
        source_kind="temporary",
        source_scope="temporary",
        source_label=_SOURCE_LABEL["temporary"],
        source_root_order=source_root_order,
    )


def _discover_temporary_themes_from_path(
    path: Path,
    source_root_order: int,
) -> tuple[list[ThemeDescriptor], list[DiagnosticDraft]]:
    if not path.exists():
        return [], [_temporary_missing_path_diagnostic(path, resource_type="theme")]
    if path.is_file():
        if path.suffix != ".json":
            return [], [
                _temporary_unsupported_path_diagnostic(
                    path,
                    resource_type="theme",
                    message="Theme paths must be .json files or directories.",
                )
            ]
        diagnostic = _theme_json_diagnostic(path, source_kind="temporary")
        if diagnostic is not None:
            return [], [diagnostic]
        return [
            ThemeDescriptor(
                name=path.stem,
                source_path=path,
                canonical_name=path.name,
                source_kind="temporary",
                source_scope="temporary",
                source=_SOURCE_LABEL["temporary"],
                source_root=path.parent,
                source_root_order=source_root_order,
            )
        ], []
    return _discover_themes_from_dir(
        path,
        source_kind="temporary",
        source_scope="temporary",
        source_label=_SOURCE_LABEL["temporary"],
        source_root_order=source_root_order,
    )


def _temporary_missing_path_diagnostic(
    path: Path, *, resource_type: str
) -> DiagnosticDraft:
    return resource_diagnostic(
        code=f"missing_{resource_type}_path",
        message=f"{resource_type.title()} path does not exist: {path}",
        source_path=path,
        resource_type=resource_type,
        source_kind="temporary",
        metadata={"path": str(path)},
    )


def _temporary_unsupported_path_diagnostic(
    path: Path, *, resource_type: str, message: str
) -> DiagnosticDraft:
    return resource_diagnostic(
        code=f"unsupported_{resource_type}_path",
        message=message,
        source_path=path,
        resource_type=resource_type,
        source_kind="temporary",
        metadata={"path": str(path)},
    )


def _resolve_runtime_path(path: Path, cwd: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (cwd / expanded).resolve()

"""Filesystem-backed resource discovery and validation."""

from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_descriptor_parsing import (
    _prompt_descriptor_from_text,
    _skill_descriptor_from_text,
)
from loushang.harness.resources._loader_types import _IGNORE_FILE_NAMES
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSourceKind,
    ResourceSourceScope,
    SkillDescriptor,
    ThemeDescriptor,
)


def _discover_prompts_from_dir(
    prompts_dir: Path,
    *,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int = 0,
) -> tuple[list[PromptFragmentDescriptor], list[DiagnosticDraft]]:
    if not prompts_dir.is_dir():
        return [], []

    descriptors: list[PromptFragmentDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in sorted(prompts_dir.iterdir(), key=lambda path: path.name):
        if entry.is_file() and entry.suffix == ".md":
            text, read_diagnostics = _read_text_file(
                entry,
                diagnostic_code="unreadable_prompt_entry",
                message_prefix="Failed to read prompt entry",
            )
            diagnostics.extend(read_diagnostics)
            if text is None:
                continue
            descriptor, frontmatter_diagnostics = _prompt_descriptor_from_text(
                name=entry.stem,
                source_path=entry,
                text=text,
                canonical_name=entry.name,
                source_kind=source_kind,
                source_scope=source_scope,
                source=source_label,
                source_root=prompts_dir,
                source_root_order=source_root_order,
            )
            diagnostics.extend(frontmatter_diagnostics)
            if descriptor is not None:
                descriptors.append(descriptor)
            continue
        diagnostics.append(
            resource_diagnostic(
                code="unsupported_prompt_entry",
                message="Prompt entries must be .md files.",
                source_path=entry,
                resource_type="prompt",
                source_kind=source_kind,
            )
        )
    return descriptors, diagnostics


def _discover_skills_from_dir(
    skills_dir: Path,
    *,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int = 0,
) -> tuple[list[SkillDescriptor], list[DiagnosticDraft]]:
    if not skills_dir.is_dir():
        return [], []

    return _discover_skills_recursive(
        skills_dir,
        root_dir=skills_dir,
        ignore_patterns=(),
        source_kind=source_kind,
        source_scope=source_scope,
        source_label=source_label,
        source_root_order=source_root_order,
    )


def _discover_skills_recursive(
    current_dir: Path,
    *,
    root_dir: Path,
    ignore_patterns: tuple[str, ...],
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int = 0,
) -> tuple[list[SkillDescriptor], list[DiagnosticDraft]]:
    descriptors: list[SkillDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    active_ignore_patterns = (
        *ignore_patterns,
        *_read_skill_ignore_patterns(current_dir, root_dir),
    )
    skill_file = current_dir / "SKILL.md"
    if skill_file.is_file():
        descriptor, skill_diagnostics = _skill_descriptor_from_file(
            skill_file,
            root_dir=root_dir,
            parent_name=current_dir.name,
            source_kind=source_kind,
            source_scope=source_scope,
            source_label=source_label,
            source_root_order=source_root_order,
        )
        diagnostics.extend(skill_diagnostics)
        return ([descriptor] if descriptor is not None else []), diagnostics

    for entry in sorted(current_dir.iterdir(), key=lambda path: path.name):
        if entry.name == "SKILL.md":
            continue
        if entry.is_file():
            if current_dir == root_dir and entry.name not in _IGNORE_FILE_NAMES:
                diagnostics.append(
                    resource_diagnostic(
                        code="unsupported_skill_entry",
                        message="Skill entries must be directories.",
                        source_path=entry,
                        resource_type="skill",
                        source_kind=source_kind,
                    )
                )
            continue
        if not entry.is_dir() or _skip_skill_directory(entry):
            continue
        if _is_skill_path_ignored(
            entry, root_dir=root_dir, patterns=active_ignore_patterns
        ):
            continue
        child_descriptors, child_diagnostics = _discover_skills_recursive(
            entry,
            root_dir=root_dir,
            ignore_patterns=active_ignore_patterns,
            source_kind=source_kind,
            source_scope=source_scope,
            source_label=source_label,
            source_root_order=source_root_order,
        )
        descriptors.extend(child_descriptors)
        diagnostics.extend(child_diagnostics)
    return descriptors, diagnostics


def _skill_descriptor_from_file(
    skill_file: Path,
    *,
    root_dir: Path,
    parent_name: str,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int,
) -> tuple[SkillDescriptor | None, list[DiagnosticDraft]]:
    content, diagnostics = _read_text_file(
        skill_file,
        diagnostic_code="unreadable_skill_entry",
        message_prefix="Failed to read skill entry",
    )
    if content is None:
        return None, diagnostics
    descriptor, parsing_diagnostics = _skill_descriptor_from_text(
        parent_name=parent_name,
        source_path=skill_file,
        content=content,
        canonical_name=skill_file.relative_to(root_dir).as_posix(),
        source_kind=source_kind,
        source_scope=source_scope,
        source=source_label,
        source_root=root_dir,
        source_root_order=source_root_order,
    )
    diagnostics.extend(parsing_diagnostics)
    return descriptor, diagnostics


def _skip_skill_directory(path: Path) -> bool:
    return path.name.startswith(".") or path.name == "node_modules"


def _read_skill_ignore_patterns(current_dir: Path, root_dir: Path) -> tuple[str, ...]:
    patterns: list[str] = []
    relative_prefix = current_dir.relative_to(root_dir).as_posix()
    prefix = "" if relative_prefix == "." else relative_prefix
    for filename in _IGNORE_FILE_NAMES:
        ignore_file = current_dir / filename
        if not ignore_file.is_file():
            continue
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw_line in lines:
            pattern = _normalize_skill_ignore_pattern(raw_line, prefix=prefix)
            if pattern is not None:
                patterns.append(pattern)
    return tuple(patterns)


def _normalize_skill_ignore_pattern(raw_line: str, *, prefix: str) -> str | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or line.startswith("!"):
        return None
    if line.startswith("\\#") or line.startswith("\\!"):
        line = line[1:]
    if line.startswith("/"):
        line = line[1:]
    if prefix:
        line = f"{prefix}/{line}"
    return line


def _is_skill_path_ignored(
    path: Path, *, root_dir: Path, patterns: tuple[str, ...]
) -> bool:
    if not patterns:
        return False
    relative_path = path.relative_to(root_dir).as_posix()
    directory_path = f"{relative_path}/"
    for pattern in patterns:
        normalized = pattern.rstrip("/")
        if pattern.endswith("/") and (
            relative_path == normalized or directory_path.startswith(pattern)
        ):
            return True
        if relative_path == normalized or relative_path.startswith(f"{normalized}/"):
            return True
        if fnmatch(relative_path, normalized) or fnmatch(directory_path, pattern):
            return True
    return False


def _discover_extensions_from_dir(
    extensions_dir: Path,
    *,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int = 0,
) -> tuple[list[ExtensionDescriptor], list[DiagnosticDraft]]:
    if not extensions_dir.is_dir():
        return [], []

    descriptors: list[ExtensionDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in sorted(
        extensions_dir.iterdir(),
        key=lambda path: (0 if path.is_dir() else 1, path.name),
    ):
        if entry.is_file() and entry.suffix == ".py":
            descriptors.append(
                ExtensionDescriptor(
                    name=entry.stem,
                    source_path=entry,
                    entry_path=entry,
                    canonical_name=entry.name,
                    source_kind=source_kind,
                    source_scope=source_scope,
                    source=source_label,
                    source_root=extensions_dir,
                    source_root_order=source_root_order,
                )
            )
            continue
        if entry.is_dir():
            entry_path = _find_extension_entry(entry)
            if entry_path is None:
                diagnostics.append(
                    resource_diagnostic(
                        code="missing_extension_entry",
                        message="Extension directories must contain extension.py or __init__.py.",
                        source_path=entry,
                        resource_type="extension",
                        source_kind=source_kind,
                    )
                )
                continue
            descriptors.append(
                ExtensionDescriptor(
                    name=entry.name,
                    source_path=entry,
                    entry_path=entry_path,
                    canonical_name=entry.name,
                    source_kind=source_kind,
                    source_scope=source_scope,
                    source=source_label,
                    source_root=extensions_dir,
                    source_root_order=source_root_order,
                )
            )
            continue
        diagnostics.append(
            resource_diagnostic(
                code="unsupported_extension_entry",
                message="Extension entries must be .py files or directories.",
                source_path=entry,
                resource_type="extension",
                source_kind=source_kind,
            )
        )
    return descriptors, diagnostics


def _discover_themes_from_dir(
    themes_dir: Path,
    *,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int = 0,
) -> tuple[list[ThemeDescriptor], list[DiagnosticDraft]]:
    if not themes_dir.is_dir():
        return [], []

    descriptors: list[ThemeDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in sorted(themes_dir.iterdir(), key=lambda path: path.name):
        if entry.is_file() and not entry.name.endswith(".json"):
            diagnostics.append(
                resource_diagnostic(
                    code="unsupported_theme_entry",
                    message="Theme file entries must be .json files.",
                    source_path=entry,
                    resource_type="theme",
                    source_kind=source_kind,
                )
            )
            continue
        if entry.is_file():
            diagnostic = _theme_json_diagnostic(entry, source_kind=source_kind)
            if diagnostic is not None:
                diagnostics.append(diagnostic)
                continue
        descriptors.append(
            ThemeDescriptor(
                name=entry.stem if entry.is_file() else entry.name,
                source_path=entry,
                canonical_name=entry.name,
                source_kind=source_kind,
                source_scope=source_scope,
                source=source_label,
                source_root=themes_dir,
                source_root_order=source_root_order,
            )
        )
    return descriptors, diagnostics


def _theme_json_diagnostic(
    path: Path, *, source_kind: ResourceSourceKind
) -> DiagnosticDraft | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return resource_diagnostic(
            code="invalid_theme_json",
            message=f"Theme JSON is invalid: {exc.msg}",
            source_path=path,
            resource_type="theme",
            source_kind=source_kind,
        )
    except Exception as exc:
        return resource_diagnostic(
            code="unreadable_theme_entry",
            message=f"Failed to read theme entry: {exc}",
            source_path=path,
            resource_type="theme",
            source_kind=source_kind,
        )
    if not isinstance(payload, dict):
        return resource_diagnostic(
            code="invalid_theme_schema",
            message="Theme JSON must be an object.",
            source_path=path,
            resource_type="theme",
            source_kind=source_kind,
        )
    return None


def _find_extension_entry(entry: Path) -> Path | None:
    for filename in ("extension.py", "__init__.py"):
        candidate = entry / filename
        if candidate.is_file():
            return candidate
    return None


def _read_text_file(
    path: Path,
    *,
    diagnostic_code: str,
    message_prefix: str,
) -> tuple[str | None, list[DiagnosticDraft]]:
    try:
        return path.read_text(encoding="utf-8").strip(), []
    except OSError as exc:
        return (
            None,
            [
                resource_diagnostic(
                    code=diagnostic_code,
                    message=f"{message_prefix}: {exc}",
                    source_path=path,
                )
            ],
        )

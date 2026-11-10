"""Filesystem-backed resource discovery and validation."""

from __future__ import annotations

import errno
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from re import Pattern
from typing import Protocol, TypeVar

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_descriptor_parsing import (
    _prompt_descriptor_from_text,
    _skill_descriptor_from_text,
)
from loushang.harness.resources._loader_types import _IGNORE_FILE_NAMES
from loushang.harness.resources._skill_ignore import (
    is_skill_path_ignored,
    normalize_skill_ignore_pattern,
)
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSourceKind,
    ResourceSourceScope,
    SkillDescriptor,
    ThemeDescriptor,
)

TextReader = Callable[[Path], str]


def _directory_entries(
    directory: Path, work_probe: Callable[[], None] | None,
) -> list[Path]:
    """Permit cancellation or a caller budget before collecting a whole directory."""

    entries: list[Path] = []
    for entry in directory.iterdir():
        if work_probe is not None:
            work_probe()
        entries.append(entry)
    return entries


def _discover_prompts_from_dir(
    prompts_dir: Path,
    *,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int = 0,
    text_reader: TextReader | None = None,
    work_probe: Callable[[], None] | None = None,
) -> tuple[list[PromptFragmentDescriptor], list[DiagnosticDraft]]:
    if not prompts_dir.is_dir():
        return [], []

    descriptors: list[PromptFragmentDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in sorted(_directory_entries(prompts_dir, work_probe), key=lambda path: path.name):
        if work_probe is not None:
            work_probe()
        if entry.is_file() and entry.suffix == ".md":
            text, read_diagnostics = _read_text_file(
                entry,
                diagnostic_code="unreadable_prompt_entry",
                message_prefix="Failed to read prompt entry",
                text_reader=text_reader,
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
    text_reader: TextReader | None = None,
    work_probe: Callable[[], None] | None = None,
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
        text_reader=text_reader,
        work_probe=work_probe,
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
    text_reader: TextReader | None = None,
    work_probe: Callable[[], None] | None = None,
) -> tuple[list[SkillDescriptor], list[DiagnosticDraft]]:
    if work_probe is not None:
        work_probe()
    descriptors: list[SkillDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    active_ignore_patterns = (
        *ignore_patterns,
        *_read_skill_ignore_patterns(
            current_dir,
            root_dir,
            text_reader=text_reader,
        ),
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
            text_reader=text_reader,
        )
        diagnostics.extend(skill_diagnostics)
        return ([descriptor] if descriptor is not None else []), diagnostics

    for entry in sorted(_directory_entries(current_dir, work_probe), key=lambda path: path.name):
        if work_probe is not None:
            work_probe()
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
        if is_skill_path_ignored(
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
            text_reader=text_reader,
            work_probe=work_probe,
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
    text_reader: TextReader | None = None,
) -> tuple[SkillDescriptor | None, list[DiagnosticDraft]]:
    content, diagnostics = _read_text_file(
        skill_file,
        diagnostic_code="unreadable_skill_entry",
        message_prefix="Failed to read skill entry",
        text_reader=text_reader,
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


def _read_skill_ignore_patterns(
    current_dir: Path,
    root_dir: Path,
    *,
    text_reader: TextReader | None,
) -> tuple[str, ...]:
    patterns: list[str] = []
    relative_prefix = current_dir.relative_to(root_dir).as_posix()
    prefix = "" if relative_prefix == "." else relative_prefix
    for filename in _IGNORE_FILE_NAMES:
        ignore_file = current_dir / filename
        if not ignore_file.is_file():
            continue
        try:
            encoded = (
                text_reader(ignore_file)
                if text_reader is not None
                else ignore_file.read_text(encoding="utf-8")
            )
            lines = encoded.splitlines()
        except OSError:
            continue
        for raw_line in lines:
            pattern = normalize_skill_ignore_pattern(raw_line, prefix=prefix)
            if pattern is not None:
                patterns.append(pattern)
    return tuple(patterns)


def _discover_extensions_from_dir(
    extensions_dir: Path,
    *,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int = 0,
    work_probe: Callable[[], None] | None = None,
) -> tuple[list[ExtensionDescriptor], list[DiagnosticDraft]]:
    if not extensions_dir.is_dir():
        return [], []

    descriptors: list[ExtensionDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in sorted(
        _directory_entries(extensions_dir, work_probe),
        key=lambda path: (0 if path.is_dir() else 1, path.name),
    ):
        if work_probe is not None:
            work_probe()
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
    text_reader: TextReader | None = None,
    work_probe: Callable[[], None] | None = None,
) -> tuple[list[ThemeDescriptor], list[DiagnosticDraft]]:
    if not themes_dir.is_dir():
        return [], []

    descriptors: list[ThemeDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    for entry in sorted(_directory_entries(themes_dir, work_probe), key=lambda path: path.name):
        if work_probe is not None:
            work_probe()
        content: str | None = None
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
            try:
                content = (
                    text_reader(entry)
                    if text_reader is not None
                    else entry.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError) as exc:
                diagnostics.append(
                    resource_diagnostic(
                        code="unreadable_theme_entry",
                        message=f"Failed to read theme entry: {exc}",
                        source_path=entry,
                        resource_type="theme",
                        source_kind=source_kind,
                    )
                )
                continue
            diagnostic = _theme_json_diagnostic_from_text(
                entry,
                content=content,
                source_kind=source_kind,
            )
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
                content=content,
            )
        )
    return descriptors, diagnostics


def _theme_json_diagnostic(
    path: Path,
    *,
    source_kind: ResourceSourceKind,
    text_reader: TextReader | None = None,
) -> DiagnosticDraft | None:
    try:
        encoded = (
            text_reader(path)
            if text_reader is not None
            else path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError) as exc:
        return resource_diagnostic(
            code="unreadable_theme_entry",
            message=f"Failed to read theme entry: {exc}",
            source_path=path,
            resource_type="theme",
            source_kind=source_kind,
        )
    return _theme_json_diagnostic_from_text(
        path,
        content=encoded,
        source_kind=source_kind,
    )


def _theme_json_diagnostic_from_text(
    path: Path,
    *,
    content: str,
    source_kind: ResourceSourceKind,
) -> DiagnosticDraft | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return resource_diagnostic(
            code="invalid_theme_json",
            message=f"Theme JSON is invalid: {exc.msg}",
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
    text_reader: TextReader | None = None,
) -> tuple[str | None, list[DiagnosticDraft]]:
    try:
        encoded = (
            text_reader(path)
            if text_reader is not None
            else path.read_text(encoding="utf-8")
        )
        return encoded.strip(), []
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


_MetadataRow = TypeVar("_MetadataRow")


class _NativeFallbackRoots(Protocol):
    """Only the declared native roots, read lazily after platform admission."""

    @property
    def project_resource_root(self) -> Path: ...

    @property
    def user_resource_roots(self) -> tuple[Path, ...]: ...


def _discover_native_fallback_metadata(
    receipt: _NativeFallbackRoots,
    *,
    max_rows: int,
    name_pattern: Pattern[str],
    diagnostic_prefix: str,
    authority_error: type[RuntimeError],
    row_factory: Callable[[str, str, str, str], _MetadataRow],
) -> tuple[list[_MetadataRow], set[str]]:
    """Observe fixed-depth names without author bytes or Catalog selection.

    Own every root/descriptor check and close; the product supplies only its
    name/budget policy, diagnostic binding and pure returned-value projection.
    """

    rows: list[_MetadataRow] = []
    diagnostics: set[str] = {f"{diagnostic_prefix}native_metadata_fallback"}
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        diagnostics.add(f"{diagnostic_prefix}native_fallback_unsupported")
        return rows, diagnostics
    roots = [(receipt.project_resource_root, "project_local", "workspace")]
    roots.extend((root, "user_global", "user") for root in receipt.user_resource_roots)
    if len(roots) > 16:
        roots = roots[:16]
        diagnostics.add(f"{diagnostic_prefix}source_truncated")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    for root, source_class, scope in roots:
        if len(rows) >= max_rows:
            diagnostics.add(f"{diagnostic_prefix}source_truncated")
            break
        try:
            before = root.lstat()
            if not stat.S_ISDIR(before.st_mode) or root.resolve(strict=True) != root:
                raise authority_error("declared root is unsafe")
            root_fd = os.open(root, flags)
        except FileNotFoundError:
            diagnostics.add(f"{diagnostic_prefix}native_root_unavailable")
            continue
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise authority_error("declared root became a link") from exc
            diagnostics.add(f"{diagnostic_prefix}native_root_unavailable")
            continue
        opened = before
        try:
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise authority_error("declared root changed on open")
            for dirname, resource_kind, suffix in (
                ("skills", "skill", None),
                ("prompts", "prompt", ".md"),
                ("themes", "theme", ".json"),
            ):
                if len(rows) >= max_rows:
                    diagnostics.add(f"{diagnostic_prefix}source_truncated")
                    break
                try:
                    directory_fd = os.open(dirname, flags, dir_fd=root_fd)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        try:
                            current = os.stat(
                                dirname, dir_fd=root_fd, follow_symlinks=False
                            )
                        except OSError:
                            raise authority_error(
                                "native directory changed during open"
                            ) from exc
                        if stat.S_ISLNK(current.st_mode):
                            raise authority_error(
                                "native directory became a link"
                            ) from exc
                    diagnostics.add(f"{diagnostic_prefix}native_root_unavailable")
                    continue
                try:
                    with os.scandir(directory_fd) as entries:
                        for index, entry in enumerate(entries):
                            if index >= max_rows or len(rows) >= max_rows:
                                diagnostics.add(f"{diagnostic_prefix}source_truncated")
                                break
                            try:
                                if suffix is None:
                                    if not entry.is_dir(follow_symlinks=False):
                                        diagnostics.add(
                                            f"{diagnostic_prefix}native_entry_skipped"
                                        )
                                        continue
                                    if name_pattern.fullmatch(entry.name) is None:
                                        diagnostics.add(
                                            f"{diagnostic_prefix}native_entry_skipped"
                                        )
                                        continue
                                    child_fd = os.open(
                                        entry.name, flags, dir_fd=directory_fd
                                    )
                                    try:
                                        metadata = os.stat(
                                            "SKILL.md",
                                            dir_fd=child_fd,
                                            follow_symlinks=False,
                                        )
                                    finally:
                                        os.close(child_fd)
                                    name = f"{entry.name}/SKILL.md"
                                else:
                                    if not entry.name.endswith(suffix):
                                        continue
                                    if (
                                        name_pattern.fullmatch(
                                            entry.name[: -len(suffix)]
                                        )
                                        is None
                                    ):
                                        diagnostics.add(
                                            f"{diagnostic_prefix}native_entry_skipped"
                                        )
                                        continue
                                    metadata = os.stat(
                                        entry.name,
                                        dir_fd=directory_fd,
                                        follow_symlinks=False,
                                    )
                                    name = entry.name
                                if not stat.S_ISREG(metadata.st_mode):
                                    diagnostics.add(
                                        f"{diagnostic_prefix}native_entry_skipped"
                                    )
                                    continue
                            except OSError as exc:
                                if exc.errno == errno.ELOOP:
                                    raise authority_error(
                                        "native child became a link"
                                    ) from exc
                                diagnostics.add(
                                    f"{diagnostic_prefix}native_entry_skipped"
                                )
                                continue
                            rows.append(
                                row_factory(name, resource_kind, source_class, scope)
                            )
                finally:
                    os.close(directory_fd)
        finally:
            os.close(root_fd)
            try:
                after = root.lstat()
                if (
                    not stat.S_ISDIR(after.st_mode)
                    or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
                    or root.resolve(strict=True) != root
                ):
                    raise authority_error("declared root changed during read")
            except OSError as exc:
                raise authority_error("declared root disappeared") from exc
    return rows, diagnostics

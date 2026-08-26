"""Pure package-layout inventory used by Package Catalog summaries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Protocol

from loushang.harness.resources._discovery_conventions import IGNORE_FILE_NAMES
from loushang.harness.resources._resource_item_projection import project_catalog_item
from loushang.harness.resources._skill_ignore import (
    is_skill_path_ignored,
    normalize_skill_ignore_pattern,
)
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.types import PackageResourceSummary


class PackageResourceInventoryPort(Protocol):
    """Summarize package contents without selecting effective Resources."""

    def summarize(
        self,
        package_root: Path,
        package_source: PackageSourceConfig | None = None,
    ) -> PackageResourceSummary: ...


@dataclass(frozen=True, slots=True)
class FilesystemPackageResourceInventory:
    """Read-only conventional-layout inventory; owns no Catalog or loader."""

    def summarize(
        self,
        package_root: Path,
        package_source: PackageSourceConfig | None = None,
    ) -> PackageResourceSummary:
        root = Path(package_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return PackageResourceSummary(source_root=root, diagnostic_count=1)

        prompt_count, prompt_diagnostics = _prompt_inventory(
            root,
            patterns=package_source.prompts if package_source is not None else None,
        )
        skill_count, skill_diagnostics = _skill_inventory(
            root,
            patterns=package_source.skills if package_source is not None else None,
        )
        extension_count, extension_diagnostics = _extension_inventory(
            root,
            patterns=package_source.extensions if package_source is not None else None,
        )
        theme_count, theme_diagnostics = _theme_inventory(
            root,
            patterns=package_source.themes if package_source is not None else None,
        )
        diagnostic_count = (
            prompt_diagnostics
            + skill_diagnostics
            + extension_diagnostics
            + theme_diagnostics
        )
        if (
            prompt_count
            + skill_count
            + extension_count
            + theme_count
            + diagnostic_count
            == 0
        ):
            diagnostic_count = 1
        return PackageResourceSummary(
            source_root=root,
            prompt_count=prompt_count,
            skill_count=skill_count,
            extension_count=extension_count,
            theme_count=theme_count,
            diagnostic_count=diagnostic_count,
        )


def summarize_package_inventory(
    package_root: Path,
    package_source: PackageSourceConfig | None = None,
    *,
    inventory: PackageResourceInventoryPort | None = None,
) -> PackageResourceSummary:
    return (inventory or FilesystemPackageResourceInventory()).summarize(
        package_root,
        package_source,
    )


def _prompt_inventory(
    root: Path,
    *,
    patterns: tuple[str, ...] | None,
) -> tuple[int, int]:
    directory = root / "prompts"
    if directory.is_symlink():
        return 0, 1
    if not directory.is_dir():
        return 0, 0
    count = 0
    diagnostics = 0
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.is_symlink() or not entry.is_file() or entry.suffix != ".md":
            diagnostics += 1
            continue
        try:
            body = entry.read_bytes()
        except OSError:
            diagnostics += 1
            continue
        projection = project_catalog_item(
            resource_kind="prompt",
            logical_path=PurePosixPath("prompts", entry.name),
            body=body,
            fallback_public_id=entry.stem,
            source_kind="external_package",
            source_scope="package",
            source_label="package_inventory",
            source_root_order=0,
        )
        if projection is None or not projection.valid:
            diagnostics += len(projection.diagnostic_reasons) if projection else 1
            continue
        diagnostics += len(projection.diagnostic_reasons)
        values = (
            entry.stem,
            projection.public_id,
            entry.name,
            f"prompts/{entry.name}",
        )
        if _matches(values, patterns):
            count += 1
    return count, diagnostics


def _skill_inventory(
    root: Path,
    *,
    patterns: tuple[str, ...] | None,
) -> tuple[int, int]:
    directory = root / "skills"
    if directory.is_symlink():
        return 0, 1
    if not directory.is_dir():
        return 0, 0
    return _skill_directory_inventory(
        directory,
        root=directory,
        ignore_patterns=(),
        package_patterns=patterns,
    )


def _skill_directory_inventory(
    current: Path,
    *,
    root: Path,
    ignore_patterns: tuple[str, ...],
    package_patterns: tuple[str, ...] | None,
) -> tuple[int, int]:
    active_ignore_patterns = (
        *ignore_patterns,
        *_read_skill_ignore_patterns(current, root=root),
    )
    skill_file = current / "SKILL.md"
    if skill_file.is_symlink():
        return 0, 1
    if skill_file.is_file():
        try:
            body = skill_file.read_bytes()
        except OSError:
            return 0, 1
        relative = skill_file.relative_to(root)
        logical = PurePosixPath("skills", *relative.parts)
        projection = project_catalog_item(
            resource_kind="skill",
            logical_path=logical,
            body=body,
            fallback_public_id=skill_file.parent.name,
            source_kind="external_package",
            source_scope="package",
            source_label="package_inventory",
            source_root_order=0,
        )
        if projection is None or not projection.valid:
            return 0, len(projection.diagnostic_reasons) if projection else 1
        diagnostics = len(projection.diagnostic_reasons)
        values = (
            skill_file.parent.name,
            projection.public_id,
            relative.as_posix(),
            logical.as_posix(),
            "SKILL.md",
        )
        return (
            (1, diagnostics) if _matches(values, package_patterns) else (0, diagnostics)
        )

    count = 0
    diagnostics = 0
    for entry in sorted(current.iterdir(), key=lambda item: item.name):
        if entry.is_symlink():
            if entry.name not in IGNORE_FILE_NAMES:
                diagnostics += 1
            continue
        if entry.is_file():
            if current == root and entry.name not in IGNORE_FILE_NAMES:
                diagnostics += 1
            continue
        if (
            not entry.is_dir()
            or entry.name.startswith(".")
            or entry.name == "node_modules"
            or is_skill_path_ignored(
                entry,
                root_dir=root,
                patterns=active_ignore_patterns,
            )
        ):
            continue
        child_count, child_diagnostics = _skill_directory_inventory(
            entry,
            root=root,
            ignore_patterns=active_ignore_patterns,
            package_patterns=package_patterns,
        )
        count += child_count
        diagnostics += child_diagnostics
    return count, diagnostics


def _read_skill_ignore_patterns(current: Path, *, root: Path) -> tuple[str, ...]:
    relative = current.relative_to(root).as_posix()
    prefix = "" if relative == "." else relative
    patterns: list[str] = []
    for filename in IGNORE_FILE_NAMES:
        ignore_file = current / filename
        if ignore_file.is_symlink() or not ignore_file.is_file():
            continue
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for raw_line in lines:
            pattern = normalize_skill_ignore_pattern(raw_line, prefix=prefix)
            if pattern is not None:
                patterns.append(pattern)
    return tuple(patterns)


def _extension_inventory(
    root: Path,
    *,
    patterns: tuple[str, ...] | None,
) -> tuple[int, int]:
    directory = root / "extensions"
    if directory.is_symlink():
        return 0, 1
    if not directory.is_dir():
        return 0, 0
    count = 0
    diagnostics = 0
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        canonical: str | None = None
        if entry.is_symlink():
            diagnostics += 1
            continue
        name = entry.stem if entry.is_file() else entry.name
        if entry.is_file() and entry.suffix == ".py":
            canonical = entry.name
        elif entry.is_dir() and any(
            (entry / filename).is_file() and not (entry / filename).is_symlink()
            for filename in ("extension.py", "__init__.py")
        ):
            canonical = entry.name
        else:
            diagnostics += 1
        if canonical is not None and _matches(
            (name, canonical, f"extensions/{canonical}"),
            patterns,
        ):
            count += 1
    return count, diagnostics


def _theme_inventory(
    root: Path,
    *,
    patterns: tuple[str, ...] | None,
) -> tuple[int, int]:
    directory = root / "themes"
    if directory.is_symlink():
        return 0, 1
    if not directory.is_dir():
        return 0, 0
    count = 0
    diagnostics = 0
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.is_symlink():
            diagnostics += 1
            continue
        if entry.is_file():
            if entry.suffix != ".json":
                diagnostics += 1
                continue
            try:
                payload = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                diagnostics += 1
                continue
            if not isinstance(payload, dict):
                diagnostics += 1
                continue
            name = entry.stem
        elif entry.is_dir():
            name = entry.name
        else:
            diagnostics += 1
            continue
        if _matches((name, entry.name, f"themes/{entry.name}"), patterns):
            count += 1
    return count, diagnostics


def _matches(values: tuple[str, ...], patterns: tuple[str, ...] | None) -> bool:
    if patterns is None:
        return True
    if not patterns:
        return False
    includes = tuple(
        pattern for pattern in patterns if not pattern.startswith(("!", "+", "-"))
    )
    excludes = tuple(pattern[1:] for pattern in patterns if pattern.startswith("!"))
    force_includes = tuple(
        pattern[1:] for pattern in patterns if pattern.startswith("+")
    )
    force_excludes = tuple(
        pattern[1:] for pattern in patterns if pattern.startswith("-")
    )
    enabled = not includes or any(
        fnmatch(value, pattern) for value in values for pattern in includes
    )
    if any(fnmatch(value, pattern) for value in values for pattern in excludes):
        enabled = False
    if any(
        value == pattern.lstrip("./") for value in values for pattern in force_includes
    ):
        enabled = True
    if any(
        value == pattern.lstrip("./") for value in values for pattern in force_excludes
    ):
        enabled = False
    return enabled


__all__ = [
    "FilesystemPackageResourceInventory",
    "PackageResourceInventoryPort",
    "summarize_package_inventory",
]

"""Package-root normalization, filtering, diagnostics, and accounting policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_types import DescriptorT
from loushang.harness.resources.diagnostics import resource_diagnostic

if TYPE_CHECKING:
    from loushang.harness.resources.packages.source import PackageSourceConfig


def _normalize_package_roots(
    package_roots: Sequence[str | Path] | None,
) -> tuple[Path, ...]:
    if not package_roots:
        return ()
    return tuple(Path(root).expanduser().resolve() for root in package_roots)


def _normalize_package_source_filters(
    package_source_filters: Mapping[str | Path, PackageSourceConfig] | None,
) -> dict[Path, PackageSourceConfig]:
    if not package_source_filters:
        return {}
    return {
        Path(root).expanduser().resolve(): config
        for root, config in package_source_filters.items()
    }


def _filter_package_descriptors(
    descriptors: list[DescriptorT],
    *,
    root: Path,
    patterns: tuple[str, ...] | None,
) -> list[DescriptorT]:
    if patterns is None:
        return descriptors
    if not patterns:
        return []
    includes = [pattern for pattern in patterns if not _is_override_pattern(pattern)]
    excludes = [pattern[1:] for pattern in patterns if pattern.startswith("!")]
    force_includes = [pattern[1:] for pattern in patterns if pattern.startswith("+")]
    force_excludes = [pattern[1:] for pattern in patterns if pattern.startswith("-")]
    filtered: list[DescriptorT] = []
    for descriptor in descriptors:
        enabled = (
            True
            if not includes
            else _descriptor_matches_patterns(
                descriptor, root=root, patterns=tuple(includes)
            )
        )
        if excludes and _descriptor_matches_patterns(
            descriptor, root=root, patterns=tuple(excludes)
        ):
            enabled = False
        if force_includes and _descriptor_matches_patterns(
            descriptor, root=root, patterns=tuple(force_includes), exact=True
        ):
            enabled = True
        if force_excludes and _descriptor_matches_patterns(
            descriptor, root=root, patterns=tuple(force_excludes), exact=True
        ):
            enabled = False
        if enabled:
            filtered.append(descriptor)
    return filtered


def _is_override_pattern(pattern: str) -> bool:
    return pattern.startswith(("!", "+", "-"))


def _descriptor_matches_patterns(
    descriptor: DescriptorT,
    *,
    root: Path,
    patterns: tuple[str, ...],
    exact: bool = False,
) -> bool:
    values = _descriptor_match_values(descriptor, root=root)
    if exact:
        return any(
            value == pattern.lstrip("./") for pattern in patterns for value in values
        )
    return any(fnmatch(value, pattern) for pattern in patterns for value in values)


def _descriptor_match_values(descriptor: DescriptorT, *, root: Path) -> tuple[str, ...]:
    values = {
        descriptor.name,
        descriptor.id or "",
        descriptor.canonical_name or "",
        descriptor.source_path.name,
        descriptor.source_path.parent.name,
    }
    try:
        relative_path = descriptor.source_path.resolve().relative_to(root).as_posix()
    except ValueError:
        relative_path = descriptor.source_path.as_posix()
    values.add(relative_path)
    return tuple(value for value in values if value)


def _package_root_diagnostic(code: str, message: str, root: Path) -> DiagnosticDraft:
    return resource_diagnostic(
        code=code,
        message=message,
        source_path=root,
        resource_type="package",
        source_kind="external_package",
        metadata={"package_root": str(root)},
    )


def _count_package_descriptors(descriptors: tuple[DescriptorT, ...], root: Path) -> int:
    return sum(
        1
        for descriptor in descriptors
        if _path_belongs_to_root(descriptor.source_path, root)
    )


def _count_package_diagnostics(
    diagnostics: tuple[DiagnosticDraft, ...], root: Path
) -> int:
    return sum(
        1 for diagnostic in diagnostics if _diagnostic_belongs_to_root(diagnostic, root)
    )


def _diagnostic_belongs_to_root(diagnostic: DiagnosticDraft, root: Path) -> bool:
    metadata = diagnostic.details.get("metadata")
    package_root = metadata.get("package_root") if isinstance(metadata, dict) else None
    if package_root == str(root):
        return True
    if diagnostic.source_path is None:
        return False
    return _path_belongs_to_root(diagnostic.source_path, root)


def _path_belongs_to_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True

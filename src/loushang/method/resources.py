from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from loushang.harness.resources.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})


class SkillResourceLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def source_path(self) -> Path: ...

    @property
    def content(self) -> str | None: ...

    @property
    def description(self) -> str | None: ...

    @property
    def metadata(self) -> Mapping[str, object]: ...

    @property
    def id(self) -> str | None: ...

    @property
    def source_kind(self) -> str: ...

    @property
    def source_scope(self) -> str: ...

    @property
    def resource_type(self) -> str: ...


class SkillResourceBundleLike(Protocol):
    @property
    def skills(self) -> Sequence[SkillResourceLike]: ...


class SkillResourceLoader(Protocol):
    def discover_resources(self, cwd: str | Path) -> SkillResourceBundleLike: ...


@dataclass(frozen=True)
class SkillResource:
    name: str
    source_path: Path
    content: str | None = None
    description: str | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    id: str | None = None
    source_kind: str = "project_local"
    source_scope: str = "project"
    resource_type: str = "skill"
    source_root: Path | None = None
    source_root_order: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", self.id or self.name)


@dataclass(frozen=True)
class SkillResourceBundle:
    skills: tuple[SkillResource, ...] = ()


def discover_skill_resources(
    cwd: str | Path,
    *,
    package_roots: Sequence[str | Path] = (),
) -> tuple[SkillResource, ...]:
    root = Path(cwd)
    resources: list[SkillResource] = []
    resources.extend(
        _discover_skill_resources_from_dir(
            root / "skills",
            source_kind="project_local",
            source_scope="project",
            source_root_order=0,
        )
    )
    for index, package_root in enumerate(package_roots):
        resources.extend(
            _discover_skill_resources_from_dir(
                Path(package_root) / "skills",
                source_kind="external_package",
                source_scope="package",
                source_root_order=index,
            )
        )
    return tuple(resources)


def _discover_skill_resources_from_dir(
    skills_dir: Path,
    *,
    source_kind: str,
    source_scope: str,
    source_root_order: int,
) -> list[SkillResource]:
    if not skills_dir.is_dir():
        return []
    return _discover_skill_resources_recursive(
        skills_dir,
        root_dir=skills_dir,
        source_kind=source_kind,
        source_scope=source_scope,
        source_root_order=source_root_order,
    )


def _discover_skill_resources_recursive(
    current_dir: Path,
    *,
    root_dir: Path,
    source_kind: str,
    source_scope: str,
    source_root_order: int,
) -> list[SkillResource]:
    skill_file = current_dir / "SKILL.md"
    if skill_file.is_file():
        resource = _skill_resource_from_file(
            skill_file,
            root_dir=root_dir,
            parent_name=current_dir.name,
            source_kind=source_kind,
            source_scope=source_scope,
            source_root_order=source_root_order,
        )
        return [resource] if resource is not None else []

    resources: list[SkillResource] = []
    for entry in sorted(current_dir.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or _skip_skill_directory(entry):
            continue
        resources.extend(
            _discover_skill_resources_recursive(
                entry,
                root_dir=root_dir,
                source_kind=source_kind,
                source_scope=source_scope,
                source_root_order=source_root_order,
            )
        )
    return resources


def _skill_resource_from_file(
    skill_file: Path,
    *,
    root_dir: Path,
    parent_name: str,
    source_kind: str,
    source_scope: str,
    source_root_order: int,
) -> SkillResource | None:
    try:
        content = skill_file.read_text(encoding="utf-8")
        parsed = parse_frontmatter(content)
    except (OSError, UnicodeError, FrontmatterParseError):
        return None

    frontmatter = parsed.frontmatter
    return SkillResource(
        name=_string_hint(frontmatter, "name") or parent_name,
        source_path=skill_file,
        content=content,
        description=_string_hint(frontmatter, "description"),
        metadata={
            "frontmatter": frontmatter,
            "body": parsed.body,
        },
        source_kind=source_kind,
        source_scope=source_scope,
        source_root=root_dir,
        source_root_order=source_root_order,
    )


def _skip_skill_directory(path: Path) -> bool:
    return path.name.startswith(".") or path.name == "node_modules"


def _string_hint(frontmatter: Mapping[str, object], key: str) -> str | None:
    value = frontmatter.get(key)
    if isinstance(value, str) and value:
        return value
    return None


__all__ = [
    "SkillResource",
    "SkillResourceBundle",
    "SkillResourceBundleLike",
    "SkillResourceLike",
    "SkillResourceLoader",
    "discover_skill_resources",
]

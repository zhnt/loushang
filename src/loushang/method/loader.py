from __future__ import annotations

from collections.abc import Iterable, Sequence
from collections.abc import Mapping as MappingABC
from pathlib import Path
from typing import Literal

from loushang.harness.resources.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)
from loushang.method.applicability import applicability_from_frontmatter, primary_domain
from loushang.method.legacy_skill_adapter import method_from_skill
from loushang.method.resources import (
    SkillResourceLike,
    SkillResourceLoader,
    discover_skill_resources,
)
from loushang.method.types import MethodDescriptor

_METHOD_ELEMENT_TYPES = frozenset({"phase", "activity", "task", "role", "guidance", "workproduct"})


class MethodLoader:
    def __init__(
        self,
        resource_loader: SkillResourceLoader | None = None,
        package_roots: tuple[str | Path, ...] = (),
        skill_authority: Literal["none", "legacy_explicit"] = "none",
    ) -> None:
        if skill_authority not in {"none", "legacy_explicit"}:
            raise ValueError("Method Skill authority is invalid")
        if resource_loader is not None and skill_authority != "legacy_explicit":
            raise ValueError(
                "Method ResourceLoader requires explicit legacy Skill authority"
            )
        self._package_roots = tuple(Path(root) for root in package_roots)
        self._resource_loader = resource_loader
        self._skill_authority = skill_authority
        self._methods: tuple[MethodDescriptor, ...] = ()
        self._cwd: Path | None = None

    def discover_methods(self, cwd: str | Path) -> list[MethodDescriptor]:
        root = Path(cwd)
        skill_methods: list[MethodDescriptor] = []
        if self._skill_authority == "legacy_explicit":
            skills: Sequence[SkillResourceLike]
            if self._resource_loader is None:
                skills = discover_skill_resources(
                    root,
                    package_roots=self._package_roots,
                )
            else:
                skills = self._resource_loader.discover_resources(root).skills
            skill_methods = [method_from_skill(skill) for skill in skills]
        package_method_resources: list[MethodDescriptor] = []
        for index, package_root in enumerate(self._package_roots):
            package_method_resources.extend(
                _discover_method_resources(
                    package_root,
                    source_kind="external_package",
                    source_scope="package",
                    source_root_order=index,
                )
            )
        project_method_resources = _discover_method_resources(
            root,
            source_kind="project_local",
            source_scope="project",
            source_root_order=0,
        )
        return _deduplicate_by_name([*skill_methods, *package_method_resources, *project_method_resources])

    def reload_methods(self, cwd: str | Path | None = None) -> list[MethodDescriptor]:
        root = Path(cwd) if cwd is not None else self._cwd or Path.cwd()
        methods = tuple(self.discover_methods(root))
        self._methods = methods
        self._cwd = root
        return list(methods)

    def list_methods(self) -> list[MethodDescriptor]:
        return list(self._methods)

    def get_method(self, id_or_name: str) -> MethodDescriptor | None:
        for method in self._methods:
            if method.id == id_or_name or method.name == id_or_name:
                return method
        return None


def _discover_method_resources(
    root: Path,
    *,
    source_kind: str,
    source_scope: str,
    source_root_order: int,
) -> list[MethodDescriptor]:
    methods_root = root / "methods"
    if not methods_root.is_dir():
        return []
    descriptors: list[MethodDescriptor] = []
    for skill_file in sorted(methods_root.rglob("SKILL.md")):
        descriptor = _method_resource_from_file(
            skill_file,
            methods_root=methods_root,
            source_kind=source_kind,
            source_scope=source_scope,
            source_root_order=source_root_order,
        )
        if descriptor is not None:
            descriptors.append(descriptor)
    return descriptors


def _method_resource_from_file(
    skill_file: Path,
    *,
    methods_root: Path,
    source_kind: str,
    source_scope: str,
    source_root_order: int,
) -> MethodDescriptor | None:
    try:
        content = skill_file.read_text(encoding="utf-8")
        parsed = parse_frontmatter(content)
    except (OSError, UnicodeError, FrontmatterParseError):
        return None

    frontmatter = parsed.frontmatter
    applicability = applicability_from_frontmatter(frontmatter)
    relative_parts = skill_file.relative_to(methods_root).parts
    path_element_type = relative_parts[0] if relative_parts and relative_parts[0] in _METHOD_ELEMENT_TYPES else None
    element_type = _string_hint(frontmatter, "type") or path_element_type
    name = _string_hint(frontmatter, "name") or skill_file.parent.name
    metadata = {
        "frontmatter": frontmatter,
        "body": parsed.body,
        "source_kind": source_kind,
        "source_scope": source_scope,
        "resource_type": "method",
        "source_root": methods_root.as_posix(),
        "source_root_order": source_root_order,
        "relative_path": skill_file.relative_to(methods_root).as_posix(),
    }
    return MethodDescriptor(
        id=_method_resource_id(name=name, element_type=element_type),
        name=name,
        description=_string_hint(frontmatter, "description") or "",
        content=content,
        kind="method_resource",
        element_type=element_type,
        domain=primary_domain(frontmatter, applicability),
        meta_role=_first_string_hint(frontmatter, ("meta_role", "meta-role", "role")),
        phase=_string_hint(frontmatter, "phase"),
        source_path=skill_file.as_posix(),
        version=_string_hint(frontmatter, "version"),
        metadata=metadata,
        applicability=applicability,
    )


def _method_resource_id(*, name: str, element_type: str | None) -> str:
    if element_type:
        return f"method:{element_type}:{name}"
    return f"method:{name}"


def _deduplicate_by_name(methods: Iterable[MethodDescriptor]) -> list[MethodDescriptor]:
    by_name: dict[str, MethodDescriptor] = {}
    for method in methods:
        by_name[method.name] = method
    return list(by_name.values())


def _first_string_hint(frontmatter: MappingABC[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if value := _string_hint(frontmatter, key):
            return value
    return None


def _string_hint(frontmatter: MappingABC[str, object], key: str) -> str | None:
    value = frontmatter.get(key)
    if isinstance(value, str) and value:
        return value
    return None


__all__ = ["MethodLoader"]

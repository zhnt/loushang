"""Explicit ``legacy_explicit`` Skill-to-Method compatibility adapter."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC

from loushang.method.applicability import applicability_from_frontmatter, primary_domain
from loushang.method.resources import SkillResourceLike
from loushang.method.types import MethodDescriptor


def method_from_skill(skill: SkillResourceLike) -> MethodDescriptor:
    """Adapt one eager legacy Skill; Catalog callers must not use this path."""

    frontmatter = _frontmatter(skill.metadata)
    applicability = applicability_from_frontmatter(frontmatter)
    metadata = {
        **dict(skill.metadata),
        "source_kind": skill.source_kind,
        "source_scope": skill.source_scope,
        "resource_type": skill.resource_type,
        "skill_id": skill.id,
        "skill_name": skill.name,
    }
    return MethodDescriptor(
        id=_skill_method_id(skill.name),
        name=skill.name,
        description=skill.description or "",
        content=skill.content or "",
        kind="skill_backed",
        element_type=_string_hint(frontmatter, "type"),
        domain=primary_domain(frontmatter, applicability),
        meta_role=_first_string_hint(
            frontmatter,
            ("meta_role", "meta-role", "role"),
        ),
        phase=_string_hint(frontmatter, "phase"),
        source_path=skill.source_path.as_posix(),
        version=_string_hint(frontmatter, "version"),
        metadata=metadata,
        applicability=applicability,
    )


def _skill_method_id(skill_name: str) -> str:
    if skill_name.startswith("skill:"):
        return skill_name
    return f"skill:{skill_name}"


def _frontmatter(metadata: object) -> MappingABC[str, object]:
    if isinstance(metadata, MappingABC):
        frontmatter = metadata.get("frontmatter")
        if isinstance(frontmatter, MappingABC):
            return frontmatter
    return {}


def _first_string_hint(
    frontmatter: MappingABC[str, object],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        if value := _string_hint(frontmatter, key):
            return value
    return None


def _string_hint(
    frontmatter: MappingABC[str, object],
    key: str,
) -> str | None:
    value = frontmatter.get(key)
    if isinstance(value, str) and value:
        return value
    return None


__all__ = ["method_from_skill"]

"""Explicit eager-body compatibility helpers for ``legacy_explicit`` only."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from loushang.harness.resources.activation import ResourceActivation
from loushang.harness.resources.frontmatter import strip_frontmatter
from loushang.harness.resources.types import ResourceBundle, SkillDescriptor


@dataclass(frozen=True, slots=True)
class LegacySkillExpansion:
    """One legacy-only Skill expansion with no Catalog evidence claim."""

    text: str


def expand_legacy_skill_input(
    *,
    skill_name: str,
    resource_bundle: ResourceBundle | None,
) -> LegacySkillExpansion | None:
    """Expand one eager descriptor only at the explicit legacy boundary."""

    skill = ResourceActivation(resource_bundle).find_skill(skill_name)
    if skill is None:
        return None
    body = strip_frontmatter(skill.content or "").strip()
    source_path = skill.source_path.as_posix()
    base_dir = skill.source_path.parent.as_posix()
    skill_block = (
        f'<skill name="{escape(skill.name, quote=True)}" '
        f'location="{escape(source_path, quote=True)}">\n'
        f"References are relative to {base_dir}.\n\n"
        f"{body}\n"
        "</skill>"
    )
    return LegacySkillExpansion(text=skill_block)


def legacy_skill_description(skill: SkillDescriptor) -> str | None:
    """Return the historical body fallback for an explicit legacy caller."""

    if isinstance(skill.description, str) and skill.description.strip():
        return skill.description.strip()
    description = strip_frontmatter(skill.content or "").strip()
    return description or None


__all__ = [
    "LegacySkillExpansion",
    "expand_legacy_skill_input",
    "legacy_skill_description",
]

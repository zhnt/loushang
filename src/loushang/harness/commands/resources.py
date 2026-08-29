"""Resource-backed command descriptors for Agent product sessions."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from loushang.harness.commands.descriptors import SessionCommandDescriptor
from loushang.harness.resources._legacy_skill_body import legacy_skill_description
from loushang.harness.resources.frontmatter import strip_frontmatter
from loushang.harness.resources.source import source_info_from_resource_descriptor
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)


class SkillCommandSummary(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str | None: ...

    @property
    def source_path(self) -> Path: ...

    @property
    def source(self) -> str: ...

    @property
    def source_kind(self) -> str: ...

    @property
    def source_scope(self) -> str: ...

    @property
    def source_root(self) -> Path | None: ...


def list_resource_command_descriptors(
    resource_bundle: ResourceBundle | None,
    *,
    effective_skills: Sequence[SkillCommandSummary] | None = None,
    allow_legacy_skill_body: bool = False,
) -> list[SessionCommandDescriptor]:
    """Project enabled prompt and skill resources into command descriptors."""

    if resource_bundle is None and effective_skills is None:
        return []

    prompts = resource_bundle.prompts if resource_bundle is not None else ()
    commands = [
        SessionCommandDescriptor(
            name=prompt.name,
            description=command_description_from_prompt(prompt),
            source="prompt",
            source_info=source_info_from_resource_descriptor(prompt),
            argument_hint=prompt.argument_hint,
        )
        for prompt in prompts
    ]
    use_legacy_bundle_skills = (
        allow_legacy_skill_body
        and effective_skills is None
        and resource_bundle is not None
    )
    legacy_skills = (
        tuple(skill for skill in resource_bundle.skills if skill.enabled)
        if use_legacy_bundle_skills and resource_bundle is not None
        else ()
    )
    skills: Sequence[SkillCommandSummary] = (
        effective_skills if effective_skills is not None else legacy_skills
    )
    commands.extend(
        SessionCommandDescriptor(
            name=f"skill:{skill.name}",
            description=(
                legacy_skill_description(skill)
                if use_legacy_bundle_skills and isinstance(skill, SkillDescriptor)
                else command_description_from_skill(skill)
            ),
            source="skill",
            source_info=source_info_from_resource_descriptor(skill),
        )
        for skill in skills
    )
    return commands


def command_description_from_prompt(prompt: PromptFragmentDescriptor) -> str | None:
    """Prefer declared prompt metadata, then use its visible template body."""

    if isinstance(prompt.description, str) and prompt.description.strip():
        return prompt.description.strip()
    description = strip_frontmatter(prompt.text).strip()
    return description or None


def command_description_from_skill(
    skill: SkillDescriptor | SkillCommandSummary,
) -> str | None:
    """Return body-free declared Skill metadata for a typed projection."""

    if isinstance(skill.description, str) and skill.description.strip():
        return skill.description.strip()
    return None


__all__ = [
    "command_description_from_prompt",
    "command_description_from_skill",
    "list_resource_command_descriptors",
]

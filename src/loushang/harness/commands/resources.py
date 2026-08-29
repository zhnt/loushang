"""Resource-backed command descriptors for Agent product sessions."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from loushang.harness.commands.descriptors import SessionCommandDescriptor
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
    skills: Sequence[SkillCommandSummary] = (
        effective_skills
        if effective_skills is not None
        else tuple(
            skill
            for skill in resource_bundle.skills
            if skill.enabled
        )
        if resource_bundle is not None
        else ()
    )
    commands.extend(
        SessionCommandDescriptor(
            name=f"skill:{skill.name}",
            description=command_description_from_skill(skill),
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
    """Prefer declared skill metadata, then use its visible skill body."""

    if isinstance(skill.description, str) and skill.description.strip():
        return skill.description.strip()
    content = getattr(skill, "content", None)
    description = strip_frontmatter(content or "").strip()
    return description or None


__all__ = [
    "command_description_from_prompt",
    "command_description_from_skill",
    "list_resource_command_descriptors",
]

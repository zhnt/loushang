"""Resource-backed command descriptors for Agent product sessions."""

from __future__ import annotations

from loushang.harness.commands.descriptors import SessionCommandDescriptor
from loushang.harness.resources.frontmatter import strip_frontmatter
from loushang.harness.resources.source import source_info_from_resource_descriptor
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)


def list_resource_command_descriptors(
    resource_bundle: ResourceBundle | None,
) -> list[SessionCommandDescriptor]:
    """Project enabled prompt and skill resources into command descriptors."""

    if resource_bundle is None:
        return []

    commands = [
        SessionCommandDescriptor(
            name=prompt.name,
            description=command_description_from_prompt(prompt),
            source="prompt",
            source_info=source_info_from_resource_descriptor(prompt),
            argument_hint=prompt.argument_hint,
        )
        for prompt in resource_bundle.prompts
    ]
    commands.extend(
        SessionCommandDescriptor(
            name=f"skill:{skill.name}",
            description=command_description_from_skill(skill),
            source="skill",
            source_info=source_info_from_resource_descriptor(skill),
        )
        for skill in resource_bundle.skills
        if skill.enabled
    )
    return commands


def command_description_from_prompt(prompt: PromptFragmentDescriptor) -> str | None:
    """Prefer declared prompt metadata, then use its visible template body."""

    if isinstance(prompt.description, str) and prompt.description.strip():
        return prompt.description.strip()
    description = strip_frontmatter(prompt.text).strip()
    return description or None


def command_description_from_skill(skill: SkillDescriptor) -> str | None:
    """Prefer declared skill metadata, then use its visible skill body."""

    if isinstance(skill.description, str) and skill.description.strip():
        return skill.description.strip()
    description = strip_frontmatter(skill.content or "").strip()
    return description or None


__all__ = [
    "command_description_from_prompt",
    "command_description_from_skill",
    "list_resource_command_descriptors",
]

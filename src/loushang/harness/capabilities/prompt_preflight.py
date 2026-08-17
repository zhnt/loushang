"""Standard slash-command preflight for prompt and skill resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html import escape

from loushang.harness.capabilities.prompt import (
    DEFAULT_PROMPT_TEMPLATE_EXPANDER,
    PromptTemplateExpander,
    append_prompt_arguments,
    expand_prompt_template,
)
from loushang.harness.commands import split_slash_command
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources.activation import ResourceActivation
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.frontmatter import strip_frontmatter
from loushang.harness.resources.types import ResourceBundle


@dataclass(frozen=True)
class PromptPreflightResult:
    text: str
    consumed: bool = False
    diagnostics: tuple[DiagnosticDraft, ...] = field(default_factory=tuple)


def preflight_user_input(
    text: str,
    *,
    resource_bundle: ResourceBundle | None = None,
    template_expander: PromptTemplateExpander = DEFAULT_PROMPT_TEMPLATE_EXPANDER,
) -> PromptPreflightResult:
    parsed = split_slash_command(text)
    if parsed is None:
        return PromptPreflightResult(text=text)
    return _preflight_resource_input(
        text,
        parsed,
        resource_bundle=resource_bundle,
        template_expander=template_expander,
    )


async def preflight_user_input_async(
    text: str,
    *,
    resource_bundle: ResourceBundle | None = None,
    execute_command: Callable[[str, str], Awaitable[object | None]] | None = None,
    template_expander: PromptTemplateExpander = DEFAULT_PROMPT_TEMPLATE_EXPANDER,
) -> PromptPreflightResult:
    parsed = split_slash_command(text)
    if parsed is None:
        return PromptPreflightResult(text=text)

    command_name, args = parsed
    if execute_command is not None:
        await execute_command(command_name, args)
        return PromptPreflightResult(text=text, consumed=True)

    return _preflight_resource_input(
        text,
        parsed,
        resource_bundle=resource_bundle,
        template_expander=template_expander,
    )


def _preflight_resource_input(
    original_text: str,
    parsed: tuple[str, str],
    *,
    resource_bundle: ResourceBundle | None,
    template_expander: PromptTemplateExpander,
) -> PromptPreflightResult:
    command_name, args = parsed

    if command_name.startswith("skill:"):
        skill_name = command_name.removeprefix("skill:")
        skill = ResourceActivation(resource_bundle).find_skill(skill_name)
        if skill is None:
            return PromptPreflightResult(
                text=original_text,
                diagnostics=(
                    resource_diagnostic(
                        code="unresolved_skill_reference",
                        message=f"Skill reference '/skill:{skill_name}' did not match any discovered skill.",
                        resource_id=skill_name,
                        resource_type="skill",
                    ),
                ),
            )
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
        return PromptPreflightResult(text=append_prompt_arguments(skill_block, args))

    prompt = ResourceActivation(resource_bundle).find_prompt(command_name)
    if prompt is None:
        return PromptPreflightResult(
            text=original_text,
            diagnostics=(
                resource_diagnostic(
                    code="unresolved_prompt_reference",
                    message=f"Prompt reference '/{command_name}' did not match any discovered prompt template.",
                    resource_id=command_name,
                    resource_type="prompt",
                ),
            ),
        )
    prompt_text = strip_frontmatter(prompt.text).strip()
    return PromptPreflightResult(
        text=expand_prompt_template(
            prompt_text,
            args,
            expander=template_expander,
        )
    )


__all__ = [
    "PromptPreflightResult",
    "preflight_user_input",
    "preflight_user_input_async",
]

"""Standard slash-command preflight for prompt and skill resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Protocol

from loushang.harness.capabilities.prompt import (
    DEFAULT_PROMPT_TEMPLATE_EXPANDER,
    PromptTemplateExpander,
    append_prompt_arguments,
    expand_prompt_template,
)
from loushang.harness.commands import split_slash_command
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._legacy_skill_body import expand_legacy_skill_input
from loushang.harness.resources.activation import ResourceActivation
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.frontmatter import strip_frontmatter
from loushang.harness.resources.types import ResourceBundle


class SkillBodyLoadRequiresAsyncError(RuntimeError):
    """A captured Catalog Skill body cannot be loaded synchronously."""


class SkillBodyAuthorityUnavailableError(RuntimeError):
    """No explicit Skill body authority was selected for this preflight."""


class SkillPreflightSummary(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def canonical_name(self) -> str: ...

    @property
    def source_path(self) -> Path: ...


class LoadedSkillPreflightBody(Protocol):
    @property
    def summary(self) -> SkillPreflightSummary: ...

    @property
    def content(self) -> str: ...


SkillBodyLoader = Callable[[str], Awaitable[LoadedSkillPreflightBody | None]]


@dataclass(frozen=True)
class PromptPreflightResult:
    text: str
    consumed: bool = False
    diagnostics: tuple[DiagnosticDraft, ...] = field(default_factory=tuple)
    loaded_skills: tuple[LoadedSkillPreflightBody, ...] = field(
        default_factory=tuple,
        repr=False,
    )


def preflight_user_input(
    text: str,
    *,
    resource_bundle: ResourceBundle | None = None,
    load_skill_body: SkillBodyLoader | None = None,
    allow_legacy_skill_body: bool = False,
    template_expander: PromptTemplateExpander = DEFAULT_PROMPT_TEMPLATE_EXPANDER,
) -> PromptPreflightResult:
    parsed = split_slash_command(text)
    if parsed is None:
        return PromptPreflightResult(text=text)
    return _preflight_resource_input(
        text,
        parsed,
        resource_bundle=resource_bundle,
        load_skill_body=load_skill_body,
        allow_legacy_skill_body=allow_legacy_skill_body,
        template_expander=template_expander,
    )


async def preflight_user_input_async(
    text: str,
    *,
    resource_bundle: ResourceBundle | None = None,
    execute_command: Callable[[str, str], Awaitable[object | None]] | None = None,
    load_skill_body: SkillBodyLoader | None = None,
    allow_legacy_skill_body: bool = False,
    template_expander: PromptTemplateExpander = DEFAULT_PROMPT_TEMPLATE_EXPANDER,
) -> PromptPreflightResult:
    parsed = split_slash_command(text)
    if parsed is None:
        return PromptPreflightResult(text=text)

    command_name, args = parsed
    if command_name.startswith("skill:") and load_skill_body is not None:
        return await _preflight_catalog_skill_input(
            text,
            command_name.removeprefix("skill:"),
            args,
            load_skill_body=load_skill_body,
        )

    if execute_command is not None:
        await execute_command(command_name, args)
        return PromptPreflightResult(text=text, consumed=True)

    return _preflight_resource_input(
        text,
        parsed,
        resource_bundle=resource_bundle,
        load_skill_body=None,
        allow_legacy_skill_body=allow_legacy_skill_body,
        template_expander=template_expander,
    )


def _preflight_resource_input(
    original_text: str,
    parsed: tuple[str, str],
    *,
    resource_bundle: ResourceBundle | None,
    load_skill_body: SkillBodyLoader | None,
    allow_legacy_skill_body: bool,
    template_expander: PromptTemplateExpander,
) -> PromptPreflightResult:
    command_name, args = parsed

    if command_name.startswith("skill:"):
        skill_name = command_name.removeprefix("skill:")
        if load_skill_body is not None:
            raise SkillBodyLoadRequiresAsyncError(
                "Catalog Skill body loading requires asynchronous preflight"
            )
        if not allow_legacy_skill_body:
            raise SkillBodyAuthorityUnavailableError(
                "Skill body expansion requires Catalog async loading or "
                "explicit legacy authority"
            )
        expanded = expand_legacy_skill_input(
            skill_name=skill_name,
            resource_bundle=resource_bundle,
        )
        if expanded is None:
            return _unresolved_skill(original_text, skill_name)
        return PromptPreflightResult(
            text=append_prompt_arguments(expanded.text, args)
        )

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


async def _preflight_catalog_skill_input(
    original_text: str,
    skill_name: str,
    args: str,
    *,
    load_skill_body: SkillBodyLoader,
) -> PromptPreflightResult:
    if not skill_name:
        return _unresolved_skill(original_text, skill_name)
    loaded = await load_skill_body(skill_name)
    if loaded is None:
        return _unresolved_skill(original_text, skill_name)
    summary = loaded.summary
    skill_id = summary.id
    name = summary.name
    canonical_name = summary.canonical_name
    source_path = summary.source_path
    content = loaded.content
    if not isinstance(skill_id, str) or not skill_id:
        raise TypeError("Loaded Skill summary id is invalid")
    if not isinstance(name, str) or not name:
        raise TypeError("Loaded Skill summary name is invalid")
    if not isinstance(canonical_name, str) or not canonical_name:
        raise TypeError("Loaded Skill summary canonical name is invalid")
    if not isinstance(source_path, Path):
        raise TypeError("Loaded Skill summary path is invalid")
    if not isinstance(content, str):
        raise TypeError("Loaded Skill content is invalid")
    if skill_name not in {
        skill_id,
        name,
        canonical_name,
        str(source_path),
    }:
        raise ValueError("Loaded Skill summary does not match the requested Skill")
    body = strip_frontmatter(content).strip()
    source_path_text = source_path.as_posix()
    base_dir = source_path.parent.as_posix()
    skill_block = (
        f'<skill name="{escape(name, quote=True)}" '
        f'location="{escape(source_path_text, quote=True)}">\n'
        f"References are relative to {base_dir}.\n\n"
        f"{body}\n"
        "</skill>"
    )
    return PromptPreflightResult(
        text=append_prompt_arguments(skill_block, args),
        loaded_skills=(loaded,),
    )


def _unresolved_skill(original_text: str, skill_name: str) -> PromptPreflightResult:
    return PromptPreflightResult(
        text=original_text,
        diagnostics=(
            resource_diagnostic(
                code="unresolved_skill_reference",
                message=(
                    f"Skill reference '/skill:{skill_name}' did not match any "
                    "discovered skill."
                ),
                resource_id=skill_name,
                resource_type="skill",
            ),
        ),
    )


__all__ = [
    "PromptPreflightResult",
    "LoadedSkillPreflightBody",
    "SkillBodyLoader",
    "SkillBodyAuthorityUnavailableError",
    "SkillBodyLoadRequiresAsyncError",
    "preflight_user_input",
    "preflight_user_input_async",
]

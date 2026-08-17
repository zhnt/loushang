"""Source-neutral descriptor parsing for discovered resource content."""

from __future__ import annotations

from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceSourceKind,
    ResourceSourceScope,
    SkillDescriptor,
)

_MAX_SKILL_NAME_LENGTH = 64

_MAX_SKILL_DESCRIPTION_LENGTH = 1024


def _prompt_descriptor_from_text(
    *,
    name: str,
    source_path: Path,
    text: str,
    canonical_name: str,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source: str,
    source_root: Path,
    source_root_order: int = 0,
) -> tuple[PromptFragmentDescriptor | None, list[DiagnosticDraft]]:
    try:
        parsed = parse_frontmatter(text)
    except FrontmatterParseError as exc:
        return None, [
            _invalid_frontmatter_diagnostic(
                exc,
                source_path=source_path,
                resource_type="prompt",
                source_kind=source_kind,
            )
        ]
    frontmatter = parsed.frontmatter
    body = parsed.body
    description = _frontmatter_string(frontmatter.get("description"))
    argument_hint = _frontmatter_string(frontmatter.get("argument-hint"))
    return (
        PromptFragmentDescriptor(
            name=name,
            source_path=source_path,
            text=text,
            description=description,
            argument_hint=argument_hint,
            metadata={
                "frontmatter": frontmatter,
                "body": body,
            },
            canonical_name=canonical_name,
            source_kind=source_kind,
            source_scope=source_scope,
            source=source,
            source_root=source_root,
            source_root_order=source_root_order,
        ),
        [],
    )


def _skill_descriptor_from_text(
    *,
    parent_name: str,
    source_path: Path,
    content: str,
    canonical_name: str,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source: str,
    source_root: Path,
    source_root_order: int = 0,
) -> tuple[SkillDescriptor | None, list[DiagnosticDraft]]:
    try:
        parsed = parse_frontmatter(content)
    except FrontmatterParseError as exc:
        return None, [
            _invalid_frontmatter_diagnostic(
                exc,
                source_path=source_path,
                resource_type="skill",
                source_kind=source_kind,
            )
        ]
    frontmatter = parsed.frontmatter
    body = parsed.body
    skill_name = _frontmatter_string(frontmatter.get("name")) or parent_name
    description = _frontmatter_string(frontmatter.get("description"))
    diagnostics = _skill_frontmatter_diagnostics(
        frontmatter=frontmatter,
        skill_name=skill_name,
        parent_name=parent_name,
        source_path=source_path,
        source_kind=source_kind,
    )
    return (
        SkillDescriptor(
            name=skill_name,
            source_path=source_path,
            content=content,
            description=description,
            disable_model_invocation=frontmatter.get("disable-model-invocation")
            is True,
            metadata={
                "frontmatter": frontmatter,
                "body": body,
            },
            canonical_name=canonical_name,
            source_kind=source_kind,
            source_scope=source_scope,
            source=source,
            source_root=source_root,
            source_root_order=source_root_order,
        ),
        diagnostics,
    )


def _invalid_frontmatter_diagnostic(
    error: FrontmatterParseError,
    *,
    source_path: Path,
    resource_type: str,
    source_kind: ResourceSourceKind,
) -> DiagnosticDraft:
    return resource_diagnostic(
        code=f"invalid_{resource_type}_frontmatter",
        message=str(error),
        source_path=source_path,
        resource_type=resource_type,
        source_kind=source_kind,
    )


def _skill_frontmatter_diagnostics(
    *,
    frontmatter: dict[str, object],
    skill_name: str,
    parent_name: str,
    source_path: Path,
    source_kind: ResourceSourceKind,
) -> list[DiagnosticDraft]:
    if not frontmatter:
        return []
    diagnostics: list[DiagnosticDraft] = []
    description = _frontmatter_string(frontmatter.get("description"))
    if description is None:
        diagnostics.append(
            _skill_validation_diagnostic(
                code="invalid_skill_description",
                message="Skill frontmatter description is required.",
                source_path=source_path,
                source_kind=source_kind,
                field="description",
            )
        )
    elif len(description) > _MAX_SKILL_DESCRIPTION_LENGTH:
        diagnostics.append(
            _skill_validation_diagnostic(
                code="invalid_skill_description",
                message=f"Skill frontmatter description exceeds {_MAX_SKILL_DESCRIPTION_LENGTH} characters.",
                source_path=source_path,
                source_kind=source_kind,
                field="description",
            )
        )
    if skill_name != parent_name:
        diagnostics.append(
            _skill_validation_diagnostic(
                code="invalid_skill_name",
                message=f'Skill frontmatter name "{skill_name}" does not match parent directory "{parent_name}".',
                source_path=source_path,
                source_kind=source_kind,
                field="name",
            )
        )
    if len(skill_name) > _MAX_SKILL_NAME_LENGTH:
        diagnostics.append(
            _skill_validation_diagnostic(
                code="invalid_skill_name",
                message=f"Skill frontmatter name exceeds {_MAX_SKILL_NAME_LENGTH} characters.",
                source_path=source_path,
                source_kind=source_kind,
                field="name",
            )
        )
    if not _is_valid_skill_name(skill_name):
        diagnostics.append(
            _skill_validation_diagnostic(
                code="invalid_skill_name",
                message="Skill frontmatter name must contain lowercase letters, numbers, and hyphens only.",
                source_path=source_path,
                source_kind=source_kind,
                field="name",
            )
        )
    return diagnostics


def _skill_validation_diagnostic(
    *,
    code: str,
    message: str,
    source_path: Path,
    source_kind: ResourceSourceKind,
    field: str,
) -> DiagnosticDraft:
    return resource_diagnostic(
        code=code,
        message=message,
        source_path=source_path,
        resource_type="skill",
        source_kind=source_kind,
        metadata={"field": field},
    )


def _is_valid_skill_name(name: str) -> bool:
    if not name or name.startswith("-") or name.endswith("-") or "--" in name:
        return False
    return all(char.islower() or char.isdigit() or char == "-" for char in name)


def _frontmatter_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None

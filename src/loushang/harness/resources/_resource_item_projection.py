"""Source-neutral descriptor projection for immutable Resource bytes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from loushang.harness.resources._descriptor_parsing import (
    _prompt_descriptor_from_text,
    _skill_descriptor_from_text,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceSourceKind,
    ResourceSourceScope,
    SkillDescriptor,
)


@dataclass(frozen=True, slots=True)
class CatalogItemProjection:
    canonical_name: str
    public_id: str
    description: str | None
    model_invocable: bool
    descriptor: PromptFragmentDescriptor | SkillDescriptor | None = None
    diagnostic_reasons: tuple[str, ...] = ()
    valid: bool = True


def project_catalog_item(
    *,
    resource_kind: str,
    logical_path: PurePosixPath,
    body: bytes | None,
    fallback_public_id: str,
    source_kind: ResourceSourceKind,
    source_scope: ResourceSourceScope,
    source_label: str,
    source_root_order: int,
) -> CatalogItemProjection | None:
    """Parse summary metadata once without granting any body-read authority."""

    if resource_kind == "skill":
        if body is None:
            return None
        try:
            content = body.decode("utf-8").strip()
        except UnicodeDecodeError:
            return CatalogItemProjection(
                canonical_name=logical_path.as_posix(),
                public_id=fallback_public_id,
                description=None,
                model_invocable=False,
                diagnostic_reasons=("invalid_skill_encoding",),
                valid=False,
            )
        parent_name = (
            logical_path.parent.name
            if logical_path.name == "SKILL.md"
            else logical_path.name
        )
        canonical_name = (
            PurePosixPath(*logical_path.parts[1:]).as_posix()
            if logical_path.parts[:1] == ("skills",)
            else logical_path.as_posix()
        )
        skill_descriptor, drafts = _skill_descriptor_from_text(
            parent_name=parent_name,
            source_path=Path(logical_path.as_posix()),
            content=content,
            canonical_name=canonical_name,
            source_kind=source_kind,
            source_scope=source_scope,
            source=source_label,
            source_root=Path(logical_path.parts[0]) if logical_path.parts else Path(),
            source_root_order=source_root_order,
        )
        if skill_descriptor is None:
            return CatalogItemProjection(
                canonical_name=logical_path.as_posix(),
                public_id=fallback_public_id,
                description=None,
                model_invocable=False,
                diagnostic_reasons=tuple(draft.code for draft in drafts),
                valid=False,
            )
        return CatalogItemProjection(
            canonical_name=skill_descriptor.canonical_name or skill_descriptor.name,
            public_id=skill_descriptor.id or skill_descriptor.name,
            description=skill_descriptor.description,
            model_invocable=not skill_descriptor.disable_model_invocation,
            descriptor=skill_descriptor,
            diagnostic_reasons=tuple(
                draft.code for draft in skill_descriptor.diagnostics
            ),
        )

    if resource_kind == "prompt":
        if body is None:
            return None
        try:
            text = body.decode("utf-8").strip()
        except UnicodeDecodeError:
            return CatalogItemProjection(
                canonical_name=logical_path.name,
                public_id=fallback_public_id,
                description=None,
                model_invocable=False,
                diagnostic_reasons=("invalid_prompt_encoding",),
                valid=False,
            )
        prompt_descriptor, drafts = _prompt_descriptor_from_text(
            name=logical_path.stem,
            source_path=Path(logical_path.as_posix()),
            text=text,
            canonical_name=logical_path.name,
            source_kind=source_kind,
            source_scope=source_scope,
            source=source_label,
            source_root=Path(logical_path.parent.as_posix()),
            source_root_order=source_root_order,
        )
        if prompt_descriptor is None:
            return CatalogItemProjection(
                canonical_name=logical_path.name,
                public_id=fallback_public_id,
                description=None,
                model_invocable=False,
                diagnostic_reasons=tuple(draft.code for draft in drafts),
                valid=False,
            )
        return CatalogItemProjection(
            canonical_name=prompt_descriptor.canonical_name or prompt_descriptor.name,
            public_id=prompt_descriptor.id or prompt_descriptor.name,
            description=prompt_descriptor.description,
            model_invocable=True,
            descriptor=prompt_descriptor,
            diagnostic_reasons=tuple(
                draft.code for draft in prompt_descriptor.diagnostics
            ),
        )

    return CatalogItemProjection(
        canonical_name=(
            logical_path.parent.name
            if logical_path.name in {"SKILL.md", "extension.py", "__init__.py"}
            else logical_path.name
        ),
        public_id=fallback_public_id,
        description=None,
        model_invocable=resource_kind == "method",
    )


__all__ = ["CatalogItemProjection", "project_catalog_item"]

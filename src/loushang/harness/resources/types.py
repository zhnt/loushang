from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from loushang.harness.diagnostics.types import DiagnosticDraft

ResourceSourceKind = Literal[
    "built_in", "project_local", "external_package", "user_global", "temporary"
]
ResourceSourceScope = Literal["builtin", "project", "package", "user", "temporary"]

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})
_PROMPT_SOURCE_ORDER: tuple[ResourceSourceKind, ...] = (
    "temporary",
    "project_local",
    "user_global",
    "external_package",
    "built_in",
)
_CONTEXT_PROMPT_KINDS = frozenset({"agents_md", "claude_md"})


@dataclass(frozen=True)
class PackageResourceSummary:
    source_root: Path
    prompt_count: int = 0
    skill_count: int = 0
    extension_count: int = 0
    theme_count: int = 0
    diagnostic_count: int = 0


@dataclass(frozen=True)
class ResourceMergeDecision:
    resource_type: str
    logical_id: str
    winner_id: str | None = None
    winner_source_kind: ResourceSourceKind | None = None
    candidate_ids: tuple[str, ...] = ()
    candidate_source_kinds: tuple[ResourceSourceKind, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class PromptFragmentDescriptor:
    name: str
    source_path: Path
    text: str
    description: str | None = None
    argument_hint: str | None = None
    kind: str = "prompt_fragment"
    source: str = "filesystem"
    enabled: bool = True
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    id: str | None = None
    resource_type: str = "prompt"
    source_kind: ResourceSourceKind = "project_local"
    source_scope: ResourceSourceScope = "project"
    canonical_name: str | None = None
    declared_id: str | None = None
    source_root: Path | None = None
    source_root_order: int = 0
    prompt_kind: str = "prompt_asset"

    def __post_init__(self) -> None:
        canonical_name = self.canonical_name or self.name
        object.__setattr__(self, "canonical_name", canonical_name)
        object.__setattr__(self, "id", self.id or self.declared_id or canonical_name)


@dataclass(frozen=True)
class SkillDescriptor:
    name: str
    source_path: Path
    content: str | None = None
    description: str | None = None
    disable_model_invocation: bool = False
    kind: str = "skill"
    source: str = "filesystem"
    enabled: bool = True
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    id: str | None = None
    resource_type: str = "skill"
    source_kind: ResourceSourceKind = "project_local"
    source_scope: ResourceSourceScope = "project"
    canonical_name: str | None = None
    declared_id: str | None = None
    source_root: Path | None = None
    source_root_order: int = 0

    def __post_init__(self) -> None:
        canonical_name = self.canonical_name or self.name
        object.__setattr__(self, "canonical_name", canonical_name)
        object.__setattr__(self, "id", self.id or self.declared_id or canonical_name)


@dataclass(frozen=True)
class ExtensionDescriptor:
    name: str
    source_path: Path
    entry_path: Path | None = None
    kind: str = "extension"
    source: str = "filesystem"
    enabled: bool = True
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    id: str | None = None
    resource_type: str = "extension"
    source_kind: ResourceSourceKind = "project_local"
    source_scope: ResourceSourceScope = "project"
    canonical_name: str | None = None
    declared_id: str | None = None
    source_root: Path | None = None
    source_root_order: int = 0

    def __post_init__(self) -> None:
        canonical_name = self.canonical_name or self.name
        object.__setattr__(self, "canonical_name", canonical_name)
        object.__setattr__(self, "id", self.id or self.declared_id or canonical_name)


@dataclass(frozen=True)
class ThemeDescriptor:
    name: str
    source_path: Path
    content: str | None = None
    kind: str = "theme"
    source: str = "filesystem"
    enabled: bool = True
    metadata: Mapping[str, object] = field(default_factory=lambda: _EMPTY_METADATA)
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    id: str | None = None
    resource_type: str = "theme"
    source_kind: ResourceSourceKind = "project_local"
    source_scope: ResourceSourceScope = "project"
    canonical_name: str | None = None
    declared_id: str | None = None
    source_root: Path | None = None
    source_root_order: int = 0

    def __post_init__(self) -> None:
        canonical_name = self.canonical_name or self.name
        object.__setattr__(self, "canonical_name", canonical_name)
        object.__setattr__(self, "id", self.id or self.declared_id or canonical_name)


@dataclass(frozen=True)
class ResourceBundle:
    cwd: Path
    agents_path: Path | None = None
    agents_md: str | None = None
    prompt_fragments: list[str] = field(default_factory=list)
    prompt_descriptors: list[PromptFragmentDescriptor] = field(default_factory=list)
    skills: list[SkillDescriptor] = field(default_factory=list)
    extensions: list[ExtensionDescriptor] = field(default_factory=list)
    prompts: list[PromptFragmentDescriptor] = field(default_factory=list)
    themes: list[ThemeDescriptor] = field(default_factory=list)
    diagnostics: list[DiagnosticDraft] = field(default_factory=list)

    def merge(
        self,
        *,
        prompt_descriptors: list[PromptFragmentDescriptor] | None = None,
        skills: list[SkillDescriptor] | None = None,
        extensions: list[ExtensionDescriptor] | None = None,
        prompts: list[PromptFragmentDescriptor] | None = None,
        themes: list[ThemeDescriptor] | None = None,
        diagnostics: list[DiagnosticDraft] | None = None,
    ) -> ResourceBundle:
        merged_prompts = [*self.prompts, *(prompts or [])]
        merged_prompt_descriptors = [
            *self.prompt_descriptors,
            *(prompt_descriptors or []),
            *merged_prompts,
        ]
        return ResourceBundle(
            cwd=self.cwd,
            agents_path=self.agents_path,
            agents_md=self.agents_md,
            prompt_fragments=[
                descriptor.text
                for descriptor in merged_prompt_descriptors
                if descriptor.enabled
            ],
            prompt_descriptors=merged_prompt_descriptors,
            skills=[*self.skills, *(skills or [])],
            extensions=[*self.extensions, *(extensions or [])],
            prompts=merged_prompts,
            themes=[*self.themes, *(themes or [])],
            diagnostics=[*self.diagnostics, *(diagnostics or [])],
        )


@dataclass(frozen=True)
class ResourceSnapshot:
    cwd: Path
    source_kinds: tuple[ResourceSourceKind, ...] = ()
    active_agents_descriptor: PromptFragmentDescriptor | None = None
    active_context_descriptors: tuple[PromptFragmentDescriptor, ...] = ()
    candidate_agents_descriptors: tuple[PromptFragmentDescriptor, ...] = ()
    active_prompt_descriptors: tuple[PromptFragmentDescriptor, ...] = ()
    candidate_prompt_descriptors: tuple[PromptFragmentDescriptor, ...] = ()
    active_skill_descriptors: tuple[SkillDescriptor, ...] = ()
    candidate_skill_descriptors: tuple[SkillDescriptor, ...] = ()
    active_extension_descriptors: tuple[ExtensionDescriptor, ...] = ()
    candidate_extension_descriptors: tuple[ExtensionDescriptor, ...] = ()
    active_theme_descriptors: tuple[ThemeDescriptor, ...] = ()
    candidate_theme_descriptors: tuple[ThemeDescriptor, ...] = ()
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    merge_decisions: tuple[ResourceMergeDecision, ...] = ()

    def to_bundle(self) -> ResourceBundle:
        ordered_prompt_descriptors: list[PromptFragmentDescriptor] = []
        context_descriptors = list(self.active_context_descriptors)
        if not context_descriptors and self.active_agents_descriptor is not None:
            context_descriptors.append(self.active_agents_descriptor)
        ordered_prompt_descriptors.extend(context_descriptors)
        ordered_prompt_descriptors.extend(
            sorted(self.active_prompt_descriptors, key=_prompt_bundle_sort_key)
        )
        agents_descriptor = (
            self.active_agents_descriptor
            or _nearest_context_descriptor(context_descriptors)
        )
        active_prompts = [
            descriptor
            for descriptor in ordered_prompt_descriptors
            if not _is_context_prompt(descriptor)
        ]
        return ResourceBundle(
            cwd=self.cwd,
            agents_path=agents_descriptor.source_path
            if agents_descriptor is not None
            else None,
            agents_md=agents_descriptor.text if agents_descriptor is not None else None,
            prompt_fragments=[
                descriptor.text
                for descriptor in ordered_prompt_descriptors
                if descriptor.enabled
            ],
            prompt_descriptors=ordered_prompt_descriptors,
            skills=list(self.active_skill_descriptors),
            extensions=list(self.active_extension_descriptors),
            prompts=active_prompts,
            themes=list(self.active_theme_descriptors),
            diagnostics=list(self.diagnostics),
        )


def _prompt_bundle_sort_key(
    descriptor: PromptFragmentDescriptor,
) -> tuple[int, int, str, str]:
    return (
        _PROMPT_SOURCE_ORDER.index(descriptor.source_kind)
        if descriptor.source_kind in _PROMPT_SOURCE_ORDER
        else len(_PROMPT_SOURCE_ORDER),
        descriptor.source_root_order,
        descriptor.canonical_name or descriptor.name,
        descriptor.source_path.as_posix(),
    )


def _is_context_prompt(descriptor: PromptFragmentDescriptor) -> bool:
    return descriptor.prompt_kind in _CONTEXT_PROMPT_KINDS


def _nearest_context_descriptor(
    descriptors: list[PromptFragmentDescriptor],
) -> PromptFragmentDescriptor | None:
    for descriptor in reversed(descriptors):
        if descriptor.source_kind == "project_local":
            return descriptor
    return descriptors[-1] if descriptors else None

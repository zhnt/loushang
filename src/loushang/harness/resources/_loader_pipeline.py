"""Resource discovery, resolution, diagnostics, and snapshot assembly pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_discovery import (
    _apply_resource_switches,
    _discover_external_package_resources,
    _discover_project_resources,
    _discover_user_global_resources,
)
from loushang.harness.resources._loader_discovery_builtin import (
    _discover_built_in_resources,
)
from loushang.harness.resources._loader_discovery_context import (
    _discover_context_descriptors,
)
from loushang.harness.resources._loader_discovery_temporary import (
    _discover_temporary_resources,
)
from loushang.harness.resources._loader_resolution import (
    _resolve_candidates,
    _resolve_extension_candidates,
    _resolve_strict_named_candidates,
)
from loushang.harness.resources._loader_types import (
    DEFAULT_CONTEXT_FILE_NAMES,
    _SourceDiscovery,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSnapshot,
    ResourceSourceKind,
    SkillDescriptor,
    ThemeDescriptor,
)

if TYPE_CHECKING:
    from loushang.harness.resources.packages.source import PackageSourceConfig


@dataclass(frozen=True)
class _ResourceDiscoveryRequest:
    cwd: Path
    package_roots: tuple[Path, ...] = ()
    package_source_filters: Mapping[Path, PackageSourceConfig] = field(
        default_factory=dict
    )
    user_resource_roots: tuple[Path, ...] = ()
    explicit_user_roots: frozenset[Path] = frozenset()
    additional_extension_paths: tuple[Path, ...] = ()
    additional_skill_paths: tuple[Path, ...] = ()
    additional_prompt_template_paths: tuple[Path, ...] = ()
    additional_theme_paths: tuple[Path, ...] = ()
    no_extensions: bool = False
    no_skills: bool = False
    no_prompt_templates: bool = False
    no_themes: bool = False
    no_context_files: bool = False
    built_in_resource_packages: tuple[str, ...] = ()
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES
    project_resource_root: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "package_source_filters",
            MappingProxyType(dict(self.package_source_filters)),
        )
        object.__setattr__(
            self,
            "explicit_user_roots",
            frozenset(self.explicit_user_roots),
        )


@dataclass(frozen=True)
class _ResourceDiscoveries:
    candidate_order: tuple[_SourceDiscovery, ...]
    diagnostic_order: tuple[_SourceDiscovery, ...]

    @property
    def prompts(self) -> tuple[PromptFragmentDescriptor, ...]:
        return tuple(
            descriptor
            for discovery in self.candidate_order
            for descriptor in discovery.prompts
        )

    @property
    def skills(self) -> tuple[SkillDescriptor, ...]:
        return tuple(
            descriptor
            for discovery in self.candidate_order
            for descriptor in discovery.skills
        )

    @property
    def extensions(self) -> tuple[ExtensionDescriptor, ...]:
        return tuple(
            descriptor
            for discovery in self.candidate_order
            for descriptor in discovery.extensions
        )

    @property
    def themes(self) -> tuple[ThemeDescriptor, ...]:
        return tuple(
            descriptor
            for discovery in self.candidate_order
            for descriptor in discovery.themes
        )

    @property
    def diagnostics(self) -> tuple[DiagnosticDraft, ...]:
        return tuple(
            diagnostic
            for discovery in self.diagnostic_order
            for diagnostic in discovery.diagnostics
        )


def _discover_snapshot(request: _ResourceDiscoveryRequest) -> ResourceSnapshot:
    target = Path(request.cwd)
    context_descriptors: list[PromptFragmentDescriptor]
    agents_descriptor: PromptFragmentDescriptor | None
    context_diagnostics: list[DiagnosticDraft]
    if request.no_context_files:
        context_descriptors, agents_descriptor, context_diagnostics = [], None, []
    else:
        context_descriptors, agents_descriptor, context_diagnostics = (
            _discover_context_descriptors(
                target,
                user_resource_roots=request.user_resource_roots,
                context_file_names=request.context_file_names,
            )
        )
    project_context_descriptors = [
        descriptor
        for descriptor in context_descriptors
        if descriptor.source_kind == "project_local"
    ]
    project_root = (
        project_context_descriptors[-1].source_path.parent
        if project_context_descriptors
        else (target if target.is_dir() else target.parent)
    )
    if request.project_resource_root is not None:
        project_root = request.project_resource_root

    built_in = _apply_resource_switches(
        _discover_built_in_resources(request.built_in_resource_packages),
        no_prompts=request.no_prompt_templates,
        no_skills=request.no_skills,
        no_extensions=request.no_extensions,
        no_themes=request.no_themes,
    )
    external = _apply_resource_switches(
        _discover_external_package_resources(
            request.package_roots,
            package_source_filters=request.package_source_filters,
        ),
        no_prompts=request.no_prompt_templates,
        no_skills=request.no_skills,
        no_extensions=request.no_extensions,
        no_themes=request.no_themes,
    )
    user_global = _apply_resource_switches(
        _discover_user_global_resources(
            request.user_resource_roots,
            explicit_roots=request.explicit_user_roots,
        ),
        no_prompts=request.no_prompt_templates,
        no_skills=request.no_skills,
        no_extensions=request.no_extensions,
        no_themes=request.no_themes,
    )
    project = _apply_resource_switches(
        _discover_project_resources(project_root),
        no_prompts=request.no_prompt_templates,
        no_skills=request.no_skills,
        no_extensions=request.no_extensions,
        no_themes=request.no_themes,
    )
    temporary = _discover_temporary_resources(
        target,
        extension_paths=request.additional_extension_paths,
        skill_paths=request.additional_skill_paths,
        prompt_paths=request.additional_prompt_template_paths,
        theme_paths=request.additional_theme_paths,
    )

    discoveries = _ResourceDiscoveries(
        candidate_order=(temporary, built_in, external, user_global, project),
        diagnostic_order=(built_in, external, user_global, project, temporary),
    )
    prompt_candidates = discoveries.prompts
    skill_candidates = discoveries.skills
    extension_candidates = discoveries.extensions
    theme_candidates = discoveries.themes

    active_prompts, prompt_diagnostics, prompt_decisions = (
        _resolve_strict_named_candidates(
            prompt_candidates,
            resource_type="prompt",
        )
    )
    active_skills, skill_diagnostics, skill_decisions = (
        _resolve_strict_named_candidates(
            skill_candidates,
            resource_type="skill",
        )
    )
    active_extensions, extension_diagnostics, extension_decisions = (
        _resolve_extension_candidates(
            extension_candidates,
            resource_type="extension",
        )
    )
    active_themes, theme_diagnostics, theme_decisions = _resolve_candidates(
        theme_candidates,
        resource_type="theme",
    )

    diagnostics = [
        *context_diagnostics,
        *discoveries.diagnostics,
        *prompt_diagnostics,
        *skill_diagnostics,
        *extension_diagnostics,
        *theme_diagnostics,
    ]
    merge_decisions = [
        *prompt_decisions,
        *skill_decisions,
        *extension_decisions,
        *theme_decisions,
    ]
    return ResourceSnapshot(
        cwd=target,
        source_kinds=_source_kinds_for(
            request.package_roots,
            request.user_resource_roots,
            has_built_in=bool(request.built_in_resource_packages),
            has_temporary=any(
                (
                    request.additional_extension_paths,
                    request.additional_skill_paths,
                    request.additional_prompt_template_paths,
                    request.additional_theme_paths,
                )
            ),
        ),
        active_agents_descriptor=agents_descriptor,
        active_context_descriptors=tuple(context_descriptors),
        candidate_agents_descriptors=tuple(context_descriptors),
        active_prompt_descriptors=tuple(active_prompts),
        candidate_prompt_descriptors=prompt_candidates,
        active_skill_descriptors=tuple(active_skills),
        candidate_skill_descriptors=skill_candidates,
        active_extension_descriptors=tuple(active_extensions),
        candidate_extension_descriptors=extension_candidates,
        active_theme_descriptors=tuple(active_themes),
        candidate_theme_descriptors=theme_candidates,
        diagnostics=tuple(diagnostics),
        merge_decisions=tuple(merge_decisions),
    )


def _source_kinds_for(
    package_roots: tuple[Path, ...],
    user_resource_roots: tuple[Path, ...] = (),
    *,
    has_built_in: bool = False,
    has_temporary: bool = False,
) -> tuple[ResourceSourceKind, ...]:
    kinds: list[ResourceSourceKind] = []
    if has_temporary:
        kinds.append("temporary")
    if has_built_in:
        kinds.append("built_in")
    if user_resource_roots:
        kinds.append("user_global")
    if package_roots:
        kinds.append("external_package")
    kinds.append("project_local")
    return tuple(kinds)

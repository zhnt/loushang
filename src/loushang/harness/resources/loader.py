"""Public resource loader facade and snapshot assembly pipeline."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_package_policy import (
    _count_package_descriptors,
    _count_package_diagnostics,
    _normalize_package_roots,
    _normalize_package_source_filters,
)
from loushang.harness.resources._loader_pipeline import (
    _discover_snapshot,
    _ResourceDiscoveryRequest,
    _source_kinds_for,
)
from loushang.harness.resources._loader_types import (
    DEFAULT_CONTEXT_FILE_NAMES,
)
from loushang.harness.resources.builtin import BuiltInResourceRegistry
from loushang.harness.resources.layout import (
    resolve_user_resource_roots,
    resolve_workspace_resource_root,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PackageResourceSummary,
    ResourceBundle,
    ResourceSnapshot,
    ResourceSourceKind,
    SkillDescriptor,
)

if TYPE_CHECKING:
    from loushang.harness.resources.packages.source import PackageSourceConfig

SystemPromptAssembler = Callable[[str | None, ResourceBundle], str | None]


def _normalize_user_resource_roots(
    user_resource_roots: Sequence[str | Path] | None,
) -> tuple[Path, ...]:
    if not user_resource_roots:
        return ()
    return tuple(Path(root).expanduser().resolve() for root in user_resource_roots)


def _normalize_runtime_paths(
    paths: list[str | Path] | tuple[str | Path, ...] | None,
) -> tuple[Path, ...]:
    if not paths:
        return ()
    return tuple(Path(path).expanduser() for path in paths)


def _resolve_prompt_input(source: str | None, *, cwd: Path) -> str | None:
    if not source:
        return None
    candidate = Path(source).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    if not candidate.exists():
        return source
    if not candidate.is_file():
        return source
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        return source


@dataclass(frozen=True)
class ResourceLoaderProfile:
    """Product defaults for the shared resource discovery engine."""

    built_in_resource_packages: tuple[str, ...] = ()
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES
    user_resource_roots: tuple[str | Path, ...] | None = None
    project_resource_mode: Literal["standard", "legacy"] = "standard"
    system_prompt_assembler: SystemPromptAssembler | None = None

    def __post_init__(self) -> None:
        if self.project_resource_mode not in {"standard", "legacy"}:
            raise ValueError("project_resource_mode must be standard or legacy")
        object.__setattr__(
            self,
            "built_in_resource_packages",
            tuple(self.built_in_resource_packages),
        )
        object.__setattr__(self, "context_file_names", tuple(self.context_file_names))
        if self.user_resource_roots is not None:
            object.__setattr__(
                self,
                "user_resource_roots",
                tuple(self.user_resource_roots),
            )


class ResourceLoader:
    def __init__(
        self,
        package_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        package_source_filters: dict[str | Path, PackageSourceConfig] | None = None,
        user_resource_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        additional_extension_paths: list[str | Path]
        | tuple[str | Path, ...]
        | None = None,
        additional_skill_paths: list[str | Path] | tuple[str | Path, ...] | None = None,
        additional_prompt_template_paths: list[str | Path]
        | tuple[str | Path, ...]
        | None = None,
        additional_theme_paths: list[str | Path] | tuple[str | Path, ...] | None = None,
        no_extensions: bool = False,
        no_skills: bool = False,
        no_prompt_templates: bool = False,
        no_themes: bool = False,
        no_context_files: bool = False,
        system_prompt: str | None = None,
        append_system_prompt: list[str] | tuple[str, ...] | None = None,
        built_in_resource_packages: list[str] | tuple[str, ...] | None = None,
        built_in_resource_registry: BuiltInResourceRegistry | None = None,
        context_file_names: list[str] | tuple[str, ...] | None = None,
        workspace_root: str | Path | None = None,
        project_resource_mode: Literal["standard", "legacy"] = "standard",
    ) -> None:
        self._snapshot: ResourceSnapshot | None = None
        self._package_roots = _normalize_package_roots(package_roots)
        self._package_source_filters = _normalize_package_source_filters(
            package_source_filters
        )
        if user_resource_roots is None:
            platform_roots, _ = resolve_user_resource_roots()
            self._user_resource_roots = platform_roots
        else:
            self._user_resource_roots = _normalize_user_resource_roots(
                user_resource_roots
            )
        self._explicit_user_resource_roots: set[Path] = set()
        self._additional_extension_paths = _normalize_runtime_paths(
            additional_extension_paths
        )
        self._additional_skill_paths = _normalize_runtime_paths(additional_skill_paths)
        self._additional_prompt_template_paths = _normalize_runtime_paths(
            additional_prompt_template_paths
        )
        self._additional_theme_paths = _normalize_runtime_paths(additional_theme_paths)
        self._no_extensions = bool(no_extensions)
        self._no_skills = bool(no_skills)
        self._no_prompt_templates = bool(no_prompt_templates)
        self._no_themes = bool(no_themes)
        self._no_context_files = bool(no_context_files)
        self._system_prompt_source = system_prompt
        self._append_system_prompt_sources = tuple(append_system_prompt or ())
        self._resolved_system_prompt: str | None = None
        self._resolved_append_system_prompt: tuple[str, ...] = ()
        registered_packages = (
            built_in_resource_registry.import_paths()
            if built_in_resource_registry is not None
            else ()
        )
        self._built_in_resource_packages = tuple(
            dict.fromkeys([*(built_in_resource_packages or ()), *registered_packages])
        )
        self._context_file_names = tuple(
            context_file_names or DEFAULT_CONTEXT_FILE_NAMES
        )
        self._workspace_root = (
            Path(workspace_root).expanduser().resolve(strict=False)
            if workspace_root is not None
            else None
        )
        self._project_resource_mode = project_resource_mode

    def set_package_roots(
        self,
        package_roots: Sequence[str | Path] | None,
        package_source_filters: Mapping[str | Path, PackageSourceConfig] | None = None,
    ) -> None:
        self._package_roots = _normalize_package_roots(package_roots)
        self._package_source_filters = _normalize_package_source_filters(
            package_source_filters
        )

    def set_user_resource_roots(
        self,
        user_resource_roots: Sequence[str | Path] | None,
        *,
        explicit_roots: Collection[str | Path] | None = None,
    ) -> None:
        self._user_resource_roots = _normalize_user_resource_roots(user_resource_roots)
        self._explicit_user_resource_roots = set(
            _normalize_user_resource_roots(
                tuple(explicit_roots) if explicit_roots is not None else None
            )
        )

    def set_workspace_root(self, workspace_root: str | Path | None) -> None:
        self._workspace_root = (
            Path(workspace_root).expanduser().resolve(strict=False)
            if workspace_root is not None
            else None
        )

    def set_runtime_options(
        self,
        *,
        additional_extension_paths: list[str | Path]
        | tuple[str | Path, ...]
        | None = None,
        additional_skill_paths: list[str | Path] | tuple[str | Path, ...] | None = None,
        additional_prompt_template_paths: list[str | Path]
        | tuple[str | Path, ...]
        | None = None,
        additional_theme_paths: list[str | Path] | tuple[str | Path, ...] | None = None,
        no_extensions: bool | None = None,
        no_skills: bool | None = None,
        no_prompt_templates: bool | None = None,
        no_themes: bool | None = None,
        no_context_files: bool | None = None,
        system_prompt: str | None = None,
        append_system_prompt: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        if additional_extension_paths is not None:
            self._additional_extension_paths = _normalize_runtime_paths(
                additional_extension_paths
            )
        if additional_skill_paths is not None:
            self._additional_skill_paths = _normalize_runtime_paths(
                additional_skill_paths
            )
        if additional_prompt_template_paths is not None:
            self._additional_prompt_template_paths = _normalize_runtime_paths(
                additional_prompt_template_paths
            )
        if additional_theme_paths is not None:
            self._additional_theme_paths = _normalize_runtime_paths(
                additional_theme_paths
            )
        if no_extensions is not None:
            self._no_extensions = bool(no_extensions)
        if no_skills is not None:
            self._no_skills = bool(no_skills)
        if no_prompt_templates is not None:
            self._no_prompt_templates = bool(no_prompt_templates)
        if no_themes is not None:
            self._no_themes = bool(no_themes)
        if no_context_files is not None:
            self._no_context_files = bool(no_context_files)
        self._system_prompt_source = system_prompt
        self._append_system_prompt_sources = tuple(append_system_prompt or ())

    def discover_resources(self, cwd: str | Path) -> ResourceBundle:
        target = Path(cwd)
        workspace_root = self._workspace_root or target
        project_resource_root = (
            resolve_workspace_resource_root(workspace_root)
            if self._project_resource_mode == "standard"
            else None
        )
        request = _ResourceDiscoveryRequest(
            cwd=target,
            package_roots=self._package_roots,
            package_source_filters=self._package_source_filters,
            user_resource_roots=self._user_resource_roots,
            explicit_user_roots=frozenset(self._explicit_user_resource_roots),
            additional_extension_paths=self._additional_extension_paths,
            additional_skill_paths=self._additional_skill_paths,
            additional_prompt_template_paths=self._additional_prompt_template_paths,
            additional_theme_paths=self._additional_theme_paths,
            no_extensions=self._no_extensions,
            no_skills=self._no_skills,
            no_prompt_templates=self._no_prompt_templates,
            no_themes=self._no_themes,
            no_context_files=self._no_context_files,
            built_in_resource_packages=self._built_in_resource_packages,
            context_file_names=self._context_file_names,
            project_resource_root=project_resource_root,
        )
        snapshot = _discover_snapshot(request)
        self._snapshot = snapshot
        self._resolved_system_prompt = _resolve_prompt_input(
            self._system_prompt_source, cwd=Path(cwd)
        )
        self._resolved_append_system_prompt = tuple(
            resolved
            for source in self._append_system_prompt_sources
            if (resolved := _resolve_prompt_input(source, cwd=Path(cwd))) is not None
        )
        return snapshot.to_bundle()

    def reload_resources(self, cwd: str | Path | None = None) -> ResourceBundle:
        if cwd is not None:
            return self.discover_resources(cwd)
        if self._snapshot is None:
            return self.discover_resources(Path.cwd())
        return self.discover_resources(self._snapshot.cwd)

    def get_resource_bundle(self) -> ResourceBundle:
        return self.get_resource_snapshot().to_bundle()

    def get_resource_snapshot(self) -> ResourceSnapshot:
        if self._snapshot is None:
            return ResourceSnapshot(
                cwd=Path.cwd(),
                source_kinds=_source_kinds_for(
                    self._package_roots,
                    self._user_resource_roots,
                    has_built_in=bool(self._built_in_resource_packages),
                    has_temporary=any(
                        (
                            self._additional_extension_paths,
                            self._additional_skill_paths,
                            self._additional_prompt_template_paths,
                            self._additional_theme_paths,
                        )
                    ),
                ),
            )
        return self._snapshot

    def get_diagnostics(self) -> list[DiagnosticDraft]:
        return list(self.get_resource_snapshot().diagnostics)

    def get_resource_diagnostics(
        self,
        *,
        source_kind: ResourceSourceKind | None = None,
        resource_type: str | None = None,
        code: str | None = None,
    ) -> list[DiagnosticDraft]:
        diagnostics = list(self.get_resource_snapshot().diagnostics)
        if source_kind is not None:
            diagnostics = [
                diagnostic
                for diagnostic in diagnostics
                if diagnostic.details.get("source_kind") == source_kind
            ]
        if resource_type is not None:
            diagnostics = [
                diagnostic
                for diagnostic in diagnostics
                if diagnostic.details.get("resource_type") == resource_type
            ]
        if code is not None:
            diagnostics = [
                diagnostic for diagnostic in diagnostics if diagnostic.code == code
            ]
        return diagnostics

    def get_package_resource_summaries(self) -> list[PackageResourceSummary]:
        snapshot = self.get_resource_snapshot()
        summaries: list[PackageResourceSummary] = []
        for root in self._package_roots:
            summaries.append(
                PackageResourceSummary(
                    source_root=root,
                    prompt_count=_count_package_descriptors(
                        snapshot.candidate_prompt_descriptors, root
                    ),
                    skill_count=_count_package_descriptors(
                        snapshot.candidate_skill_descriptors, root
                    ),
                    extension_count=_count_package_descriptors(
                        snapshot.candidate_extension_descriptors, root
                    ),
                    theme_count=_count_package_descriptors(
                        snapshot.candidate_theme_descriptors, root
                    ),
                    diagnostic_count=_count_package_diagnostics(
                        snapshot.diagnostics, root
                    ),
                )
            )
        return summaries

    def get_skills(self) -> list[SkillDescriptor]:
        return list(self.get_resource_snapshot().active_skill_descriptors)

    def get_prompts(self) -> dict[str, object]:
        bundle = self.get_resource_bundle()
        return {
            "agents_md": bundle.agents_md,
            "prompt_fragments": list(bundle.prompt_fragments),
            "prompt_descriptors": list(bundle.prompt_descriptors),
            "prompts": list(bundle.prompts),
        }

    def get_agents_files(self) -> dict[str, object]:
        bundle = self.get_resource_bundle()
        context_descriptors = [
            descriptor
            for descriptor in bundle.prompt_descriptors
            if descriptor.prompt_kind in {"agents_md", "claude_md"}
        ]
        return {
            "agents_files": [
                {"path": str(descriptor.source_path), "content": descriptor.text}
                for descriptor in context_descriptors
            ]
        }

    def get_append_system_prompt(self) -> list[str]:
        return list(self.get_resource_bundle().prompt_fragments)

    def get_system_prompt_override(self) -> str | None:
        return self._resolved_system_prompt

    def get_append_system_prompt_overrides(self) -> list[str]:
        return list(self._resolved_append_system_prompt)

    def get_extensions(self) -> list[ExtensionDescriptor]:
        return list(self.get_resource_snapshot().active_extension_descriptors)


class ProfiledResourceLoader(ResourceLoader):
    """Resource loader bound to one Product profile."""

    def __init__(
        self,
        *args: Any,
        profile: ResourceLoaderProfile,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault(
            "built_in_resource_packages",
            profile.built_in_resource_packages,
        )
        kwargs.setdefault("context_file_names", profile.context_file_names)
        kwargs.setdefault("project_resource_mode", profile.project_resource_mode)
        if profile.user_resource_roots is not None:
            kwargs.setdefault("user_resource_roots", profile.user_resource_roots)
        super().__init__(*args, **kwargs)
        self._resource_profile = profile

    def get_system_prompt(self, *, base_prompt: str | None = None) -> str | None:
        assembler = self._resource_profile.system_prompt_assembler
        if assembler is None:
            return base_prompt
        return assembler(base_prompt, self.get_resource_bundle())

"""Public resource loader facade and snapshot assembly pipeline."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._catalog_input_preparation import (
    prepare_resource_catalog_input_receipt,
)
from loushang.harness.resources._catalog_input_receipt import (
    CatalogPluginPackageInput,
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)
from loushang.harness.resources.builtin import BuiltInResourceRegistry
from loushang.harness.resources.layout import (
    resolve_user_resource_roots,
    resolve_workspace_resource_root,
)
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PackageResourceSummary,
    ResourceBundle,
    ResourceSourceKind,
    SkillDescriptor,
)

SystemPromptAssembler = Callable[[str | None, ResourceBundle], str | None]


class ResourceLoaderCompatibilityError(RuntimeError):
    """A legacy loader projection is unavailable from the selected authority."""

    code = "resource_loader_compatibility_unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{self.code}: {reason}")


def _normalize_user_resource_roots(
    user_resource_roots: Sequence[str | Path] | None,
) -> tuple[Path, ...]:
    if not user_resource_roots:
        return ()
    return tuple(Path(root).expanduser().resolve() for root in user_resource_roots)


def _normalize_package_roots(
    package_roots: Sequence[str | Path] | None,
) -> tuple[Path, ...]:
    if not package_roots:
        return ()
    return tuple(Path(root).expanduser().resolve() for root in package_roots)


def _normalize_package_source_filters(
    package_source_filters: Mapping[str | Path, PackageSourceConfig] | None,
) -> dict[Path, PackageSourceConfig]:
    if not package_source_filters:
        return {}
    return {
        Path(root).expanduser().resolve(): config
        for root, config in package_source_filters.items()
    }


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


def _package_mounts_from_legacy_roots(
    package_roots: Sequence[str | Path] | None,
    package_source_filters: Mapping[str | Path, PackageSourceConfig] | None,
) -> tuple[PackageResourceMount, ...]:
    roots = _normalize_package_roots(package_roots)
    filters = _normalize_package_source_filters(package_source_filters)
    return tuple(
        PackageResourceMount(root=root, source_filter=filters.get(root))
        for root in roots
    )


def _verify_package_mounts(mounts: Sequence[PackageResourceMount]) -> None:
    for mount in mounts:
        mount.verify()


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
        self._snapshot: Any | None = None
        self._catalog_projection: ResourceCatalogProjection | None = None
        self._catalog_inputs_pending = False
        self._catalog_authority_selected = False
        self._legacy_authority_selected = False
        self._initial_resource_catalog_input_receipt: (
            ResourceCatalogInputReceipt | None
        ) = None
        self._catalog_plugin_package_inputs: tuple[CatalogPluginPackageInput, ...] = ()
        self._package_mounts = _package_mounts_from_legacy_roots(
            package_roots,
            package_source_filters,
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
        """Compatibility adapter for path-backed, non-Plugin Package roots."""

        self.set_package_mounts(
            _package_mounts_from_legacy_roots(
                package_roots,
                package_source_filters,
            )
        )

    def set_package_mounts(
        self,
        mounts: Sequence[PackageResourceMount],
        *,
        catalog_plugin_package_inputs: Sequence[CatalogPluginPackageInput] = (),
    ) -> None:
        self._initial_resource_catalog_input_receipt = None
        next_mounts = tuple(mounts)
        _verify_package_mounts(next_mounts)
        next_plugin_inputs = tuple(catalog_plugin_package_inputs)
        if any(
            not isinstance(item, CatalogPluginPackageInput)
            for item in next_plugin_inputs
        ):
            raise TypeError("Catalog Plugin package inputs are invalid")
        previous_mounts = self._package_mounts
        self._package_mounts = next_mounts
        self._catalog_plugin_package_inputs = next_plugin_inputs
        retained = {
            id(mount.revision_handle)
            for mount in next_mounts
            if mount.revision_handle is not None
        }
        for mount in previous_mounts:
            handle = mount.revision_handle
            if handle is not None and id(handle) not in retained:
                handle.close()

    def set_user_resource_roots(
        self,
        user_resource_roots: Sequence[str | Path] | None,
        *,
        explicit_roots: Collection[str | Path] | None = None,
    ) -> None:
        self._initial_resource_catalog_input_receipt = None
        self._user_resource_roots = _normalize_user_resource_roots(user_resource_roots)
        self._explicit_user_resource_roots = set(
            _normalize_user_resource_roots(
                tuple(explicit_roots) if explicit_roots is not None else None
            )
        )

    def set_workspace_root(self, workspace_root: str | Path | None) -> None:
        self._initial_resource_catalog_input_receipt = None
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
        self._initial_resource_catalog_input_receipt = None
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
        """Run the explicit legacy discovery and publish its compatibility view."""

        if self._catalog_authority_selected:
            raise ResourceLoaderCompatibilityError(
                "catalog_loader_cannot_enter_legacy_authority"
            )
        self._legacy_authority_selected = True
        return self._discover_resources(cwd)

    def prepare_catalog_input_receipt(
        self,
        cwd: str | Path,
    ) -> ResourceCatalogInputReceipt:
        """Return normalized source facts without running effective selection."""

        if self._legacy_authority_selected:
            raise ResourceLoaderCompatibilityError(
                "legacy_loader_cannot_prepare_catalog_inputs"
            )
        # Authority selection is monotonic even if preparation fails.  A
        # Catalog-required caller must never fall back to legacy discovery by
        # handling a preparation error and reusing this loader.
        self._catalog_authority_selected = True
        self._catalog_inputs_pending = True
        self._initial_resource_catalog_input_receipt = None
        _verify_package_mounts(self._package_mounts)
        target = Path(cwd)
        project_resource_root = (
            resolve_workspace_resource_root(self._workspace_root or target)
            if self._project_resource_mode == "standard"
            else None
        )
        receipt = prepare_resource_catalog_input_receipt(
            cwd=target,
            project_resource_root=project_resource_root,
            package_mounts=self._package_mounts,
            catalog_plugin_package_inputs=self._catalog_plugin_package_inputs,
            user_resource_roots=self._user_resource_roots,
            explicit_user_resource_roots=self._explicit_user_resource_roots,
            additional_extension_paths=self._additional_extension_paths,
            additional_skill_paths=self._additional_skill_paths,
            additional_prompt_template_paths=(
                self._additional_prompt_template_paths
            ),
            additional_theme_paths=self._additional_theme_paths,
            no_extensions=self._no_extensions,
            no_skills=self._no_skills,
            no_prompt_templates=self._no_prompt_templates,
            no_themes=self._no_themes,
            no_context_files=self._no_context_files,
            built_in_resource_packages=self._built_in_resource_packages,
            context_file_names=self._context_file_names,
        )
        _verify_package_mounts(self._package_mounts)
        self._resolved_system_prompt = _resolve_prompt_input(
            self._system_prompt_source,
            cwd=target,
        )
        self._resolved_append_system_prompt = tuple(
            resolved
            for source in self._append_system_prompt_sources
            if (resolved := _resolve_prompt_input(source, cwd=target)) is not None
        )
        return receipt

    def create_catalog_session_view(self) -> CatalogSessionResourceLoaderView:
        """Create an isolated compatibility view over this input authority."""

        if self._legacy_authority_selected:
            raise ResourceLoaderCompatibilityError(
                "legacy_loader_cannot_create_catalog_session_view"
            )
        self._catalog_authority_selected = True
        self._catalog_inputs_pending = True
        return CatalogSessionResourceLoaderView(self)

    def _discover_resources(
        self,
        cwd: str | Path,
    ) -> ResourceBundle:
        from loushang.harness.resources._loader_pipeline import (
            _discover_snapshot,
            _ResourceDiscoveryRequest,
        )

        self._initial_resource_catalog_input_receipt = None
        _verify_package_mounts(self._package_mounts)
        target = Path(cwd)
        workspace_root = self._workspace_root or target
        project_resource_root = (
            resolve_workspace_resource_root(workspace_root)
            if self._project_resource_mode == "standard"
            else None
        )
        request = _ResourceDiscoveryRequest(
            cwd=target,
            package_mounts=self._package_mounts,
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
            catalog_plugin_package_inputs=self._catalog_plugin_package_inputs,
        )
        discovery = _discover_snapshot(request)
        _verify_package_mounts(self._package_mounts)
        snapshot = discovery.snapshot
        self._snapshot = snapshot
        self._catalog_projection = None
        self._catalog_inputs_pending = False
        self._initial_resource_catalog_input_receipt = discovery.catalog_input_receipt
        self._resolved_system_prompt = _resolve_prompt_input(
            self._system_prompt_source, cwd=Path(cwd)
        )
        self._resolved_append_system_prompt = tuple(
            resolved
            for source in self._append_system_prompt_sources
            if (resolved := _resolve_prompt_input(source, cwd=Path(cwd))) is not None
        )
        return snapshot.to_bundle()

    def adopt_catalog_projection(self, projection: ResourceCatalogProjection) -> None:
        """Forward compatibility reads to one exact captured Catalog projection."""

        if not isinstance(projection, ResourceCatalogProjection):
            raise TypeError("Resource loader requires a Catalog projection")
        if self._legacy_authority_selected:
            raise ResourceLoaderCompatibilityError(
                "legacy_loader_cannot_adopt_catalog_projection"
            )
        self._catalog_authority_selected = True
        self._catalog_projection = projection
        self._snapshot = None
        self._catalog_inputs_pending = False

    def restore_catalog_projection(
        self,
        projection: ResourceCatalogProjection | None,
    ) -> None:
        """Restore a previously captured Catalog projection during rollback."""

        if self._legacy_authority_selected:
            raise ResourceLoaderCompatibilityError(
                "legacy_loader_cannot_restore_catalog_projection"
            )
        if not self._catalog_authority_selected:
            raise ResourceLoaderCompatibilityError(
                "catalog_projection_restore_without_catalog_authority"
            )
        if projection is not None and not isinstance(
            projection,
            ResourceCatalogProjection,
        ):
            raise TypeError("Resource loader requires a Catalog projection")
        self._catalog_authority_selected = True
        self._catalog_projection = projection
        self._snapshot = None
        self._catalog_inputs_pending = projection is None

    def close(self) -> None:
        self._initial_resource_catalog_input_receipt = None
        closed: set[int] = set()
        for mount in self._package_mounts:
            handle = mount.revision_handle
            if handle is not None and id(handle) not in closed:
                handle.close()
                closed.add(id(handle))

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def reload_resources(self, cwd: str | Path | None = None) -> ResourceBundle:
        if cwd is not None:
            return self.discover_resources(cwd)
        if self._snapshot is None:
            return self.discover_resources(Path.cwd())
        return self.discover_resources(self._snapshot.cwd)

    def get_resource_bundle(self) -> ResourceBundle:
        projection = self._catalog_projection
        if projection is not None:
            return projection.to_compatibility_bundle()
        return self.get_resource_snapshot().to_bundle()

    def get_resource_snapshot(self) -> Any:
        if self._catalog_projection is not None:
            raise ResourceLoaderCompatibilityError(
                "catalog_projection_has_no_legacy_candidate_snapshot"
            )
        if self._catalog_authority_selected and self._catalog_projection is None:
            raise ResourceLoaderCompatibilityError(
                "catalog_projection_not_published"
            )
        if self._snapshot is None:
            from loushang.harness.resources._loader_pipeline import _source_kinds_for
            from loushang.harness.resources.types import ResourceSnapshot

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

    def _take_initial_resource_catalog_input_receipt(
        self,
    ) -> ResourceCatalogInputReceipt:
        """Transfer the latest exact discovery inputs to one Product adapter."""

        receipt = self._initial_resource_catalog_input_receipt
        if receipt is None:
            raise RuntimeError(
                "No unclaimed initial Resource Catalog input receipt is available"
            )
        self._initial_resource_catalog_input_receipt = None
        return receipt

    @property
    def _package_roots(self) -> tuple[Path, ...]:
        return tuple(mount.root for mount in self._package_mounts if mount.enabled)

    def get_diagnostics(self) -> list[DiagnosticDraft]:
        if self._catalog_projection is not None:
            return list(self.get_resource_bundle().diagnostics)
        return list(self.get_resource_snapshot().diagnostics)

    def get_resource_diagnostics(
        self,
        *,
        source_kind: ResourceSourceKind | None = None,
        resource_type: str | None = None,
        code: str | None = None,
    ) -> list[DiagnosticDraft]:
        diagnostics = self.get_diagnostics()
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
        if self._catalog_projection is not None:
            raise ResourceLoaderCompatibilityError(
                "catalog_projection_has_no_legacy_package_summary"
            )
        snapshot = self.get_resource_snapshot()
        from loushang.harness.resources._loader_package_policy import (
            _count_package_descriptors,
            _count_package_diagnostics,
        )

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
        return list(self.get_resource_bundle().skills)

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
        return list(self.get_resource_bundle().extensions)


class CatalogSessionResourceLoaderView(ResourceLoader):
    """Session-owned Catalog compatibility view over a shared input loader.

    Configuration and input preparation remain on the shared loader. Catalog
    publication state is deliberately local to this view, so one Session can
    neither observe nor roll back another Session's projection.
    """

    def __init__(self, source_loader: ResourceLoader) -> None:
        if not isinstance(source_loader, ResourceLoader):
            raise TypeError("Catalog Session view requires a ResourceLoader")
        self._source_loader = source_loader
        self._snapshot: Any | None = None
        self._catalog_projection: ResourceCatalogProjection | None = None
        self._catalog_inputs_pending = True
        self._catalog_authority_selected = True
        self._legacy_authority_selected = False

    @property
    def input_loader(self) -> ResourceLoader:
        """Return the shared configuration/input authority for diagnostics."""

        return self._source_loader

    def set_package_roots(
        self,
        package_roots: Sequence[str | Path] | None,
        package_source_filters: Mapping[str | Path, PackageSourceConfig] | None = None,
    ) -> None:
        self._source_loader.set_package_roots(
            package_roots,
            package_source_filters,
        )

    def set_package_mounts(
        self,
        mounts: Sequence[PackageResourceMount],
        *,
        catalog_plugin_package_inputs: Sequence[CatalogPluginPackageInput] = (),
    ) -> None:
        self._source_loader.set_package_mounts(
            mounts,
            catalog_plugin_package_inputs=catalog_plugin_package_inputs,
        )

    def set_user_resource_roots(
        self,
        user_resource_roots: Sequence[str | Path] | None,
        *,
        explicit_roots: Collection[str | Path] | None = None,
    ) -> None:
        self._source_loader.set_user_resource_roots(
            user_resource_roots,
            explicit_roots=explicit_roots,
        )

    def set_workspace_root(self, workspace_root: str | Path | None) -> None:
        self._source_loader.set_workspace_root(workspace_root)

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
        self._source_loader.set_runtime_options(
            additional_extension_paths=additional_extension_paths,
            additional_skill_paths=additional_skill_paths,
            additional_prompt_template_paths=additional_prompt_template_paths,
            additional_theme_paths=additional_theme_paths,
            no_extensions=no_extensions,
            no_skills=no_skills,
            no_prompt_templates=no_prompt_templates,
            no_themes=no_themes,
            no_context_files=no_context_files,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
        )

    def prepare_catalog_input_receipt(
        self,
        cwd: str | Path,
    ) -> ResourceCatalogInputReceipt:
        return self._source_loader.prepare_catalog_input_receipt(cwd)

    def _take_initial_resource_catalog_input_receipt(
        self,
    ) -> ResourceCatalogInputReceipt:
        return self._source_loader._take_initial_resource_catalog_input_receipt()

    @property
    def _package_roots(self) -> tuple[Path, ...]:
        return self._source_loader._package_roots

    def get_system_prompt_override(self) -> str | None:
        return self._source_loader.get_system_prompt_override()

    def get_append_system_prompt_overrides(self) -> list[str]:
        return self._source_loader.get_append_system_prompt_overrides()

    def get_system_prompt(self, *, base_prompt: str | None = None) -> str | None:
        profile = getattr(self._source_loader, "_resource_profile", None)
        assembler = getattr(profile, "system_prompt_assembler", None)
        if assembler is None:
            return base_prompt
        return assembler(base_prompt, self.get_resource_bundle())

    def close(self) -> None:
        """Release only this view; the shared input loader owns source leases."""

        self._catalog_projection = None
        self._catalog_inputs_pending = True


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


__all__ = [
    "CatalogSessionResourceLoaderView",
    "DEFAULT_CONTEXT_FILE_NAMES",
    "ProfiledResourceLoader",
    "ResourceLoader",
    "ResourceLoaderCompatibilityError",
    "ResourceLoaderProfile",
]

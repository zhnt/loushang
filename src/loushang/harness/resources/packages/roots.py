from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._catalog_input_receipt import (
    CatalogPluginPackageInput,
)
from loushang.harness.resources.layout import resolve_user_resource_roots
from loushang.harness.resources.packages.manifest import (
    project_plugin_diagnostics,
    resolve_package_manifest,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.packages.source import (
    PackageSourceConfig,
    is_remote_package_source,
)
from loushang.harness.resources.packages.source_resolver import (
    configured_package_sources,
    package_source_scopes,
)
from loushang.harness.resources.plugins.authority import (
    PluginInspection,
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.manifest import PluginManifestError
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)


class ResourceRootSettingsSnapshot(Protocol):
    @property
    def package_roots(self) -> tuple[str, ...]: ...

    @property
    def plugin_sources(self) -> tuple[str, ...]: ...

    @property
    def package_sources(self) -> tuple[PackageSourceConfig, ...]: ...

    @property
    def disabled_plugins(self) -> tuple[str, ...]: ...


class ResourceRootSettingsManager(Protocol):
    @property
    def global_base_dir(self) -> Path | None: ...

    @property
    def project_base_dir(self) -> Path | None: ...

    def get_settings(self) -> ResourceRootSettingsSnapshot: ...

    def get_global_settings(self) -> Mapping[str, object]: ...


class ResourceRootLoader(Protocol):
    def set_package_mounts(
        self,
        mounts: Sequence[PackageResourceMount],
        *,
        catalog_plugin_package_inputs: Sequence[CatalogPluginPackageInput] = (),
    ) -> None: ...

    def set_user_resource_roots(
        self,
        user_resource_roots: Sequence[str | Path] | None,
        *,
        explicit_roots: Collection[str | Path] | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class SelectedPluginPackageInput:
    """Product-selected published package evidence for Resource discovery.

    The caller retains the package's original revision handle.  Root
    configuration acquires an independent lease before transferring the mount
    to the Resource loader.
    """

    package: PublishedPluginPackage
    binding: PluginSourceBinding

    def __post_init__(self) -> None:
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Selected Plugin input requires a published package")
        if not isinstance(self.binding, PluginSourceBinding):
            raise TypeError("Selected Plugin input requires a source binding")
        if self.binding.plugin_id != self.package.manifest.name:
            raise ValueError("Selected Plugin package binding does not match its package")
        if (
            self.binding.content_digest != self.package.content_digest
            or self.binding.manifest_digest != self.package.manifest_digest
            or self.binding.dependency_lock != self.package.dependency_lock
        ):
            raise ValueError("Selected Plugin package binding lineage is invalid")


@dataclass(frozen=True)
class ResolvedPackageResourceRoots:
    mounts: tuple[PackageResourceMount, ...] = ()
    catalog_plugin_package_inputs: tuple[CatalogPluginPackageInput, ...] = ()

    @property
    def roots(self) -> tuple[str, ...]:
        return tuple(str(mount.root) for mount in self.mounts if mount.enabled)

    @property
    def filters(self) -> dict[Path, PackageSourceConfig]:
        return {
            mount.root: mount.source_filter
            for mount in self.mounts
            if mount.enabled and mount.source_filter is not None
        }

    @property
    def revision_handles(self) -> tuple[VerifiedRevisionHandle, ...]:
        handles: list[VerifiedRevisionHandle] = []
        seen: set[int] = set()
        for mount in self.mounts:
            handle = mount.revision_handle
            if handle is not None and id(handle) not in seen:
                handles.append(handle)
                seen.add(id(handle))
        return tuple(handles)


def configure_resource_loader_roots(
    *,
    resource_loader: ResourceRootLoader,
    settings_manager: ResourceRootSettingsManager,
    materializer: PackageMaterializer,
    diagnostics_service: DiagnosticsService | None = None,
    session_id: str | None = None,
    selected_plugin_packages: Sequence[SelectedPluginPackageInput] = (),
) -> ResolvedPackageResourceRoots:
    """Bind standard package and user resource roots to one loader."""

    settings = settings_manager.get_settings()
    scoped_package_sources = configured_package_sources(settings_manager)
    resolved = resolve_package_resource_roots(
        package_roots=settings.package_roots,
        plugin_sources=settings.plugin_sources,
        package_sources=scoped_package_sources or settings.package_sources,
        materializer=materializer,
        package_source_scopes=package_source_scopes(settings_manager),
        global_base_dir=settings_manager.global_base_dir,
        project_base_dir=settings_manager.project_base_dir,
        disabled_plugins=settings.disabled_plugins,
        diagnostics_service=diagnostics_service,
        session_id=session_id,
        selected_plugin_packages=selected_plugin_packages,
    )
    try:
        resource_loader.set_package_mounts(
            resolved.mounts,
            catalog_plugin_package_inputs=resolved.catalog_plugin_package_inputs,
        )
    except Exception:
        _close_mounts(resolved.mounts)
        raise
    configured_global_roots = settings_manager.get_global_settings().get(
        "resource_roots",
        (),
    )
    global_resource_roots: tuple[str | Path, ...] = (
        tuple(configured_global_roots)
        if isinstance(configured_global_roots, list | tuple)
        and all(isinstance(root, str | Path) for root in configured_global_roots)
        else ()
    )
    user_roots, explicit_roots = resolve_user_resource_roots(
        global_resource_roots,
        global_base_dir=settings_manager.global_base_dir,
    )
    resource_loader.set_user_resource_roots(
        user_roots,
        explicit_roots=explicit_roots,
    )
    return resolved


def resolve_package_resource_roots(
    *,
    package_roots: tuple[str, ...],
    plugin_sources: tuple[str, ...],
    package_sources: tuple[PackageSourceConfig, ...],
    materializer: PackageMaterializer,
    package_source_scopes: dict[str, str] | None = None,
    global_base_dir: str | Path | None = None,
    project_base_dir: str | Path | None = None,
    disabled_plugins: tuple[str, ...] = (),
    diagnostics_service: DiagnosticsService | None = None,
    session_id: str | None = None,
    selected_plugin_packages: Sequence[SelectedPluginPackageInput] = (),
) -> ResolvedPackageResourceRoots:
    selected_inputs = tuple(selected_plugin_packages)
    if any(not isinstance(item, SelectedPluginPackageInput) for item in selected_inputs):
        raise TypeError("Selected Plugin package inputs are invalid")
    selected_plugin_ids = tuple(
        item.package.manifest.name for item in selected_inputs
    )
    if len(set(selected_plugin_ids)) != len(selected_plugin_ids):
        raise ValueError("Selected Plugin package inputs must be unique")
    mounts: list[PackageResourceMount] = []
    for configured_root in package_roots:
        _upsert_package_mount(
            mounts,
            PackageResourceMount(root=Path(configured_root)),
        )
    authority = PluginResolutionAuthority(disabled_plugins=disabled_plugins)
    resolved_plugins: list[tuple[str, PluginInspection]] = []
    for source in plugin_sources:
        if is_remote_package_source(source):
            record = materializer.get_record(source)
            if record is not None and record.lifecycle == "installed":
                inspection = authority.inspect(
                    PluginSource(
                        path=record.target_path,
                        url=source,
                        kind="remote",
                    )
                )
                if not inspection.runtime_ready:
                    _record_plugin_manifest_diagnostics(
                        diagnostics_service,
                        source=source,
                        diagnostics=project_plugin_diagnostics(inspection.diagnostics),
                        session_id=session_id,
                    )
                    continue
                resolved_plugins.append((source, inspection))
            continue
        inspection = authority.inspect(PluginSource(path=Path(source).expanduser()))
        if not inspection.runtime_ready:
            _record_plugin_manifest_diagnostics(
                diagnostics_service,
                source=source,
                diagnostics=project_plugin_diagnostics(inspection.diagnostics),
                session_id=session_id,
            )
            continue
        resolved_plugins.append((source, inspection))
    runtime_resolution: PluginRuntimeResolution | None = None
    try:
        runtime_resolution = authority.publish_runtime(
            tuple(inspection for _, inspection in resolved_plugins),
            binding_store=materializer,
        )
    except (PluginManifestError, PluginRevisionError) as exc:
        _record_plugin_identity_diagnostic(
            diagnostics_service,
            source=_plugin_source_for_error(
                resolved_plugins,
                exc=exc,
                error_path=exc.path,
            ),
            exc=exc,
            session_id=session_id,
        )
        raise
    assert runtime_resolution is not None
    configured_plugin_ids = {
        package.manifest.name for package in runtime_resolution.packages
    }
    duplicate_plugin_ids = sorted(set(selected_plugin_ids) & configured_plugin_ids)
    if duplicate_plugin_ids:
        runtime_resolution.close()
        raise ValueError(
            "Product-selected Plugin duplicates a configured Plugin source: "
            + ", ".join(duplicate_plugin_ids)
        )
    selected_packages: list[
        tuple[PublishedPluginPackage, PluginSourceBinding]
    ] = []
    try:
        for selected_input in selected_inputs:
            package = selected_input.package
            revision_handle = package.revision_handle.acquire()
            leased_package = replace(package, revision_handle=revision_handle)
            _upsert_package_mount(
                mounts,
                PackageResourceMount(
                    root=leased_package.package_root,
                    content_digest=leased_package.content_digest,
                    revision_handle=revision_handle,
                ),
            )
            selected_packages.append((leased_package, selected_input.binding))
        for package, plugin in zip(
            runtime_resolution.packages,
            runtime_resolution.plugins,
            strict=True,
        ):
            if plugin.enabled:
                resolved_resources = authority.resolve_resources(plugin)
                root = resolved_resources.package_roots[0]
            else:
                root = package.package_root
            _upsert_package_mount(
                mounts,
                PackageResourceMount(
                    root=root,
                    enabled=plugin.enabled,
                    content_digest=package.content_digest,
                    revision_handle=package.revision_handle,
                ),
            )
    except Exception:
        runtime_resolution.close()
        _close_mounts(mounts)
        raise
    try:
        for package_source in package_sources:
            if is_remote_package_source(package_source.source):
                record = materializer.get_record(package_source.source)
                if record is None or record.lifecycle != "installed":
                    continue
                resolved_root = resolve_package_manifest(
                    record.target_path
                ).package_root
            else:
                scope = (package_source_scopes or {}).get(package_source.source)
                resolved_root = _resolve_local_package_source(
                    package_source.source,
                    scope=scope,
                    global_base_dir=global_base_dir,
                    project_base_dir=project_base_dir,
                )
            _upsert_package_mount(
                mounts,
                PackageResourceMount(
                    root=Path(resolved_root),
                    source_filter=package_source,
                ),
            )
    except Exception:
        runtime_resolution.close()
        _close_mounts(mounts)
        raise
    catalog_plugin_package_inputs: list[CatalogPluginPackageInput] = []
    enabled_packages = [
        *selected_packages,
        *(
            (package, binding)
            for package, plugin, binding in zip(
                runtime_resolution.packages,
                runtime_resolution.plugins,
                runtime_resolution.bindings,
                strict=True,
            )
            if plugin.enabled
        ),
    ]
    for package, binding in enabled_packages:
        matching_orders = [
            index
            for index, mount in enumerate(mounts)
            if mount.enabled and mount.revision_handle is package.revision_handle
        ]
        if len(matching_orders) != 1:
            runtime_resolution.close()
            _close_mounts(mounts)
            raise ValueError("Published Plugin does not have one discovery mount")
        catalog_plugin_package_inputs.append(
            CatalogPluginPackageInput(
                package=package,
                binding=binding,
                source_root_order=matching_orders[0],
            )
        )
    return ResolvedPackageResourceRoots(
        mounts=tuple(mounts),
        catalog_plugin_package_inputs=tuple(catalog_plugin_package_inputs),
    )


def _upsert_package_mount(
    mounts: list[PackageResourceMount],
    candidate: PackageResourceMount,
) -> None:
    for index, current in enumerate(mounts):
        if current.root != candidate.root:
            continue
        if current.verified and candidate.verified:
            if current.content_digest != candidate.content_digest:
                raise ValueError(
                    f"Package mount root has conflicting revisions: {current.root}"
                )
            if current.revision_handle is not candidate.revision_handle:
                candidate.close()
            base = current
        elif candidate.verified:
            base = candidate
        else:
            base = current
        mounts[index] = replace(
            base,
            source_filter=candidate.source_filter or current.source_filter,
            enabled=current.enabled or candidate.enabled,
        )
        return
    mounts.append(candidate)


def _close_mounts(mounts: Sequence[PackageResourceMount]) -> None:
    closed: set[int] = set()
    for mount in mounts:
        handle = mount.revision_handle
        if handle is not None and id(handle) not in closed:
            handle.close()
            closed.add(id(handle))


def _plugin_source_for_error(
    resolved_plugins: list[tuple[str, PluginInspection]],
    *,
    exc: Exception,
    error_path: Path,
) -> str:
    attributed_source = getattr(exc, "plugin_source", None)
    if isinstance(attributed_source, str) and attributed_source:
        return attributed_source
    for source, inspection in resolved_plugins:
        package = inspection.package
        if package is None:
            continue
        if _path_belongs_to(error_path, package.root):
            return source
    return str(error_path)


def _path_belongs_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_local_package_source(
    source: str,
    *,
    scope: str | None,
    global_base_dir: str | Path | None,
    project_base_dir: str | Path | None,
) -> Path:
    path = Path(source).expanduser()
    if path.is_absolute():
        return path.resolve()
    base: str | Path | None = None
    if scope in {"user", "global"}:
        base = global_base_dir
    elif scope == "project":
        base = project_base_dir
    if base is None:
        return path.resolve()
    return (Path(base).expanduser() / path).resolve()


def _record_plugin_identity_diagnostic(
    diagnostics_service: DiagnosticsService | None,
    *,
    source: str,
    exc: PluginManifestError | PluginRevisionError,
    session_id: str | None,
) -> None:
    if diagnostics_service is None:
        return
    diagnostics_service.capture_failure(
        code=exc.code,
        error=exc,
        phase="startup",
        source="package",
        level="warning",
        session_id=session_id,
        details={"plugin_source": source},
    )


def _record_plugin_manifest_diagnostics(
    diagnostics_service: DiagnosticsService | None,
    *,
    source: str,
    diagnostics: tuple[dict[str, object], ...],
    session_id: str | None,
) -> None:
    if diagnostics_service is None:
        return
    drafts: list[DiagnosticDraft] = []
    for diagnostic in diagnostics:
        code = diagnostic.get("code")
        message = diagnostic.get("message")
        path = diagnostic.get("path")
        if not isinstance(code, str) or not isinstance(message, str):
            continue
        drafts.append(
            DiagnosticDraft(
                code=code,
                message=message,
                source_path=Path(path) if isinstance(path, str) else None,
                details={"plugin_source": source},
            )
        )
    diagnostics_service.record_drafts(
        drafts,
        phase="startup",
        source="package",
        session_id=session_id,
        level="warning",
    )

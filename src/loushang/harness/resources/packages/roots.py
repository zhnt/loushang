from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources.layout import resolve_user_resource_roots
from loushang.harness.resources.packages.manifest import resolve_package_manifest
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
from loushang.harness.resources.plugins import PluginManager
from loushang.harness.resources.plugins.manifest import PluginManifestError
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    ResolvedPluginPackage,
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
    ) -> None: ...

    def set_user_resource_roots(
        self,
        user_resource_roots: Sequence[str | Path] | None,
        *,
        explicit_roots: Collection[str | Path] | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class ResolvedPackageResourceRoots:
    mounts: tuple[PackageResourceMount, ...] = ()

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
    )
    try:
        resource_loader.set_package_mounts(resolved.mounts)
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
) -> ResolvedPackageResourceRoots:
    mounts: list[PackageResourceMount] = []
    for configured_root in package_roots:
        _upsert_package_mount(
            mounts,
            PackageResourceMount(root=Path(configured_root)),
        )
    manager = PluginManager(disabled_plugins=disabled_plugins)
    resolved_plugins: list[tuple[str, ResolvedPluginPackage]] = []
    for source in plugin_sources:
        if is_remote_package_source(source):
            record = materializer.get_record(source)
            if record is not None and record.lifecycle == "installed":
                manifest = resolve_package_manifest(
                    record.target_path,
                    plugin_source=PluginSource(
                        path=record.target_path,
                        url=source,
                        kind="remote",
                    ),
                )
                package = manifest.resolved_plugin_package
                if package is None:
                    _record_plugin_manifest_diagnostics(
                        diagnostics_service,
                        source=source,
                        diagnostics=manifest.diagnostics,
                        session_id=session_id,
                    )
                    continue
                resolved_plugins.append((source, package))
            continue
        try:
            manifest = resolve_package_manifest(
                source,
                plugin_source=PluginSource(path=Path(source).expanduser()),
            )
        except Exception as exc:
            _record_plugin_source_diagnostic(
                diagnostics_service,
                source=source,
                exc=exc,
                session_id=session_id,
            )
            continue
        package = manifest.resolved_plugin_package
        if package is None:
            _record_plugin_manifest_diagnostics(
                diagnostics_service,
                source=source,
                diagnostics=manifest.diagnostics,
                session_id=session_id,
            )
            continue
        resolved_plugins.append((source, package))
    published_plugins: tuple[ResolvedPluginPackage, ...] = ()
    try:
        published_plugins = materializer.publish_plugin_packages(
            tuple(package for _, package in resolved_plugins)
        )
        materializer.bind_plugin_packages(published_plugins)
    except (PluginManifestError, PluginRevisionError) as exc:
        _record_plugin_identity_diagnostic(
            diagnostics_service,
            source=_plugin_source_for_error(
                resolved_plugins,
                published_plugins,
                error_path=exc.path,
            ),
            exc=exc,
            session_id=session_id,
        )
        for package in published_plugins:
            if package.revision_handle is not None:
                package.revision_handle.close()
        raise
    revision_handles = tuple(
        package.revision_handle
        for package in published_plugins
        if package.revision_handle is not None
    )
    try:
        for package in published_plugins:
            plugin = manager.add_resolved_plugin_package(package)
            if plugin.enabled:
                resolved_resources = manager.resolver.resolve_resources(plugin)
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
        for handle in revision_handles:
            handle.close()
        raise
    try:
        for package_source in package_sources:
            if is_remote_package_source(package_source.source):
                record = materializer.get_record(package_source.source)
                if record is None or record.lifecycle != "installed":
                    continue
                resolved_root = resolve_package_manifest(record.target_path).package_root
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
        for handle in revision_handles:
            handle.close()
        raise
    return ResolvedPackageResourceRoots(mounts=tuple(mounts))


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
    resolved_plugins: list[tuple[str, ResolvedPluginPackage]],
    published_plugins: tuple[ResolvedPluginPackage, ...],
    *,
    error_path: Path,
) -> str:
    candidates = published_plugins or tuple(
        package for _, package in resolved_plugins
    )
    for (source, _), package in zip(resolved_plugins, candidates, strict=True):
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


def _record_plugin_source_diagnostic(
    diagnostics_service: DiagnosticsService | None,
    *,
    source: str,
    exc: Exception,
    session_id: str | None,
) -> None:
    if diagnostics_service is None:
        return
    diagnostics_service.capture_failure(
        code="plugin_source_unresolved",
        error=exc,
        phase="startup",
        source="bootstrap",
        level="warning",
        session_id=session_id,
        details={"plugin_source": source, "exception_type": type(exc).__name__},
    )


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

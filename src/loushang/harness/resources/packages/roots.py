from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.resources.layout import resolve_user_resource_roots
from loushang.harness.resources.packages.manifest import resolve_package_manifest
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.source import (
    PackageSourceConfig,
    is_remote_package_source,
)
from loushang.harness.resources.packages.source_resolver import (
    configured_package_sources,
    package_source_scopes,
)
from loushang.harness.resources.plugins import PluginManager


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
    def set_package_roots(
        self,
        package_roots: Sequence[str | Path] | None,
        package_source_filters: Mapping[str | Path, PackageSourceConfig] | None = None,
    ) -> None: ...

    def set_user_resource_roots(
        self,
        user_resource_roots: Sequence[str | Path] | None,
        *,
        explicit_roots: Collection[str | Path] | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class ResolvedPackageResourceRoots:
    roots: tuple[str, ...] = ()
    filters: dict[Path, PackageSourceConfig] = field(default_factory=dict)


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
    package_source_filters: dict[str | Path, PackageSourceConfig] = {
        root: config for root, config in resolved.filters.items()
    }
    resource_loader.set_package_roots(resolved.roots, package_source_filters)
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
    roots: list[str] = []
    filters: dict[Path, PackageSourceConfig] = {}
    for configured_root in package_roots:
        _append_package_root(roots, configured_root)
    manager = PluginManager(disabled_plugins=disabled_plugins)
    for source in plugin_sources:
        if is_remote_package_source(source):
            record = materializer.get_record(source)
            if record is not None and record.lifecycle == "installed":
                _append_package_root(
                    roots, resolve_package_manifest(record.target_path).package_root
                )
            continue
        try:
            plugin = manager.add_plugin_source(source)
        except Exception as exc:
            _record_plugin_source_diagnostic(
                diagnostics_service,
                source=source,
                exc=exc,
                session_id=session_id,
            )
            continue
        if plugin.enabled:
            _append_package_root(
                roots, plugin.manifest.package_root or plugin.manifest.root
            )
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
        _append_package_root(roots, resolved_root)
        filters[Path(resolved_root).expanduser().resolve()] = package_source
    return ResolvedPackageResourceRoots(roots=tuple(roots), filters=filters)


def _append_package_root(roots: list[str], root: str | Path) -> None:
    normalized = str(Path(root).expanduser().resolve())
    if normalized not in roots:
        roots.append(normalized)


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

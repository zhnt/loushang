from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loushang.harness.resources.packages.inventory import summarize_package_inventory
from loushang.harness.resources.packages.manifest import (
    project_plugin_diagnostics,
    resolve_package_manifest,
)
from loushang.harness.resources.packages.materializer import (
    PackageMaterializer,
)
from loushang.harness.resources.packages.source import (
    PackageSourceConfig,
    is_remote_package_source,
    package_source_from_raw,
    package_source_match_key,
    remote_package_name,
)
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
)
from loushang.harness.resources.plugins.types import PluginSource
from loushang.harness.resources.types import PackageResourceSummary

if TYPE_CHECKING:
    from loushang.harness.resources.loader import ResourceLoaderProfile

PackageCatalogKind = Literal["package_root", "plugin", "remote_package", "catalog"]
PackageCatalogScope = Literal["user", "project", "session", "merged", "catalog"]
PackageSummaryProvider = Callable[
    [Path, Path, PackageSourceConfig | None], PackageResourceSummary
]


@dataclass(frozen=True)
class PackageCatalogDiagnostic:
    code: str
    message: str
    path: str
    package_name: str | None = None
    conflict_versions: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageCatalogEntry:
    """Product-neutral package catalog record.

    This describes discovered package sources and their materialization state.
    It intentionally has no CLI, RPC, or presentation field names.
    """

    name: str
    kind: PackageCatalogKind
    scope: PackageCatalogScope
    version: str
    source: str
    path: Path | None
    enabled: bool
    summary: PackageResourceSummary
    lifecycle: str | None = None
    security: str | None = None
    pinned: bool = False
    requested_ref: str | None = None
    resolved_commit: str | None = None
    installed_commit: str | None = None
    dirty: bool = False
    last_updated_at: str | None = None
    filtered: bool = False
    description: str = ""
    source_type: str | None = None
    requirement: str | None = None
    resolved_name: str | None = None
    resolved_version: str | None = None
    installer: str | None = None
    installed_distributions: tuple[str, ...] = ()
    package_root: Path | None = None
    manifest_diagnostics: tuple[dict[str, object], ...] = ()
    catalog_diagnostics: tuple[PackageCatalogDiagnostic, ...] = ()
    conflict_diagnostics: tuple[PackageCatalogDiagnostic, ...] = ()
    conflict_versions: tuple[str, ...] = ()

    @property
    def has_version_conflict(self) -> bool:
        return bool(self.conflict_versions)


@dataclass(frozen=True)
class PackageCatalogSources:
    package_roots: tuple[tuple[str, PackageCatalogScope], ...] = ()
    plugin_sources: tuple[tuple[str, PackageCatalogScope], ...] = ()
    package_sources: tuple[tuple[PackageSourceConfig, PackageCatalogScope], ...] = ()


class PackageCatalogBuilder:
    """Build the reusable catalog for local, plugin, and remote packages."""

    def __init__(
        self,
        *,
        summary_provider: PackageSummaryProvider | None = None,
    ) -> None:
        self._summary_provider = summary_provider or summarize_package_resources

    def collect(
        self,
        *,
        sources: PackageCatalogSources,
        disabled_plugins: tuple[str, ...] = (),
        cwd: Path,
        catalog_path: Path | None = None,
        materializer: PackageMaterializer | None = None,
    ) -> tuple[PackageCatalogEntry, ...]:
        entries: list[PackageCatalogEntry] = []
        for root, scope in sources.package_roots:
            package_root = Path(root).expanduser().resolve()
            entries.append(
                PackageCatalogEntry(
                    name=package_root.name,
                    kind="package_root",
                    scope=scope,
                    version="",
                    source=str(package_root),
                    path=package_root,
                    enabled=True,
                    summary=self._summary_provider(package_root, cwd, None),
                )
            )

        for package_source, scope in sources.package_sources:
            if is_remote_package_source(package_source.source):
                entries.append(
                    self.remote_package_entry(
                        source=package_source.source,
                        scope=scope,
                        cwd=cwd,
                        materializer=materializer,
                        package_source=package_source,
                    )
                )
                continue
            package_root = _resolve_local_source(package_source.source, cwd)
            entries.append(
                PackageCatalogEntry(
                    name=package_root.name,
                    kind="package_root",
                    scope=scope,
                    version="",
                    source=str(package_root),
                    path=package_root,
                    enabled=True,
                    summary=self._summary_provider(package_root, cwd, package_source),
                    filtered=package_source.filtered,
                )
            )

        plugin_authority = PluginResolutionAuthority(disabled_plugins=disabled_plugins)
        for source, scope in sources.plugin_sources:
            if is_remote_package_source(source):
                entries.append(
                    self.remote_package_entry(
                        source=source,
                        scope=scope,
                        cwd=cwd,
                        materializer=materializer,
                        plugin_authority=plugin_authority,
                    )
                )
                continue
            entries.append(
                self._local_plugin_entry(
                    source=source,
                    scope=scope,
                    cwd=cwd,
                    plugin_authority=plugin_authority,
                    materializer=materializer,
                )
            )

        entries.extend(load_package_catalog(catalog_path))
        return mark_package_conflicts(entries)

    def _local_plugin_entry(
        self,
        *,
        source: str,
        scope: PackageCatalogScope,
        cwd: Path,
        plugin_authority: PluginResolutionAuthority,
        materializer: PackageMaterializer | None,
    ) -> PackageCatalogEntry:
        configured_root = Path(source).expanduser().resolve()
        inspection = plugin_authority.inspect(
            PluginSource(path=Path(source).expanduser()),
            binding_validator=materializer,
        )
        package = inspection.package
        manifest_diagnostics = project_plugin_diagnostics(inspection.diagnostics)
        plugin = (
            inspection.plugin
            if package is not None and not manifest_diagnostics
            else None
        )
        if package is not None:
            package_root = package.package_root
        else:
            package_root = configured_root
        enabled = plugin.enabled if plugin is not None else False
        return PackageCatalogEntry(
            name=(
                plugin.manifest.name
                if plugin is not None
                else package.manifest.name
                if package is not None
                else configured_root.name
            ),
            kind="plugin",
            scope=scope,
            version=(
                plugin.manifest.version or ""
                if plugin is not None
                else package.manifest.version or ""
                if package is not None
                else ""
            ),
            source=(
                str(plugin.source.path) if plugin is not None else str(configured_root)
            ),
            path=package_root,
            enabled=enabled,
            summary=(
                self._summary_provider(package_root, cwd, None)
                if enabled
                else empty_package_summary(package_root)
            ),
            manifest_diagnostics=manifest_diagnostics,
        )

    def remote_package_entry(
        self,
        *,
        source: str,
        scope: PackageCatalogScope,
        cwd: Path | None = None,
        materializer: PackageMaterializer | None = None,
        package_source: PackageSourceConfig | None = None,
        plugin_authority: PluginResolutionAuthority | None = None,
    ) -> PackageCatalogEntry:
        record = materializer.get_record(source) if materializer is not None else None
        lifecycle = record.lifecycle if record is not None else "remote_registered"
        path = record.target_path if record is not None else None
        installed = lifecycle == "installed"
        if plugin_authority is not None and path is not None and installed:
            inspection = plugin_authority.inspect(
                PluginSource(path=path, url=source, kind="remote"),
                binding_validator=materializer,
            )
            resolved_plugin_package = inspection.package
            manifest_diagnostics = project_plugin_diagnostics(inspection.diagnostics)
            plugin = (
                inspection.plugin
                if resolved_plugin_package is not None and not manifest_diagnostics
                else None
            )
            manifest_root = (
                resolved_plugin_package.root
                if resolved_plugin_package is not None
                else path.resolve()
            )
            manifest_package_root = (
                resolved_plugin_package.package_root
                if resolved_plugin_package is not None
                else manifest_root
            )
            manifest_version = (
                resolved_plugin_package.manifest.version or ""
                if resolved_plugin_package is not None
                else ""
            )
        else:
            manifest = resolve_package_manifest(
                path or Path(),
                installed=installed,
            )
            resolved_plugin_package = manifest.resolved_plugin_package
            manifest_diagnostics = manifest.diagnostics
            manifest_root = manifest.root
            manifest_package_root = manifest.package_root
            manifest_version = manifest.version
            plugin = None
        enabled = plugin.enabled if plugin is not None else installed
        if plugin_authority is not None and plugin is None:
            enabled = False
        summary_root = manifest_package_root if path is not None else manifest_root
        summary = (
            empty_package_summary(summary_root)
            if path is None or not enabled or not summary_root.is_dir()
            else self._summary_provider(
                summary_root, cwd or summary_root, package_source
            )
        )
        return PackageCatalogEntry(
            name=(
                plugin.manifest.name
                if plugin is not None
                else resolved_plugin_package.manifest.name
                if resolved_plugin_package is not None
                else remote_package_name(source)
            ),
            kind="remote_package",
            scope=scope,
            version=(
                plugin.manifest.version or ""
                if plugin is not None
                else resolved_plugin_package.manifest.version or ""
                if resolved_plugin_package is not None
                else manifest_version
            ),
            source=source,
            path=path,
            enabled=enabled,
            summary=summary,
            lifecycle=lifecycle,
            security=record.security if record is not None else "allowed",
            pinned=record.pinned if record is not None else False,
            requested_ref=record.requested_ref if record is not None else None,
            resolved_commit=record.resolved_commit if record is not None else None,
            installed_commit=record.installed_commit if record is not None else None,
            dirty=record.dirty if record is not None else False,
            last_updated_at=record.last_updated_at if record is not None else None,
            filtered=package_source.filtered if package_source is not None else False,
            source_type=record.source_type if record is not None else None,
            requirement=record.requirement if record is not None else None,
            resolved_name=record.resolved_name if record is not None else None,
            resolved_version=record.resolved_version if record is not None else None,
            installer=record.installer if record is not None else None,
            installed_distributions=record.installed_distributions
            if record is not None
            else (),
            package_root=(
                manifest_package_root
                if path is not None and manifest_package_root != manifest_root
                else None
            ),
            manifest_diagnostics=manifest_diagnostics,
        )


def package_catalog_sources(
    settings_manager: object | None,
    *,
    package_roots: tuple[str, ...],
    plugin_sources: tuple[str, ...],
    package_sources: tuple[PackageSourceConfig, ...],
) -> PackageCatalogSources:
    """Read scoped resource declarations without owning product settings."""

    roots: list[tuple[str, PackageCatalogScope]] = []
    plugins: list[tuple[str, PackageCatalogScope]] = []
    configured: list[tuple[PackageSourceConfig, PackageCatalogScope]] = []
    raw_configured: list[tuple[PackageSourceConfig, PackageCatalogScope]] = []
    seen: set[str] = set()
    if settings_manager is not None:
        for method_name, scope in _CATALOG_SETTINGS_SCOPES:
            getter = getattr(settings_manager, method_name, None)
            if not callable(getter):
                continue
            patch = getter()
            if not isinstance(patch, Mapping):
                continue
            roots.extend(
                (value, scope) for value in _string_values(patch.get("package_roots"))
            )
            plugins.extend(
                (value, scope) for value in _string_values(patch.get("plugin_sources"))
            )
            raw_configured.extend(
                (value, scope)
                for value in _package_source_values(
                    patch.get("packages", patch.get("package_sources"))
                )
            )
        for source, scope in sorted(
            raw_configured, key=lambda item: _scope_rank(item[1])
        ):
            normalized = _normalize_local_source_for_scope(
                source, scope, settings_manager
            )
            match_key = package_source_match_key(normalized.source)
            if match_key in seen:
                continue
            seen.add(match_key)
            configured.append((normalized, scope))
    if not configured:
        configured.extend((source, "merged") for source in package_sources)
    if not roots and not plugins and not configured:
        roots.extend((root, "merged") for root in package_roots)
        plugins.extend((source, "merged") for source in plugin_sources)
    return PackageCatalogSources(
        package_roots=tuple(roots),
        plugin_sources=tuple(plugins),
        package_sources=tuple(configured),
    )


def collect_package_catalog(
    *,
    package_roots: tuple[str, ...],
    plugin_sources: tuple[str, ...],
    disabled_plugins: tuple[str, ...],
    cwd: Path,
    package_sources: tuple[PackageSourceConfig, ...] = (),
    settings_manager: object | None = None,
    catalog_path: Path | None = None,
    materializer: PackageMaterializer | None = None,
    summary_provider: PackageSummaryProvider | None = None,
) -> tuple[PackageCatalogEntry, ...]:
    """Collect a package catalog with Product resource semantics injected."""

    return PackageCatalogBuilder(summary_provider=summary_provider).collect(
        sources=package_catalog_sources(
            settings_manager,
            package_roots=package_roots,
            plugin_sources=plugin_sources,
            package_sources=package_sources,
        ),
        disabled_plugins=disabled_plugins,
        cwd=cwd,
        catalog_path=catalog_path,
        materializer=materializer,
    )


def summarize_package_resources(
    package_root: Path,
    cwd: Path,
    package_source: PackageSourceConfig | None = None,
) -> PackageResourceSummary:
    del cwd
    return summarize_package_inventory(package_root, package_source)


def summarize_profiled_package_resources(
    package_root: Path,
    cwd: Path,
    package_source: PackageSourceConfig | None = None,
    *,
    profile: ResourceLoaderProfile,
) -> PackageResourceSummary:
    """Compatibility signature over the Product-neutral inventory port."""

    del cwd, profile
    return summarize_package_inventory(package_root, package_source)


def empty_package_summary(package_root: Path) -> PackageResourceSummary:
    return PackageResourceSummary(source_root=package_root)


def load_package_catalog(catalog_path: Path | None) -> tuple[PackageCatalogEntry, ...]:
    if catalog_path is None:
        return ()
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (
            _catalog_diagnostic_entry(
                catalog_path,
                "invalid_package_catalog",
                f"Invalid package catalog JSON: {exc.msg}",
            ),
        )
    except Exception as exc:
        return (
            _catalog_diagnostic_entry(
                catalog_path,
                "unreadable_package_catalog",
                f"Package catalog could not be read: {exc}",
            ),
        )
    items = payload.get("packages") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return (
            _catalog_diagnostic_entry(
                catalog_path,
                "invalid_package_catalog",
                "Package catalog must be a list or an object with a packages list.",
            ),
        )
    entries: list[PackageCatalogEntry] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        source = item.get("source", item.get("url", ""))
        entries.append(
            PackageCatalogEntry(
                name=name,
                kind="catalog",
                scope="catalog",
                version=item["version"] if isinstance(item.get("version"), str) else "",
                source=source if isinstance(source, str) else "",
                path=None,
                enabled=False,
                description=item["description"]
                if isinstance(item.get("description"), str)
                else "",
                summary=PackageResourceSummary(
                    source_root=catalog_path,
                    prompt_count=_nonnegative_int(item.get("prompts")),
                    skill_count=_nonnegative_int(item.get("skills")),
                    extension_count=_nonnegative_int(item.get("extensions")),
                    theme_count=_nonnegative_int(item.get("themes")),
                ),
            )
        )
    return tuple(entries)


def mark_package_conflicts(
    entries: list[PackageCatalogEntry],
) -> tuple[PackageCatalogEntry, ...]:
    versions_by_name: dict[str, set[str]] = {}
    for entry in entries:
        versions_by_name.setdefault(entry.name, set()).add(entry.version)
    marked: list[PackageCatalogEntry] = []
    for entry in entries:
        versions = tuple(
            sorted(version for version in versions_by_name[entry.name] if version)
        )
        if len(versions) > 1:
            diagnostic = PackageCatalogDiagnostic(
                code="package_version_conflict",
                message=(
                    f"Package '{entry.name}' has multiple configured versions: "
                    f"{', '.join(versions)}."
                ),
                path=str(entry.path or entry.source),
                package_name=entry.name,
                conflict_versions=versions,
            )
            entry = replace(
                entry,
                conflict_versions=versions,
                conflict_diagnostics=(*entry.conflict_diagnostics, diagnostic),
            )
        marked.append(entry)
    return tuple(marked)


_CATALOG_SETTINGS_SCOPES: tuple[tuple[str, PackageCatalogScope], ...] = (
    ("get_global_settings", "user"),
    ("get_project_settings", "project"),
    ("get_session_settings", "session"),
)


def _catalog_diagnostic_entry(
    catalog_path: Path, code: str, message: str
) -> PackageCatalogEntry:
    return PackageCatalogEntry(
        name=catalog_path.name,
        kind="catalog",
        scope="catalog",
        version="",
        source=str(catalog_path),
        path=catalog_path,
        enabled=False,
        summary=empty_package_summary(catalog_path),
        catalog_diagnostics=(
            PackageCatalogDiagnostic(
                code=code, message=message, path=str(catalog_path)
            ),
        ),
    )


def _resolve_local_source(source: str, cwd: Path) -> Path:
    path = Path(source).expanduser()
    return path.resolve() if path.is_absolute() else (cwd / path).resolve()


def _normalize_local_source_for_scope(
    source: PackageSourceConfig,
    scope: PackageCatalogScope,
    settings_manager: object,
) -> PackageSourceConfig:
    if is_remote_package_source(source.source):
        return source
    path = Path(source.source).expanduser()
    if path.is_absolute():
        return replace(source, source=str(path.resolve()))
    base = _scope_base_dir(settings_manager, scope)
    return (
        replace(source, source=str((base / path).resolve()))
        if base is not None
        else source
    )


def _scope_base_dir(
    settings_manager: object, scope: PackageCatalogScope
) -> Path | None:
    attr = (
        "global_base_dir"
        if scope == "user"
        else "project_base_dir"
        if scope == "project"
        else ""
    )
    value = getattr(settings_manager, attr, None) if attr else None
    return Path(value).expanduser().resolve() if value is not None else None


def _scope_rank(scope: PackageCatalogScope) -> int:
    return {"project": 0, "user": 1, "session": 2}.get(scope, 3)


def _string_values(value: object) -> tuple[str, ...]:
    return (
        tuple(item for item in value if isinstance(item, str) and item)
        if isinstance(value, list | tuple)
        else ()
    )


def _package_source_values(value: object) -> tuple[PackageSourceConfig, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(
        source
        for item in value
        if (source := package_source_from_raw(item)) is not None
    )


def _nonnegative_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )

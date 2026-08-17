"""Product-neutral projections for package catalog and lifecycle records."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from loushang.harness.resources.packages.catalog import (
    PackageCatalogDiagnostic,
    PackageCatalogEntry,
    PackageSummaryProvider,
    collect_package_catalog,
)
from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
    PackageMaterializer,
)
from loushang.harness.resources.packages.source import PackageSourceConfig


def collect_projected_package_entries(
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
) -> list[dict[str, object]]:
    """Collect and project package records with Product policy injected."""

    return project_package_entries(
        collect_package_catalog(
            package_roots=package_roots,
            plugin_sources=plugin_sources,
            disabled_plugins=disabled_plugins,
            cwd=cwd,
            package_sources=package_sources,
            settings_manager=settings_manager,
            catalog_path=catalog_path,
            materializer=materializer,
            summary_provider=summary_provider,
        )
    )


def project_package_entries(
    entries: Sequence[PackageCatalogEntry],
) -> list[dict[str, object]]:
    """Project shared package records into the established listing shape."""

    return [project_package_entry(entry) for entry in entries]


def project_package_entry(entry: PackageCatalogEntry) -> dict[str, object]:
    """Project one package catalog entry without owning discovery policy."""

    summary = entry.summary
    package_kind = {
        "package_root": "local_package_root",
        "plugin": "plugin_package",
        "remote_package": "remote_package",
        "catalog": "catalog_package",
    }[entry.kind]
    kind = "remote_plugin" if entry.kind == "remote_package" else entry.kind
    payload: dict[str, object] = {
        "name": entry.name,
        "kind": kind,
        "packageKind": package_kind,
        "scope": entry.scope,
        "version": entry.version,
        "source": entry.source,
        "path": str(entry.path) if entry.path is not None else "",
        "enabled": entry.enabled,
        "prompts": summary.prompt_count,
        "skills": summary.skill_count,
        "extensions": summary.extension_count,
        "themes": summary.theme_count,
        "diagnostics": summary.diagnostic_count
        + len(entry.manifest_diagnostics)
        + len(entry.catalog_diagnostics),
        "description": entry.description,
    }
    if entry.lifecycle is not None:
        payload.update(
            {
                "lifecycle": entry.lifecycle,
                "security": entry.security or "allowed",
                "pinned": entry.pinned,
                "requestedRef": entry.requested_ref or "",
                "resolvedCommit": entry.resolved_commit or "",
                "installedCommit": entry.installed_commit or "",
                "dirty": entry.dirty,
                "lastUpdatedAt": entry.last_updated_at or "",
                "filtered": entry.filtered,
            }
        )
    elif entry.filtered:
        payload["filtered"] = True
    if entry.source_type is not None:
        payload.update(
            {
                "sourceType": entry.source_type,
                "requirement": entry.requirement or "",
                "resolvedName": entry.resolved_name or "",
                "resolvedVersion": entry.resolved_version or "",
                "installer": entry.installer or "",
                "installedDistributions": list(entry.installed_distributions),
            }
        )
    if entry.package_root is not None:
        payload["packageRoot"] = str(entry.package_root)
    if entry.manifest_diagnostics:
        payload["manifestDiagnostics"] = entry.manifest_diagnostics
    if entry.catalog_diagnostics:
        payload["catalogDiagnostics"] = tuple(
            _project_catalog_diagnostic(diagnostic)
            for diagnostic in entry.catalog_diagnostics
        )
    if entry.has_version_conflict:
        versions = list(entry.conflict_versions)
        payload.update(
            {
                "version_conflict": True,
                "versionConflict": True,
                "conflictVersions": versions,
                "conflict_versions": versions,
                "conflictDiagnostics": tuple(
                    _project_catalog_diagnostic(diagnostic)
                    for diagnostic in entry.conflict_diagnostics
                ),
            }
        )
    return payload


def serialize_package_materialization_record(
    record: PackageMaterializationRecord,
) -> dict[str, object]:
    """Project a package lifecycle record for command/event consumers."""

    return {
        "source": record.source,
        "name": record.name,
        "lifecycle": record.lifecycle,
        "targetPath": str(record.target_path),
        "errorMessage": record.error_message,
        "security": record.security,
        "pinned": record.pinned,
        "requestedRef": record.requested_ref,
        "resolvedCommit": record.resolved_commit,
        "installedCommit": record.installed_commit,
        "dirty": record.dirty,
        "lastUpdatedAt": record.last_updated_at,
        "sourceType": record.source_type,
        "requirement": record.requirement,
        "resolvedName": record.resolved_name,
        "resolvedVersion": record.resolved_version,
        "installer": record.installer,
        "installedDistributions": list(record.installed_distributions),
    }


def _project_catalog_diagnostic(
    diagnostic: PackageCatalogDiagnostic,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "path": diagnostic.path,
    }
    if diagnostic.package_name is not None:
        payload["packageName"] = diagnostic.package_name
    if diagnostic.conflict_versions:
        payload["conflictVersions"] = list(diagnostic.conflict_versions)
    return payload


__all__ = [
    "collect_projected_package_entries",
    "project_package_entries",
    "project_package_entry",
    "serialize_package_materialization_record",
]

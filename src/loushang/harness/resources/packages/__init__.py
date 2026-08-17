"""Lazy public exports for resource package management."""

# ruff: noqa: F401 - TYPE_CHECKING imports preserve the typed public facade.

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loushang.harness.resources.packages.catalog import (
        PackageCatalogBuilder,
        PackageCatalogDiagnostic,
        PackageCatalogEntry,
        PackageCatalogSources,
        PackageSummaryProvider,
        collect_package_catalog,
        empty_package_summary,
        load_package_catalog,
        mark_package_conflicts,
        package_catalog_sources,
        summarize_package_resources,
        summarize_profiled_package_resources,
    )
    from loushang.harness.resources.packages.catalog_diagnostics import (
        PackageCatalogDiagnosticsRecorder,
        record_package_lockfile_diagnostics,
        record_package_source_policy_denial,
    )
    from loushang.harness.resources.packages.manifest import (
        PackageManifestInfo,
        resolve_package_manifest,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
        PackageMaterializationLifecycle,
        PackageMaterializationRecord,
        PackageMaterializer,
        PackageMaterializerBackend,
        PackageProgressEvent,
        PackageSourcePolicy,
        PythonPackageInstallerBackend,
        package_offline_enabled,
        resolve_session_package_install_root,
    )
    from loushang.harness.resources.packages.operations import (
        PackageMaterializerPort,
        PackageMaterializerProvider,
        PackageOperationsRuntime,
        PackageResourceRefresh,
        PackageSourceRegistration,
        PackageUpdatePreparation,
    )
    from loushang.harness.resources.packages.projection import (
        collect_projected_package_entries,
        project_package_entries,
        project_package_entry,
        serialize_package_materialization_record,
    )
    from loushang.harness.resources.packages.roots import (
        ResolvedPackageResourceRoots,
        configure_resource_loader_roots,
        resolve_package_resource_roots,
    )
    from loushang.harness.resources.packages.security import (
        PackageSecurityPolicy,
        PackageSourceSecurityReport,
    )
    from loushang.harness.resources.packages.source import (
        PackageSourceConfig,
        PackageSourceIdentity,
        clone_source_and_ref,
        is_python_package_source,
        is_remote_package_source,
        package_source_from_raw,
        package_source_match_key,
        python_package_name,
        python_package_requirement,
        remote_package_name,
    )
    from loushang.harness.resources.packages.source_resolver import (
        MissingSourceAction,
        MissingSourceResolver,
        PackageResolveResult,
        PackageSourceResolver,
        configured_package_sources,
        package_source_scopes,
    )

_EXPORT_MODULES = {
    "GitPackageMaterializerBackend": "loushang.harness.resources.packages.materializer",
    "MissingSourceAction": "loushang.harness.resources.packages.source_resolver",
    "MissingSourceResolver": "loushang.harness.resources.packages.source_resolver",
    "PackageCatalogBuilder": "loushang.harness.resources.packages.catalog",
    "PackageCatalogDiagnostic": "loushang.harness.resources.packages.catalog",
    "PackageCatalogDiagnosticsRecorder": "loushang.harness.resources.packages.catalog_diagnostics",
    "PackageCatalogEntry": "loushang.harness.resources.packages.catalog",
    "PackageCatalogSources": "loushang.harness.resources.packages.catalog",
    "PackageSummaryProvider": "loushang.harness.resources.packages.catalog",
    "PackageManifestInfo": "loushang.harness.resources.packages.manifest",
    "PackageMaterializationLifecycle": "loushang.harness.resources.packages.materializer",
    "PackageMaterializationRecord": "loushang.harness.resources.packages.materializer",
    "PackageMaterializer": "loushang.harness.resources.packages.materializer",
    "PackageMaterializerBackend": "loushang.harness.resources.packages.materializer",
    "PackageMaterializerPort": "loushang.harness.resources.packages.operations",
    "PackageMaterializerProvider": "loushang.harness.resources.packages.operations",
    "PackageOperationsRuntime": "loushang.harness.resources.packages.operations",
    "PackageProgressEvent": "loushang.harness.resources.packages.materializer",
    "PackageResolveResult": "loushang.harness.resources.packages.source_resolver",
    "PackageSourceConfig": "loushang.harness.resources.packages.source",
    "PackageSourceIdentity": "loushang.harness.resources.packages.source",
    "PackageSourcePolicy": "loushang.harness.resources.packages.materializer",
    "PackageResourceRefresh": "loushang.harness.resources.packages.operations",
    "PackageSecurityPolicy": "loushang.harness.resources.packages.security",
    "PackageSourceSecurityReport": "loushang.harness.resources.packages.security",
    "PackageSourceRegistration": "loushang.harness.resources.packages.operations",
    "PackageSourceResolver": "loushang.harness.resources.packages.source_resolver",
    "PackageUpdatePreparation": "loushang.harness.resources.packages.operations",
    "PythonPackageInstallerBackend": "loushang.harness.resources.packages.materializer",
    "ResolvedPackageResourceRoots": "loushang.harness.resources.packages.roots",
    "clone_source_and_ref": "loushang.harness.resources.packages.source",
    "collect_package_catalog": "loushang.harness.resources.packages.catalog",
    "collect_projected_package_entries": "loushang.harness.resources.packages.projection",
    "configure_resource_loader_roots": "loushang.harness.resources.packages.roots",
    "configured_package_sources": "loushang.harness.resources.packages.source_resolver",
    "empty_package_summary": "loushang.harness.resources.packages.catalog",
    "is_python_package_source": "loushang.harness.resources.packages.source",
    "is_remote_package_source": "loushang.harness.resources.packages.source",
    "load_package_catalog": "loushang.harness.resources.packages.catalog",
    "mark_package_conflicts": "loushang.harness.resources.packages.catalog",
    "package_catalog_sources": "loushang.harness.resources.packages.catalog",
    "package_offline_enabled": "loushang.harness.resources.packages.materializer",
    "package_source_match_key": "loushang.harness.resources.packages.source",
    "package_source_scopes": "loushang.harness.resources.packages.source_resolver",
    "package_source_from_raw": "loushang.harness.resources.packages.source",
    "project_package_entries": "loushang.harness.resources.packages.projection",
    "project_package_entry": "loushang.harness.resources.packages.projection",
    "python_package_name": "loushang.harness.resources.packages.source",
    "python_package_requirement": "loushang.harness.resources.packages.source",
    "remote_package_name": "loushang.harness.resources.packages.source",
    "record_package_lockfile_diagnostics": "loushang.harness.resources.packages.catalog_diagnostics",
    "record_package_source_policy_denial": "loushang.harness.resources.packages.catalog_diagnostics",
    "resolve_package_manifest": "loushang.harness.resources.packages.manifest",
    "resolve_package_resource_roots": "loushang.harness.resources.packages.roots",
    "resolve_session_package_install_root": "loushang.harness.resources.packages.materializer",
    "serialize_package_materialization_record": "loushang.harness.resources.packages.projection",
    "summarize_profiled_package_resources": "loushang.harness.resources.packages.catalog",
    "summarize_package_resources": "loushang.harness.resources.packages.catalog",
}


def __getattr__(name: str) -> Any:
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORT_MODULES})


__all__ = list(_EXPORT_MODULES)

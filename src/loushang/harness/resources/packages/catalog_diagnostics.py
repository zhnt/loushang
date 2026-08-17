"""Diagnostics projection for product-neutral package catalog entries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticRecord
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.packages.catalog import (
    PackageCatalogDiagnostic,
    PackageCatalogEntry,
)


@dataclass(frozen=True)
class PackageCatalogDiagnosticsRecorder:
    """Record package-catalog discovery diagnostics without a product wire schema."""

    diagnostics_service: DiagnosticsService | None
    session_id: str | None = None

    def record(self, entries: Iterable[PackageCatalogEntry]) -> None:
        if self.diagnostics_service is None:
            return
        records = []
        for entry in entries:
            records.extend(self._records_for_entry(entry))
        self.diagnostics_service.record_many(records)

    def _records_for_entry(self, entry: PackageCatalogEntry) -> list[DiagnosticRecord]:
        records = []
        for diagnostic in entry.manifest_diagnostics:
            if not isinstance(diagnostic, Mapping):
                continue
            records.append(
                self._normalize(
                    entry,
                    code=str(diagnostic.get("code") or "invalid_package_manifest"),
                    message=str(
                        diagnostic.get("message") or "Package manifest diagnostic."
                    ),
                    path=diagnostic.get("path"),
                    source_kind="external_package",
                )
            )
        records.extend(
            self._normalize_catalog_diagnostic(entry, diagnostic)
            for diagnostic in entry.catalog_diagnostics
        )
        records.extend(
            self._normalize_catalog_diagnostic(
                entry, diagnostic, source_kind="external_package"
            )
            for diagnostic in entry.conflict_diagnostics
        )
        return records

    def _normalize_catalog_diagnostic(
        self,
        entry: PackageCatalogEntry,
        diagnostic: PackageCatalogDiagnostic,
        *,
        source_kind: str | None = None,
    ) -> DiagnosticRecord:
        details: dict[str, object] = {}
        if diagnostic.conflict_versions:
            details["conflict_versions"] = list(diagnostic.conflict_versions)
        return self._normalize(
            entry,
            code=diagnostic.code,
            message=diagnostic.message,
            path=diagnostic.path,
            source_kind=source_kind,
            details=details,
        )

    def _normalize(
        self,
        entry: PackageCatalogEntry,
        *,
        code: str,
        message: str,
        path: object,
        source_kind: str | None,
        details: dict[str, object] | None = None,
    ) -> DiagnosticRecord:
        assert self.diagnostics_service is not None
        diagnostic_details: dict[str, object] = {
            "package_source": entry.source,
            "package_name": entry.name,
            "package_kind": entry.kind,
        }
        if details:
            diagnostic_details.update(details)
        return self.diagnostics_service.normalize_diagnostic(
            resource_diagnostic(
                code=code,
                message=message,
                source_path=Path(path) if isinstance(path, str) else None,
                resource_type="package",
                source_kind=source_kind,
            ),
            details=diagnostic_details,
            phase="resource_loading",
            source="package",
            session_id=self.session_id,
        )


def record_package_lockfile_diagnostics(
    diagnostics: Iterable[Mapping[str, object]],
    *,
    diagnostics_service: DiagnosticsService,
    session_id: str | None = None,
) -> tuple[DiagnosticRecord, ...]:
    """Record structured lockfile failures exposed by a materializer."""

    return tuple(
        diagnostics_service.capture_failure(
            code=str(diagnostic.get("code") or "package_lockfile_unreadable"),
            error=str(
                diagnostic.get("message") or "Package lockfile could not be read."
            ),
            phase="startup",
            source="bootstrap",
            level="warning",
            session_id=session_id,
            source_path=(
                Path(path)
                if isinstance((path := diagnostic.get("path")), str)
                else None
            ),
            details={
                key: value
                for key, value in diagnostic.items()
                if key not in {"code", "message", "path"}
            },
        )
        for diagnostic in diagnostics
    )


def record_package_source_policy_denial(
    diagnostics_service: DiagnosticsService | None,
    *,
    package_source: str,
    reason: str | None,
    session_id: str | None = None,
) -> DiagnosticRecord | None:
    """Record one standard package-source policy rejection."""

    if diagnostics_service is None:
        return None
    return diagnostics_service.capture_failure(
        code="package_source_policy_denied",
        error=reason or "Package source denied by policy.",
        phase="runtime",
        source="policy",
        session_id=session_id,
        details={
            "plugin_source": package_source,
            "policy": "package_security",
            "disposition": "deny",
        },
    )


__all__ = [
    "PackageCatalogDiagnosticsRecorder",
    "record_package_lockfile_diagnostics",
    "record_package_source_policy_denial",
]

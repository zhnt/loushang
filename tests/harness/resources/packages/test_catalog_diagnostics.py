from __future__ import annotations

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.resources.packages.catalog import (
    PackageCatalogDiagnostic,
    PackageCatalogEntry,
)
from loushang.harness.resources.packages.catalog_diagnostics import (
    PackageCatalogDiagnosticsRecorder,
    record_package_lockfile_diagnostics,
    record_package_source_policy_denial,
)
from loushang.harness.resources.types import PackageResourceSummary


def test_catalog_diagnostics_recorder_keeps_typed_catalog_details(tmp_path) -> None:
    manifest_path = tmp_path / "package.json"
    catalog_path = tmp_path / "catalog.json"
    entry = PackageCatalogEntry(
        name="review-pack",
        kind="remote_package",
        scope="project",
        version="1.0.0",
        source="https://example.test/review-pack.git",
        path=tmp_path,
        enabled=True,
        summary=PackageResourceSummary(source_root=tmp_path),
        manifest_diagnostics=(
            {
                "code": "invalid_package_manifest",
                "message": "Manifest is invalid.",
                "path": str(manifest_path),
            },
        ),
        catalog_diagnostics=(
            PackageCatalogDiagnostic(
                code="invalid_package_catalog",
                message="Catalog is invalid.",
                path=str(catalog_path),
            ),
        ),
        conflict_diagnostics=(
            PackageCatalogDiagnostic(
                code="package_version_conflict",
                message="Versions conflict.",
                path=str(tmp_path),
                conflict_versions=("1.0.0", "2.0.0"),
            ),
        ),
    )
    service = DiagnosticsService()

    PackageCatalogDiagnosticsRecorder(service, session_id="session-1").record([entry])

    manifest = service.get_diagnostics(code="invalid_package_manifest")[0]
    catalog = service.get_diagnostics(code="invalid_package_catalog")[0]
    conflict = service.get_diagnostics(code="package_version_conflict")[0]
    assert manifest.source_path == manifest_path
    assert catalog.source_path == catalog_path
    assert conflict.details["conflict_versions"] == ["1.0.0", "2.0.0"]
    assert conflict.details["package_name"] == "review-pack"
    assert conflict.session_id == "session-1"


def test_lockfile_diagnostics_recorder_preserves_structured_details(tmp_path) -> None:
    service = DiagnosticsService()
    lockfile = tmp_path / "package-lock.json"

    records = record_package_lockfile_diagnostics(
        [
            {
                "code": "package_lockfile_unreadable",
                "message": "Lockfile is invalid.",
                "path": str(lockfile),
                "line": 4,
            }
        ],
        diagnostics_service=service,
        session_id="session-1",
    )

    assert records == tuple(service.get_last_diagnostics())
    assert records[0].source_path == lockfile
    assert records[0].details == {"line": 4}
    assert records[0].session_id == "session-1"


def test_package_source_policy_denial_records_standard_diagnostic() -> None:
    service = DiagnosticsService()

    record = record_package_source_policy_denial(
        service,
        package_source="http://packages.example.invalid/review-pack.git",
        reason="HTTPS is required.",
        session_id="session-1",
    )

    assert record is service.get_last_diagnostics()[0]
    assert record.code == "package_source_policy_denied"
    assert record.message == "HTTPS is required."
    assert record.phase == "runtime"
    assert record.source == "policy"
    assert record.session_id == "session-1"
    assert record.details == {
        "plugin_source": "http://packages.example.invalid/review-pack.git",
        "policy": "package_security",
        "disposition": "deny",
    }


def test_package_source_policy_denial_ignores_missing_diagnostics_service() -> None:
    assert (
        record_package_source_policy_denial(
            None,
            package_source="package",
            reason=None,
        )
        is None
    )

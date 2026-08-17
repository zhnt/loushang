from __future__ import annotations

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.session.cwd_audit import (
    audit_cwd_bound_services,
    project_root_from_settings_base,
    record_cwd_bound_services_audit,
)


def test_cwd_audit_reports_project_root_mismatch(tmp_path) -> None:
    session_cwd = tmp_path / "project" / "src"
    project_root = tmp_path / "other"

    result = audit_cwd_bound_services(
        session_cwd=session_cwd,
        project_root=project_root,
    )

    assert result.ok is False
    assert result.issues[0].code == "settings_project_cwd_mismatch"


def test_cwd_audit_accepts_matching_resource_cwd(tmp_path) -> None:
    cwd = tmp_path / "project"

    result = audit_cwd_bound_services(session_cwd=cwd, resource_cwd=cwd)

    assert result.ok is True


def test_cwd_audit_records_standard_startup_diagnostics(tmp_path) -> None:
    audit = audit_cwd_bound_services(
        session_cwd=tmp_path / "project",
        resource_cwd=tmp_path / "other",
    )
    diagnostics = DiagnosticsService()

    record_cwd_bound_services_audit(
        audit,
        diagnostics_service=diagnostics,
        session_id="session-1",
    )

    records = diagnostics.get_last_diagnostics()
    assert [record.code for record in records] == ["resource_bundle_cwd_mismatch"]
    assert records[0].phase == "startup"
    assert records[0].source == "bootstrap"
    assert records[0].session_id == "session-1"


def test_project_root_resolves_settings_directory(tmp_path) -> None:
    project = tmp_path / "project"

    assert project_root_from_settings_base(project / ".loushang") == project
    assert project_root_from_settings_base(project) == project
    assert project_root_from_settings_base(None) is None

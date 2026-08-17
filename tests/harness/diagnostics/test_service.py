from __future__ import annotations

from pathlib import Path


def _record(
    code: str,
    *,
    level: str = "error",
    phase: str = "runtime",
    source: str = "session",
    timestamp: str = "2026-07-12T00:00:00Z",
    session_id: str | None = "s1",
    entry_id: str | None = None,
    details: dict[str, object] | None = None,
    occurrence_count: int = 1,
):
    from loushang.harness.diagnostics.types import DiagnosticRecord

    return DiagnosticRecord(
        type=level,  # type: ignore[arg-type]
        code=code,
        message=f"{code} message",
        phase=phase,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        timestamp=timestamp,
        session_id=session_id,
        entry_id=entry_id,
        details=details or {},
        occurrence_count=occurrence_count,
    )


def test_service_aggregates_duplicates_and_preserves_latest_timestamp() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService

    service = DiagnosticsService()
    first = service.record(_record("provider_failed", entry_id="e1"))
    second = service.record(
        _record(
            "provider_failed",
            timestamp="2026-07-12T00:01:00Z",
            entry_id="e2",
            occurrence_count=2,
        )
    )

    assert first.fingerprint is not None
    assert second.fingerprint == first.fingerprint
    assert second.timestamp == "2026-07-12T00:01:00Z"
    assert second.entry_id == "e1"
    assert second.occurrence_count == 3
    assert service.get_last_diagnostics() == [second]


def test_service_enforces_capacity_without_reordering_records() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService

    service = DiagnosticsService(max_records=2)
    first = service.record(_record("first"))
    second = service.record(_record("second"))
    third = service.record(_record("third"))

    assert service.get_last_diagnostics() == [second, third]
    assert service.get_last_diagnostics(limit=1) == [third]
    assert service.get_last_diagnostics(limit=0) == []
    assert first not in service.get_last_diagnostics()


def test_service_query_overrides_direct_filters_and_correlates_tools() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService
    from loushang.harness.diagnostics.types import DiagnosticsQuery

    service = DiagnosticsService()
    snake = service.record(
        _record(
            "tool_failed",
            source="tool",
            details={"tool_call_id": "tc1"},
        )
    )
    camel = service.record(
        _record(
            "tool_failed_again",
            source="tool",
            details={"toolCallId": "tc2"},
        )
    )
    service.record(_record("startup_warning", level="warning", phase="startup", source="bootstrap"))

    assert service.get_diagnostics(
        phase="startup",
        source="bootstrap",
        query=DiagnosticsQuery(
            phase="runtime",
            source="tool",
            tool_call_id="tc1",
        ),
    ) == [snake]
    assert service.get_diagnostics(query=DiagnosticsQuery(tool_call_id="tc2")) == [camel]
    assert service.get_diagnostics(query=DiagnosticsQuery(code="tool_failed", limit=1)) == [snake]
    assert service.get_diagnostics(query=DiagnosticsQuery(limit=0)) == []


def test_service_builds_occurrence_summary_and_deduplicated_error_report() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService
    from loushang.harness.diagnostics.types import DiagnosticsQuery

    service = DiagnosticsService()
    service.record(_record("provider_failed", source="provider", occurrence_count=2))
    warning = service.record(
        _record("startup_warning", level="warning", phase="startup", source="bootstrap")
    )
    primary = service.record(_record("retry_failed"))

    summary = service.get_diagnostics_summary(DiagnosticsQuery(session_id="s1"))
    report = service.get_last_error_report()

    assert summary.total_count == 4
    assert summary.error_count == 3
    assert summary.warning_count == 1
    assert summary.info_count == 0
    assert summary.by_code == {"provider_failed": 2, "startup_warning": 1, "retry_failed": 1}
    assert summary.by_source == {"provider": 2, "bootstrap": 1, "session": 1}
    assert summary.by_phase == {"runtime": 3, "startup": 1}
    assert summary.latest_error == primary
    assert report is not None
    assert report.primary == primary
    assert report.related == (service.get_last_diagnostics()[0], warning)


def test_service_normalizes_resource_and_exception_details() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService
    from loushang.harness.resources.diagnostics import resource_diagnostic

    service = DiagnosticsService()
    resource = service.normalize_diagnostic(
        resource_diagnostic(
            code="invalid_extension",
            message="Extension is invalid.",
            source_path=Path("/tmp/extensions/review.py"),
            resource_id="review",
            resource_type="extension",
            source_kind="project_local",
            metadata={"line": 4},
        ),
        phase="resource_loading",
        source="loader",
        level="warning",
        details={"action": "ignored", "resource_type": "extension_override"},
    )
    failure = service.capture_failure(
        code="provider_failed",
        error=RuntimeError("provider unavailable"),
        phase="runtime",
        source="provider",
        details={"provider": "demo"},
    )

    assert resource.details == {
        "resource_id": "review",
        "resource_type": "extension_override",
        "source_kind": "project_local",
        "metadata": {"line": 4},
        "action": "ignored",
    }
    assert resource.source_path == Path("/tmp/extensions/review.py")
    assert failure.message == "provider unavailable"
    assert failure.details == {"provider": "demo"}
    assert service.get_last_diagnostics() == [failure]


def test_service_records_resource_diagnostics_with_shared_scope() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService
    from loushang.harness.diagnostics.types import DiagnosticDraft

    service = DiagnosticsService()

    records = service.record_drafts(
        [DiagnosticDraft(code="invalid_prompt", message="Prompt is invalid.")],
        phase="resource_loading",
        source="loader",
        session_id="session-1",
    )

    assert records == service.get_last_diagnostics()
    assert records[0].code == "invalid_prompt"
    assert records[0].session_id == "session-1"


def test_draft_normalization_preserves_fingerprint_deduplication() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService
    from loushang.harness.diagnostics.types import DiagnosticDraft

    service = DiagnosticsService()
    draft = DiagnosticDraft(
        code="extension_failed",
        message="Extension failed.",
        details={"metadata": {"extension": "demo"}},
    )

    first = service.record(
        service.normalize_diagnostic(draft, phase="runtime", source="extensions")
    )
    second = service.record(
        service.normalize_diagnostic(draft, phase="runtime", source="extensions")
    )

    assert second.fingerprint == first.fingerprint
    assert second.occurrence_count == 2


def test_service_runs_and_normalizes_startup_checks() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService
    from loushang.harness.diagnostics.types import DiagnosticRecord, StartupCheckResult

    service = DiagnosticsService()

    def passed_check() -> StartupCheckResult:
        return StartupCheckResult(name="config", ok=True)

    def explicit_record() -> DiagnosticRecord:
        return _record("explicit_warning", level="warning", phase="startup", source="bootstrap")

    def skipped_check() -> None:
        return None

    def broken_check() -> None:
        raise ValueError("bad startup state")

    records = service.run_startup_checks(
        [passed_check, explicit_record, skipped_check, broken_check],
        session_id="s1",
    )

    assert [record.code for record in records] == [
        "startup_check_passed",
        "explicit_warning",
        "startup_check_exception",
    ]
    assert records[0].message == "Startup check 'config' passed."
    assert records[0].type == "info"
    assert records[0].details == {"check": "config", "ok": True}
    assert records[-1].message == "bad startup state"
    assert records[-1].details == {
        "check": "broken_check",
        "exception_type": "ValueError",
    }


def test_directory_startup_check_reports_missing_path(tmp_path) -> None:
    from loushang.harness.diagnostics.types import directory_available_startup_check

    missing = tmp_path / "missing"
    check = directory_available_startup_check(
        name="workspace",
        path=missing,
        code="workspace_unavailable",
        message=f"Workspace is unavailable: {missing}",
        detail_key="workspace",
    )

    result = check()

    assert result is not None
    assert result.code == "workspace_unavailable"
    assert result.details == {"workspace": str(missing)}


def test_standard_startup_checks_include_cwd_package_and_product_checks(
    tmp_path,
) -> None:
    from loushang.harness.diagnostics.service import (
        DiagnosticsService,
        run_standard_startup_checks,
    )
    from loushang.harness.diagnostics.types import StartupCheckResult

    records = run_standard_startup_checks(
        DiagnosticsService(),
        cwd=str(tmp_path / "missing-cwd"),
        package_roots=(str(tmp_path / "missing-package"),),
        additional_checks=(
            lambda: StartupCheckResult(name="product", ok=True, code="product_ready"),
        ),
        session_id="session-1",
    )

    assert [record.code for record in records] == [
        "cwd_unavailable",
        "package_root_unavailable",
        "product_ready",
    ]
    assert all(record.session_id == "session-1" for record in records)


def test_service_clears_only_runtime_diagnostics() -> None:
    from loushang.harness.diagnostics.service import DiagnosticsService

    service = DiagnosticsService()
    startup = service.record(_record("startup", phase="startup", source="bootstrap"))
    service.record(_record("runtime"))
    resource = service.record(_record("resource", phase="resource_loading", source="loader"))

    service.clear_runtime_diagnostics()

    assert service.get_last_diagnostics() == [startup, resource]

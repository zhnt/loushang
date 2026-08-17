from __future__ import annotations

from pathlib import Path


def test_diagnostics_service_normalizes_and_queries_records() -> None:
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService
    from loushang.harness.diagnostics.types import DiagnosticDraft

    service = DiagnosticsService()
    record = service.normalize_diagnostic(
        DiagnosticDraft(
            code="duplicate_skill",
            message="Duplicate skill 'review' ignored.",
            source_path=Path("/tmp/review/SKILL.md"),
        ),
        phase="resource_loading",
        source="loader",
        session_id="s1",
    )

    service.record(record)

    assert service.get_last_diagnostics() == [record]
    assert service.get_diagnostics(phase="resource_loading", source="loader", type="warning") == [record]
    assert service.get_diagnostics(query=DiagnosticsQuery(session_id="s1", code="duplicate_skill", limit=1)) == [record]
    assert service.get_diagnostics(query=DiagnosticsQuery(session_id="other")) == []
    assert service.get_last_error_report() is None


def test_diagnostics_service_filters_tool_correlated_records() -> None:
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService

    service = DiagnosticsService()
    matching = service.capture_failure(
        code="tool_execution_failed",
        error="command failed",
        phase="runtime",
        source="tool",
        session_id="s1",
        details={"tool_call_id": "tc1", "tool_name": "bash"},
    )
    service.capture_failure(
        code="tool_execution_failed",
        error="other command failed",
        phase="runtime",
        source="tool",
        session_id="s1",
        details={"toolCallId": "tc2", "toolName": "bash"},
    )

    assert service.get_diagnostics(query=DiagnosticsQuery(tool_call_id="tc1")) == [matching]


def test_diagnostics_service_preserves_resource_diagnostic_details() -> None:
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.resources.diagnostics import resource_diagnostic

    service = DiagnosticsService()
    record = service.normalize_diagnostic(
        resource_diagnostic(
            code="extension_runtime_failed",
            message="Extension hook failed.",
            resource_id="deploy",
            resource_type="extension_command",
            source_kind="project_local",
            metadata={"extension": "deploy-ext"},
        ),
        phase="runtime",
        source="extensions",
        details={"event": "command"},
    )

    assert record.details == {
        "resource_id": "deploy",
        "resource_type": "extension_command",
        "source_kind": "project_local",
        "metadata": {"extension": "deploy-ext"},
        "event": "command",
    }


def test_diagnostics_service_builds_error_report_and_clears_runtime_records() -> None:
    from loushang.harness.diagnostics import DiagnosticsService

    service = DiagnosticsService()
    warning = service.normalize_exception(
        code="startup_hint",
        exc=RuntimeError("startup warning"),
        phase="startup",
        source="bootstrap",
        level="warning",
    )
    error = service.normalize_exception(
        code="retry_failed",
        exc=RuntimeError("network error"),
        phase="runtime",
        source="session",
        session_id="s1",
        entry_id="e1",
    )
    service.record_many([warning, error])

    report = service.get_last_error_report()

    assert report is not None
    assert report.primary == error
    assert warning in report.related

    service.clear_runtime_diagnostics()

    assert service.get_diagnostics(phase="runtime") == []
    assert service.get_diagnostics(phase="startup") == [warning]


def test_diagnostics_service_captures_failures() -> None:
    from loushang.harness.diagnostics import DiagnosticsService

    service = DiagnosticsService()

    record = service.capture_failure(
        code="provider_failed",
        error=RuntimeError("provider unavailable"),
        phase="runtime",
        source="provider",
        session_id="s1",
        details={"provider": "demo"},
    )

    assert service.get_last_diagnostics() == [record]
    assert record.code == "provider_failed"
    assert record.source == "provider"
    assert record.details == {"provider": "demo"}
    assert service.get_last_error_report() is not None
    assert service.get_last_error_report().primary == record


def test_diagnostics_service_deduplicates_repeated_records() -> None:
    from loushang.harness.diagnostics import DiagnosticsService

    service = DiagnosticsService()

    first = service.capture_failure(
        code="assistant_response_error",
        error="provider returned error",
        phase="runtime",
        source="provider",
        session_id="s1",
        entry_id="e1",
        details={"provider": "demo", "model_id": "alpha"},
    )
    second = service.capture_failure(
        code="assistant_response_error",
        error="provider returned error",
        phase="runtime",
        source="provider",
        session_id="s1",
        entry_id="e2",
        details={"provider": "demo", "model_id": "alpha"},
    )

    records = service.get_last_diagnostics()

    assert len(records) == 1
    assert records[0].code == "assistant_response_error"
    assert records[0].occurrence_count == 2
    assert records[0].fingerprint == first.fingerprint
    assert second.fingerprint == first.fingerprint


def test_diagnostics_service_error_report_related_records_are_deduplicated() -> None:
    from loushang.harness.diagnostics import DiagnosticsService

    service = DiagnosticsService()

    service.capture_failure(
        code="assistant_response_error",
        error="provider returned error",
        phase="runtime",
        source="provider",
        session_id="s1",
    )
    service.capture_failure(
        code="assistant_response_error",
        error="provider returned error",
        phase="runtime",
        source="provider",
        session_id="s1",
    )
    retry_failed = service.capture_failure(
        code="retry_failed",
        error="provider returned error",
        phase="runtime",
        source="session",
        session_id="s1",
    )

    report = service.get_last_error_report()

    assert report is not None
    assert report.primary == retry_failed
    assert [record.code for record in report.related] == ["assistant_response_error"]
    assert report.related[0].occurrence_count == 2


def test_diagnostics_service_summarizes_records_with_occurrences() -> None:
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService

    service = DiagnosticsService()
    service.capture_failure(
        code="assistant_response_error",
        error="provider failed",
        phase="runtime",
        source="provider",
        session_id="s1",
    )
    service.capture_failure(
        code="assistant_response_error",
        error="provider failed",
        phase="runtime",
        source="provider",
        session_id="s1",
    )
    service.record(
        service.normalize_exception(
            code="startup_hint",
            exc="missing optional config",
            phase="startup",
            source="bootstrap",
            level="warning",
            session_id="s1",
        )
    )

    summary = service.get_diagnostics_summary(DiagnosticsQuery(session_id="s1"))

    assert summary.total_count == 3
    assert summary.error_count == 2
    assert summary.warning_count == 1
    assert summary.info_count == 0
    assert summary.by_code == {"assistant_response_error": 2, "startup_hint": 1}
    assert summary.by_source == {"provider": 2, "bootstrap": 1}
    assert summary.by_phase == {"runtime": 2, "startup": 1}
    assert summary.latest_error is not None
    assert summary.latest_error.code == "assistant_response_error"


def test_diagnostics_serialization_projects_stable_json_shape() -> None:
    from loushang.harness.diagnostics import (
        DiagnosticRecord,
        DiagnosticSummary,
        ErrorReport,
        serialize_diagnostic,
        serialize_diagnostic_summary,
        serialize_error_report,
    )

    record = DiagnosticRecord(
        type="error",
        code="tool_execution_failed",
        message="tool failed",
        phase="runtime",
        source="tool",
        timestamp="2026-05-01T00:00:00Z",
        session_id="s1",
        entry_id="e1",
        source_path=Path("/tmp/project/tool.py"),
        details={"path": Path("/tmp/project/input.txt"), "values": (1, 2)},
        fingerprint="fp",
        occurrence_count=4,
    )

    assert serialize_diagnostic(record) == {
        "type": "error",
        "code": "tool_execution_failed",
        "message": "tool failed",
        "phase": "runtime",
        "source": "tool",
        "timestamp": "2026-05-01T00:00:00Z",
        "details": {"path": "/tmp/project/input.txt", "values": [1, 2]},
        "occurrenceCount": 4,
        "sessionId": "s1",
        "entryId": "e1",
        "sourcePath": "/tmp/project/tool.py",
        "fingerprint": "fp",
    }
    assert serialize_error_report(ErrorReport(primary=record)) == {
        "primary": serialize_diagnostic(record),
        "related": [],
    }
    assert serialize_diagnostic_summary(
        DiagnosticSummary(
            total_count=4,
            error_count=4,
            warning_count=0,
            info_count=0,
            by_code={"tool_execution_failed": 4},
            by_source={"tool": 4},
            by_phase={"runtime": 4},
            latest_error=record,
        )
    ) == {
        "totalCount": 4,
        "errorCount": 4,
        "warningCount": 0,
        "infoCount": 0,
        "byCode": {"tool_execution_failed": 4},
        "bySource": {"tool": 4},
        "byPhase": {"runtime": 4},
        "latestError": serialize_diagnostic(record),
    }


def test_diagnostics_service_runs_startup_checks() -> None:
    from loushang.harness.diagnostics import DiagnosticsService, StartupCheckResult

    service = DiagnosticsService()

    def model_config_check() -> StartupCheckResult:
        return StartupCheckResult(
            name="model_config",
            ok=False,
            code="model_auth_unresolved",
            level="warning",
            message="Provider demo has no configured API key.",
            details={"provider": "demo"},
        )

    records = service.run_startup_checks([model_config_check], session_id="s1")

    assert len(records) == 1
    assert records[0].code == "model_auth_unresolved"
    assert records[0].type == "warning"
    assert records[0].phase == "startup"
    assert records[0].source == "bootstrap"
    assert records[0].session_id == "s1"
    assert records[0].details == {"check": "model_config", "ok": False, "provider": "demo"}
    assert service.get_last_diagnostics() == records


def test_diagnostics_service_records_startup_check_exceptions() -> None:
    from loushang.harness.diagnostics import DiagnosticsService

    service = DiagnosticsService()

    def broken_check() -> None:
        raise ValueError("bad startup state")

    records = service.run_startup_checks([broken_check])

    assert len(records) == 1
    assert records[0].code == "startup_check_exception"
    assert records[0].type == "error"
    assert records[0].phase == "startup"
    assert records[0].source == "diagnostics"
    assert records[0].message == "bad startup state"
    assert records[0].details == {"check": "broken_check", "exception_type": "ValueError"}

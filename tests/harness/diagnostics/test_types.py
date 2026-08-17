from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import get_args

import pytest


def test_diagnostic_vocabularies_are_stable() -> None:
    from loushang.harness.diagnostics.types import (
        DiagnosticLevel,
        DiagnosticPhase,
        DiagnosticSource,
    )

    assert get_args(DiagnosticLevel) == ("info", "warning", "error")
    assert get_args(DiagnosticPhase) == ("startup", "resource_loading", "runtime")
    assert get_args(DiagnosticSource) == (
        "bootstrap",
        "loader",
        "package",
        "extensions",
        "session",
        "policy",
        "exec",
        "tool",
        "diagnostics",
        "provider",
        "model",
        "agent",
    )


def test_diagnostic_record_preserves_correlation_and_comparison_behavior() -> None:
    from loushang.harness.diagnostics.types import DiagnosticRecord

    source_path = Path("/tmp/project/tool.py")
    record = DiagnosticRecord(
        type="error",
        code="tool_failed",
        message="Tool failed.",
        phase="runtime",
        source="tool",
        timestamp="2026-07-12T00:00:00Z",
        session_id="s1",
        entry_id="e1",
        source_path=source_path,
        details={"tool_call_id": "tc1"},
        fingerprint="one",
        occurrence_count=3,
    )
    different_fingerprint = DiagnosticRecord(
        type="error",
        code="tool_failed",
        message="Tool failed.",
        phase="runtime",
        source="tool",
        timestamp="2026-07-12T00:00:00Z",
        session_id="s1",
        entry_id="e1",
        source_path=source_path,
        details={"tool_call_id": "tc1"},
        fingerprint="two",
        occurrence_count=3,
    )

    assert record.source_path is source_path
    assert record.details == {"tool_call_id": "tc1"}
    assert record == different_fingerprint
    with pytest.raises(FrozenInstanceError):
        record.code = "changed"  # type: ignore[misc]


def test_diagnostic_draft_defensively_freezes_input_details() -> None:
    from loushang.harness.diagnostics.types import DiagnosticDraft

    supplied_details: dict[str, object] = {"attempt": 1}
    draft = DiagnosticDraft(
        code="retry_pending",
        message="Retry is pending.",
        details=supplied_details,
    )
    supplied_details["attempt"] = 2

    assert draft.details == {"attempt": 1}
    with pytest.raises(TypeError):
        draft.details["attempt"] = 3  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        draft.code = "changed"  # type: ignore[misc]


def test_diagnostic_aggregate_and_query_defaults_are_stable() -> None:
    from loushang.harness.diagnostics.types import (
        DiagnosticRecord,
        DiagnosticsQuery,
        DiagnosticSummary,
        ErrorReport,
        StartupCheckResult,
    )

    record = DiagnosticRecord(
        type="warning",
        code="optional_config_missing",
        message="Optional config is missing.",
        phase="startup",
        source="bootstrap",
        timestamp="2026-07-12T00:00:00Z",
    )

    assert ErrorReport(primary=record).related == ()
    assert DiagnosticSummary(1, 0, 1, 0).by_code == {}
    assert DiagnosticsQuery() == DiagnosticsQuery(
        phase=None,
        source=None,
        level=None,
        session_id=None,
        entry_id=None,
        tool_call_id=None,
        code=None,
        limit=None,
    )
    assert StartupCheckResult(name="config", ok=True).source == "bootstrap"
    with pytest.raises(TypeError):
        DiagnosticsQuery("runtime")  # type: ignore[misc]

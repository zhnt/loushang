from __future__ import annotations


def test_coding_diagnostics_generic_facades_are_removed() -> None:
    import importlib.util

    import loushang.coding as coding
    import loushang.coding.diagnostics as diagnostics
    from loushang.harness.diagnostics import DiagnosticRecord, DiagnosticsService

    assert importlib.util.find_spec("loushang.coding.diagnostics.service") is None
    assert importlib.util.find_spec("loushang.coding.diagnostics.types") is None
    assert (
        importlib.util.find_spec("loushang.coding.diagnostics.problem_bridge") is None
    )
    assert not hasattr(coding, "DiagnosticsService")
    assert not hasattr(diagnostics, "DiagnosticRecord")
    assert DiagnosticRecord.__module__ == "loushang.harness.diagnostics.types"
    assert DiagnosticsService.__module__ == "loushang.harness.diagnostics.service"


def test_diagnostics_serialization_is_harness_owned() -> None:
    from loushang.harness.diagnostics import serialize_diagnostic
    from loushang.harness.diagnostics.types import DiagnosticRecord

    record = DiagnosticRecord(
        type="error",
        code="tool_failed",
        message="Tool failed.",
        phase="runtime",
        source="tool",
        timestamp="2026-07-12T00:00:00Z",
        session_id="s1",
    )

    assert serialize_diagnostic.__module__ == "loushang.harness.diagnostics.serialization"
    assert serialize_diagnostic(record) == {
        "type": "error",
        "code": "tool_failed",
        "message": "Tool failed.",
        "phase": "runtime",
        "source": "tool",
        "timestamp": "2026-07-12T00:00:00Z",
        "details": {},
        "occurrenceCount": 1,
        "sessionId": "s1",
    }

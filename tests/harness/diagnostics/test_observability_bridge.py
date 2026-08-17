from __future__ import annotations

from loushang.foundation.observability.records import ProblemRecord
from loushang.harness.diagnostics import DiagnosticsService
from loushang.harness.diagnostics.observability_bridge import (
    DiagnosticsProblemStore,
    diagnostic_source_for_problem,
)


def _problem(
    *, source: str | None = "tool", mode: str | None = "runtime"
) -> ProblemRecord:
    return ProblemRecord(
        code="tool_failed",
        severity="error",
        source=source,
        message="Tool failed.",
        time="2026-07-12T00:00:00Z",
        session_id="s1",
        mode=mode,
        recoverable=True,
    )


def test_problem_store_records_problem_and_normalized_diagnostic_once() -> None:
    diagnostics = DiagnosticsService()
    store = DiagnosticsProblemStore(diagnostics)

    store.record_problem(_problem())

    assert [record.code for record in store.all()] == ["tool_failed"]
    records = diagnostics.get_last_diagnostics()
    assert len(records) == 1
    assert records[0].code == "tool_failed"
    assert records[0].source == "tool"
    assert records[0].phase == "runtime"
    assert records[0].details == {
        "problem_source": "tool",
        "recoverable": True,
        "mode": "runtime",
    }


def test_problem_store_direct_record_uses_the_same_bridge_once() -> None:
    diagnostics = DiagnosticsService()
    store = DiagnosticsProblemStore(diagnostics)

    store.record(_problem())

    assert len(store.all()) == 1
    records = diagnostics.get_last_diagnostics()
    assert len(records) == 1
    assert records[0].occurrence_count == 1


def test_problem_store_uses_neutral_source_mapping_unless_product_overrides_it() -> (
    None
):
    diagnostics = DiagnosticsService()
    store = DiagnosticsProblemStore(diagnostics)

    store.record_problem(_problem(source="config", mode="startup"))

    record = diagnostics.get_last_diagnostics()[0]
    assert record.source == "diagnostics"
    assert record.phase == "startup"
    assert record.details["problem_source"] == "config"


def test_problem_store_accepts_a_product_source_resolver() -> None:
    diagnostics = DiagnosticsService()

    def source_resolver(record: ProblemRecord):
        if record.source == "config":
            return "model"
        return diagnostic_source_for_problem(record)

    store = DiagnosticsProblemStore(diagnostics, source_resolver=source_resolver)
    store.record_problem(_problem(source="config"))

    assert diagnostics.get_last_diagnostics()[0].source == "model"

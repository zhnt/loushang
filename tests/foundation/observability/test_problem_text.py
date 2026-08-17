from __future__ import annotations

from loushang.foundation.observability._router import InMemoryProblemStore
from loushang.foundation.observability.problem_text import (
    format_problem_summary,
    is_problem_log_line,
    recent_problem_store_lines,
)
from loushang.foundation.observability.records import ProblemRecord


def test_format_problem_summary_uses_stable_problem_text() -> None:
    record = ProblemRecord(
        code="provider_retry",
        severity="warning",
        source="provider",
        message="Retrying request.",
    )

    assert (
        format_problem_summary(record)
        == "PROBLEM warning provider_retry source=provider Retrying request."
    )


def test_recent_problem_store_lines_returns_the_latest_records() -> None:
    store = InMemoryProblemStore()
    store.record(ProblemRecord(code="first", severity="info"))
    store.record(ProblemRecord(code="second", severity="error"))

    assert recent_problem_store_lines(store, limit=1) == ["PROBLEM error second"]
    assert recent_problem_store_lines(store, limit=0) == []


def test_is_problem_log_line_selects_problem_and_warning_error_log_lines() -> None:
    assert is_problem_log_line("2026-05-14T00:00:00Z PROBLEM error provider_failed")
    assert is_problem_log_line("2026-05-14T00:00:00Z WARNING retrying provider")
    assert is_problem_log_line("2026-05-14T00:00:00Z ERROR provider failed")
    assert not is_problem_log_line("2026-05-14T00:00:00Z DEBUG ignored")

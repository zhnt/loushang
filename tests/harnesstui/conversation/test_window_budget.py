from __future__ import annotations

import pytest

from loushang.harnesstui.conversation.window_budget import (
    trim_records_to_line_budget,
)
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
    ErrorRecord,
    StatusRecord,
    ThinkingRecord,
    ThinkingVisibility,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


def test_window_budget_reuses_unchanged_tuple_at_exact_budget() -> None:
    records: tuple[DisplayRecord, ...] = (
        UserPromptRecord("old"),
        AssistantMessageRecord("new"),
    )

    result, evicted_count, changed = trim_records_to_line_budget(
        records,
        line_budget=3,
    )

    assert result is records
    assert evicted_count == 0
    assert changed is False


def test_window_budget_counts_record_separator_when_evicting_oldest() -> None:
    records: tuple[DisplayRecord, ...] = (
        UserPromptRecord("old"),
        AssistantMessageRecord("new"),
    )

    assert trim_records_to_line_budget(records, line_budget=2) == (
        (AssistantMessageRecord("new"),),
        1,
        True,
    )


@pytest.mark.parametrize("line_budget", (0, -1))
def test_window_budget_clamps_non_positive_budget(line_budget: int) -> None:
    records: tuple[DisplayRecord, ...] = (
        UserPromptRecord("old"),
        AssistantMessageRecord("new"),
    )

    assert trim_records_to_line_budget(records, line_budget=line_budget) == (
        (),
        2,
        True,
    )
    assert trim_records_to_line_budget((), line_budget=line_budget) == (
        (),
        0,
        False,
    )


def test_window_budget_partially_trims_only_boundary_record() -> None:
    records: tuple[DisplayRecord, ...] = (
        UserPromptRecord("fully evicted"),
        AssistantMessageRecord("a\nb\nc", stable=False),
        StatusRecord("new"),
    )

    assert trim_records_to_line_budget(records, line_budget=4) == (
        (
            AssistantMessageRecord(
                "[older assistant output omitted from active UI window]\nc",
                stable=False,
            ),
            StatusRecord("new"),
        ),
        1,
        True,
    )


@pytest.mark.parametrize(
    ("record", "expected"),
    (
        (
            UserPromptRecord("a\nb\nc"),
            UserPromptRecord("[older prompt content omitted from active UI window]\nc"),
        ),
        (
            AssistantMessageRecord("a\nb\nc", stable=False),
            AssistantMessageRecord(
                "[older assistant output omitted from active UI window]\nc",
                stable=False,
            ),
        ),
        (
            ThinkingRecord("a\nb\nc", ThinkingVisibility.COLLAPSED),
            ThinkingRecord(
                "[older thinking content omitted from active UI window]\nc",
                ThinkingVisibility.COLLAPSED,
            ),
        ),
        (
            StatusRecord("a\nb\nc"),
            StatusRecord("[older status content omitted from active UI window]\nc"),
        ),
    ),
)
def test_window_budget_preserves_text_record_kind_and_metadata(
    record: DisplayRecord,
    expected: DisplayRecord,
) -> None:
    assert trim_records_to_line_budget((record,), line_budget=2) == (
        (expected,),
        0,
        True,
    )


def test_window_budget_counts_blank_text_and_ignores_terminal_newline() -> None:
    trailing_newline: tuple[DisplayRecord, ...] = (AssistantMessageRecord("a\nb\n"),)
    blank: tuple[DisplayRecord, ...] = (StatusRecord(""),)

    result, evicted_count, changed = trim_records_to_line_budget(
        trailing_newline,
        line_budget=2,
    )
    assert result is trailing_newline
    assert (evicted_count, changed) == (0, False)

    result, evicted_count, changed = trim_records_to_line_budget(
        blank,
        line_budget=1,
    )
    assert result is blank
    assert (evicted_count, changed) == (0, False)


def test_window_budget_trims_error_diagnostics_inside_header_budget() -> None:
    record = ErrorRecord("boom", "d1\nd2\nd3")

    assert trim_records_to_line_budget((record,), line_budget=3) == (
        (
            ErrorRecord(
                "boom",
                "[older error diagnostics omitted from active UI window]\nd3",
            ),
        ),
        0,
        True,
    )
    assert trim_records_to_line_budget((record,), line_budget=1) == (
        (ErrorRecord("[older error details omitted from active UI window]"),),
        0,
        True,
    )


def test_window_budget_trims_tool_output_after_reserving_fixed_fields() -> None:
    record = ToolExecutionRecord(
        name="shell",
        state="failed",
        elapsed_seconds=2.5,
        command="cmd",
        output="o1\no2\no3",
        output_kind="code",
        language="bash",
        stderr="err",
        exit_code=1,
        show_stats=True,
    )

    assert trim_records_to_line_budget((record,), line_budget=6) == (
        (
            ToolExecutionRecord(
                name="shell",
                state="failed",
                elapsed_seconds=2.5,
                command="cmd",
                output="[older tool output omitted from active UI window]\no3",
                output_kind="code",
                language="bash",
                stderr="err",
                exit_code=1,
                show_stats=True,
            ),
        ),
        0,
        True,
    )


def test_window_budget_collapses_tool_fixed_fields_when_they_exhaust_budget() -> None:
    record = ToolExecutionRecord(
        name="shell",
        state="completed",
        elapsed_seconds=1.0,
        command="c1\nc2",
        output="o1\no2\no3",
        stderr="err",
    )

    assert trim_records_to_line_budget((record,), line_budget=2) == (
        (
            ToolExecutionRecord(
                name="shell",
                state="completed",
                elapsed_seconds=1.0,
                output="[older tool output omitted from active UI window]",
            ),
        ),
        0,
        True,
    )
    assert trim_records_to_line_budget((record,), line_budget=1) == (
        (),
        1,
        True,
    )


def test_window_budget_preserves_existing_tool_exit_code_overshoot() -> None:
    record = ToolExecutionRecord(
        name="shell",
        state="failed",
        elapsed_seconds=1.0,
        command="cmd",
        output="o1\no2",
        stderr="err",
        exit_code=1,
    )

    result, evicted_count, changed = trim_records_to_line_budget(
        (record,),
        line_budget=2,
    )

    assert result == (
        ToolExecutionRecord(
            name="shell",
            state="failed",
            elapsed_seconds=1.0,
            output="[older tool output omitted from active UI window]",
            exit_code=1,
        ),
    )
    assert (evicted_count, changed) == (0, True)


def test_window_budget_treats_non_text_records_as_one_line() -> None:
    records: tuple[DisplayRecord, ...] = (
        ContextCompactionRecord(summary="summary", tokens_before=100),
        WorkedDividerRecord(elapsed_seconds=1.5),
    )

    result, evicted_count, changed = trim_records_to_line_budget(
        records,
        line_budget=3,
    )

    assert result is records
    assert (evicted_count, changed) == (0, False)

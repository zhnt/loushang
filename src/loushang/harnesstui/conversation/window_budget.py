from __future__ import annotations

from dataclasses import replace

from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ErrorRecord,
    StatusRecord,
    ThinkingRecord,
    ToolExecutionRecord,
    UserPromptRecord,
)


def trim_records_to_line_budget(
    records: tuple[DisplayRecord, ...],
    *,
    line_budget: int,
) -> tuple[tuple[DisplayRecord, ...], int, bool]:
    """Keep the newest logical-line window and tail-trim its oldest record.

    The returned integer counts only records fully evicted from the prefix;
    the boolean reports whether the input window changed. An unchanged result
    preserves the identity of ``records``.
    """

    line_budget = max(0, line_budget)
    if not records or line_budget <= 0:
        return (), len(records), bool(records)

    kept_newest_first: list[DisplayRecord] = []
    used_lines = 0
    fully_evicted_count = 0
    changed = False

    for index in range(len(records) - 1, -1, -1):
        record = records[index]
        separator_lines = 1 if kept_newest_first else 0
        available = line_budget - used_lines - separator_lines
        if available <= 0:
            fully_evicted_count = index + 1
            changed = True
            break

        record_lines = _record_logical_line_count(record)
        if record_lines <= available:
            kept_newest_first.append(record)
            used_lines += separator_lines + record_lines
            continue

        trimmed = _tail_trim_record(record, max_lines=available)
        if trimmed is not None:
            kept_newest_first.append(trimmed)
            used_lines += separator_lines + _record_logical_line_count(trimmed)
            fully_evicted_count = index
        else:
            fully_evicted_count = index + 1
        changed = True
        break

    kept_records = tuple(reversed(kept_newest_first))
    if not changed and len(kept_records) == len(records):
        return records, 0, False
    return kept_records, fully_evicted_count, True


def _record_logical_line_count(record: DisplayRecord) -> int:
    if isinstance(
        record,
        UserPromptRecord | AssistantMessageRecord | ThinkingRecord | StatusRecord,
    ):
        return _text_line_count(record.text)
    if isinstance(record, ToolExecutionRecord):
        count = 1
        if record.command:
            count += _text_line_count(record.command)
        if record.output:
            count += _text_line_count(record.output)
        if record.stderr:
            count += _text_line_count(record.stderr)
        if record.exit_code is not None:
            count += 1
        return count
    if isinstance(record, ErrorRecord):
        return 1 + (_text_line_count(record.diagnostics) if record.diagnostics else 0)
    return 1


def _text_line_count(text: str) -> int:
    if not text:
        return 1
    return max(1, text.count("\n") + (0 if text.endswith("\n") else 1))


def _tail_trim_record(
    record: DisplayRecord,
    *,
    max_lines: int,
) -> DisplayRecord | None:
    if max_lines <= 0:
        return None
    if isinstance(record, UserPromptRecord):
        return UserPromptRecord(
            _tail_trim_text(
                record.text,
                max_lines=max_lines,
                marker="[older prompt content omitted from active UI window]",
            )
        )
    if isinstance(record, AssistantMessageRecord):
        return AssistantMessageRecord(
            _tail_trim_text(
                record.text,
                max_lines=max_lines,
                marker="[older assistant output omitted from active UI window]",
            ),
            stable=record.stable,
        )
    if isinstance(record, ThinkingRecord):
        return replace(
            record,
            text=_tail_trim_text(
                record.text,
                max_lines=max_lines,
                marker="[older thinking content omitted from active UI window]",
            ),
        )
    if isinstance(record, StatusRecord):
        return StatusRecord(
            _tail_trim_text(
                record.text,
                max_lines=max_lines,
                marker="[older status content omitted from active UI window]",
            )
        )
    if isinstance(record, ErrorRecord):
        if max_lines <= 1 or not record.diagnostics:
            return ErrorRecord("[older error details omitted from active UI window]")
        return replace(
            record,
            diagnostics=_tail_trim_text(
                record.diagnostics,
                max_lines=max_lines - 1,
                marker="[older error diagnostics omitted from active UI window]",
            ),
        )
    if isinstance(record, ToolExecutionRecord):
        return _tail_trim_tool_record(record, max_lines=max_lines)
    return None


def _tail_trim_tool_record(
    record: ToolExecutionRecord,
    *,
    max_lines: int,
) -> ToolExecutionRecord | None:
    output_budget = max_lines - 1
    if record.command:
        output_budget -= _text_line_count(record.command)
    if record.stderr:
        output_budget -= _text_line_count(record.stderr)
    if record.exit_code is not None:
        output_budget -= 1
    if output_budget <= 0:
        if max_lines <= 1:
            return None
        return replace(
            record,
            output="[older tool output omitted from active UI window]",
            stderr="",
            command="",
        )
    return replace(
        record,
        output=_tail_trim_text(
            record.output,
            max_lines=output_budget,
            marker="[older tool output omitted from active UI window]",
        ),
    )


def _tail_trim_text(text: str, *, max_lines: int, marker: str) -> str:
    if max_lines <= 1:
        return marker
    if _text_line_count(text) <= max_lines:
        return text
    lines = text.rstrip("\n").rsplit("\n", max_lines - 1)
    return "\n".join([marker, *lines[-(max_lines - 1) :]])


__all__ = ["trim_records_to_line_budget"]
